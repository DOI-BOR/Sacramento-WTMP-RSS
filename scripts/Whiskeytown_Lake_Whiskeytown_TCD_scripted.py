from hec.model import RunTimeStep
from hec.rss.model import OpController
from hec.rss.model import OpRule
from hec.rss.model import OpValue     
from hec.rss.model.globalvariable import TimeSeriesGlobalVariable, ScalarGlobalVariable
from hec.script import Constants


# Script constants
lastIterationPassNum = 2


def initRuleScript(currentRule, network):
    """Initialize the Whiskeytown WQCD rule, disabling it if WQ is not running.

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
    Unlike the forecast-variant Whiskeytown script, this version has no
    violation counter to reset here, since this script makes its gate
    decision from a directly-specified configuration rather than tracking
    violations over time.
    """

    # This rule depends on WQ results, so force it off (and warn) if the
    # current run does not have Water Quality enabled, or if this
    # reservoir isn't in the active WQ geometry extent.
    applyRule = checkApplyRule(currentRule, network)

    # Handle case where rule is active or disable but WQ for reservoir is not being run
    if not applyRule:
        currentRule.setEvalRule(False)
        network.getRssRun().printWarningMessage("Warning: Scripted rule " + currentRule.getName() + 
            " references Water Quality which is disabled for this simulation. Rule will be ignored.")
        return Constants.TRUE

    # WQ is being simulated
    else:
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
    # No WQ run at all for this simulation -- rule cannot apply.
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
    """Evaluate the Whiskeytown WQCD outlet-flow rule using a specified gate configuration.

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
        resolved to a valid value.

    Notes
    -----
    Unlike the forecast-variant Whiskeytown script (which decides a gate
    level from reservoir state and a temperature target), this version
    reads an explicit, externally-specified upper/lower gate configuration
    from global variables (getGateConfig) and applies it directly, with a
    50/50 flow split when both gates are open. The getOptimalFlows
    function below is fully implemented but not called from this active
    code path; it is left available as an alternative, selectable by
    commenting/uncommenting, same as in the forecast-variant script.
    """

    # Only evaluation rule if running WQ (getEvalRule) *and* compute iteration > 0
    #  (On 0th iteration, only local res decisions being evaluated and WQ is not being run yet)
    computeIter = currentRule.getComputeIteration()
    evalRule = currentRule.getEvalRule() and (computeIter >= lastIterationPassNum)
    if evalRule:

        # Get current water quality target
        # (read here even though the active code path below doesn't use
        # it; it would be needed if getOptimalFlows were selected instead)
        wqTarget = getGVTemperature(network, currentRuntimestep, "Whiskeytown_target")

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

        # Find current minimum flow requirement through the controlled outlet with the WQCD.
        # checkZero=False here allows a flow of exactly 0 to pass validation;
        # the inline comment below notes this would need to change to
        # checkZero=True if the getOptimalFlows() branch were used instead,
        # since that function's blending math assumes a positive flow.
        usePrevStepAsEstimate = True  # if flow value not available, use previous timestep val as estimate
        co_flow = resOp.getWQControlDeviceFlow(currentRuntimestep, currentRule, usePrevStepAsEstimate)
        if not isValidValue(co_flow,checkZero=False): # would need to be checkZero=true, if using getOptimalFlows()...
            raise ValueError("Invalid value: " + str(co_flow) + " for Whiskeytown controlled outlet flow for time step: "
                             + str(currentRuntimestep.step))

        # Options for outlet operation below - comment out what you don't want
    
        # Specify all flow coming through the lower of the 2 inlets (convention is [lower, upper])
        # ----------------------------------------------------------------------------------------
        # wqcdFlows = [co_flow, 0.]
        
        # Optimize outflows to try and meet a temperature target
        # ----------------------------------------------------------------------------------------
        #wqcdFlows = getOptimalFlows(currentRule, network, currentRuntimestep, resElev, wqTarget, co_flow)        

        # Specified gate config, w/ 50/50 blending if both are open
        # ----------------------------------------------------------------------------------------
        # Read the externally-specified gate states and translate them into
        # a flow split: both open means an even 50/50 split; otherwise all
        # flow goes through whichever single gate is open.
        upper,lower = getGateConfig(network, currentRuntimestep)
        if upper == 1 and lower == 1 :
            wqcdFlows = [co_flow * 0.5, co_flow * 0.5]
        elif lower == 1:
            wqcdFlows = [co_flow, 0.]
        else:  # we should have caught any invalid gate config already 
            wqcdFlows = [0., co_flow]
        resOp.setWQControlDeviceFlowRatios(wqcdFlows, currentRule, co_flow)

    return None


def getGVTemperature(network, currentRuntimestep, gvName):
    """Read a temperature global variable's current value, converted to degrees C.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the global variable.
    currentRuntimestep : object
        Current simulation time step object.
    gvName : str
        Name of the global variable to read.

    Returns
    -------
    float
        Current value of the global variable, converted to degrees
        Celsius if it was not already in that unit.

    Raises
    ------
    NameError
        If the global variable is not found.
    ValueError
        If the variable's current value is invalid.
    NotImplementedError
        If the global variable is neither a TimeSeriesGlobalVariable nor a
        ScalarGlobalVariable.

    Notes
    -----
    Same unit-detection convention as the other scripts in this project:
    time-series units are checked for a "c" substring; scalar values above
    32 are assumed Fahrenheit.
    """

    globVar = network.getGlobalVariable(gvName)
    if not globVar:
        raise NameError("Global variable: " + gvName + " not found.")

    # Read and validate before attempting any unit conversion.
    temp = globVar.getCurrentValue(currentRuntimestep)
    validVal = isValidValue(temp)
    if not validVal:
        raise ValueError("Global variable: " + gvName + " has invalid value " +
                         str(temp) + " for time step: " + str(currentRuntimestep.step))

    # Units conversion: detect source units differently depending on
    # whether this is a time-series or scalar global variable.
    if type(globVar) is TimeSeriesGlobalVariable:
        tsc = globVar.getTimeSeriesContainer()
        units = tsc.getUnits()
        if 'c' in units.lower():
            convert2C = False
        else:
            convert2C = True
    elif type(globVar) is ScalarGlobalVariable:
        if temp > 32.:
            convert2C = True
        else:
            convert2C = False
    else:
        raise NotImplementedError("Only Scalar and Time Series Global Variable types supported for Temperature Inputs")

    # Apply the Fahrenheit-to-Celsius conversion only if needed.
    if convert2C:
        tempDegC = (temp - 32.) * 5./9.
    else:
        tempDegC = temp
    return tempDegC


def getGateConfig(network, currentRuntimestep):
    """Read the externally-specified upper and lower gate open/closed states.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the two gate-state
        global variables.
    currentRuntimestep : object
        Current simulation time step object.

    Returns
    -------
    tuple of (float, float)
        Upper and lower gate states (expected to be 0 or 1 each).

    Raises
    ------
    NameError
        If either "Whiskeytown_Upper_Gate_open" or
        "Whiskeytown_Lower_Gate_open" global variable is not found.
    ValueError
        If the combination fails isValidGateConfig (i.e. neither gate is
        open).

    Notes
    -----
    Despite the error message's wording ("gates must be either 0 or 1,
    and one must be open"), isValidGateConfig only actually checks that
    at least one of the two values equals 1 -- it does not verify that
    both values are strictly 0 or 1 (e.g. a stray value like 0.5 for the
    other gate would not be caught here). This gap between the message
    and the actual check is preserved as-is rather than corrected.
    """

    # Read the upper gate's open/closed state.
    globalVarName = "Whiskeytown_Upper_Gate_open"    
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    upper = globVar.getCurrentValue(currentRuntimestep)    

    # Read the lower gate's open/closed state.
    globalVarName = "Whiskeytown_Lower_Gate_open"    
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    lower = globVar.getCurrentValue(currentRuntimestep)    

    # Confirm at least one gate is open before returning the pair.
    if not isValidGateConfig(upper,lower):
        raise ValueError("Global gate config variables are invalid: Whiskeytown gates must be either 0 or 1, and one must be open" +
                         " for time step: " + str(currentRuntimestep.step))
        
    return upper,lower


def isValidValue(value, checkZero=True):
    """Check whether a value is a well-defined float and (optionally) non-negative.

    Parameters
    ----------
    value : object
        Value to validate.
    checkZero : bool, optional
        If True (default), values less than 0.0 are considered invalid.
        If False, negative values (including exactly 0.0) are allowed
        through, provided they pass the float-type and defined-value
        checks.

    Returns
    -------
    bool
        False if ``value`` is not a Python float, equals
        ``Constants.UNDEFINED_DOUBLE``, or (if ``checkZero``) is negative;
        True otherwise.

    Notes
    -----
    Unlike every other ``isValidValue`` in this project (which check
    ``value is None`` or ``not value``), this version requires
    ``isinstance(value, float)`` as its first check -- meaning a value
    that is an int, or otherwise not a native float type, is rejected
    outright regardless of its numeric validity. This is a stricter and
    structurally different check than the rest of the codebase and is
    preserved exactly rather than reconciled.
    """
    if not isinstance(value,float):
        return False
    elif value == Constants.UNDEFINED_DOUBLE:
        return False
    elif checkZero and value < 0.0:
        return False
    else:
        return True


def isValidGateConfig(upper,lower):
    """Check that at least one of the two Whiskeytown gates is open.

    Parameters
    ----------
    upper : float
        Upper gate's open/closed state (expected 0 or 1).
    lower : float
        Lower gate's open/closed state (expected 0 or 1).

    Returns
    -------
    bool
        True if ``upper`` or ``lower`` equals 1; False if neither does.

    Notes
    -----
    As noted in getGateConfig's docstring, this only verifies that at
    least one gate reports a value of exactly 1 -- it does not verify
    that the other value is strictly 0 (or that both are limited to the
    0/1 range at all).
    """
    if upper == 1 or lower == 1:
        return True
    else:
        return False


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
    Not called anywhere else in this file; getOptimalFlows instead
    resolves the subdomain inline. Preserved here, unused, matching the
    pattern seen in the other Whiskeytown and Shasta TCD scripts.
    """
    # Walk from the rule to its controlled reservoir, then to the matching
    # WQ subdomain in the current run's geometry.
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    wqRun = network.getRssRun().getWQRun()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getSubdomForRSSElemId(res.getIndex())
    return resWQGeoSubdom
    

def getOptimalFlows(currentRule, network, currentRuntimestep, resElev, targetTemp, totalFlow):
    """Compute the lower/upper outlet flow split that best meets a temperature target.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object.
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object (unused directly in this
        function's body; present for interface consistency with its
        intended caller in runRuleScript).
    resElev : float
        Current reservoir elevation.
    targetTemp : float
        Desired blended outlet temperature.
    totalFlow : float
        Total controlled-outlet flow to split between the lower and upper
        outlets.

    Returns
    -------
    list of float
        2-element list ``[lowerFlow, upperFlow]``.

    Notes
    -----
    Unlike the forecast-variant Whiskeytown script (which only references
    a same-named, never-defined function in a comment), this function is
    fully implemented and ready to use, but is not called anywhere in
    this file's active code path -- it is offered as a selectable
    alternative via the commented-out line in runRuleScript.
    """

    upperWithdrawalElev = 1110.
    lowerWithdrawalElev = 972.

    # If the reservoir is too low for the upper outlet to draw from
    # meaningfully, send all flow through the lower outlet immediately.
    if resElev < upperWithdrawalElev:
        return [totalFlow, 0.]  # (convention is [lower, upper])

    # Otherwise, determine the water temperature available at each
    # outlet's withdrawal elevation from the reservoir's vertical profile.
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

    # If the target is colder than even the lower outlet can provide, use
    # the lower outlet exclusively (it's the coolest available option).
    if targetTemp < lowerTemp:
        return [totalFlow, 0.]
    # If the target is warmer than even the upper outlet can provide, use
    # the upper outlet exclusively (it's the warmest available option).
    elif targetTemp > upperTemp:
        return [0., totalFlow]
    else:  # blending
        # Target falls between the two outlets' temperatures: blend flow
        # proportionally so the mixed temperature lands on the target.
        if abs(upperTemp - lowerTemp) < 0.001:  # shouldn't happen, but just in case
            # Degenerate case: upper and lower temps are effectively equal,
            # so any split gives the same blended result; split evenly.
            halfFlow = 0.5 * totalFlow
            return [halfFlow, halfFlow]
        else:
            # Linear interpolation: closer to upperTemp means more lower
            # flow is needed to pull the blend down toward targetTemp.
            lowerFlow = (upperTemp - targetTemp) / (upperTemp - lowerTemp) * totalFlow
            upperFlow = totalFlow - lowerFlow
            return [lowerFlow, upperFlow]