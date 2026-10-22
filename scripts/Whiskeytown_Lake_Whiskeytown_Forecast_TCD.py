from hec.model import RunTimeStep
from hec.rss.model import OpController
from hec.rss.model import OpRule
from hec.rss.model import OpValue     
from hec.script import Constants
from datetime import date


# WQCD operations
resetUpperMonth = 1  # reset to upper in Jan
temperatureThreshold = 0.1
targetTemperature = 13.
maxViolationDays = 3
checkOpHour = 12  # Hour to do operations check
# Variable names
globalVarNameNumUpOutlet = 'Whiskeytown_upper_gates_forecast'
globalVarNameNumLowOutlet = 'Whiskeytown_lower_gates_forecast'
stateVarNameWQCDViolations = 'Whiskeytown_WQCD_Violations'
stateVarNameWQCDLevel = 'Whiskeytown_WQCD_Level'
# Script constants
lastIterationPassNum = 2


def initRuleScript(currentRule, network):
    """Initialize the Whiskeytown WQCD rule, disabling it or resetting its violation counter.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object being initialized.
    network : object
        HEC-ResSim network object for the current compute.

    Returns
    -------
    int
        ``Constants.TRUE``, unconditionally (both branches return True;
        there is no failure path here).

    Notes
    -----
    The rule is force-disabled (via checkApplyRule) if WQ is not running
    or the reservoir is outside the active WQ geometry extent. When the
    rule remains active, the temperature-target violation counter is reset
    to 0 at the start of the simulation, ensuring a fresh run doesn't
    inherit a stale violation count from a prior run's state.
    """

    applyRule = checkApplyRule(currentRule, network)

    # Handle case where rule is active or disable but WQ for reservoir is not being run
    if not applyRule:
        currentRule.setEvalRule(False)
        network.getRssRun().printWarningMessage("Warning: Scripted rule " + currentRule.getName() + 
            " references Water Quality which is disabled for this simulation. Rule will be ignored.")
        return Constants.TRUE

    # WQ is being simulated
    else:
        setTempTargetViolations(network, 0)
        return Constants.TRUE


def checkApplyRule(currentRule, network):
    """Check whether this rule should be applied for the current simulation.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object, used to reach the controlled
        reservoir element.
    network : object
        HEC-ResSim network object, used to reach the current WQ run and
        geometry.

    Returns
    -------
    bool
        False if Water Quality is not running at all, or if the
        reservoir's WQ subdomain falls outside the active WQ geometry
        extent; True otherwise.
    """
    wqRun = network.getWQRun()
    if not wqRun:
        return False
    # Resolve this reservoir's WQ subdomain and confirm it falls inside the
    # geometry extent actually being simulated in the current WQ run.
    rssWQGeometry = wqRun.getRssWQGeometry()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    return rssWQGeometry.isInExtent(resWQGeoSubdom)
    

def runRuleScript(currentRule, network, currentRuntimestep):
    """Evaluate the Whiskeytown WQCD outlet-flow rule for the current time step.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object being evaluated.
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object.

    Returns
    -------
    None
        This rule communicates its decision by calling
        ``setWQControlDeviceFlowRatios`` directly rather than returning an
        OpValue; the function's own return value has no effect on the
        compute.

    Raises
    ------
    ValueError
        If reservoir elevation or controlled-outlet flow cannot be
        resolved to a valid value at the current or (for elevation, as a
        fallback) previous time step.

    Notes
    -----
    Three alternative outlet-operation strategies are sketched in comments
    above the active code: a fixed all-lower-outlet split, an
    unimplemented temperature-optimization call (``getOptimalFlows``,
    which is not defined anywhere in this file), and the forecasting
    approach actually used here (``getForecastFlows``). Only one of these
    is meant to be active at a time by commenting out the others.

    IMPORTANT: as written, ``wqcdFlows`` is computed by
    ``getForecastFlows`` (which also has side effects -- it writes the
    operation-level state variable, the per-outlet opening global
    variables, and the violation counter) but that returned value is then
    immediately discarded and overwritten by the line
    ``wqcdFlows = [co_flow, 0.]``, forcing 100% of flow through the lower
    outlet regardless of what the forecast logic decided. This means the
    entire gate-level decision logic in getForecastFlows currently has no
    effect on the actual flow split applied to the reservoir, even though
    it does still update the persistent state/global variables as if it
    had taken effect. This is preserved exactly rather than corrected, but
    is almost certainly not the intended behavior -- the override line
    looks like leftover debugging/placeholder code that was never removed
    after forecast logic was verified to run without errors.
    """

    # Only evaluation rule if running WQ (getEvalRule) *and* compute iteration > 0
    #  (On 0th iteration, only local res decisions being evaluated and WQ is not being run yet)
    computeIter = currentRule.getComputeIteration()
    evalRule = currentRule.getEvalRule() and (computeIter >= lastIterationPassNum)
    
    if evalRule:

        # Get reservoir elevation, falling back to the previous time step
        # if the current one is not yet valid (e.g. not computed yet this
        # iteration).
        resOp = currentRule.getController().getReservoirOp()
        res = resOp.getReservoirElement()
        resElev = res.getStorageFunction().getElevation(currentRuntimestep)
        if not isValidValue(resElev):  # try previous time step value
            prevRuntimestep = RunTimeStep(currentRuntimestep)
            prevRuntimestep.setStep(currentRuntimestep.getPrevStep())
            resElev = res.getStorageFunction().getElevation(prevRuntimestep)
        if not isValidValue(resElev):
            raise ValueError("Invalid value: " + str(resElev) + 
                             " for reservoir elevation for time step: " + str(currentRuntimestep.step))

        # Find current minimum flow requirement through the controlled outlet with the WQCD
        usePrevStepAsEstimate = True  # if flow value not available, use previous timestep val as estimate
        co_flow = resOp.getWQControlDeviceFlow(currentRuntimestep, currentRule, usePrevStepAsEstimate)
        if not isValidValue(co_flow):
            raise ValueError("Invalid value: " + str(co_flow) + " for Whiskeytown controlled outlet flow for time step: "
                             + str(currentRuntimestep.step))

        # Options for outlet operation below - comment out what you don't want
    
        # Specify all flow coming through the lower of the 2 inlets (convention is [lower, upper])
        # ----------------------------------------------------------------------------------------
        # wqcdFlows = [co_flow, 0.]
        
        # Optimize outflows to try and meet a temperature target
        # ----------------------------------------------------------------------------------------
        #wqcdFlows = getOptimalFlows(currentRule, network, currentRuntimestep, resElev, wqTarget, co_flow)        

        # Forecasting
        # ----------------------------------------------------------------------------------------
        wqcdFlows = getForecastFlows(currentRule, network, currentRuntimestep, resElev, co_flow)

        # Predict flows for forecasting
        wqcdFlows = [co_flow, 0.]
        
        resOp.setWQControlDeviceFlowRatios(wqcdFlows, currentRule, co_flow)

    return None


def isValidValue(value):
    """Check whether a numeric value is defined and non-negative.

    Parameters
    ----------
    value : float
        Value to validate, typically a reservoir elevation or controlled-
        outlet flow reading.

    Returns
    -------
    bool
        False if ``value`` is ``None``, equals
        ``Constants.UNDEFINED_DOUBLE``, or is negative; True otherwise.
    """
    if value is None:
        return False
    elif value == Constants.UNDEFINED_DOUBLE:
        return False
    elif value < 0.:
        return False
    else:
        return True


def getReservoirWQSubdomain(currentRule, network):
    """Look up the Water Quality subdomain geometry associated with a rule's reservoir.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object, used to reach the controller and
        its reservoir element.
    network : object
        HEC-ResSim network object, used to reach the current run's Water
        Quality run and geometry.

    Returns
    -------
    object
        The WQ subdomain geometry object corresponding to the reservoir
        element controlled by ``currentRule``.

    Notes
    -----
    This function is not called anywhere else in this file; getForecastFlows
    instead resolves the subdomain inline via
    ``network.getWQRun().getRssWQGeometry().getWQSubdomain(res)``. It is
    preserved here, unused, matching the same pattern seen in the
    3ptMinFF Shasta TCD script.
    """
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    wqRun = network.getRssRun().getWQRun()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getSubdomForRSSElemId(res.getIndex())
    return resWQGeoSubdom
    

def getOutletOptions():
    """Return the catalog of discrete Whiskeytown outlet-level configurations.

    Returns
    -------
    dict
        Mapping of integer level (1 = upper only, 2 = blended, 3 = lower
        only) to a 2-element list ``[lower, upper]`` indicating whether
        each outlet is open (1) or closed (0) for that configuration.

    Notes
    -----
    Unlike the Shasta TCD's gate catalog (which tracks a *count* of open
    gates per level), Whiskeytown's two outlets are simple binary
    open/closed switches, since there is only one lower and one upper
    outlet rather than multiple gates per level.
    """
    # Level number, state of level opening [lower, upper]
    outletOptions = {1: [0, 1],  # upper only
                     2: [1, 1],  # upper and lower blending
                     3: [1, 0]}  # lower only
    return outletOptions


def getOutletsForLevel(level):
    """Look up the outlet open/closed configuration for a given discrete level.

    Parameters
    ----------
    level : int
        Outlet level key into the dictionary returned by getOutletOptions
        (1-3).

    Returns
    -------
    list of int
        2-element list ``[lower, upper]`` of 0/1 open-closed flags.
    """
    outletOptions = getOutletOptions()
    return outletOptions[level]


def setOutlets(network, currentRuntimestep, levelName, outletOpen):
    """Write the open/closed state of a single Whiskeytown outlet.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the relevant global
        variable.
    currentRuntimestep : object
        Current simulation time step object.
    levelName : str
        Outlet name: "upper" or "lower" (case-insensitive).
    outletOpen : int
        0 (closed) or 1 (open) state to write.

    Returns
    -------
    None

    Raises
    ------
    NameError
        If ``levelName`` is not recognized, or the resolved global
        variable is not found.
    ValueError
        If ``outletOpen`` is outside the valid 0/1 range.
    """

    # Select the global variable corresponding to the named outlet.
    if levelName.lower() == 'upper':
        globalVarName = globalVarNameNumUpOutlet
    elif levelName.lower() == 'lower':
        globalVarName = globalVarNameNumLowOutlet
    else:
        raise NameError("Outlet level: " + levelName + " not recognized.")
        
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    
    # Validate before writing, since this is a binary open/closed flag,
    # not a gate count.
    if outletOpen < 0 or outletOpen > 1:
        raise ValueError("Global variable: " + globalVarName + " has invalid value " +
                         str(outletOpen) + " for time step: " + str(currentRuntimestep.step))
                    
    globVar.setCurrentValue(currentRuntimestep, outletOpen)


def setOutletOpenings(network, currentRuntimestep, openings):
    """Write the open/closed state of both Whiskeytown outlets at once.

    Parameters
    ----------
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object.
    openings : list of int
        2-element list ``[lower, upper]`` of 0/1 open-closed flags, as
        returned by getOutletsForLevel.

    Returns
    -------
    None
    """
    setOutlets(network, currentRuntimestep, 'lower', openings[0])
    setOutlets(network, currentRuntimestep, 'upper', openings[1])
    

def setOperationLevel(network, currentRuntimestep, level):
    """Store the current discrete outlet level in the WQCD level state variable.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the state variable.
    currentRuntimestep : object
        Current simulation time step object.
    level : int
        Outlet level value to store (per getOutletOptions).

    Returns
    -------
    None
    """
    sv = network.getStateVariable(stateVarNameWQCDLevel)
    sv.setValue(currentRuntimestep, level)


def getPrevOpLevel(network, currentRuntimestep):
    """Read the WQCD outlet level stored at the previous time step.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the state variable.
    currentRuntimestep : object
        Current simulation time step object; the previous step's index is
        derived from this.

    Returns
    -------
    int or float
        Outlet level value stored at the previous time step (step index
        clamped to a minimum of 0, so the first time step reads its own
        step 0 value rather than a negative index).
    """
    sv = network.getStateVariable(stateVarNameWQCDLevel)
    iCurStep = currentRuntimestep.getStep()
    iPrevStep = max(0, iCurStep - 1)
    rts = RunTimeStep()
    rts.setStep(iPrevStep)
    return sv.getValue(rts)


def setTempTargetViolations(network, numViolations):
    """Store the running count of consecutive temperature-target violation days.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the state variable.
    numViolations : int
        Number of consecutive violations to store.

    Returns
    -------
    None

    Notes
    -----
    This state variable is stored at a fixed step index of 1 rather than
    the current time step, matching the pattern in the main Shasta TCD
    script, so it functions as a single persistent counter across the
    simulation rather than a per-time-step time series.
    """
    sv = network.getStateVariable(stateVarNameWQCDViolations)
    rts = RunTimeStep()
    rts.setStep(1)
    sv.setValue(rts, numViolations)


def getTempTargetViolations(network):
    """Read the running count of consecutive temperature-target violation days.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the state variable.

    Returns
    -------
    int
        Current violation count, read from the fixed step-1 storage
        location used by setTempTargetViolations.
    """
    sv = network.getStateVariable(stateVarNameWQCDViolations)
    rts = RunTimeStep()
    rts.setStep(1)
    return sv.getValue(rts)
    

def getForecastFlows(currentRule, network, currentRuntimestep, resElev, co_flow):
    """Determine the forecast WQCD outlet level and flow split for the current time step.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object.
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object.
    resElev : float
        Current reservoir elevation.
    co_flow : float
        Total controlled-outlet flow to be distributed between the lower
        and upper outlets.

    Returns
    -------
    list of float
        2-element list ``[lowerFlow, upperFlow]`` giving the flow through
        each outlet.

    Notes
    -----
    NOTE: as documented in runRuleScript, the return value of this
    function is currently discarded by its caller and overwritten with a
    fixed all-lower-outlet split; the gate-level decision logic described
    below still executes and still updates persistent state/global
    variables, but has no effect on the actual applied flow split.

    Decision logic:

    - If the reservoir elevation is below the upper withdrawal point
      (1110 ft), lower-only operation (the last catalog level) is forced
      immediately, bypassing all other logic, since the upper outlet
      cannot meaningfully draw water at that elevation.
    - Otherwise, the water temperature at the layer nearest the upper
      withdrawal elevation and at the layer nearest the lower withdrawal
      elevation (972 ft) are both determined by scanning the reservoir's
      vertical layer boundaries.
    - For the very first time step(s) of the simulation (``iCurStep <= 1``),
      the catalog of outlet levels is scanned in order until one is found
      whose blended withdrawal temperature is below the target; if none
      ever satisfies the target, the loop completes without an explicit
      fallback and ``level`` is left at whatever the last dictionary entry
      was, which may not be intentional (mirrors the analogous fragility
      noted in the Shasta TCD scripts' first-time-step handling).
    - On subsequent time steps, the decision is only reconsidered once per
      day, at ``checkOpHour``; outside that hour, the previous level is
      simply held.
    - At the check hour, if the current month equals ``resetUpperMonth``
      (intended to force a reset to upper-only operation every January),
      level 1 is forced. NOTE: this comparison is written as
      ``curTime.month == resetUpperMonth`` rather than
      ``curTime.month() == resetUpperMonth`` -- since ``month`` is a
      method on the HecTime object used elsewhere in this file (and
      called with parentheses everywhere else, e.g. ``curTime.month()``),
      omitting the parentheses here compares a bound method object to an
      integer, which is very unlikely to ever evaluate as True. As
      written, this seasonal reset branch is effectively dead code and
      will not trigger as intended. This is flagged here rather than
      corrected.
    - Otherwise, the previous level's blended temperature is evaluated
      against the target; temperatures exceeding the threshold accumulate
      a violation counter, which resets to 0 whenever the target is met.
      Once violations reach ``maxViolationDays``, the operation moves one
      level down (toward more lower-outlet use); otherwise the previous
      level is held.
    """

    upperWithdrawalElev = 1110.
    lowerWithdrawalElev = 972.

    outletOptions = getOutletOptions()  # Dictionary with level number, level openings [lower, upper]

    # Check if reservoir elevation is above upper withdrawal point
    if resElev < upperWithdrawalElev:
        level = len(outletOptions)  # last entry, lower only
        setTempTargetViolations(network, 0)
        return setDataForLevel(network, currentRuntimestep, level, co_flow)

    wqRun = network.getWQRun()
    engineAdapter = wqRun.getWQEngineAdapter()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    resLayerElevs = resWQGeoSubdom.getResLayerBoundaryElevs()
    numLayers = len(resLayerElevs)-1
    layerTemps = engineAdapter.getReservoirLayerTemperatures(resWQGeoSubdom)

    # Find withdrawal temps: scan top-down for the first layer bottom below
    # the upper withdrawal elevation, and bottom-up for the first layer top
    # above the lower withdrawal elevation.
    for k in reversed(range(numLayers)):
        layerBotElev = resLayerElevs[k]
        if layerBotElev < upperWithdrawalElev:
            upperTemp = layerTemps[k]
            break
    for k in range(numLayers):
        layerTopElev = resLayerElevs[k+1]
        if layerTopElev > lowerWithdrawalElev:
            lowerTemp = layerTemps[k]
            break

    curTime = currentRuntimestep.getHecTime()
    try:
        curDate = date(3000, curTime.month(), curTime.day())
    except ValueError: # Leap year issue
        curDate = date(3000, curTime.month(), curTime.day()-1)
    curHour = curTime.hour()
    iCurStep = currentRuntimestep.getStep()

    # Previous gate operation
    prevOpLevel = getPrevOpLevel(network, currentRuntimestep)
    if prevOpLevel < 1 or prevOpLevel > len(outletOptions):
        prevOpLevel = 1  # only upper

    # For first time step(s), just find an acceptable operation
    if iCurStep <= 1:
        # Scan catalog levels in order (upper-only first) until one meets
        # the temperature target; if none do, level keeps whatever value
        # the loop's last iteration left it at (see Notes above).
        for level, outletOpenings in outletOptions.items():
            outletTemp = getTempForOp(outletOpenings, lowerTemp, upperTemp)
            if outletTemp < targetTemperature:
                break
        return setDataForLevel(network, currentRuntimestep, level, co_flow)
    else:
        # Only check once per day
        if curHour != checkOpHour:
            return setDataForLevel(network, currentRuntimestep, prevOpLevel, co_flow)
        elif curTime.month == resetUpperMonth:
            # See Notes above: missing parentheses on .month means this
            # branch is effectively unreachable as written.
            level = 1
            return setDataForLevel(network, currentRuntimestep, level, co_flow)
        else:
            # Evaluate the previous level's blended temperature against the
            # target, tracking consecutive violation days before actually
            # moving to a lower (deeper, cooler) operation level.
            numViolations = getTempTargetViolations(network)
            tempPrevOp = getTempForOp(outletOptions[prevOpLevel], lowerTemp, upperTemp)
            if tempPrevOp > targetTemperature + temperatureThreshold:
                numViolations += 1
                setTempTargetViolations(network, numViolations)
                print("Incrementing num violations", numViolations)
            else:
                print("Setting temp target violations 0")
                setTempTargetViolations(network, 0)
            if numViolations >= maxViolationDays and prevOpLevel < len(outletOptions):  # move to next level down in elevation
                print("Updating Level")
                level = prevOpLevel + 1
                setTempTargetViolations(network, 0)
            else:
                level = prevOpLevel
            return setDataForLevel(network, currentRuntimestep, level, co_flow)


def getTempForOp(outletOpenings, lowerTemp, upperTemp):
    """Compute the flow-weighted blended temperature for a given outlet configuration.

    Parameters
    ----------
    outletOpenings : list of int
        2-element list ``[lower, upper]`` of 0/1 open-closed flags.
    lowerTemp : float
        Water temperature at the lower outlet's withdrawal elevation.
    upperTemp : float
        Water temperature at the upper outlet's withdrawal elevation.

    Returns
    -------
    float
        Blended temperature, weighted by how many of the two outlets are
        open (assumes equal flow split between any simultaneously open
        outlets, since ``outletOpenings`` values are only 0 or 1, not
        actual flow amounts).
    """
    totalOpenings = float(sum(outletOpenings))
    outletTemp = (outletOpenings[0] * lowerTemp + outletOpenings[1] * upperTemp) / totalOpenings
    return outletTemp

def setDataForLevel(network, currentRuntimestep, level, coFlow):
    """Commit a chosen outlet level and compute its resulting flow split.

    Parameters
    ----------
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object.
    level : int
        Outlet level to commit (writes the level state variable and the
        per-outlet open/closed global variables).
    coFlow : float
        Total controlled-outlet flow to be split between whichever
        outlets are open at this level.

    Returns
    -------
    list of float
        2-element list ``[lowerFlow, upperFlow]`` giving the flow through
        each outlet, split evenly among however many outlets are open at
        this level.
    """
    setOperationLevel(network, currentRuntimestep, level)
    outletOpenings = getOutletsForLevel(level)
    setOutletOpenings(network, currentRuntimestep, outletOpenings)
    totalOpenings = float(sum(outletOpenings))
    flows = []
    # Split total flow evenly across however many outlets are open
    # (1 or 2) at this level.
    for j in range(len(outletOpenings)):
        flow = float(outletOpenings[j]) / totalOpenings * coFlow
        flows.append(flow)
    return flows