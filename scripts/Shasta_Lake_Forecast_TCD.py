from hec.model import RunTimeStep
from hec.heclib.util import HecTime
from hec.rss.model import OpController
from hec.rss.model import OpRule
from hec.rss.model import OpValue     
from hec.rss.model import ReservoirElement
from hec.rss.model import ReservoirDamElement
from hec.rss.plugins.waterquality.model import RssWQGeometry
from hec.rss.wq.model import WQRun
from hec.script import Constants
from hec.rss.model.globalvariable import TimeSeriesGlobalVariable, ScalarGlobalVariable
from hec.wqenginecore import WQEngineAdapter
from hec.wqenginecore import WQResHydro
from hec.wqenginecore import WQException
from hec.wqenginecore import WqIoHydroType
from hec.wqenginecore import WQTime
from hec.wqenginecore.geometry import SubDomain
from hec.wqenginecore.geometry import WQControlDevice
from java.util import Vector
from datetime import date


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

# River outlet elevations (centerline)
#  Name   #   Elev  #
#  RRL    #   742.  #
#  RRM    #   842.  #
#  RRU    #   942.  #

# Script "Global variables"
# TCD Operations
# Operation window: the TCD gate-switching logic below behaves differently
# inside vs. outside this seasonal window (see getForecastTCDTempAndFlows).
startOpDate = date(3000, 5, 1)  # May 1st
endOpDate = date(3000, 12, 1)  # Dec 1st
temperatureThreshold = 0.1
maxViolationDays = 2
checkOpHour = 10  # Hour to do operations check (approx daily average)
gateOpLookbackDays = 2  # For operations outside of target op period
# Variable names
globalVarNameNumUpGates = 'Total_TCDU_gates_forecast'
globalVarNameNumMidGates = 'Total_TCDM_gates_forecast'
globalVarNameNumLowGates = 'Total_TCDL_gates_forecast'
globalVarNameNumSideGates = 'Total_TCDS_gates_forecast'
globalVarNameNumUpGatesHist = 'Total_TCDU_gates_open'
globalVarNameNumMidGatesHist = 'Total_TCDM_gates_open'
globalVarNameNumLowGatesHist = 'Total_TCDL_gates_open'
globalVarNameNumSideGatesHist = 'Total_TCDS_gates_open'
globalVarNameTCDTarget = 'TCD_target'
globalVarNameEquilibTemp = 'KRDD_Equilibrium_Temp'
globalVarNameDSControlLoc = 'Downstream_Control_Loc'
globalVarNameUSTempTarget = 'Upstream_Temp_Target'
stateVarNameTCDViolations = 'TCD_Violations'
stateVarNameTCDLevel = 'TCD_Level'
# Script constants
lastIterationPassNum = 2

# list of alterantives where TCD script is not computed
alts_to_skip = [
	'SacTrnNSF',
]

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
        middle gate groupings (the alternate/elevated operable port at each
        level); if False, uses the "usual" (lower/default) operable port.

    Returns
    -------
    tuple of (list of int, list of int, list of int, list of int)
        Side, lower, middle, and upper gate inlet indices, respectively.

    Notes
    -----
    The upper gate indices (19, 20, 21) do not vary with ``useHighPt``,
    since the port-index table above defines only one tier of upper ports.
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


def getRiverOutletElevs():
    """Return the centerline elevations of the three river outlet structures.

    Returns
    -------
    dict
        Mapping of river outlet element name to centerline elevation (ft):
        "Outlet 16-RRL" (742 ft), "Outlet 15-RRM" (842 ft), and
        "Outlet 14-RRU" (942 ft).
    """
    return {'Outlet 16-RRL': 742., 'Outlet 15-RRM': 842., 'Outlet 14-RRU': 942.}


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
    wqRun = network.getWQRun()
    engineAdapter = wqRun.getWQEngineAdapter()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    wqcd = rssWQGeometry.getWQControlDevice(currentRule.getController().getReleaseElement())
    elevs = engineAdapter.getWQCDInletLevels(resWQGeoSubdom, wqcd)
    return elevs


def getNumGateOptions():
    """Return the catalog of discrete gate-level configurations.

    Returns
    -------
    dict
        Mapping of integer gate level (1 = highest elevation withdrawal,
        7 = lowest) to a 4-element list ``[side, lower, middle, upper]``
        giving the number of open gates at each level for that
        configuration. Levels 2, 4, and 6 are "blending" configurations
        that open gates at two adjacent levels simultaneously; the others
        are single-level configurations.
    """
    # Level number, number of gate openings [side, lower, middle, upper]
    numGateOptions = {1: [0, 0, 0, 5],  # upper only
                      2: [0, 0, 2, 3],  # upper and middle blending
                      3: [0, 0, 5, 0],  # middle only
                      4: [0, 2, 3, 0],  # middle and lower blending
                      5: [0, 5, 0, 0],  # lower only
                      6: [2, 3, 0, 0],  # lower and side blending
                      7: [2, 0, 0, 0]}  # side only
    return numGateOptions


def getGatesForLevel(level):
    """Look up the gate-opening configuration for a given discrete gate level.

    Parameters
    ----------
    level : int
        Gate level key into the dictionary returned by getNumGateOptions
        (1-7).

    Returns
    -------
    list of int
        4-element list ``[side, lower, middle, upper]`` giving the number
        of open gates at each level.
    """
    numGateOptions = getNumGateOptions()
    return numGateOptions[level]


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
    The rule is force-disabled (via checkApplyRule) if WQ is not running,
    the reservoir is outside the active WQ geometry extent, or the current
    alternative name is in the alts_to_skip list (e.g. 'SacTrnNSF'). When
    the rule remains active, this function registers the TCD's gate-index
    groupings (side/lower/middle/upper, using the "usual" rather than
    "high point" ports) with the WQ engine adapter via
    ``setShastaTCDInfo``, a one-time setup step specific to this
    reservoir's optimization logic in the engine.
    """

    applyRule = checkApplyRule(currentRule, network)

    alt = str(network.getAlternative())
        	
    # Handle case where rule is active or disable but WQ for reservoir is not being run
    if not applyRule or alt in alts_to_skip:
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

    Notes
    -----
    This checks two separate conditions required for the rule to be
    meaningful: WQ must be running for this simulation at all, and this
    specific reservoir's subdomain must actually be included in the WQ
    geometry extent currently being simulated.
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
    """Evaluate the Shasta TCD gate/flow rule for the current time step.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object being evaluated.
    network : object
        HEC-ResSim network object, used to look up global/state variables
        and the current WQ run.
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
    The rule only evaluates once ``computeIter >= lastIterationPassNum``
    (2), similar to the ``computeIter > 1`` iteration gates used elsewhere
    in this project, ensuring WQ results are available before TCD
    decisions are made. If the penstock flow is below 1 cfs (treated as
    effectively zero), the previous time step's gate level is reused
    (falling back to the historical record, and finally to level 1 /
    "upper only" if no historical value can be found -- note the
    ``preLevel`` vs. ``prevLevel`` naming: this fallback assignment appears
    intended to set ``prevLevel`` but is written as ``preLevel``, a
    distinct variable that is never used afterward, so the intended
    default of level 1 in this edge case silently does not take effect).
    Otherwise, the full optimization in getForecastTCDTempAndFlows is run
    to find a gate configuration and flow split meeting the water-quality
    target.
    """

    # Only evaluation rule if running WQ (getEvalRule) *and* compute iteration > 0
    #  (On 0th iteration, only local res decisions being evaluated and WQ is not being run yet)
    computeIter = currentRule.getComputeIteration()
    evalRule = currentRule.getEvalRule() and (computeIter >= lastIterationPassNum)

    if evalRule:

        # Get current water quality target
        wqTarget = getGVTemperature(network, currentRuntimestep, globalVarNameTCDTarget)
    
        # Get reservoir elevation, falling back to the previous time step if
        # the current one is not yet valid (e.g. not yet computed this iteration).
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

        # Find any river outlet flow, which affects the target TCD temperature
        # needed to meet the combined downstream temperature (see
        # getTCDTempAndFlowsForLevel).
        riverOutletFlow, riverOutletTemp = getRiverOutletFlowAndTemp(currentRule, network, currentRuntimestep, usePrevStepAsEstimate)

        # If no penstock flow, use same gate configuration as previous time step
        if penstockFlow < 1.0:  # 1 cfs
            prevLevel = getPrevGateLevel(network, currentRuntimestep)
            if not isValidValue(prevLevel):
                # might happen first time step - try getting the historical gate value
                prevLevel = getHistoricalGateLevel(network, currentRuntimestep)
                if prevLevel < 0:  # no historical value found
                    preLevel = 1  # default to upper gates only
            # Don't allow a gate level that would be invalid given the
            # current reservoir elevation.
            elevRestrictionLevel = getElevationRestrictionLevel(currentRule, network, resElev)
            prevLevel = max(prevLevel, elevRestrictionLevel)
            setGateLevel(network, currentRuntimestep, prevLevel)
            nGates = getGatesForLevel(prevLevel)  # [side, lower, middle, upper]
            setGateOpenings(network, currentRuntimestep, nGates)
            tcdFlows = splitFlowForLevel(currentRule, network, prevLevel, penstockFlow)
        else:
            # Find optimal flow distribution in WQCD and resulting average water quality, given a
            #  wq target and total WQCD flow
            tcdTemp, tcdFlows = getForecastTCDTempAndFlows(currentRule, network, currentRuntimestep, resElev, wqTarget, penstockFlow,
                                                           riverOutletFlow, riverOutletTemp)

        resOp.setWQControlDeviceFlowRatios(tcdFlows, currentRule, penstockFlow)

    return None


def splitFlowForLevel(currentRule, network, level, penstockFlow):
    """Evenly split a small penstock flow across all operable inlets at a gate level.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object, used to reach inlet elevation
        information.
    network : object
        HEC-ResSim network object.
    level : int
        Gate level (per getNumGateOptions) whose open gate groups should
        receive flow.
    penstockFlow : float
        Total flow to distribute evenly across the active outlet points.

    Returns
    -------
    list of float
        Flow assigned to each TCD inlet index; zero everywhere except the
        operable inlets belonging to the open gate groups for ``level``,
        each of which receives an equal share of ``penstockFlow``.

    Notes
    -----
    This is used as a simplified fallback (rather than the full
    optimization in getTCDTempAndFlowsForLevel) when penstock flow is too
    small (<1 cfs) to be worth optimizing; see runRuleScript.
    """

    elevs = getInletElevs(currentRule, network)
    nInletLevels = len(elevs)
    tcdFlows = [0. for j in range(nInletLevels)]
    sideIdx, lowerIdx, middleIdx, upperIdx = getGateIndexes(False)
    nGates = getGatesForLevel(level)  # [side, lower, middle, upper]

    # Count active outlet points across all levels with at least one open
    # gate, so the per-point average flow can be computed below.
    nPts = 0
    if nGates[0] > 0:
        nPts += len(sideIdx)
    if nGates[1] > 0:
        nPts += len(lowerIdx)
    if nGates[2] > 0:
        nPts += len(middleIdx)
    if nGates[3] > 0:
        nPts += len(upperIdx)

    avgFlow = penstockFlow / nPts
    if nGates[0] > 0:
        for idx in sideIdx:
            tcdFlows[idx] = avgFlow
    if nGates[1] > 0:
        for idx in lowerIdx:
            tcdFlows[idx] = avgFlow
    if nGates[2] > 0:
        for idx in middleIdx:
            tcdFlows[idx] = avgFlow
    if nGates[3] > 0:
        for idx in upperIdx:
            tcdFlows[idx] = avgFlow
    
    return tcdFlows


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
    Unit detection differs by global-variable type: for a time series
    variable, the DSS units string is inspected for a "c" substring
    (case-insensitive) to decide whether conversion is needed; for a
    scalar variable, a value greater than 32 is assumed to be Fahrenheit
    (since no plausible Celsius water/air temperature would exceed 32
    here) and is converted accordingly. The equilibrium-temperature global
    variable (globalVarNameEquilibTemp) is validated allowing zero as a
    valid value (``checkZero=False``), unlike other temperature variables,
    presumably because an equilibrium temperature of exactly 0 deg C is
    physically plausible and should not be rejected as invalid.
    """

    globVar = network.getGlobalVariable(gvName)
    if not globVar:
        raise NameError("Global variable: " + gvName + " not found.")

    temp = globVar.getCurrentValue(currentRuntimestep)
    if gvName == globalVarNameEquilibTemp:
        validVal = isValidValue(temp, checkZero=False)
    else:
        validVal = isValidValue(temp, checkZero=True)
    if not validVal:
        raise ValueError("Global variable: " + gvName + " has invalid value " +
                         str(temp) + " for time step: " + str(currentRuntimestep.step))

    # Units conversion
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


def getRiverOutletFlowAndTemp(currentRule, network, currentRuntimestep, usePrevStepAsEstimate):
    """Compute the combined flow and flow-weighted average temperature across all river outlets.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object.
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object.
    usePrevStepAsEstimate : bool
        Passed through to each individual outlet's flow lookup; if the
        current time step's flow is unavailable, the previous time step's
        decision value is used as an estimate.

    Returns
    -------
    tuple of (float, float)
        Total combined flow across all river outlets, and the
        flow-weighted average temperature of that combined flow (0 if
        total flow is zero).
    """

    totalFlow = 0.
    totalFlowTemp = 0.
    totalTemp = 0.
    roDict = getRiverOutletElevs()
    
    # Accumulate flow and flow-weighted temperature across each of the
    # three river outlets, so the weighted average can be computed after
    # the loop.
    for roName, roElev in roDict.items():
        flow, temp = getRiverOutletFlowAndTempSingle(currentRule, network, roName, roElev, currentRuntimestep, usePrevStepAsEstimate)
        totalFlow += flow
        totalFlowTemp += flow * temp

    if totalFlow > 0.:
        totalTemp = totalFlowTemp / totalFlow
        
    return totalFlow, totalTemp
    

def getRiverOutletFlowAndTempSingle(currentRule, network, name, elevation, currentRuntimestep, usePrevStepAsEstimate):
    """Get the flow and resulting release temperature for a single river outlet.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object, used to reach the reservoir
        operation and controllers.
    network : object
        HEC-ResSim network object, used to reach the WQ run/engine.
    name : str
        Name of the river outlet element (see getRiverOutletElevs).
    elevation : float
        Centerline elevation of this river outlet, used to query the WQ
        engine for the release temperature at that elevation.
    currentRuntimestep : object
        Current simulation time step object.
    usePrevStepAsEstimate : bool
        If the current time step's flow is unavailable, fall back to the
        previous time step's decision value.

    Returns
    -------
    tuple of (float, float)
        Flow through this outlet and its release temperature. Returns
        ``(0., 0.)`` if the outlet's flow is zero or negative (no
        temperature query is made in that case, since there is no release
        to characterize).

    Raises
    ------
    NameError
        If the named river outlet element cannot be found.
    ValueError
        If the resolved flow is invalid, or if the computed temperature
        falls outside the plausible 0-100 degree range.
    """

    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
        
    rivOutlet = res.getElementByName(name)
    if rivOutlet is None:
        raise NameError("River outlet: " + name + " not found")

    wqRun = network.getWQRun()
    engineAdapter = wqRun.getWQEngineAdapter()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    tempConstit = wqRun.getWQConstituent("Water Temperature")

    roCntrlr = resOp.getControllerForElement(rivOutlet)
    flow = roCntrlr.getCurMinOpValue(currentRuntimestep).value;
    # Fall back to the previous time step's decision value if the current
    # flow is not yet valid (e.g. not yet computed this iteration).
    if not isValidValue(flow) and usePrevStepAsEstimate:
        rts = RunTimeStep()
        rts.setStep(currentRuntimestep.getStep() - 1)
        flow = roCntrlr.getDecisionValue(rts)
    if not isValidValue(flow):
        raise ValueError("Invalid value: " + str(flow) + " for " + name + " flow for time step: " + str(currentRuntimestep.step))
    
    if flow > 0.:
        # Find temperature
        temp = engineAdapter.getWQResultForReleaseAtElev(resWQGeoSubdom, tempConstit, flow, elevation)
        if temp > 100. or temp < 0.:
            message = "Temperature outside of range (0,100) for flow " + str(flow) + " elevation " + str(elevation) + " temperature " + str(temp)
            print(message)
            raise ValueError(message)
        return flow, temp
    else:
        return 0., 0.


def getNumGatesOpen(network, currentRuntimestep, levelName, isHistorical=False):
    """Read the current (or historical) number of open gates for a given level.

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
    isHistorical : bool, optional
        If True, reads the historical "_open" global variable instead of
        the forecast variable. Defaults to False.

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
    """

    maxGates = 5
    # Select the forecast or historical global variable name based on the
    # requested gate level and whether historical data was requested.
    if levelName.lower() == 'upper':
        if isHistorical:
            globalVarName = globalVarNameNumUpGatesHist
        else:
            globalVarName = globalVarNameNumUpGates
    elif levelName.lower() == 'middle':
        if isHistorical:
            globalVarName = globalVarNameNumMidGatesHist
        else:
            globalVarName = globalVarNameNumMidGates
    elif levelName.lower() == 'lower':
        if isHistorical:
            globalVarName = globalVarNameNumLowGatesHist
        else:
            globalVarName = globalVarNameNumLowGates
    elif levelName.lower() == 'side':
        # Side level caps out at 2 gates rather than 5.
        if isHistorical:
            globalVarName = globalVarNameNumSideGatesHist
        else:
            globalVarName = globalVarNameNumSideGates
        maxGates = 2
    else:
        raise NameError("Gate level: " + levelName + " not recognized.")
        
    # Read the resolved global variable and validate it's within the
    # physically possible range of gate counts for this level.
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    numGates = globVar.getCurrentValue(currentRuntimestep)

    #network.printMessage('read global var '+globalVarName+': '+str(numGates))

    if numGates < 0 or numGates > maxGates:
        raise ValueError("Global variable: " + globalVarName + " has invalid value " +
                         str(numGates) + " for time step: " + str(currentRuntimestep.step))
    else:
        return numGates


def setNumGatesOpen(network, currentRuntimestep, levelName, numGates):
    """Write the current number of open gates for a given level.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up and set the relevant
        global variable.
    currentRuntimestep : object
        Current simulation time step object.
    levelName : str
        Gate level name: "upper", "middle", "lower", or "side"
        (case-insensitive).
    numGates : int
        Number of open gates to set at this level.

    Returns
    -------
    None

    Raises
    ------
    NameError
        If ``levelName`` is not recognized, or the resolved global
        variable is not found.
    ValueError
        If ``numGates`` is negative or exceeds the maximum gate count for
        that level (5 for upper/middle/lower, 2 for side).

    Notes
    -----
    Unlike getNumGatesOpen, this only ever writes to the forecast global
    variable (there is no historical variant to write to, since historical
    values represent observed, not forecast, operations).
    """

    maxGates = 5
    # Unlike getNumGatesOpen, there is no historical variant here -- this
    # always targets the forecast global variable.
    if levelName.lower() == 'upper':
        globalVarName = globalVarNameNumUpGates
    elif levelName.lower() == 'middle':
        globalVarName = globalVarNameNumMidGates
    elif levelName.lower() == 'lower':
        globalVarName = globalVarNameNumLowGates
    elif levelName.lower() == 'side':
        globalVarName = globalVarNameNumSideGates
        maxGates = 2
    else:
        raise NameError("Gate level: " + levelName + " not recognized.")
        
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    
    # Validate before writing, so an out-of-range value never reaches the
    # stored global variable.
    if numGates < 0 or numGates > maxGates:
        raise ValueError("Global variable: " + globalVarName + " has invalid value " +
                         str(numGates) + " for time step: " + str(currentRuntimestep.step))
                    
    globVar.setCurrentValue(currentRuntimestep, numGates)


def setGateOpenings(network, currentRuntimestep, nGates):
    """Write the number of open gates for all four levels at once.

    Parameters
    ----------
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object.
    nGates : list of int
        4-element list ``[side, lower, middle, upper]`` of gate counts, as
        returned by getGatesForLevel.

    Returns
    -------
    None
    """
    setNumGatesOpen(network, currentRuntimestep, 'side', nGates[0])
    setNumGatesOpen(network, currentRuntimestep, 'lower', nGates[1])
    setNumGatesOpen(network, currentRuntimestep, 'middle', nGates[2])
    setNumGatesOpen(network, currentRuntimestep, 'upper', nGates[3])


def setGateLevel(network, currentRuntimestep, level):
    """Store the current discrete gate level in the TCD level state variable.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the state variable.
    currentRuntimestep : object
        Current simulation time step object.
    level : int
        Gate level value to store (per getNumGateOptions).

    Returns
    -------
    None
    """
    sv = network.getStateVariable(stateVarNameTCDLevel)
    sv.setValue(currentRuntimestep, level)


def getPrevGateLevel(network, currentRuntimestep):
    """Read the TCD gate level stored at the previous time step.

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
        Gate level value stored at the previous time step (step index
        clamped to a minimum of 0, so the first time step reads its own
        step 0 value rather than a negative index).
    """
    sv = network.getStateVariable(stateVarNameTCDLevel)
    iCurStep = currentRuntimestep.getStep()
    iPrevStep = max(0, iCurStep - 1)
    rts = RunTimeStep()
    rts.setStep(iPrevStep)
    return sv.getValue(rts)


def getHistoricalGateLevel(network, currentRuntimestep):
    """Infer the discrete gate level from historical (observed) gate-opening counts.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up historical gate-opening
        global variables.
    currentRuntimestep : object
        Current simulation time step object.

    Returns
    -------
    int
        Gate level (per getNumGateOptions) whose open/closed pattern
        matches the historical record at each of the four gate levels.

    Raises
    ------
    ValueError
        If no cataloged gate-level configuration's open/closed pattern
        matches the historical record.

    Notes
    -----
    Matching is done on open/closed status only (nonzero vs. zero gate
    count at each level), not on the exact number of gates open; a level
    "matches" if, for every gate group, the historical count and the
    cataloged count are both zero or both nonzero.
    """

    nGatesHist = []
    gateLevelNames = ['side', 'lower', 'middle', 'upper']
    # Read the historical open/closed gate counts for each level first, so
    # they can be compared against every cataloged configuration below.
    for gateLevelName in gateLevelNames:
        nOpen = getNumGatesOpen(network, currentRuntimestep, gateLevelName, isHistorical=True)
        nGatesHist.append(nOpen)
        #network.printMessage(gateLevelName+' nOpen '+str(nOpen))

    gateOptions = getNumGateOptions()
    level = -1
    # Search cataloged configurations for one whose open/closed pattern
    # (not exact gate counts) matches the historical record at every level.
    for level, nGates in gateOptions.items():
        matches = True
        #network.printMessage('gateOptions level '+str(level)+str(nGates))
        for gateLevel in range(len(gateLevelNames)):
            #network.printMessage('gatelevel '+str(gateLevel)+' histGate: '+str(nGatesHist[gateLevel])+' gateOp: '+str(nGates[gateLevel]))
            if nGatesHist[gateLevel] == 0 and nGates[gateLevel] != 0:
                matches = False
            elif nGatesHist[gateLevel] != 0 and nGates[gateLevel] == 0:
                matches = False
        if matches:
            break
    if not matches:
        message = "Historical gate level not found for time step " + str(currentRuntimestep.getStep()) + "\n"
        for j, gateLevelName in enumerate(gateLevelNames):
            message += gateLevelName + " gates open: " + str(nGatesHist[j]) + "\n"
        raise ValueError(message)

    return level


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
    the current time step, so it functions as a single persistent counter
    across the simulation rather than a per-time-step time series.
    """
    sv = network.getStateVariable(stateVarNameTCDViolations)
    rts = RunTimeStep()
    rts.setStep(1)
    sv.setValue(rts, numViolations)


def setUpstreamTempTarget(network, currentRuntimestep, target):
    """Store the back-calculated upstream (at-dam) temperature target.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the global variable.
    currentRuntimestep : object
        Current simulation time step object.
    target : float
        Back-calculated temperature target at the TCD outlet (i.e. at
        Shasta Dam), as computed by backRouteWQTarget2.

    Returns
    -------
    None
    """
    gv = network.getGlobalVariable(globalVarNameUSTempTarget)
    gv.setCurrentValue(currentRuntimestep, target)


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
    sv = network.getStateVariable(stateVarNameTCDViolations)
    rts = RunTimeStep()
    rts.setStep(1)
    return sv.getValue(rts)


def isValidValue(value, checkZero=True):
    """Check whether a numeric value is defined and (optionally) non-negative.

    Parameters
    ----------
    value : float
        Value to validate.
    checkZero : bool, optional
        If True (default), values less than 0 are considered invalid. If
        False, only ``None`` and ``Constants.UNDEFINED_DOUBLE`` are
        checked, allowing negative (and zero) values through.

    Returns
    -------
    bool
        False if ``value`` is ``None``, equals
        ``Constants.UNDEFINED_DOUBLE``, or (if ``checkZero``) is negative;
        True otherwise.

    Notes
    -----
    Unlike the ``isValidValue`` used in the other rule scripts in this
    project, this version checks ``value is None`` rather than
    ``not value`` (so a value of exactly 0.0 is not rejected on that basis
    alone) and exposes the negative-value check as an optional
    ``checkZero`` parameter so callers like getGVTemperature can allow
    negative or zero temperatures where physically plausible.
    """
    if value is None:
        return False
    elif value == Constants.UNDEFINED_DOUBLE:
        return False
    elif checkZero and value < 0.:
        return False
    else:
        return True


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

    Notes
    -----
    Leakage-zone percentage contributions (upper/middle/lower) are
    hard-coded here per the cited report table; see getTotalLeakageFraction
    for how they combine with reservoir elevation.
    """
    upperFraction = 13.09/100.
    middleFraction = 19.7/100.
    lowerFraction = 12.65/100.
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

    Notes
    -----
    The middle-zone leakage fraction is 0 in this calibration (unlike the
    pre-2010 table), reflecting a presumed physical change (e.g. sealing)
    at that leakage zone.
    """
    upperFraction = 16.3/100.
    middleFraction = 0./100.
    lowerFraction = 15.75/100.
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
    comment notes "we have bigger concerns than leakage at this point,"
    i.e. a reservoir elevation this low is a far more serious problem than
    estimating leakage precisely.
    """

    #grossFraction = 0.2  # Assumed leakage fraction when pool elev > 1000. and all gates closed
    topElev = 1000.
    z1Elev = elevs[getIdxForLeakageZone(1)]
    z2Elev = elevs[getIdxForLeakageZone(2)]
    z3Elev = elevs[getIdxForLeakageZone(3)]
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

    Notes
    -----
    Combines a base coefficient and a gate-ratio-dependent coefficient
    (from the regression table) with the elevation ratio, total leakage
    fraction, and total flow to produce an absolute leakage flow estimate.
    """
    tableVals = getLeakageTableVals(currentYear, zone)
    leakageFlow = (tableVals[0] + tableVals[1]*gateRatio)/100. * elevationRatio * totalLeakFract * flow
    return leakageFlow


def chooseMinFlowFract(nOpenLevels, ptNum):
    """Choose the minimum flow fraction for an inlet point in the flow-split optimization.

    Parameters
    ----------
    nOpenLevels : int
        Number of gate levels currently open.
    ptNum : int
        Index of the inlet point within its gate level (0 = lowest).

    Returns
    -------
    float
        Minimum flow fraction (currently always 0.01, i.e. 1%) to assign
        as a lower bound for this inlet point in the optimization.

    Notes
    -----
    The branching on ``nOpenLevels`` and ``ptNum`` currently always
    resolves to the same constant (0.01) regardless of input; the
    conditional structure appears to be a placeholder for previously (or
    potentially in the future) differentiated minimum-flow logic, but as
    written it has no effect on the returned value.
    """
    if ptNum == 0:
        if nOpenLevels == 1:
            minFF = 0.01
        else:
            minFF = 0.01
    else:
        if nOpenLevels == 1:
            minFF = 0.01
        else:
            minFF = 0.01
    return minFF


def checkRecentGateOp(network, currentRuntimestep):
    """Check whether the TCD gate level has changed within a recent lookback window.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the gate-level state
        variable.
    currentRuntimestep : object
        Current simulation time step object.

    Returns
    -------
    tuple of (bool, int or float)
        Whether the gate level changed at any point within the lookback
        window, and the gate level at the immediately preceding time step.

    Notes
    -----
    The lookback window spans ``gateOpLookbackDays`` days (converted to
    time steps using the model's time-step size), but is clamped so it
    never searches before the first valid lookback step of the run
    (``lbSteps + 1``). This is used outside the main seasonal operation
    window (see getForecastTCDTempAndFlows) to avoid switching gates too
    frequently.
    """

    stateVarTCDlevel = network.getStateVariable(stateVarNameTCDLevel)
    iCurStep = currentRuntimestep.getStep()
    lbSteps = currentRuntimestep.getRunTimeWindow().getNumLookbackSteps()

    numStepsDay = int(24. * 60. / currentRuntimestep.getRunTimeWindow().getTimeStepMinutes())
    iStartStep = max(lbSteps+1, iCurStep - gateOpLookbackDays * numStepsDay)
    recentChange = False
    rts = RunTimeStep()
    rts.setStep(iStartStep)
    holdLevel = stateVarTCDlevel.getValue(rts)
    # Scan every step between the lookback start and the current step for
    # any change away from the level held at the start of the window.
    for j in range(iStartStep+1, iCurStep):
        rts.setStep(j)
        level = stateVarTCDlevel.getValue(rts)
        if level != holdLevel:
            recentChange = True
            break
    rts.setStep(iCurStep-1)
    prevLevel = stateVarTCDlevel.getValue(rts)

    return recentChange, prevLevel


def getElevationRestrictionLevel(currentRule, network, resElev):
    """Determine the highest (most restrictive) gate level allowed at a given reservoir elevation.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object, used to reach TCD inlet
        elevations.
    network : object
        HEC-ResSim network object.
    resElev : float
        Current reservoir elevation.

    Returns
    -------
    int
        The lowest-numbered (least restrictive / highest withdrawal
        elevation) gate level whose elevation restriction is satisfied by
        ``resElev``, or 0 if no restriction applies (i.e. even level 1 is
        unrestricted at this elevation... see Notes for the actual
        iteration order).

    Notes
    -----
    Restrictions are only defined for levels 1-4 (blending/single-level
    upper and middle configurations); levels 5-7 have no defined
    restriction and default to 0 via the ``except KeyError`` fallback.
    Iteration order follows ``nGateOptions.items()`` (levels 1 through 7
    in the catalog's natural order), returning as soon as a level's
    restriction is satisfied -- in practice this does not guarantee the
    most restrictive or least restrictive match is found first depending
    on dict iteration order in the runtime's Python/Jython version, but
    is preserved as-is. Requirements: "upper only" (level 1) needs the
    upper gate invert submerged by at least 35 ft; "upper and middle"
    (level 2) needs only the upper invert submerged; "middle only"
    (level 3) needs the middle invert submerged by at least 35 ft;
    "middle and lower" (level 4) needs only the middle invert submerged.
    """
    elevs = getInletElevs(currentRule, network)
    nGateOptions = getNumGateOptions()  # dictionary of options for gates (e.g., level 1 = [0,0,0,5] upper only)
    sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(False)
    elevRestrictions = {1: elevs[upperGateIdx[0]] + 35.,  # upper only needs invert submerged by at least 35'
                        2: elevs[upperGateIdx[0]],        # upper and middle needs upper invert submerged
                        3: elevs[middleGateIdx[0]] + 35.,  # middle only needs invert submerged by at least 35'
                        4: elevs[middleGateIdx[0]]}        # middle and lower needs middle invert submerged
    # Loop over the options, returning the first level (in catalog order)
    # whose elevation restriction is satisfied by the current reservoir
    # elevation; levels without a defined restriction default to 0.
    for level, nGates in nGateOptions.items():
        try:
            elevRestriction = elevRestrictions[level]
        except KeyError:
            elevRestriction = 0.
        if resElev > elevRestriction:
            return level
    return 0


def getTotalGateFlows(tcdFlows):
    """Sum per-inlet flows into totals for each of the four gate levels.

    Parameters
    ----------
    tcdFlows : list of float
        Per-inlet flow values, indexed as in the port-index reference
        table.

    Returns
    -------
    tuple of (float, float, float, float)
        Total flow through the side, lower, middle, and upper gate groups
        respectively (using the "usual", not "high point", port
        groupings).
    """
    useHighPt = False
    sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(useHighPt)
    
    totalUpperFlow = 0.
    for idx in upperGateIdx:
        totalUpperFlow += tcdFlows[idx]
    totalMiddleFlow = 0.
    for idx in middleGateIdx:
        totalMiddleFlow += tcdFlows[idx]
    totalLowerFlow = 0.
    for idx in lowerGateIdx:
        totalLowerFlow += tcdFlows[idx]
    totalSideFlow = 0.
    for idx in sideGateIdx:
        totalSideFlow += tcdFlows[idx]
    return totalSideFlow, totalLowerFlow, totalMiddleFlow, totalUpperFlow


def getTotalLeakageFlow(tcdFlows):
    """Sum per-inlet flows across all leakage-zone inlets.

    Parameters
    ----------
    tcdFlows : list of float
        Per-inlet flow values, indexed as in the port-index reference
        table.

    Returns
    -------
    float
        Total flow attributed to leakage zones (indices from
        getLeakageIndexes).
    """
    leakageIdx = getLeakageIndexes()
    totalLeakageFlow = 0.
    for idx in leakageIdx:
        totalLeakageFlow += tcdFlows[idx]
    return totalLeakageFlow
    

def getForecastTCDTempAndFlows(currentRule, network, currentRuntimestep, resElev, targetTemp, tcdMinFlow, 
                               riverOutletFlow, riverOutletTemp):
    """Determine the forecast TCD gate level, outlet temperature, and flow split for the current time step.

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
        Desired downstream water-quality temperature target.
    tcdMinFlow : float
        Total penstock flow to be distributed through the TCD.
    riverOutletFlow : float
        Combined flow through the river outlets (bypassing the TCD).
    riverOutletTemp : float
        Flow-weighted average temperature of the river outlet flow.

    Returns
    -------
    tuple of (float, list of float)
        Resulting TCD outlet temperature and the per-inlet flow
        distribution achieving it.

    Raises
    ------
    ValueError
        Propagated from findTCDTempAndFlowsNoRestriction if no gate
        configuration can be found that meets the target.

    Notes
    -----
    This is the core decision logic for the TCD gate-switching strategy,
    with different behavior depending on where the current time step falls:

    - **First time step(s)** (within the lookback window): tries to adopt
      the historical gate level if one can be matched; otherwise searches
      for the uppermost unrestricted level that meets the target
      temperature via findTCDTempAndFlowsNoRestriction.
    - **Not the daily check hour**: simply holds the previous gate level
      (subject to elevation restriction) without re-evaluating whether it
      still meets the target -- gate decisions are only reconsidered once
      per day, at ``checkOpHour``.
    - **At the check hour, outside the seasonal operation window**
      (``startOpDate``-``endOpDate``): the only requirement is to avoid
      switching gates too often (via checkRecentGateOp); if a recent
      change already occurred, hold the previous level, otherwise search
      unrestricted for the best level.
    - **At the check hour, inside the seasonal operation window**: gates
      may only move one direction -- from upper (shallower) levels toward
      lower (deeper) levels -- never back up except when reservoir
      elevation forces a downward move. The current level is evaluated
      against the target; violations accumulate over
      ``maxViolationDays`` consecutive days before moving down a level
      (with some additional logic to catch a level switch that
      overshoots and moves too cold, trying to move back up one level if
      that still meets the target).

    The one-way (upper-to-lower only) movement rule inside the operation
    period, combined with the violation-day counter, is intended to
    prevent the TCD from oscillating between adjacent gate levels in
    response to small temperature fluctuations near the target.
    """

    curTime = currentRuntimestep.getHecTime()
    #network.printMessage(curTime.toString())
    try:
        curDate = date(3000, curTime.month(), curTime.day())
    except ValueError: # Leap year issue
        curDate = date(3000, curTime.month(), curTime.day()-1)
    curHour = curTime.hour()
    iCurStep = currentRuntimestep.getStep()
    insideOpPeriod = curDate >= startOpDate and curDate <= endOpDate
    
    elevRestrictionLevel = getElevationRestrictionLevel(currentRule, network, resElev)
    #network.printMessage('elevRestrictionLevel: '+str(elevRestrictionLevel))
    gateOptions = getNumGateOptions()
    nGateOptions = len(gateOptions)

    useHighPt = False
    sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(useHighPt)

    # For first time step(s), use the historical record if possible
    # iCurStep comes in at num LB steps + 1 for first time step
    if iCurStep <= currentRuntimestep.getRunTimeWindow().getNumLookbackSteps() + 1:
        histLevel = getHistoricalGateLevel(network, currentRuntimestep)
        #network.printMessage('histLevel: '+str(histLevel))
        if histLevel > 0:  # valid value found
            level = max(histLevel, elevRestrictionLevel)
            tcdTemp, tcdFlows = setDataForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, 
                                                tcdMinFlow, riverOutletFlow, riverOutletTemp, level)
            #network.printMessage('histlevel tcdTemp: '+str(tcdTemp))
        else:  # find a set of gate openings that hits the target temperature without any operating restrictions
            tcdTemp, tcdFlows = findTCDTempAndFlowsNoRestriction(currentRule, network,
                                   currentRuntimestep, resElev, elevRestrictionLevel, targetTemp, 
                                   tcdMinFlow, riverOutletFlow, riverOutletTemp)
            #network.printMessage('unrestricted tcdTemp: '+str(tcdTemp))
        setTempTargetViolations(network, 0)
        return tcdTemp, tcdFlows
    else:  # Not the first time step
        prevGateLevel = getPrevGateLevel(network, currentRuntimestep)
        # Only one check per day
        if curHour != checkOpHour:
            level = max(prevGateLevel, elevRestrictionLevel)
            tcdTemp, tcdFlows = setDataForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, 
                                                tcdMinFlow, riverOutletFlow, riverOutletTemp, level)
            return tcdTemp, tcdFlows
        else:
            # Outside of operation period - only requirement is don't switch gates too often
            if not insideOpPeriod:
                recentChange, prevGateLevel = checkRecentGateOp(network, currentRuntimestep)
                setTempTargetViolations(network, 0)
                if recentChange:
                    level = max(prevGateLevel, elevRestrictionLevel)
                    tcdTemp, tcdFlows = setDataForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, 
                                                        tcdMinFlow, riverOutletFlow, riverOutletTemp, level)
                    return tcdTemp, tcdFlows
                else:
                    tcdTemp, tcdFlows = findTCDTempAndFlowsNoRestriction(currentRule, network,
                                           currentRuntimestep, resElev, elevRestrictionLevel, targetTemp, 
                                           tcdMinFlow, riverOutletFlow, riverOutletTemp)
                    return tcdTemp, tcdFlows
            # Inside operation period - one way movement from upper to lower levels
            else:
                #network.printMessage("**************************************************************************************")
                #network.printMessage(curTime.toString())
                if prevGateLevel < elevRestrictionLevel:  # move down a gate level if forced by reservoir elevation
                    level = elevRestrictionLevel
                    tcdTemp, tcdFlows = setDataForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, 
                                                        tcdMinFlow, riverOutletFlow, riverOutletTemp, level)
                    setTempTargetViolations(network, 0)
                    return tcdTemp, tcdFlows
                else:
                    # Evaluate the current (previous) gate level against the target.
                    nGates = getGatesForLevel(prevGateLevel)
                    targetTemp, tcdTemp, tcdFlows = getTCDTempAndFlowsForLevel(currentRule, network, currentRuntimestep, 
                                           resElev, targetTemp, tcdMinFlow, nGates, riverOutletFlow, riverOutletTemp)
                    numViolations = getTempTargetViolations(network)
                    
                    totSideFlow, totLowFlow, totMidFlow, totUpFlow = getTotalGateFlows(tcdFlows)
                    totLeakFlow = getTotalLeakageFlow(tcdFlows)
                    flowPctCutoff = 0.10  # can't be less than 3% = 1 + 1 + 1 min flow fractions

                    # Track consecutive days where the current level runs too
                    # warm (a real violation) vs. too cold (overshoot, where we
                    # may be able to move back up a level) vs. an acceptable match.
                    if tcdTemp > targetTemp + temperatureThreshold:
                        numViolations += 1
                        setTempTargetViolations(network, numViolations)
                    else:
                        if tcdTemp < targetTemp - 0.5:   # We switched levels prematurely and now we're way too cold
                            # See if we can go up a level and still meet the target
                            # Turn this off for downstream operations
                            if prevGateLevel > 100 and prevGateLevel > elevRestrictionLevel:
                                nGates2 = getGatesForLevel(prevGateLevel-1)
                                targetTemp2, tcdTemp2, tcdFlows2 = getTCDTempAndFlowsForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, tcdMinFlow, nGates2, riverOutletFlow, riverOutletTemp)
                                if tcdTemp2 < targetTemp2 + temperatureThreshold:
                                    prevGateLevel = prevGateLevel-1
                                setTempTargetViolations(network, 0)
                        else:
                            if prevGateLevel == 6: # lower and side blending
                                totLowFlow = tcdFlows[lowerGateIdx[1]] + tcdFlows[lowerGateIdx[2]]
                                if totLowFlow / tcdMinFlow < flowPctCutoff:
                                    numViolations += 1  # increment violations to move to a lower level
                                    setTempTargetViolations(network, numViolations)
                                else:
                                    setTempTargetViolations(network, 0)
                            else:
                                setTempTargetViolations(network, 0)
                    # Only actually switch down a level once violations have
                    # accumulated for maxViolationDays consecutive checks.
                    if numViolations >= maxViolationDays and prevGateLevel < nGateOptions:  # move to next level down in elevation
                        level = prevGateLevel + 1
                        tcdTemp, tcdFlows = setDataForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, 
                                    tcdMinFlow, riverOutletFlow, riverOutletTemp, level)
                        if level == 3 or level == 5:  # middle only or lower only
                            if tcdTemp < targetTemp + temperatureThreshold:
                                setTempTargetViolations(network, 0)
                        else:
                            setTempTargetViolations(network, 0)
                        return tcdTemp, tcdFlows
                    else:
                        level = prevGateLevel
                        setGateLevel(network, currentRuntimestep, level)
                        setGateOpenings(network, currentRuntimestep, nGates)
                        return tcdTemp, tcdFlows


def setDataForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, 
                    tcdMinFlow, riverOutletFlow, riverOutletTemp, level):
    """Commit a chosen gate level and compute its optimized temperature and flows.

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
        Desired downstream temperature target.
    tcdMinFlow : float
        Total penstock flow through the TCD.
    riverOutletFlow : float
        Combined river outlet flow.
    riverOutletTemp : float
        Flow-weighted average river outlet temperature.
    level : int
        Gate level to commit (writes gate-level state and gate-opening
        global variables).

    Returns
    -------
    tuple of (float, list of float)
        Resulting optimized TCD temperature and per-inlet flow
        distribution for the given level.
    """
    setGateLevel(network, currentRuntimestep, level)
    nGates = getGatesForLevel(level)
    setGateOpenings(network, currentRuntimestep, nGates)
    targetTemp, tcdTemp, tcdFlows = getTCDTempAndFlowsForLevel(currentRule, network, currentRuntimestep, 
                                       resElev, targetTemp, tcdMinFlow, nGates, riverOutletFlow, riverOutletTemp)
    return tcdTemp, tcdFlows


def findTCDTempAndFlowsNoRestriction(currentRule, network, currentRuntimestep, resElev, elevRestrictionLevel,
                                     targetTemp, tcdMinFlow, riverOutletFlow, riverOutletTemp):
    """Search all unrestricted gate levels for the uppermost one meeting the temperature target.

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
    elevRestrictionLevel : int
        Minimum (lowest-numbered) gate level allowed given current
        elevation; levels below this are skipped.
    targetTemp : float
        Desired downstream temperature target.
    tcdMinFlow : float
        Total penstock flow through the TCD.
    riverOutletFlow : float
        Combined river outlet flow.
    riverOutletTemp : float
        Flow-weighted average river outlet temperature.

    Returns
    -------
    tuple of (float, list of float)
        Resulting TCD temperature and per-inlet flow distribution for the
        selected gate level.

    Raises
    ------
    ValueError
        If no level in the catalog (at or above ``elevRestrictionLevel``)
        can produce a temperature within the required tolerance of the
        target.

    Notes
    -----
    This is used when no reliable prior gate state is available (first
    time step with no historical match, or outside the operation period
    with no recent gate change) and the model must pick a level from
    scratch. Iterates through gate levels in catalog order (1 = highest
    elevation withdrawal downward); for each level, if the resulting
    temperature is within a small buffer (0.02 deg) of the target, that
    level is accepted -- unless the *previous* (one level higher)
    candidate was actually closer to the target, in which case the
    function backs up and returns that higher level's result instead
    (preferring the least restrictive level that still adequately meets
    the target). If no level ever gets within tolerance, the last
    (lowest, most restrictive) level in the catalog is accepted
    regardless. If the loop somehow completes without returning (e.g. an
    empty catalog), a ValueError is raised.
    """
    
    # Loop over the options
    nGateOptions = getNumGateOptions()  # dictionary of options for gates (e.g., level 1 = [0,0,0,5] upper only)
    errorCode = -9999.
    levelAbvResult = -9999.
    for level, nGates in nGateOptions.items():
        if level >= elevRestrictionLevel:
            targetTemp, tcdTemp, tcdFlows = getTCDTempAndFlowsForLevel(currentRule, network, currentRuntimestep, 
                                               resElev, targetTemp, tcdMinFlow, nGates, riverOutletFlow, riverOutletTemp)
            if tcdTemp != errorCode and tcdTemp < targetTemp + 0.02:  # small buffer
                # This level meets the target; but if the previous
                # (higher/less restrictive) level we tried was actually
                # closer to the target, prefer that one instead.
                if level > 1 and abs(levelAbvResult - targetTemp) < abs(tcdTemp - targetTemp):
                    setGateLevel(network, currentRuntimestep, level - 1)
                    setGateOpenings(network, currentRuntimestep, levelAbvNumGates)
                    return levelAbvResult, levelAbvFlows
                else:
                    setGateLevel(network, currentRuntimestep, level)
                    setGateOpenings(network, currentRuntimestep, nGates)
                    return tcdTemp, tcdFlows
            elif tcdTemp != errorCode and level == len(nGateOptions):
                # Last (most restrictive) level in the catalog: accept it
                # even if it didn't get within the small buffer above.
                setGateLevel(network, currentRuntimestep, level)
                setGateOpenings(network, currentRuntimestep, nGates)
                return tcdTemp, tcdFlows
            levelAbvResult = tcdTemp
            levelAbvFlows = tcdFlows
            levelAbvNumGates = nGates

    raise ValueError("No optimized TCD flows found")
    

def getDSControlLoc(network,currentRuntimestep):
    """Read the configured downstream temperature-control location index.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to look up the global variable.
    currentRuntimestep : object
        Current simulation time step object (unused directly, but present
        for interface consistency with other global-variable readers).

    Returns
    -------
    int
        Downstream control location index: 0 (at Shasta Dam), 1 (Highway
        44), 2 (CCR), or 3 (Ball's Ferry).

    Raises
    ------
    NameError
        If the global variable is not found, has no value, or has a value
        outside the valid 0-3 range.

    Notes
    -----
    The commented-out fallback code below the raise (defaulting to
    location 2, "Abv Clear Cr", with a warning instead of raising) is
    unreachable dead code -- it sits after an unconditional ``raise``
    inside the ``if fail:`` branch, so it can never execute as written.
    It is preserved as-is since it may represent previously intended
    (or possibly future) fallback behavior.
    """
    gv = network.getGlobalVariable(globalVarNameDSControlLoc)

    fail=False
    if not gv:
        fail = True
    else:
        loc = gv.getValue()
        if loc is None:
            fail = True
        elif loc < 0 or loc > 3:
            fail = True
    if fail:
        raise NameError("Global variable: " + globalVarNameDSControlLoc + " not found.")
        #if currentRuntimestep.getStep() < 2:        
        #	network.getRssRun().printWarningMessage("Warning: Forecast_TCS script can't understand downstream control loc " +
        #                                        globalVarNameDSControlLoc +". Assuming default of 'Abv Clear Cr'.")
        #return 2
    else:
    	return gv.getValue()


def getKeswickOutflow(currentRule, network, currentRuntimestep, usePrevStepAsEstimate=True):
    """Get the current (or estimated) outflow from Keswick Reservoir.

    Parameters
    ----------
    currentRule : object
        HEC-ResSim scripted rule object (unused directly; present for
        interface consistency with other flow-lookup functions in this
        file).
    network : object
        HEC-ResSim network object, used to locate the Keswick Reservoir
        element.
    currentRuntimestep : object
        Current simulation time step object.
    usePrevStepAsEstimate : bool, optional
        If the current/decision flow is unavailable or below 0.1 cfs, fall
        back to the previous time step's decision value. Defaults to True.

    Returns
    -------
    float
        Keswick Reservoir outflow (cfs).

    Raises
    ------
    NameError
        If the "Keswick Reservoir" network element cannot be found.
    ValueError
        If the resolved flow is invalid even after the fallback.

    Notes
    -----
    Keswick is immediately downstream of Shasta Dam; its outflow is used
    in backRouteWQTarget2 to estimate Sacramento River travel velocity via
    a power-law approximation.
    """

    keswickName = "Keswick Reservoir"
    kesElem = network.findElement(keswickName)
    if not kesElem:
        raise NameError("Network element: " + keswickName + " not found.")
    kesOpSet = kesElem.getReservoirOp()   #.getOperationSet(opsetId)
    rde = ReservoirDamElement()
    childElemVec = kesElem.getElementsByClass(type(rde), None)
    cntrlr = kesOpSet.getControllerForElement(childElemVec[0])
    flow = cntrlr.getCurMinOpValue(currentRuntimestep).value
    # Fall back to the previous time step's decision value if the current
    # flow is unavailable or implausibly small (< 0.1 cfs).
    if (not isValidValue(flow) or flow < 0.1) and usePrevStepAsEstimate:
        rts = RunTimeStep()
        rts.setStep(currentRuntimestep.getStep() - 1)
        flow = cntrlr.getDecisionValue(rts)
    if not isValidValue(flow):
        raise ValueError("Invalid value: " + str(flow) + " for " + keswickName + " flow for time step: " + str(currentRuntimestep.step))

    return flow


def getKeswickAvgTemp(network, currentRuntimestep):
    """Compute the volume-weighted average water temperature in Keswick Reservoir.

    Parameters
    ----------
    network : object
        HEC-ResSim network object, used to locate Keswick Reservoir and
        its WQ geometry/engine.
    currentRuntimestep : object
        Current simulation time step object (unused directly, since layer
        results are read for the current engine state without an explicit
        time-step argument).

    Returns
    -------
    float
        Volume-weighted average water temperature across all vertical
        layers of Keswick Reservoir.

    Raises
    ------
    NameError
        If the "Keswick Reservoir" network element cannot be found.

    Notes
    -----
    Used in backRouteWQTarget2 as the starting temperature for the
    downstream temperature-routing calculation, since Keswick's pool
    temperature mixes with the TCD outlet temperature before continuing
    downstream.
    """

    keswickName = "Keswick Reservoir"
    kesElem = network.findElement(keswickName)
    if not kesElem:
        raise NameError("Network element: " + keswickName + " not found.")
        
    wqRun = network.getRssRun().getWQRun()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(kesElem)
    engineAdapter = wqRun.getWQEngineAdapter()
    layerTemps = engineAdapter.getReservoirLayerTemperatures(resWQGeoSubdom)
    nLayers = len(layerTemps)
    layerVols = engineAdapter.getHydroResult(resWQGeoSubdom.getId(), WqIoHydroType.CELL_VOLUME.id, 
        WQTime.TIME_STEP_INFO.END_OF_STEP.id, nLayers)
    avgTemp = 0.
    totalVol = 0.
    # Volume-weight each layer's temperature to get the overall pool average.
    for j in range(nLayers):
        avgTemp += layerTemps[j] * layerVols[j]
        totalVol += layerVols[j]
    return avgTemp / totalVol


def backRouteWQTarget2(network, currentRuntimestep, wqTarget, tcdMinFlow, riverOutletFlow):
    """Back-calculate the required TCD outlet temperature from a downstream temperature target.

    Parameters
    ----------
    network : object
        HEC-ResSim network object.
    currentRuntimestep : object
        Current simulation time step object.
    wqTarget : float
        Desired temperature target at the downstream control location.
    tcdMinFlow : float
        Total penstock flow through the TCD (unused directly in this
        function's body, but accepted for interface consistency with its
        caller, getTCDTempAndFlowsForLevel).
    riverOutletFlow : float
        Combined river outlet flow (unused directly in this function's
        body; see the same note as ``tcdMinFlow``).

    Returns
    -------
    float
        Required TCD outlet temperature at Shasta Dam such that, after
        mixing with Keswick Reservoir and traveling downstream to the
        configured control location, the resulting temperature meets
        ``wqTarget``.

    Raises
    ------
    NotImplementedError
        If the downstream control location index is not one of the four
        recognized values.
    ValueError
        If the search below fails to bracket a solution.

    Notes
    -----
    This function references ``currentRule`` (passed to
    getKeswickOutflow) without ``currentRule`` being a parameter of this
    function; as written, this would raise a NameError if this code path
    is ever executed, since ``currentRule`` is not defined in this
    function's scope, its enclosing module scope, or passed in. This
    appears to be an omitted parameter, preserved here exactly rather
    than corrected.

    If the control location is at Shasta Dam itself (location 0), no
    backrouting is needed and the target is returned unchanged. Otherwise,
    a downstream distance (Highway 44, CCR, or Ball's Ferry) is used with
    a power-law velocity approximation (based on Keswick outflow) to
    estimate river travel time in model time steps. The function then
    performs a bisection-style bracketing search over candidate TCD outlet
    temperatures: for each candidate, it simulates mixing with Keswick
    Reservoir (weighted by a calibrated fraction of Keswick's conservation
    pool volume) and then routes the resulting temperature downstream
    step-by-step using a simple exchange with the equilibrium temperature
    global variable, comparing the final routed temperature against the
    future (lead-time-adjusted) target. Once two candidate temperatures
    are found that bracket the target (one routes too warm, one too
    cool), the result is linearly interpolated between them. If the very
    first candidate already produces a routed temperature below the
    target with no bracketing possible, that first candidate is accepted
    outright as a fallback; if a solution cannot be bracketed at all, a
    ValueError is raised.
    """

    # Get the downstream control location
    loc = getDSControlLoc(network,currentRuntimestep)
    #network.printMessage('getDSControlLoc: ' + str(loc))
    
    if loc == 0:  # At Shasta Dam - no backrouting needed
        #network.printMessage('In Shasta Dam - no backroute')
        return wqTarget
    elif loc == 1:  # Highway 44
        downstreamDistance = 30000.  # in feet
    elif loc == 2:  # CCR
        downstreamDistance = 53000.
    elif loc == 3:  # Ball's Ferry
        downstreamDistance = 137000.
    else:
        raise NotImplementedError('Downstream location index ' + str(loc) + ' not recognized.')
        
    # Power law approximation for velocity in the Sacramento River
    keswickFlow = getKeswickOutflow(currentRule, network, currentRuntimestep)
    Kcoef = 2.
    alpha = 0.33
    velocity = Kcoef * (keswickFlow / 1000)**alpha  # power law approximation
    # Calculate travel time in model steps
    if velocity <= 0.0:
        print('WARNING: Keswick flow <= 0 in Forecast TCD script. Specified flows may be incorrect.')
        travTime = 0.0
    else:
        travTime = downstreamDistance / velocity
    deltaT = currentRuntimestep.getTimeStepSeconds()
    travTimeSteps = int(round(travTime / deltaT))
    #network.printMessage('travTimeSteps ' + str(travTimeSteps))

    # Look up the water-quality target at the future time step corresponding
    # to the estimated downstream travel time, since a parcel of water
    # leaving the dam now will arrive downstream at that later time.
    futureRts = RunTimeStep()
    futureRts.setStep(min(currentRuntimestep.getStep() + travTimeSteps, currentRuntimestep.getTotalNumSteps()-1))
    targetTempFuture = getGVTemperature(network, futureRts, globalVarNameTCDTarget)
    #network.printMessage('Future temp target ' + str(targetTempFuture))
    
    # Get Keswick pool information
    flowVol = keswickFlow * 86400.
    kesConPoolVol = 20100. * 43560.  # cubic feet, assumed this is top of conservation
    kesFraction = flowVol / kesConPoolVol
    multiplier = 0.14  # Calibration factor
    kesFraction = min(kesFraction * multiplier, 1.)
    keswickResAvgTemp = getKeswickAvgTemp(network, currentRuntimestep)
    #exchCoef = 0.0098  # exchange rate between atmosphere and river temp
    exchCoef = 0.015 # exchange rate between atmosphere and river temp
    tSearchMin = keswickResAvgTemp - 6.
    tSearchMax = keswickResAvgTemp + 12.
    numIters = 51
    bracketed = False
    cantBeMet = False
    #network.printMessage('Keswick vars ' + str(keswickResAvgTemp) + ', ' + str(kesFraction))
    #network.printMessage('Travel time steps ' + str(travTimeSteps))
    # Scan candidate outlet temperatures across the search range, routing
    # each one downstream, until two consecutive candidates bracket the
    # future target temperature (one above, one below).
    for j in range(numIters):
        outletTemp = tSearchMin + float(j) / float(numIters+1) * (tSearchMax - tSearchMin)
        # Impact of Keswick
        t = (1 - kesFraction) * keswickResAvgTemp + kesFraction * outletTemp
        # Route downstream
        for k in range(travTimeSteps):
            futureRts.setStep(min(currentRuntimestep.getStep() + k, currentRuntimestep.getTotalNumSteps() - 1))
            eqTemp = getGVTemperature(network, futureRts, globalVarNameEquilibTemp)
            deltaTemp = (eqTemp - t) * exchCoef
            t += deltaTemp
        #network.printMessage('Iter vars ' + str(outletTemp) + ', ' + str(t))
        if j == 0:
            prevT = t
            prevOutletT = outletTemp
        if t > targetTempFuture and prevT < targetTempFuture:
            upperOutletT = outletTemp
            upperT = t
            lowerOutletT = prevOutletT
            lowerT = prevT
            bracketed = True
            #network.printMessage('Break loop 1 ' + str(prevT) + ', ' + str(t) + ', ' + str(targetTempFuture))
            break
        elif prevT > targetTempFuture and t < targetTempFuture:
            lowerOutletT = outletTemp
            lowerT = t
            upperOutletT = prevOutletT
            upperT = prevT
            bracketed = True
            #network.printMessage('Break loop 2 ' + str(prevT) + ', ' + str(t) + ', ' + str(targetTempFuture))
            break
        elif j == 0 and t > targetTempFuture:
            cantBeMet = True
            break
        prevT = t
        prevOutletT = outletTemp

    if bracketed:
        # Linear interpolation
        targetTemp = (targetTempFuture - lowerT) / (upperT - lowerT) * (upperOutletT - lowerOutletT) + lowerOutletT
        #network.printMessage('Upper, lower T ' + str(upperT) + ', ' + str(lowerT))
        #network.printMessage('Upper, lower outlet T ' + str(upperOutletT) + ', ' + str(lowerOutletT))
        #network.printMessage('Backrouted target temp ' + str(targetTemp))
    elif cantBeMet:
        targetTemp = outletTemp
    else:
        if t < targetTempFuture:
            targetTemp = outletTemp
        else:
            #network.printMessage('Target Temperature Downstream' + str(targetTempFuture))
            raise ValueError('Outlet temperature not bracketed')
    
    return targetTemp


def getTCDTempAndFlowsForLevel(currentRule, network, currentRuntimestep, resElev, targetTemp, tcdMinFlow, nGates, 
                               riverOutletFlow, riverOutletTemp):
    """Optimize the TCD inlet flow distribution for a fixed gate configuration.

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
        Desired downstream temperature target (will be adjusted/back-routed
        internally; the adjusted value is also returned).
    tcdMinFlow : float
        Total penstock flow through the TCD.
    nGates : list of int
        4-element ``[side, lower, middle, upper]`` count of open gates at
        each level, as returned by getGatesForLevel.
    riverOutletFlow : float
        Combined river outlet flow (bypassing the TCD).
    riverOutletTemp : float
        Flow-weighted average river outlet temperature.

    Returns
    -------
    tuple of (float, float, list of float)
        The (possibly adjusted) target temperature actually used for the
        optimization, the resulting optimized TCD outlet temperature, and
        the per-inlet flow distribution achieving it.

    Raises
    ------
    ValueError
        If the WQ engine's flow optimization fails (wrapped from
        WQException) or if the resulting flows do not sum to within 1 cfs
        of ``tcdMinFlow``.

    Notes
    -----
    This is the detailed physical optimization underlying the higher-level
    gate-selection logic in getForecastTCDTempAndFlows. The steps are:

    1. Back-route the downstream target temperature to an equivalent
       at-dam target (backRouteWQTarget2), then further adjust that target
       to account for river outlet flow diluting/mixing with the TCD
       outlet downstream (if any river outlet flow exists), clamping the
       adjusted target to a plausible 0.1-35 degC range to avoid chasing
       an unreachable target caused by large river-outlet contributions.
    2. Compute uncontrollable leakage flow for each of the six leakage
       zones (using the appropriate pre/post-2010 coefficient table based
       on the current simulation year), fixing each leakage zone's
       min/max flow bounds to the same computed value (i.e. leakage is
       not a decision variable in the optimization).
    3. For each operable gate group (side, lower, middle, upper) with at
       least one open gate, set minimum/maximum flow bounds per inlet
       point: fully submerged groups get a small minimum fraction up to
       the full penstock flow as a maximum; partially submerged groups
       (only applicable to middle/upper, which have multiple elevation
       tiers) are constrained using the sharp-crested weir equation
       (calcWeirFlow) to estimate a physical maximum flow given the
       submergence depth.
    4. Call the WQ engine's flow optimizer (``computeWQCDFlows``) with
       these per-inlet bounds, the fixed total flow, and the adjusted
       target temperature, then retrieve the resulting predicted outlet
       temperature.
    5. Validate that the optimizer's flows sum to within 1 cfs of the
       requested total flow, raising with diagnostic output otherwise.

    If the WQ engine raises a WQException during optimization, diagnostic
    context (flows, elevation, target, gate counts, and bounds) is printed
    before re-raising as a bare ValueError (which, as written, discards
    the original exception's message in the raised error itself, though it
    has already been printed).
    """

    # Route target temperature back from downstream location
    backRoutedWqTarget = backRouteWQTarget2(network, currentRuntimestep, targetTemp, tcdMinFlow, riverOutletFlow)
    #network.printMessage('Target, backrouted temps ' + str(targetTemp) + ', ' + str(backRoutedWqTarget))
    targetTemp = backRoutedWqTarget

    # Adjust target temperature for river outlet impact: back out the
    # river outlet's contribution so the TCD alone, combined with the
    # river outlet flow, still averages to the original downstream target.
    if riverOutletFlow > 0.:
        totalDownstreamFlow = tcdMinFlow + riverOutletFlow
        newTargetTemp = (totalDownstreamFlow * targetTemp - riverOutletFlow * riverOutletTemp) / tcdMinFlow
        # Prevent cases where TCD trying to operate to -100 degrees to account for lots of river outlet flow
        targetTemp = min(max(newTargetTemp, 0.1), 35.)

    # Set variable storing the upstream (at Shasta) back-calculated target temperature
    setUpstreamTempTarget(network, currentRuntimestep, targetTemp)

    elevs = getInletElevs(currentRule, network)
    nInletLevels = len(elevs)
    numSideGatesOpen = nGates[0]
    numLowerGatesOpen = nGates[1]
    numMiddleGatesOpen = nGates[2]
    numUpperGatesOpen = nGates[3]

    # Get the year for the current timestep
    currentYear = 2023
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

    useHighPt = False
    sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(useHighPt)

    # Side (lowest level) gates: always fully submerged when open, so each
    # point just gets a small minimum fraction and the full flow as a max.
    if numSideGatesOpen > 0:
        for count, idx in enumerate(sideGateIdx):
            flowFract = chooseMinFlowFract(numLevelsOpen, count)
            if count == 1:  # Override the second from the bottom pt to also use 5%/10% min flow fracts
                flowFract = chooseMinFlowFract(numLevelsOpen, 0)
            inletFlowMin[idx] = flowFract * tcdMinFlow
            inletFlowMax[idx] = tcdMinFlow
                
    # Lower level gates: same simple treatment as side gates.
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
        
    wqRun = network.getWQRun()
    engineAdapter = wqRun.getWQEngineAdapter()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    wqcd = rssWQGeometry.getWQControlDevice(currentRule.getController().getReleaseElement())
    tempConstituent = wqRun.getWQConstituent("Water Temperature")
    # Hand the per-inlet bounds, fixed total flow, and adjusted target
    # temperature to the WQ engine's optimizer; on failure, print rich
    # diagnostic context before re-raising.
    try:
        tcdFlows = engineAdapter.computeWQCDFlows(resWQGeoSubdom, wqcd, tempConstituent, nInletLevels, inletFlowMin, inletFlowMax, tcdMinFlow, targetTemp)
    except WQException as wqe:
        print(wqe.getNativeExceptionMessage())
        print("Penstock flow", tcdMinFlow)
        print("River outlet flow", riverOutletFlow)
        print("Res elevation", resElev)
        print("Target temperature", targetTemp)
        print("Nof upper gates open", numUpperGatesOpen)
        print("Nof middle gates open", numMiddleGatesOpen)
        print("Nof lower gates open", numLowerGatesOpen)
        print("Nof side gates open", numSideGatesOpen)
        print("inletFlowMin", inletFlowMin)
        print("inletFlowMax", inletFlowMax)
        raise ValueError()
        
    tcdResult = engineAdapter.getWQResultOptimized(resWQGeoSubdom, wqcd)

    # Error checking: confirm the optimizer's solution actually respects
    # the fixed total flow constraint within a small tolerance.
    if abs(sum(tcdFlows) - tcdMinFlow) > 1.:  # 1 cfs
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

    return targetTemp, tcdResult, tcdFlows