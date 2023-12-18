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
        setTempTargetViolations(network, 0)
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


#######################################################################################################
# Check whether a value is valid
def isValidValue(value):
    if value is None:
        return False
    elif value == Constants.UNDEFINED_DOUBLE:
        return False
    elif value < 0.:
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
def getOutletOptions():  # Level number, state of level opening [lower, upper]
    outletOptions = {1: [0, 1],  # upper only
                     2: [1, 1],  # upper and lower blending
                     3: [1, 0]}  # lower only
    return outletOptions


#######################################################################################################
# Get outlet options for an integer level value [lower, upper]
def getOutletsForLevel(level):
    outletOptions = getOutletOptions()
    return outletOptions[level]


#######################################################################################################
# Set the open outlets at a given level for the global variable timeseries
def setOutlets(network, currentRuntimestep, levelName, outletOpen):

    if levelName.lower() == 'upper':
        globalVarName = globalVarNameNumUpOutlet
    elif levelName.lower() == 'lower':
        globalVarName = globalVarNameNumLowOutlet
    else:
        raise NameError("Outlet level: " + levelName + " not recognized.")
        
    globVar = network.getGlobalVariable(globalVarName)
    if not globVar:
        raise NameError("Global variable: " + globalVarName + " not found.")
    
    if outletOpen < 0 or outletOpen > 1:
        raise ValueError("Global variable: " + globalVarName + " has invalid value " +
                         str(outletOpen) + " for time step: " + str(currentRuntimestep.step))
                    
    globVar.setCurrentValue(currentRuntimestep, outletOpen)


#######################################################################################################
# Set the outlets open at a given level for the global variable timeseries
#   openings = [lower, upper]
def setOutletOpenings(network, currentRuntimestep, openings):
    setOutlets(network, currentRuntimestep, 'lower', openings[0])
    setOutlets(network, currentRuntimestep, 'upper', openings[1])
    

#######################################################################################################
# Set the gate level
def setOperationLevel(network, currentRuntimestep, level):
    sv = network.getStateVariable(stateVarNameWQCDLevel)
    sv.setValue(currentRuntimestep, level)


#######################################################################################################
# Get the gate level for the previous time step
def getPrevOpLevel(network, currentRuntimestep):
    sv = network.getStateVariable(stateVarNameWQCDLevel)
    iCurStep = currentRuntimestep.getStep()
    iPrevStep = max(0, iCurStep - 1)
    rts = RunTimeStep()
    rts.setStep(iPrevStep)
    return sv.getValue(rts)


#######################################################################################################
# Set the number of temperature target violations
def setTempTargetViolations(network, numViolations):
    sv = network.getStateVariable(stateVarNameWQCDViolations)
    rts = RunTimeStep()
    rts.setStep(1)
    sv.setValue(rts, numViolations)


#######################################################################################################
# Get the number of temperature target violations
def getTempTargetViolations(network):
    sv = network.getStateVariable(stateVarNameWQCDViolations)
    rts = RunTimeStep()
    rts.setStep(1)
    return sv.getValue(rts)
    

#######################################################################################################
# Calculate WQCD flow distribution for a forecast simulation
def getForecastFlows(currentRule, network, currentRuntimestep, resElev, co_flow):

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

    # Find withdrawal temps
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
            level = 1
            return setDataForLevel(network, currentRuntimestep, level, co_flow)
        else:
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


#######################################################################################################
# Given outlet openings and outlet temperatures, calculate the combined temperature
def getTempForOp(outletOpenings, lowerTemp, upperTemp):
    totalOpenings = float(sum(outletOpenings))
    outletTemp = (outletOpenings[0] * lowerTemp + outletOpenings[1] * upperTemp) / totalOpenings
    return outletTemp

#######################################################################################################
# Given a level, set things and return WQCD flows
def setDataForLevel(network, currentRuntimestep, level, coFlow):
    setOperationLevel(network, currentRuntimestep, level)
    outletOpenings = getOutletsForLevel(level)
    setOutletOpenings(network, currentRuntimestep, outletOpenings)
    totalOpenings = float(sum(outletOpenings))
    flows = []
    for j in range(len(outletOpenings)):
        flow = float(outletOpenings[j]) / totalOpenings * coFlow
        flows.append(flow)
    return flows
