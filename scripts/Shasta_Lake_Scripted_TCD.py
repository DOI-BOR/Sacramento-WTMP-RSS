from hec.model import RunTimeStep
from hec.rss.model import OpController
from hec.rss.model import OpRule
from hec.rss.model import OpValue     
from hec.rss.model import ReservoirElement
from hec.rss.model.globalvariable import TimeSeriesGlobalVariable, ScalarGlobalVariable
from hec.rss.plugins.waterquality.model import RssWQGeometry
from hec.rss.wq.model import WQRun
from hec.script import Constants
from hec.wqenginecore import WQEngineAdapter
from hec.wqenginecore import WQResHydro
from hec.wqenginecore.geometry import SubDomain
from hec.wqenginecore.geometry import WQControlDevice
from java.util import Vector


# Reference information

# TCD inlet definitions
# Port Index #     Elev     #  Name                   # Operable? #
#      0     #     695.5    #  TCD Deep               #     Y     #
#      1     #     720.     #  TCD Side A             #     Y     #
#      2     #     749.5    #  Leakage Zone 6         #     N     #
#      3     #     760.     #  TCD Side B             #     Y     #
#      4     #     780.     #  Leakage Zone 5         #     N     #
#      5     #     800.     #  TCD Side C (usual)     #     Y     #
#      6     #     802.     #  TCD Lower Bot          #     Y     #
#      7     #     805.6    #  Leakage Zone 4         #     N     #
#      8     #     816.     #  TCD Lower Mid          #     Y     #
#      9     #     820.     #  TCD Side C (high)      #     Y     #
#      10    #     830.     #  TCD Lower Top (usual)  #     Y     #
#      11    #     833.6    #  Leakage Zone 3         #     N     #
#      12    #     850.     #  TCD Lower Top (high)   #     Y     #
#      13    #     896.7    #  Leakage Zone 2         #     N     #
#      14    #     900.     #  TCD Middle Bot         #     Y     #
#      15    #     921.     #  TCD Middle Mid         #     Y     #
#      16    #     942.     #  TCD Middle Top (usual) #     Y     #
#      17    #     946.7    #  Leakage Zone 1         #     N     #
#      18    #     962.     #  TCD Middle Top (high)  #     Y     #
#      19    #    1000.     #  TCD Upper Bot          #     Y     #
#      20    #    1021.     #  TCD Upper Mid          #     Y     #
#      21    #    1042.     #  TCD Upper Top          #     Y     #

# Withdrawal indices, from lowest to highest in elevation
# This needs to be consistent with the TCD info in the Reservoir Physical tab

# Script constants
lastIterationPassNum = 2



def getLeakageIndexes():
    """Return the TCD inlet indices that represent uncontrollable leakage zones.

    Returns
    -------
    list of int
        Inlet indices (see the port-index reference table above) for
        Leakage Zones 6, 5, 4, 3, 2, and 1 respectively, in descending
        zone-number order matching ascending elevation.
    """
    return [2, 4, 7, 11, 13, 17]


def getGateIndexes(useHighPt):
    """Return the TCD inlet indices grouped by operable gate level.

    Parameters
    ----------
    useHighPt : bool
        If True, uses the "high point" variant of the side, lower, and
        middle gate groupings (the alternate/elevated operable port at
        each level); if False, uses the "usual" (lower/default) operable
        port.

    Returns
    -------
    tuple of (list of int, list of int, list of int, list of int)
        Side, lower, middle, and upper gate inlet indices, respectively.

    Notes
    -----
    The upper gate indices (19, 20, 21) do not vary with ``useHighPt``,
    since the port-index table above defines only one tier of upper
    ports. In this script, ``useHighPt`` is decided dynamically each time
    step by checkUseHighPoint, rather than being fixed at False as in the
    main (gate-level/violation-tracking) Shasta TCD script.
    """

    if useHighPt:
        # Elevated-port variant: substitutes the higher-elevation operable
        # port at each level (e.g. side index 9 instead of 5).
        sideIdx = [0, 1, 3, 9]
        lowerIdx = [6, 8, 12]
        middleIdx = [14, 15, 18]
    else:
        # Default/"usual" operable port at each level.
        sideIdx = [0, 1, 3, 5]
        lowerIdx = [6, 8, 10]
        middleIdx = [14, 15, 16]
        
    # Upper gates have only one tier, so they don't vary with useHighPt.
    upperIdx = [19, 20, 21]
    return sideIdx, lowerIdx, middleIdx, upperIdx


def getInletElevs(currentRule, network):
    """Retrieve the TCD inlet elevations from the WQ engine's reservoir geometry.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object, used to reach the reservoir
        operation and its release element.
    network : object
        HEC-ResSim network object, used to reach the current WQ run, its
        engine adapter, and its WQ geometry.

    Returns
    -------
    list of float
        Inlet elevations for the reservoir's TCD, indexed as in the
        port-index reference table at the top of this file. These values
        originate from the Reservoir Physical tab configuration, passed
        through to the WQ geometry.
    """
    # Walk from the network's WQ run down to the specific control device
    # geometry for this reservoir, then ask the engine for its inlet
    # elevations.
    wqRun = network.getWQRun()
    engineAdapter = wqRun.getWQEngineAdapter()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    wqcd = rssWQGeometry.getWQControlDevice(currentRule.getController().getReleaseElement())
    elevs = engineAdapter.getWQCDInletLevels(resWQGeoSubdom, wqcd)
    return elevs


def initRuleScript(currentRule, network):
    """Initialize the Shasta TCD rule, disabling it or registering TCD info with the WQ engine.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object being initialized.
    network : object
        HEC-ResSim network object for the current compute.

    Returns
    -------
    int
        ``Constants.TRUE``, unconditionally (both the disabled and the
        active-WQ branches return True; there is no failure path here).

    Notes
    -----
    The rule is force-disabled (via checkApplyRule) if WQ is not running
    or the reservoir is outside the active WQ geometry extent. When the
    rule remains active, this function registers the TCD's gate-index
    groupings with the WQ engine adapter via ``setShastaTCDInfo`` using
    the "usual" (not high-point) ports as a one-time startup default;
    note that getTCDTempAndFlows3ptMinFF re-registers this same
    information every time step using a dynamically chosen ``useHighPt``
    value, so this initial registration is effectively just a starting
    default that gets overwritten on the first rule evaluation.
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
        # Pass information to the WQEngine that says we're dealing with the Shasta TCD
        wqRun = network.getWQRun()
        engineAdapter = wqRun.getWQEngineAdapter()
        resOp = currentRule.getController().getReservoirOp()
        res = resOp.getReservoirElement()
        rssWQGeometry = wqRun.getRssWQGeometry()
        resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
        wqcd = rssWQGeometry.getWQControlDevice(currentRule.getController().getReleaseElement())

        # Register the default (non-high-point) gate groupings with the
        # engine before the first time step is evaluated.
        useHighPt = False
        sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(useHighPt)
        engineAdapter.setShastaTCDInfo(resWQGeoSubdom.getId(), wqcd.getId(), sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx)
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
    """Evaluate the Shasta TCD flow-optimization rule for the current time step.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object being evaluated.
    network : object
        HEC-ResSim network object, used to look up global variables and
        the current WQ run.
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
        If reservoir elevation or penstock flow cannot be resolved to a
        valid value at the current or (as a fallback) previous time step.

    Notes
    -----
    Unlike the main (gate-level/violation-tracking) Shasta TCD script,
    this version has no persistent gate-level state machine, no seasonal
    operation-window logic, and no river-outlet or downstream
    temperature-backrouting adjustment -- the water-quality target is
    read directly from the "TCD_target" global variable and used as-is.
    Instead, this version re-optimizes the full inlet flow distribution
    from scratch every time step (getTCDTempAndFlows3ptMinFF), given
    whatever gate counts are currently open (read from global variables
    rather than decided by this script). If the computed penstock flow is
    below 1 cfs, it is floored to exactly 1 cfs so a flow distribution can
    still be calculated, and a warning is printed in that case.
    """

    # Only evaluation rule if running WQ (getEvalRule) *and* compute iteration > 0
    #  (On 0th iteration, only local res decisions being evaluated and WQ is not being run yet)
    computeIter = currentRule.getComputeIteration()
    evalRule = currentRule.getEvalRule() and (computeIter >= lastIterationPassNum)
    if evalRule:

        # Get current water quality target
        wqTarget = getGVTemperature(network, currentRuntimestep, "TCD_target")
    
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
    
        # Find current minimum flow requirement through the WQCD
        usePrevStepAsEstimate = True  # if flow value not available, use previous timestep val as estimate
        penstockFlow = resOp.getWQControlDeviceFlow(currentRuntimestep, currentRule, usePrevStepAsEstimate)
        if not isValidValue(penstockFlow):
            raise ValueError("Invalid value: " + str(penstockFlow) + 
                             " for penstock flow for time step: " + str(currentRuntimestep.step))
        # Assume a nominal minimum flow to be able to calculate a distribution
        penstockFlow = max(penstockFlow, 1.0)
        if penstockFlow == 1.0:
            print("Warning: penstock flow = 1cfs " + str(currentRuntimestep.step))
    
        # Find optimal flow distribution in WQCD and resulting average water quality, given a
        #  wq target and total WQCD flow
        tcdTemp, tcdFlows = getTCDTempAndFlows3ptMinFF(currentRule, network, currentRuntimestep, resElev, wqTarget, penstockFlow)

        resOp.setWQControlDeviceFlowRatios(tcdFlows, currentRule, penstockFlow)

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
        If the variable's current value is invalid (per the default
        ``checkZero=True`` behavior of isValidValue, used here for all
        calls regardless of variable name).
    NotImplementedError
        If the global variable is neither a TimeSeriesGlobalVariable nor a
        ScalarGlobalVariable.

    Notes
    -----
    Unit detection differs by global-variable type: for a time series
    variable, the DSS units string is inspected for a "c" substring
    (case-insensitive) to decide whether conversion is needed; for a
    scalar variable, a value greater than 32 is assumed to be Fahrenheit
    (since no plausible Celsius water/air temperature would exceed 32
    here) and is converted accordingly. Unlike the equivalent function in
    the main Shasta TCD script, this version always validates with
    ``checkZero=True`` (the isValidValue default) regardless of which
    global variable name is passed in.
    """

    globVar = network.getGlobalVariable(gvName)
    if not globVar:
        raise NameError("Global variable: " + gvName + " not found.")

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

    if convert2C:
        tempDegC = (temp - 32.) * 5./9.
    else:
        tempDegC = temp
    return tempDegC


def getNumGatesOpen(network, currentRuntimestep, levelName):
    """Read the current number of open gates for a given TCD level.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the relevant global
        variable.
    currentRuntimestep : object
        Current simulation time step object.
    levelName : str
        Gate level name: "upper", "middle", "lower", or "side"
        (case-insensitive).

    Returns
    -------
    int
        Current number of open gates at the given level.

    Raises
    ------
    NameError
        If ``levelName`` is not recognized, or the resolved global
        variable is not found.
    ValueError
        If the resolved value is negative or exceeds the maximum gate
        count for that level (5 for upper/middle/lower, 2 for side).

    Notes
    -----
    Unlike the equivalent function in the main Shasta TCD script, this
    version has no ``isHistorical`` option and no separate "_forecast"
    vs. "_open" variable distinction -- there is only a single "_open"
    global variable per level, read directly as the current gate state
    (this script has no forecast gate-level decision state of its own; it
    always reacts to whatever gates are currently reported open).
    """

    maxGates = 5
    # Select the global variable name for the requested gate level.
    if levelName.lower() == 'upper':
        globalVarName = "Total_TCDU_gates_open"
    elif levelName.lower() == 'middle':
        globalVarName = "Total_TCDM_gates_open"
    elif levelName.lower() == 'lower':
        globalVarName = "Total_TCDL_gates_open"
    elif levelName.lower() == 'side':
        # Side level caps out at 2 gates rather than 5.
        globalVarName = "Total_TCDS_gates_open"
        maxGates = 2
    else:
        raise NameError("Gate level: " + levelName + " not recognized.")
        
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    numGates = globVar.getCurrentValue(currentRuntimestep)
    
    # Validate against the physically possible range of gate counts for
    # this level before trusting the value.
    if numGates < 0 or numGates > maxGates:
        raise ValueError("Global variable: " + globalVarName + " has invalid value " +
                         str(numGates) + " for time step: " + str(currentRuntimestep.step))
    else:
        return numGates


def isValidValue(value, checkZero=True):
    """Check whether a numeric value is truthy, defined, and (optionally) non-negative.

    Parameters
    ----------
    value : float
        Value to validate.
    checkZero : bool, optional
        If True (default), values less than 0 are considered invalid. If
        False, only falsy values (including 0.0) and
        ``Constants.UNDEFINED_DOUBLE`` are checked.

    Returns
    -------
    bool
        False if ``value`` is falsy (including 0.0 or None), equals
        ``Constants.UNDEFINED_DOUBLE``, or (if ``checkZero``) is negative;
        True otherwise.

    Notes
    -----
    Like the calibration-variant rule scripts elsewhere in this project
    (and unlike the main Shasta TCD script's isValidValue, which checks
    ``value is None``), this version uses ``if not value:`` as its first
    check, meaning a value of exactly 0.0 is always rejected regardless
    of ``checkZero``.
    """
    if not value:
        return False
    elif value == Constants.UNDEFINED_DOUBLE:
        return False
    elif checkZero and value < 0.:
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
    This function is not called anywhere else in this file; the rest of
    this script instead calls ``network.getWQRun().getRssWQGeometry()
    .getWQSubdomain(res)`` directly inline wherever it needs the
    subdomain (see, e.g., getInletElevs, initRuleScript,
    getTCDTempAndFlows3ptMinFF). It is preserved here, unused, in case it
    is relied upon elsewhere in the project or retained for future use.
    """
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    wqRun = network.getRssRun().getWQRun()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getSubdomForRSSElemId(res.getIndex())
    return resWQGeoSubdom


def getTotalLeakageFraction2000(resElev, elevs):
    """Compute total TCD leakage fraction using pre-2010 (2000-2009) calibration.

    Parameters
    ----------
    resElev : float
        Current reservoir elevation.
    elevs : list of float
        TCD inlet elevations (see getInletElevs).

    Returns
    -------
    float
        Total leakage fraction of gross flow, per the pre-2010 calibration
        in the W2 Report, Table 16.
    """
    upperFraction = 13.09/100.
    middleFraction = 19.7/100.
    lowerFraction = 12.65/100.
    # Delegate to the shared elevation-based interpolation using these
    # pre-2010 zone percentages and a 0.2 gross-leakage assumption.
    fraction = getTotalLeakageFraction(resElev, elevs, upperFraction, middleFraction, lowerFraction, 0.2)
    return fraction


def getTotalLeakageFraction2010(resElev, elevs):
    """Compute total TCD leakage fraction using 2010-onward calibration.

    Parameters
    ----------
    resElev : float
        Current reservoir elevation.
    elevs : list of float
        TCD inlet elevations (see getInletElevs).

    Returns
    -------
    float
        Total leakage fraction of gross flow, per the 2010-onward
        calibration in the W2 Report, Table 17.
    """
    upperFraction = 16.3/100.
    middleFraction = 0./100.
    lowerFraction = 15.75/100.
    # Same elevation-interpolation routine as the 2000 variant, but with
    # the 2010-onward zone percentages (middle leakage assumed eliminated).
    fraction = getTotalLeakageFraction(resElev, elevs, upperFraction, middleFraction, lowerFraction, 0.2)
    return fraction


def getTotalLeakageFraction(resElev, elevs, upperFraction, middleFraction, lowerFraction, grossFraction):
    """Compute the total TCD leakage fraction as a function of reservoir elevation.

    Parameters
    ----------
    resElev : float
        Current reservoir elevation.
    elevs : list of float
        TCD inlet elevations (see getInletElevs).
    upperFraction : float
        Fraction of gross leakage attributable to the upper leakage zone
        (Zone 1) when fully exposed.
    middleFraction : float
        Fraction of gross leakage attributable to the middle leakage zone
        (Zone 2) when fully exposed.
    lowerFraction : float
        Fraction of gross leakage attributable to the lower leakage zone
        (Zone 3) when fully exposed.
    grossFraction : float
        Assumed total leakage fraction when the pool elevation is at or
        above 1000 ft and all gates are closed.

    Returns
    -------
    float
        Total leakage fraction of gross penstock flow, interpolated
        piecewise between four elevation bands anchored at 1000 ft and the
        Zone-1, Zone-2, and Zone-3 inlet elevations.

    Notes
    -----
    As reservoir elevation drops below 1000 ft, successive leakage zones
    become submerged and are assumed to stop contributing their
    respective fraction of leakage (the corresponding fraction term is
    phased out linearly between zone boundaries via ``resElevFactor``).
    Below Zone 3's elevation, leakage is treated as zero -- the inline
    comment notes "we have bigger concerns than leakage at this point."
    """

    #grossFraction = 0.2  # Assumed leakage fraction when pool elev > 1000. and all gates closed
    topElev = 1000.
    z1Elev = elevs[getIdxForLeakageZone(1)]
    z2Elev = elevs[getIdxForLeakageZone(2)]
    z3Elev = elevs[getIdxForLeakageZone(3)]
    # Identify which of the four elevation bands the reservoir currently
    # falls into, and phase out the appropriate zone fraction(s) linearly
    # as elevation drops through that band.
    if resElev >= topElev:
        fraction = grossFraction
    elif resElev >= z1Elev:
        resElevFactor = 1. - (resElev - z1Elev) / (topElev - z1Elev)  # =0 at 1000, 1 at 945ish
        fraction = grossFraction * (1. - upperFraction*resElevFactor)
    elif resElev >= z2Elev:
        resElevFactor = 1. - (resElev - z2Elev) / (z1Elev - z2Elev)  # =0 at 945ish, 1 at 900ish
        fraction = grossFraction * (1. - upperFraction - middleFraction*resElevFactor)
    elif resElev >= z3Elev:
        resElevFactor = 1. - (resElev - z3Elev) / (z2Elev - z3Elev)  # =0 at 900ish, 1 at 831ish
        fraction = grossFraction * (1. - upperFraction - middleFraction - lowerFraction*resElevFactor)
    else:
        # we have bigger concerns than leakage at this point
        fraction = 0.
    return fraction


def getLeakageTableVals(currentYear, zoneNum):
    """Look up leakage-flow regression coefficients for a given year and leakage zone.

    Parameters
    ----------
    currentYear : int
        Calendar year of the current time step, used to select between
        pre-2010 and 2010-onward coefficient tables.
    zoneNum : int
        Leakage zone number (1-6; see the port-index reference table).

    Returns
    -------
    list of float
        2-element list of regression coefficients ``[base, gateRatioCoef]``
        for the given zone and year, taken from the W2 Report, Tables 16
        (pre-2010) and 17 (2010 onward). Zones 5 and 6 fold in additional
        "Bottom 7"/"Bottom 8" leakage contributions into the base
        coefficient. Returns an empty list if ``zoneNum`` is not
        recognized.
    """
    vals = []
    # Zone 6 (also includes "Bottom 8" leakage)
    if zoneNum == 6:
        if currentYear < 2010:
            vals = [1.79 + 6.77, 0.]
        else:
            vals = [2.23 + 8.44, 0.]
    # Zone 5 (also includes "Bottom 7" leakage)
    elif zoneNum == 5:
        if currentYear < 2010:
            vals = [3.84 + 31.12, 0.]
        else:
            vals = [4.78 + 38.76, 0.]
    # Zone 4
    elif zoneNum == 4:
        if currentYear < 2010:
            vals = [1.03, 10.01]
        else:
            vals = [1.28, 12.47]
    # Zone 3
    elif zoneNum == 3:
        if currentYear < 2010:
            vals = [9.34, 3.31]
        else:
            vals = [11.63, 4.12]
    # Zone 2
    elif zoneNum == 2:
        if currentYear < 2010:
            vals = [8.05, 11.65]
        else:
            vals = [0., 0.]
    # Zone 1
    elif zoneNum == 1:
        if currentYear < 2010:
            vals = [13.09, 0.]
        else:
            vals = [16.3, 0.]
    return vals


def calcWeirFlow(H, numOpenGates):
    """Estimate maximum flow through a partially submerged gate using a sharp-crested weir equation.

    Parameters
    ----------
    H : float
        Head of submergence over the gate invert, in feet.
    numOpenGates : int
        Number of open gates of this type contributing to the total flow
        estimate.

    Returns
    -------
    float
        Estimated maximum flow (cfs) through the given number of open
        gates at this submergence depth.

    Notes
    -----
    Uses the sharp-crested weir equation from White's Fluid Mechanics, 3rd
    ed., p. 624, assuming imperial units (g = 32.1 ft/s^2) and a fixed
    gate width of 50 ft per gate.
    """
    g = 32.1  # assuming imperial units here
    weirCoef = 0.564  # from White
    width = 50.  # gates are 50' wide
    # Sharp-crested weir equation: Q = Cw * L * sqrt(g) * H^1.5, scaled by
    # the number of open gates of this type.
    q = weirCoef * width * g**0.5 * H**1.5 * numOpenGates
    return q


def getIdxForLeakageZone(z):
    """Translate a leakage zone number into its TCD inlet index.

    Parameters
    ----------
    z : int
        Leakage zone number (1 = highest elevation leakage zone, 6 =
        lowest), per the port-index reference table at the top of this
        file.

    Returns
    -------
    int
        TCD inlet index corresponding to leakage zone ``z``.

    Notes
    -----
    getLeakageIndexes returns inlet indices ordered from lowest to highest
    zone number (6 down to 1); this function reverses that ordering so
    zone 1 (highest elevation) maps to the last entry and zone 6 (lowest)
    maps to the first.
    """
    leakageIdx = getLeakageIndexes()
    i = len(leakageIdx) - z
    return leakageIdx[i]


def calcLeakage(currentYear, zone, gateRatio, elevationRatio, totalLeakFract, flow):
    """Compute the leakage flow for a single zone given gate state and elevation.

    Parameters
    ----------
    currentYear : int
        Calendar year, used to select the appropriate coefficient table
        via getLeakageTableVals.
    zone : int
        Leakage zone number (1-6).
    gateRatio : float
        Fraction of nearby gates that are closed (contributing to
        leakage); typically ``(total - open) / total`` for the relevant
        gate group.
    elevationRatio : float
        Fraction (0-1) describing how submerged this leakage zone is
        relative to its elevation band.
    totalLeakFract : float
        Total leakage fraction of gross flow, from
        getTotalLeakageFraction2000/2010.
    flow : float
        Total penstock flow (cfs) that the leakage fraction is applied to.

    Returns
    -------
    float
        Estimated leakage flow (cfs) for this zone.
    """
    tableVals = getLeakageTableVals(currentYear, zone)
    # Combine the base and gate-ratio-dependent regression terms with the
    # elevation ratio, total leakage fraction, and total flow.
    leakageFlow = (tableVals[0] + tableVals[1]*gateRatio)/100. * elevationRatio * totalLeakFract * flow
    return leakageFlow


def chooseMinFlowFract(nOpenLevels, ptNum):
    """Choose a minimum flow fraction for an inlet point based on level openness and point position.

    Parameters
    ----------
    nOpenLevels : int
        Number of gate levels currently open.
    ptNum : int
        Index of the inlet point within its gate level (0 = lowest point
        at that level).

    Returns
    -------
    float
        Minimum flow fraction (of total penstock flow) to assign as a
        lower bound for this inlet point in the optimization: 10% for the
        lowest point when only one level is open, 5% for the lowest point
        when multiple levels are open, 2% for other points when only one
        level is open, or 1% for other points when multiple levels are
        open.

    Notes
    -----
    Unlike the equivalent function in the main Shasta TCD script (which
    always returns a flat 1% regardless of its inputs), this version has
    genuinely differentiated minimum-flow fractions depending on both
    whether the point is the lowest in its level and how many levels are
    currently open -- giving the lowest/primary point at each level a
    higher guaranteed minimum flow.
    """
    if ptNum == 0:
        if nOpenLevels == 1:
            minFF = 0.10
        else:
            minFF = 0.05
    else:
        if nOpenLevels == 1:
            minFF = 0.02
        else:
            minFF = 0.01
    return minFF


def checkUseHighPoint(network, currentRuntimestep):
    """Decide whether to use the elevated ("high point") gate ports after a recent single-level switch.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to read gate-opening global
        variables and the gate-level state history.
    currentRuntimestep : object
        Current simulation time step object.

    Returns
    -------
    bool
        True if the TCD recently (within the lookback window) transitioned
        from a two-level blending configuration down to a single level,
        and the level it transitioned *from* was open at some point in
        that lookback window; False otherwise (including when fewer than
        4 time steps of history are available).

    Notes
    -----
    This implements a specific operational heuristic: when the TCD has
    just dropped from a blended two-level configuration (upper+middle,
    middle+lower, or lower+side) down to operating a single level alone,
    it checks whether the level just vacated was active recently (within
    ``gateOpLookbackDays`` = 45 days). If so, it signals that the
    remaining single level should use its elevated ("high point") port
    rather than the usual one -- presumably to ease the transition or
    avoid an abrupt temperature change by keeping withdrawal closer to the
    just-vacated level's elevation. Only one of the three transition
    patterns can be true at a time, since each requires the other three
    levels to be fully closed.
    """

    # Read the currently open gate count at each of the four levels.
    nSideOpen = getNumGatesOpen(network, currentRuntimestep, 'Side')
    nLowerOpen = getNumGatesOpen(network, currentRuntimestep, 'Lower')
    nMiddleOpen = getNumGatesOpen(network, currentRuntimestep, 'Middle')
    nUpperOpen = getNumGatesOpen(network, currentRuntimestep, 'Upper')

    # Number of days to look back on when checking for a recent op change
    gateOpLookbackDays = 45

    # Determine whether exactly one level is open and, if so, which level
    # would have been the "upper" partner in a recently-ended blend.
    doCheck = False
    # Check if recently switched from upper and middle to just middle
    if nUpperOpen == 0 and nMiddleOpen > 0 and nLowerOpen == 0 and nSideOpen == 0:
        doCheck = True
        checkLevel = 'Upper'
    # Check if recently switched from middle and lower to just lower
    elif nUpperOpen == 0 and nMiddleOpen == 0 and nLowerOpen > 0 and nSideOpen == 0:
        doCheck = True
        checkLevel = 'Middle'
    # Check if recently switched from lower and side to just side
    elif nUpperOpen == 0 and nMiddleOpen == 0 and nLowerOpen == 0 and nSideOpen > 0:
        doCheck = True
        checkLevel = 'Lower'

    if doCheck:
        # Set up
        iCurStep = currentRuntimestep.getStep()
        lbSteps = currentRuntimestep.getRunTimeWindow().getNumLookbackSteps() + 1
        # Not enough simulated history yet to meaningfully check for a
        # recent change; treat as no recent change.
        if iCurStep - lbSteps <= 3:
            return False
        numStepsDay = int(24. * 60. / currentRuntimestep.getRunTimeWindow().getTimeStepMinutes())
        iStartStep = max(lbSteps, iCurStep - gateOpLookbackDays * numStepsDay)
        rts = RunTimeStep()
        # Scan the lookback window for any time step where the
        # just-vacated level still had gates open.
        recentChange = False
        for j in range(iStartStep, iCurStep):
            rts.setStep(j)
            nGatesOpen = getNumGatesOpen(network, rts, checkLevel)
            if nGatesOpen > 0:
                recentChange = True
                break
        return recentChange
    else:
        return False


def getTCDTempAndFlows3ptMinFF(currentRule, network, currentRuntimestep, resElev, targetTemp, tcdMinFlow):
    """Optimize the TCD inlet flow distribution for the currently open gates.

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
    targetTemp : float
        Desired TCD outlet temperature target, used directly (no
        downstream backrouting adjustment in this script).
    tcdMinFlow : float
        Total penstock flow through the TCD.

    Returns
    -------
    tuple of (float, list of float)
        Resulting optimized TCD outlet temperature and the per-inlet flow
        distribution achieving it.

    Raises
    ------
    ValueError
        If the resulting flows do not sum to within 1 cfs of
        ``tcdMinFlow``.

    Notes
    -----
    Unlike getTCDTempAndFlowsForLevel in the main Shasta TCD script, the
    gate counts here are read directly from the currently-reported
    "_open" global variables (via getNumGatesOpen) rather than being
    chosen by this script from a catalog of discrete levels -- this
    script reacts to whatever gate configuration is currently in place
    rather than deciding one. It also re-registers the TCD's gate-index
    groupings with the WQ engine every time step (via
    ``setShastaTCDInfo``), using a ``useHighPt`` value decided fresh each
    time step by checkUseHighPoint, rather than registering this once at
    initialization as in the main script.

    Processing steps:

    1. Compute uncontrollable leakage flow for each of the six leakage
       zones (using the pre/post-2010 coefficient table matching the
       current simulation year), fixing each leakage zone's min/max flow
       bounds to the same computed value.
    2. For the side (lowest) level's deepest point (index 0), apply a
       fixed 35% leakage-adjusted flow fraction directly -- a different
       treatment than the main Shasta TCD script, which has no equivalent
       side-port special case and instead routes all leakage through the
       dedicated leakage-zone calculations above. All other side points,
       and all lower/middle/upper points, use chooseMinFlowFract to set a
       minimum bound with the remaining flow allowed up to the full
       penstock flow (middle/upper additionally capped by the weir-flow
       estimate when only partially submerged, same as the main script).
    3. Call the WQ engine's flow optimizer (``computeWQCDFlows``) with
       these per-inlet bounds, the fixed total flow, and the target
       temperature (used directly, without any downstream adjustment),
       then retrieve the resulting predicted outlet temperature.
    4. Validate that the optimizer's flows sum to within 1 cfs of the
       requested total flow, raising with diagnostic output otherwise.
    """

    wqRun = network.getWQRun()
    engineAdapter = wqRun.getWQEngineAdapter()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    wqcd = rssWQGeometry.getWQControlDevice(currentRule.getController().getReleaseElement())
    tempConstituent = wqRun.getWQConstituent("Water Temperature")

    elevs = getInletElevs(currentRule, network)
    nInletLevels = len(elevs)

    # Get the year for the current timestep
    currentYear = 2010
    hecTime = currentRuntimestep.getHecTime()
    if hecTime:
        currentYear = hecTime.year()

    # Set min/max flow limits through individual inlets to constrain optimization problem
    inletFlowMin = []
    inletFlowMax = []
    # Initialize
    for j in range(nInletLevels):
        inletFlowMin.append(0.)
        inletFlowMax.append(0.)

    # Set leakage (uncontrollable)
    if currentYear < 2010:
        totalLeakageFraction = getTotalLeakageFraction2000(resElev, elevs)
    else:
        totalLeakageFraction = getTotalLeakageFraction2010(resElev, elevs)
    # Gate total numbers, open numbers, and ratios for leakage
    numSideGates = 2
    numLowerGates = 5
    numMiddleGates = 5
    numUpperGates = 5
    # Read currently-open gate counts directly from global variables,
    # since this script has no gate-level decision state of its own.
    numSideGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Side')
    numLowerGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Lower')
    numMiddleGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Middle')
    numUpperGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Upper')
    sideGateRatio = (numSideGates - numSideGatesOpen)/numSideGates
    lowerGateRatio = (numLowerGates - numLowerGatesOpen)/numLowerGates
    middleGateRatio = (numMiddleGates - numMiddleGatesOpen)/numMiddleGates
    # Zone 6 - no gate ratio or elev ratio: fix min=max so it is not a
    # decision variable in the optimizer below.
    zone = 6
    i = getIdxForLeakageZone(zone)
    inletFlowMin[i] = calcLeakage(currentYear, zone, 1., 1., totalLeakageFraction, tcdMinFlow)
    inletFlowMax[i] = inletFlowMin[i]
    # Zone 5 - no gate ratio or elev ratio
    zone = 5
    i = getIdxForLeakageZone(zone)
    inletFlowMin[i] = calcLeakage(currentYear, zone, 1., 1., totalLeakageFraction, tcdMinFlow)
    inletFlowMax[i] = inletFlowMin[i]
    # Zone 4 - dependent on lower gate ratio
    zone = 4
    i = getIdxForLeakageZone(zone)
    inletFlowMin[i] = calcLeakage(currentYear, zone, lowerGateRatio, 1., totalLeakageFraction, tcdMinFlow)
    inletFlowMax[i] = inletFlowMin[i]
    # Zone 3 - dependent on elevation and side gate ratio
    zone = 3
    i = getIdxForLeakageZone(zone)
    iz2 = getIdxForLeakageZone(2)
    elevRatio = max(0., min((resElev-elevs[i])/(elevs[iz2]-elevs[i]), 1.))
    inletFlowMin[i] = calcLeakage(currentYear, zone, sideGateRatio, elevRatio, totalLeakageFraction, tcdMinFlow)
    inletFlowMax[i] = inletFlowMin[i]
    # Zone 2 - dependent on elevation and middle gate ratio
    zone = 2
    i = getIdxForLeakageZone(zone)
    iz1 = getIdxForLeakageZone(1)
    elevRatio = max(0., min((resElev-elevs[i])/(elevs[iz1]-elevs[i]), 1.))
    inletFlowMin[i] = calcLeakage(currentYear, zone, middleGateRatio, elevRatio, totalLeakageFraction, tcdMinFlow)
    inletFlowMax[i] = inletFlowMin[i]
    # Zone 1 - dependent on elevation
    zone = 1
    i = getIdxForLeakageZone(zone)
    elevRatio = max(0., min((resElev-elevs[i])/(1000.-elevs[i]), 1.))
    inletFlowMin[i] = calcLeakage(currentYear, zone, 1., elevRatio, totalLeakageFraction, tcdMinFlow)
    inletFlowMax[i] = inletFlowMin[i]

    # Count how many of the four gate levels have at least one gate open,
    # used by chooseMinFlowFract to scale minimum per-inlet flow bounds.
    numLevelsOpen = 0
    if numSideGatesOpen > 0:
        numLevelsOpen += 1
    if numLowerGatesOpen > 0:
        numLevelsOpen += 1
    if numMiddleGatesOpen > 0:
        numLevelsOpen += 1
    if numUpperGatesOpen > 0:
        numLevelsOpen += 1

    # Decide whether to use elevated ports this time step, then
    # re-register the current gate groupings with the WQ engine to match.
    useHighPt = checkUseHighPoint(network, currentRuntimestep)
    sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(useHighPt)
    engineAdapter.setShastaTCDInfo(resWQGeoSubdom.getId(), wqcd.getId(), sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx)

    # Side (lowest level) gates: the deepest point (idx 0) gets a fixed
    # leakage-adjusted flow fraction rather than the usual min/max bound
    # treatment; the remaining side points use the standard approach.
    if numSideGatesOpen > 0:
        for count, idx in enumerate(sideGateIdx):
            if idx == 0:
                inletFlowMin[idx] = 0.35 * tcdMinFlow * (1.0 - totalLeakageFraction)
                inletFlowMax[idx] = inletFlowMin[idx]
            else:
                flowFract = chooseMinFlowFract(numLevelsOpen, count)
                if count == 1:  # Override the second from the bottom pt to also use 5%/10% min flow fracts
                    flowFract = chooseMinFlowFract(numLevelsOpen, 0)
                inletFlowMin[idx] = flowFract * tcdMinFlow
                inletFlowMax[idx] = tcdMinFlow
                
    # Lower level gates: always fully submerged when open, so each point
    # just gets a minimum fraction and the full flow as a max.
    if numLowerGatesOpen > 0:
        for count, idx in enumerate(lowerGateIdx):
            flowFract = chooseMinFlowFract(numLevelsOpen, count)
            inletFlowMin[idx] = flowFract * tcdMinFlow
            inletFlowMax[idx] = tcdMinFlow

    # Middle level gates: constrained by how many of the tiered inlet
    # points are actually submerged at the current reservoir elevation.
    if numMiddleGatesOpen > 0:
        if resElev > elevs[middleGateIdx[2]]:  # All pts submerged
            for count, idx in enumerate(middleGateIdx):
                flowFract = chooseMinFlowFract(numLevelsOpen, count)
                inletFlowMin[idx] = flowFract * tcdMinFlow
                inletFlowMax[idx] = tcdMinFlow
        elif resElev > elevs[middleGateIdx[1]]:  # Lower 2 pts submerged
            for count, idx in enumerate(middleGateIdx):
                flowFract = chooseMinFlowFract(numLevelsOpen, count)
                inletFlowMin[idx] = flowFract * tcdMinFlow
                inletFlowMax[idx] = tcdMinFlow
                if count == 1:
                    break
        elif resElev > elevs[middleGateIdx[0]]:  # Only lower pt submerged
            # Use weir eqn limitation for this one
            hGateSubmerged = min(45., resElev - elevs[middleGateIdx[0]])
            weirMaxEstimate = calcWeirFlow(hGateSubmerged, numMiddleGatesOpen)
            flowFract = chooseMinFlowFract(numLevelsOpen, 0)
            idx = middleGateIdx[0]
            inletFlowMin[idx] = min(flowFract * tcdMinFlow, weirMaxEstimate)
            inletFlowMax[idx] = min(tcdMinFlow, weirMaxEstimate)
    
    # Upper level gates: same tiered-submergence treatment as middle gates.
    if numUpperGatesOpen > 0:
        if resElev > elevs[upperGateIdx[2]]:  # All pts submerged
            for count, idx in enumerate(upperGateIdx):
                flowFract = chooseMinFlowFract(numLevelsOpen, count)
                inletFlowMin[idx] = flowFract * tcdMinFlow
                inletFlowMax[idx] = tcdMinFlow
        elif resElev > elevs[upperGateIdx[1]]:  # Lower 2 pts submerged
            for count, idx in enumerate(upperGateIdx):
                flowFract = chooseMinFlowFract(numLevelsOpen, count)
                inletFlowMin[idx] = flowFract * tcdMinFlow
                inletFlowMax[idx] = tcdMinFlow
                if count == 1:
                    break
        elif resElev > elevs[upperGateIdx[0]]:  # Only lower pt submerged
            # Use weir eqn limitation for this one
            hGateSubmerged = min(45., resElev - elevs[upperGateIdx[0]])
            weirMaxEstimate = calcWeirFlow(hGateSubmerged, numUpperGatesOpen)
            flowFract = chooseMinFlowFract(numLevelsOpen, 0)
            idx = upperGateIdx[0]
            inletFlowMin[idx] = min(flowFract * tcdMinFlow, weirMaxEstimate)
            inletFlowMax[idx] = min(tcdMinFlow, weirMaxEstimate)
        
    # Hand the per-inlet bounds, fixed total flow, and target temperature
    # directly to the WQ engine's optimizer (no backrouting adjustment
    # applied to targetTemp in this script).
    tcdFlows = engineAdapter.computeWQCDFlows(resWQGeoSubdom, wqcd, tempConstituent, nInletLevels, inletFlowMin, inletFlowMax, tcdMinFlow, targetTemp)
    tcdResult = engineAdapter.getWQResultOptimized(resWQGeoSubdom, wqcd)
    #print("TCD Result: {0:.2f}".format(tcdResult))
    #for j in range(nInletLevels):
    #    print("TCD level {0}".format(j+1))
    #    print("Flow {0:.2f}".format(tcdFlows[j]))

    # Error checking: confirm the optimizer's solution actually respects
    # the fixed total flow constraint within a small tolerance.
    if abs(sum(tcdFlows) - tcdMinFlow) > 1.0:
        print("TCD flows /= Penstock flow")
        print(hecTime.toString())
        print("Sum TCD flows", sum(tcdFlows))
        print("Penstock flow", tcdMinFlow)
        print("Res elevation", resElev)
        print("Target temperature", targetTemp)
        print("Nof upper gates open", numUpperGatesOpen)
        print("Nof middle gates open", numMiddleGatesOpen)
        print("Nof lower gates open", numLowerGatesOpen)
        print("Nof side gates open", numSideGatesOpen)
        print("inletFlowMin", inletFlowMin)
        print("inletFlowMax", inletFlowMax)
        print("tcdFlows", tcdFlows)
        raise ValueError()

    return tcdResult, tcdFlows