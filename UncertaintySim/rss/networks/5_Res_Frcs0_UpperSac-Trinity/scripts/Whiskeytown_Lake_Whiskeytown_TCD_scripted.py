from hec.model import RunTimeStep
from hec.rss.model import OpController
from hec.rss.model import OpRule
from hec.rss.model import OpValue     
from hec.script import Constants


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
		return Constants.TRUE



#######################################################################################################
# This checks whether we should be applying this rule in a given simulation
def checkApplyRule(currentRule, network):

	wqRun = network.getRssRun().getWQRun()
	if not wqRun:
		return False

	rssWQGeometry = wqRun.getRssWQGeometry()
	resWQGeoSubdom = getReservoirWQSubdomain(currentRule, network)
	return rssWQGeometry.isInExtent(resWQGeoSubdom)
	

#######################################################################################################
# This is called each simulated forward time step during the simulation
def runRuleScript(currentRule, network, currentRuntimestep):

	# Only evaluation rule if running WQ (getEvalRule) *and* compute iteration > 0
	#  (On 0th iteration, only local res decisions being evaluated and WQ is not being run yet)
	computeIter = currentRule.getComputeIteration()
	evalRule = currentRule.getEvalRule() and (computeIter > 1)
	
	if evalRule:

		# Get current water quality target
		wqTarget = getTargetWQ(network, currentRuntimestep)

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

		# Specified gate config, w/ 50/50 blending if both are open
		# ----------------------------------------------------------------------------------------
		upper,lower = getGateConfig(network, currentRuntimestep)
		if upper == 1 and lower == 1 :
			wqcdFlows = [co_flow * 0.5, co_flow * 0.5]
		elif lower == 1:
			wqcdFlows = [co_flow, 0.]
		else:  # we should have caught any invalid gate config already 
			wqcdFlows = [0., co_flow]
		resOp.setWQControlDeviceFlowRatios(wqcdFlows, currentRule, co_flow)

	return None


#######################################################################################################
# Get the water quality target value by looking for the global variable timeseries
def getTargetWQ(network, currentRuntimestep):

	globalVarName = "Whiskeytown_target"
	convert2C = True
	
	globVar = network.getGlobalVariable(globalVarName)
	if not globVar:
		raise NameError("Global variable: " + globalVarName + " not found.")
	target = globVar.getCurrentValue(currentRuntimestep)
	
	if not isValidValue(target):
		raise ValueError("Global variable: " + globalVarName + " has invalid value " +
		                 str(target) + " for time step: " + str(currentRuntimestep.step))
	else:
		if convert2C:
			targetDegC = (target - 32.) * 5./9.
		else:
			targetDegC = target
		#print("Target temperature: {0:.2f}".format(targetDegC))
		return targetDegC


#######################################################################################################
# Get the water quality target value by looking for the global variable timeseries
def getGateConfig(network, currentRuntimestep):

	globalVarName = "Whiskeytown_Upper_Gate_open"	
	globVar = network.getGlobalVariable(globalVarName)
	if not globVar:
		raise NameError("Global variable: " + globalVarName + " not found.")
	upper = globVar.getCurrentValue(currentRuntimestep)	

	globalVarName = "Whiskeytown_Lower_Gate_open"	
	globVar = network.getGlobalVariable(globalVarName)
	if not globVar:
		raise NameError("Global variable: " + globalVarName + " not found.")
	lower = globVar.getCurrentValue(currentRuntimestep)	

	if not isValidGateConfig(upper,lower):
		raise ValueError("Global gate config variables are invalid: Whiskeytown gates must be either 0 or 1, and one must be open" +
		                 " for time step: " + str(currentRuntimestep.step))
		
	return upper,lower




#######################################################################################################
# Check whether a WQ target value is valid
def isValidValue(value):
	if value == Constants.UNDEFINED_DOUBLE:
		return False
	else:
		return True

#######################################################################################################
# Check whether a WQ target value is valid
def isValidGateConfig(upper,lower):
	if upper == 1 or lower == 1:
		return True
	else:
		return False


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
# Calculate optimal WQCD flow distribution for a WQ target and total flow rate
def getOptimalFlows(currentRule, network, currentRuntimestep, resElev, targetTemp, totalFlow):

	upperWithdrawalElev = 1110.
	lowerWithdrawalElev = 972.

	# Check reservoir elevation is above upper withdrawal point
	if resElev < upperWithdrawalElev:
		return [totalFlow, 0.]  # (convention is [lower, upper])

	wqRun = network.getRssRun().getWQRun()
	engineAdapter = wqRun.getWqEngineAdapter()
	resWQGeoSubdom = getReservoirWQSubdomain(currentRule, network)

	resLayerElevs = resWQGeoSubdom.getResVerticalLayerBoundaries()
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

	if targetTemp < lowerTemp:
		return [totalFlow, 0.]
	elif targetTemp > upperTemp:
		return [0., totalFlow]
	else:  # blending
		if abs(upperTemp - lowerTemp) < 0.001:  # shouldn't happen, but just in case
			halfFlow = 0.5 * totalFlow
			return [halfFlow, halfFlow]
		else:
			lowerFlow = (upperTemp - targetTemp) / (upperTemp - lowerTemp) * totalFlow
			upperFlow = totalFlow - lowerFlow
			return [lowerFlow, upperFlow]
