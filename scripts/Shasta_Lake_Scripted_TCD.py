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


#######################################################################################################
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



#######################################################################################################
# Gets indexes of leakage points
def getLeakageIndexes():
    return [2, 4, 7, 11, 13, 17]


#######################################################################################################
# Gets indexes of gate points
def getGateIndexes(useHighPt):

    if useHighPt:
        sideIdx = [0, 1, 3, 9]
        lowerIdx = [6, 8, 12]
        middleIdx = [14, 15, 18]
    else:
        sideIdx = [0, 1, 3, 5]
        lowerIdx = [6, 8, 10]
        middleIdx = [14, 15, 16]
        
    upperIdx = [19, 20, 21]
    return sideIdx, lowerIdx, middleIdx, upperIdx


#######################################################################################################
# Gets the inlet elevations from the WQ Geometry (which gets passed the data in the Reservoir Physical tab)
def getInletElevs(currentRule, network):
    wqRun = network.getWQRun()
    engineAdapter = wqRun.getWQEngineAdapter()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    wqcd = rssWQGeometry.getWQControlDevice(currentRule.getController().getReleaseElement())
    elevs = engineAdapter.getWQCDInletLevels(resWQGeoSubdom, wqcd)
    return elevs


#######################################################################################################
# Called at the start of the simulation
def initRuleScript(currentRule, network):

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

        useHighPt = False
        sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(useHighPt)
        engineAdapter.setShastaTCDInfo(resWQGeoSubdom.getId(), wqcd.getId(), sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx)
        return Constants.TRUE


#######################################################################################################
# This checks whether we should be applying this rule in a given simulation
# Needs to have WQ running and the reservoir in the active WQ geometry
def checkApplyRule(currentRule, network):
    wqRun = network.getWQRun()
    if not wqRun:
        return False
    rssWQGeometry = wqRun.getRssWQGeometry()
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    resWQGeoSubdom = rssWQGeometry.getWQSubdomain(res)
    return rssWQGeometry.isInExtent(resWQGeoSubdom)


#######################################################################################################
# This is called each simulated forward time step during the simulation
def runRuleScript(currentRule, network, currentRuntimestep):

    # Only evaluation rule if running WQ (getEvalRule) *and* compute iteration > 0
    #  (On 0th iteration, only local res decisions being evaluated and WQ is not being run yet)
    computeIter = currentRule.getComputeIteration()
    evalRule = currentRule.getEvalRule() and (computeIter >= lastIterationPassNum)
    if evalRule:

        # Get current water quality target
        wqTarget = getGVTemperature(network, currentRuntimestep, "TCD_target")
    
        # Get reservoir elevation
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


#######################################################################################################
# Get the water quality target value by looking for the global variable timeseries
def getGVTemperature(network, currentRuntimestep, gvName):

    globVar = network.getGlobalVariable(gvName)
    if not globVar:
        raise NameError("Global variable: " + gvName + " not found.")

    temp = globVar.getCurrentValue(currentRuntimestep)
    validVal = isValidValue(temp)
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


#######################################################################################################
# Get the total number of gates open at a given level by looking for the global variable timeseries
def getNumGatesOpen(network, currentRuntimestep, levelName):

    maxGates = 5
    if levelName.lower() == 'upper':
        globalVarName = "Total_TCDU_gates_open"
    elif levelName.lower() == 'middle':
        globalVarName = "Total_TCDM_gates_open"
    elif levelName.lower() == 'lower':
        globalVarName = "Total_TCDL_gates_open"
    elif levelName.lower() == 'side':
        globalVarName = "Total_TCDS_gates_open"
        maxGates = 2
    else:
        raise NameError("Gate level: " + levelName + " not recognized.")
        
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    numGates = globVar.getCurrentValue(currentRuntimestep)
    
    if numGates < 0 or numGates > maxGates:
        raise ValueError("Global variable: " + globalVarName + " has invalid value " +
                         str(numGates) + " for time step: " + str(currentRuntimestep.step))
    else:
        return numGates


#######################################################################################################
# Check whether a WQ target value is valid
def isValidValue(value, checkZero=True):
    if not value:
        return False
    elif value == Constants.UNDEFINED_DOUBLE:
        return False
    elif checkZero and value < 0.:
        return False
    else:
        return True
    

#######################################################################################################
# Get the WQSubdomain object from the reservoir using the current rule
def getReservoirWQSubdomain(currentRule, network):
    resOp = currentRule.getController().getReservoirOp()
    res = resOp.getReservoirElement()
    wqRun = network.getRssRun().getWQRun()
    rssWQGeometry = wqRun.getRssWQGeometry()
    resWQGeoSubdom = rssWQGeometry.getSubdomForRSSElemId(res.getIndex())
    return resWQGeoSubdom


#######################################################################################################
# Calculate total TCD leakage fraction, applicable for years 2000-2009
# From W2 Report, Table 16
def getTotalLeakageFraction2000(resElev, elevs):
    upperFraction = 13.09/100.
    middleFraction = 19.7/100.
    lowerFraction = 12.65/100.
    fraction = getTotalLeakageFraction(resElev, elevs, upperFraction, middleFraction, lowerFraction, 0.2)
    return fraction


#######################################################################################################
# Calculate total TCD leakage fraction, applicable for years 2010 onward
# From W2 Report, Table 17
def getTotalLeakageFraction2010(resElev, elevs):
    upperFraction = 16.3/100.
    middleFraction = 0./100.
    lowerFraction = 15.75/100.
    fraction = getTotalLeakageFraction(resElev, elevs, upperFraction, middleFraction, lowerFraction, 0.2)
    return fraction


#######################################################################################################
# Calculate the total leakage fraction based on reservoir elevation
def getTotalLeakageFraction(resElev, elevs, upperFraction, middleFraction, lowerFraction, grossFraction):

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


#######################################################################################################
# Get TCD leakage table coefficients for each zone
# From W2 Report, Tables 16 and 17
def getLeakageTableVals(currentYear, zoneNum):
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


#######################################################################################################
# Calculate a theoretical maximum flow through a given gate level based on depth of gate submergence
#   and the number of open gates
# Estimate max using a sharp crested weir equation (Fluid Mechanics, White, 3rd ed., pg 624)
def calcWeirFlow(H, numOpenGates):
    g = 32.1  # assuming imperial units here
    weirCoef = 0.564  # from White
    width = 50.  # gates are 50' wide
    q = weirCoef * width * g**0.5 * H**1.5 * numOpenGates
    return q


#######################################################################################################
# Gets the TCD outlet index for a given leakage zone
def getIdxForLeakageZone(z):
    leakageIdx = getLeakageIndexes()
    i = len(leakageIdx) - z
    return leakageIdx[i]


#######################################################################################################
# Calculates leakage as a function of several inputs
def calcLeakage(currentYear, zone, gateRatio, elevationRatio, totalLeakFract, flow):
    tableVals = getLeakageTableVals(currentYear, zone)
    leakageFlow = (tableVals[0] + tableVals[1]*gateRatio)/100. * elevationRatio * totalLeakFract * flow
    return leakageFlow


#######################################################################################################
# Chooses the minimum flow fraction based on the number of open levels and the point number (0 = lowest)
def chooseMinFlowFract(nOpenLevels, ptNum):
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


#######################################################################################################
# Check whether to use an elevated top point for a single open gate level after a recent op change
def checkUseHighPoint(network, currentRuntimestep):

    nSideOpen = getNumGatesOpen(network, currentRuntimestep, 'Side')
    nLowerOpen = getNumGatesOpen(network, currentRuntimestep, 'Lower')
    nMiddleOpen = getNumGatesOpen(network, currentRuntimestep, 'Middle')
    nUpperOpen = getNumGatesOpen(network, currentRuntimestep, 'Upper')

    # Number of days to look back on when checking for a recent op change
    gateOpLookbackDays = 45

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
        if iCurStep - lbSteps <= 3:
            return False
        numStepsDay = int(24. * 60. / currentRuntimestep.getRunTimeWindow().getTimeStepMinutes())
        iStartStep = max(lbSteps, iCurStep - gateOpLookbackDays * numStepsDay)
        rts = RunTimeStep()
        # Check for a recent change
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


#######################################################################################################
# Ask the WQEngine for the optimal WQCD flow distribution for a WQ target and total flow rate
def getTCDTempAndFlows3ptMinFF(currentRule, network, currentRuntimestep, resElev, targetTemp, tcdMinFlow):

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
    numSideGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Side')
    numLowerGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Lower')
    numMiddleGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Middle')
    numUpperGatesOpen = getNumGatesOpen(network, currentRuntimestep, 'Upper')
    sideGateRatio = (numSideGates - numSideGatesOpen)/numSideGates
    lowerGateRatio = (numLowerGates - numLowerGatesOpen)/numLowerGates
    middleGateRatio = (numMiddleGates - numMiddleGatesOpen)/numMiddleGates
    # Zone 6 - no gate ratio or elev ratio
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

    numLevelsOpen = 0
    if numSideGatesOpen > 0:
        numLevelsOpen += 1
    if numLowerGatesOpen > 0:
        numLevelsOpen += 1
    if numMiddleGatesOpen > 0:
        numLevelsOpen += 1
    if numUpperGatesOpen > 0:
        numLevelsOpen += 1

    useHighPt = checkUseHighPoint(network, currentRuntimestep)
    sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx = getGateIndexes(useHighPt)
    engineAdapter.setShastaTCDInfo(resWQGeoSubdom.getId(), wqcd.getId(), sideGateIdx, lowerGateIdx, middleGateIdx, upperGateIdx)

    # Side (lowest level) gates
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
                
    # Lower level gates
    if numLowerGatesOpen > 0:
        for count, idx in enumerate(lowerGateIdx):
            flowFract = chooseMinFlowFract(numLevelsOpen, count)
            inletFlowMin[idx] = flowFract * tcdMinFlow
            inletFlowMax[idx] = tcdMinFlow

    # Middle level gates
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
    
    # Upper level gates
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
        
    tcdFlows = engineAdapter.computeWQCDFlows(resWQGeoSubdom, wqcd, tempConstituent, nInletLevels, inletFlowMin, inletFlowMax, tcdMinFlow, targetTemp)
    tcdResult = engineAdapter.getWQResultOptimized(resWQGeoSubdom, wqcd)
    #print("TCD Result: {0:.2f}".format(tcdResult))
    #for j in range(nInletLevels):
    #    print("TCD level {0}".format(j+1))
    #    print("Flow {0:.2f}".format(tcdFlows[j]))

    # Error checking
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

