from hec.model import RunTimeStep
from hec.rss.model import OpController
from hec.rss.model import OpRule
from hec.rss.model import OpValue     
from hec.rss.model import ReservoirElement
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
# Port Level #     Elev     #  Name           # Operable? # Mobile? #
#   1     #     695.5    #  TCD Deep       #     Y     #    N    #
#   2     #     720.     #  TCD Side A     #     Y     #    N    #
#   3     #     749.5    #  Leakage Zone 6 #     N     #    N    #
#   4     #     760.     #  TCD Side B     #     Y     #    N    #
#   5     #     780.     #  Leakage Zone 5 #     N     #    N    #
#   6     #     800.     #  TCD Side C     #     Y     #    N    #
#   7     #     802.     #  TCD Lower Bot  #     Y     #    N    #
#   8     #     805.6    #  Leakage Zone 4 #     N     #    N    #
#   9     #     816.     #  TCD Lower Mid  #     Y     #    N    #
#   10    #     830.     #  TCD Lower Top  #     Y     #    N    #
#   11    #     833.6    #  Leakage Zone 3 #     N     #    N    #
#   12    #     896.7    #  Leakage Zone 2 #     N     #    N    #
#   13    #     900.     #  TCD Middle Bot #     Y     #    N    #
#   14    #     921.     #  TCD Middle Mid #     Y     #    N    #
#   15    #     942.     #  TCD Middle Top #     Y     #    N    #
#   16    #     946.7    #  Leakage Zone 1 #     N     #    N    #
#   17    #    1000.     #  TCD Upper Bot  #     Y     #    N    #
#   18    #    1021.     #  TCD Upper Mid  #     Y     #    N    #
#   19    #    1042.     #  TCD Upper Top  #     Y     #    N    #


#######################################################################################################
def getDefaultInletElevs():
	elevs = [695.5, 720., 749.5, 760., 780., 800., 802., 805.6, 816., 830., 833.6, 896.7, 
	         900., 921., 942., 946.7, 1000., 1021., 1042.]
	return elevs


#######################################################################################################
# Called at the start of the simulation
def initRuleScript(currentRule, network):

	wqRun = network.getRssRun().getWQRun()

	# Handle case where rule is active or disable but WQ is not being run
	if not wqRun:
		currentRule.setEvalRule(False)
		network.getRssRun().printWarningMessage("Warning: Scripted rule " + currentRule.getName() + 
			" references Water Quality which is disabled for this simulation. Rule will be ignored.")
		return Constants.TRUE

	# WQ is being simulated
	else:
		return Constants.TRUE


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
def getTargetWQ(network, currentRuntimestep):

	globalVarName = "TCD_target"
	convert2C = False
	
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
def isValidValue(value):
	if not value:
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
# Calculate total TCD leakage fraction, applicable for years 2000-2009
# From W2 Report, Table 16
def getTotalLeakageFraction2000(resElev):
	upperFraction = 13.09/100.
	middleFraction = 19.7/100.
	lowerFraction = 12.65/100.
	fraction = getTotalLeakageFraction(resElev, upperFraction, middleFraction, lowerFraction, 0.2)
	return fraction


#######################################################################################################
# Calculate total TCD leakage fraction, applicable for years 2010 onward
# From W2 Report, Table 17
def getTotalLeakageFraction2010(resElev):
	upperFraction = 16.3/100.
	middleFraction = 0./100.
	lowerFraction = 15.75/100.
	fraction = getTotalLeakageFraction(resElev, upperFraction, middleFraction, lowerFraction, 0.2)
	return fraction


#######################################################################################################
# Calculate the total leakage fraction based on reservoir elevation
def getTotalLeakageFraction(resElev, upperFraction, middleFraction, lowerFraction, grossFraction):

	#grossFraction = 0.2  # Assumed leakage fraction when pool elev > 1000. and all gates closed
	if resElev >= 1000.:
		fraction = grossFraction
	elif resElev >= 945.:
		resElevFactor = 1. - (resElev-945.)/(1000.-945.)  # =0 at 1000, 1 at 945
		fraction = grossFraction * (1. - upperFraction*resElevFactor)
	elif resElev >= 900.:
		resElevFactor = 1. - (resElev-900.)/(945.-900.)  # =0 at 945, 1 at 900
		fraction = grossFraction * (1. - upperFraction - middleFraction*resElevFactor)
	elif resElev >= 831.:
		resElevFactor = 1. - (resElev-831.)/(900.-831.)  # =0 at 900, 1 at 831
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
			vals = [1.79 + 6.77]
		else:
			vals = [2.23 + 8.44]
	# Zone 5 (also includes "Bottom 7" leakage)
	elif zoneNum == 5:
		if currentYear < 2010:
			vals = [3.84 + 31.12]
		else:
			vals = [4.78 + 38.76]
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
			vals = [13.09]
		else:
			vals = [16.3]
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
# Ask the WQEngine for the optimal WQCD flow distribution for a WQ target and total flow rate
def getTCDTempAndFlows3ptMinFF(currentRule, network, currentRuntimestep, resElev, targetTemp, tcdMinFlow):

	elevs = getDefaultInletElevs()
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
		totalLeakageFraction = getTotalLeakageFraction2000(resElev)
	else:
		totalLeakageFraction = getTotalLeakageFraction2010(resElev)
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
	# Zone 6
	i = 2
	tableVals = getLeakageTableVals(currentYear, 6)
	inletFlowMin[i] = tableVals[0]/100. * totalLeakageFraction*tcdMinFlow
	inletFlowMax[i] = inletFlowMin[i]
	# Zone 5
	i = 4
	tableVals = getLeakageTableVals(currentYear, 5)
	inletFlowMin[i] = tableVals[0]/100. * totalLeakageFraction*tcdMinFlow
	inletFlowMax[i] = inletFlowMin[i]
	# Zone 4
	i = 7
	tableVals = getLeakageTableVals(currentYear, 4)
	inletFlowMin[i] = (tableVals[0] + tableVals[1]*lowerGateRatio)/100. * totalLeakageFraction*tcdMinFlow
	inletFlowMax[i] = inletFlowMin[i]
	# Zone 3
	i = 10
	elevRatio = max(0., min((resElev-elevs[i])/(elevs[11]-elevs[i]), 1.))
	tableVals = getLeakageTableVals(currentYear, 3)
	inletFlowMin[i] = (tableVals[0] + tableVals[1]*sideGateRatio)/100. * elevRatio*totalLeakageFraction*tcdMinFlow
	inletFlowMax[i] = inletFlowMin[i]
	# Zone 2
	i = 11
	tableVals = getLeakageTableVals(currentYear, 2)
	elevRatio = max(0., min((resElev-elevs[i])/(elevs[15]-elevs[i]), 1.))
	inletFlowMin[i] = (tableVals[0] + tableVals[1]*middleGateRatio)/100. * elevRatio*totalLeakageFraction*tcdMinFlow
	inletFlowMax[i] = inletFlowMin[i]
	# Zone 1
	i = 15
	tableVals = getLeakageTableVals(currentYear, 1)
	elevRatio = max(0., min((resElev-elevs[i])/(1000.-elevs[i]), 1.))
	inletFlowMin[i] = tableVals[0]/100. * elevRatio*totalLeakageFraction*tcdMinFlow
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
	
	# Side (lowest level) gates
	if numSideGatesOpen > 0:
		#inletFlowMin[0] = minOpenLevelFlowRatio/4. * tcdMinFlow
		

		if numLevelsOpen == 1:
			inletFlowMin[0] = 0.10 * tcdMinFlow
		else:
			inletFlowMin[0] = 0.05 * tcdMinFlow
		inletFlowMax[0] = tcdMinFlow
		#if currentYear < 2010:
		#	inletFlowMin[1] = 0.35 * tcdMinFlow
		#	inletFlowMax[1] = tcdMinFlow
		#else:
		if numLevelsOpen == 1:
			inletFlowMin[1] = 0.10 * tcdMinFlow
		else:
			inletFlowMin[1] = 0.05 * tcdMinFlow
		inletFlowMax[1] = tcdMinFlow
		if numLevelsOpen == 1:
			inletFlowMin[3] = 0.02 * tcdMinFlow
		else:
			inletFlowMin[3] = 0.01 * tcdMinFlow
		inletFlowMax[3] = tcdMinFlow
		if numLevelsOpen == 1:
			inletFlowMin[5] = 0.02 * tcdMinFlow
		else:
			inletFlowMin[5] = 0.01 * tcdMinFlow
		inletFlowMax[5] = tcdMinFlow

	# Lower level gates
	if numLowerGatesOpen > 0:
		if numLevelsOpen == 1:
			inletFlowMin[6] = 0.10 * tcdMinFlow
		else:
			inletFlowMin[6] = 0.05 * tcdMinFlow
		inletFlowMax[6] = tcdMinFlow
		if numLevelsOpen == 1:
			inletFlowMin[8] = 0.02 * tcdMinFlow
		else:
			inletFlowMin[8] = 0.01 * tcdMinFlow
		inletFlowMax[8] = tcdMinFlow
		if numLevelsOpen == 1:
			inletFlowMin[9] = 0.02 * tcdMinFlow
		else:
			inletFlowMin[9] = 0.01 * tcdMinFlow
		inletFlowMax[9] = tcdMinFlow

	# Middle level gates
	if numMiddleGatesOpen > 0:
		if resElev > elevs[14]:  # All pts submerged
			if numLevelsOpen == 1:
				inletFlowMin[12] = 0.10 * tcdMinFlow
			else:
				inletFlowMin[12] = 0.05 * tcdMinFlow
			inletFlowMax[12] = tcdMinFlow
			if numLevelsOpen == 1:
				inletFlowMin[13] = 0.02 * tcdMinFlow
			else:
				inletFlowMin[13] = 0.01 * tcdMinFlow
			inletFlowMax[13] = tcdMinFlow
			if numLevelsOpen == 1:
				inletFlowMin[14] = 0.02 * tcdMinFlow
			else:
				inletFlowMin[14] = 0.01 * tcdMinFlow
			inletFlowMax[14] = tcdMinFlow
		elif resElev > elevs[13]:  # Lower 2 pts submerged
			if numLevelsOpen == 1:
				inletFlowMin[12] = 0.10 * tcdMinFlow
			else:
				inletFlowMin[12] = 0.05 * tcdMinFlow
			inletFlowMax[12] = tcdMinFlow
			if numLevelsOpen == 1:
				inletFlowMin[13] = 0.02 * tcdMinFlow
			else:
				inletFlowMin[13] = 0.01 * tcdMinFlow
			inletFlowMax[13] = tcdMinFlow
		elif resElev > elevs[12]:  # Only lower pt submerged
			# Use weir eqn limitation for this one
			hGateSubmerged = min(45., resElev - elevs[12])
			weirMaxEstimate = calcWeirFlow(hGateSubmerged, numMiddleGatesOpen)
			if numLevelsOpen == 1:
				qmin = 0.10 * tcdMinFlow
			else:
				qmin = 0.05 * tcdMinFlow
			inletFlowMin[12] = min(qmin, weirMaxEstimate)
			inletFlowMax[12] = min(tcdMinFlow, weirMaxEstimate)
	
	# Upper level gates
	if numUpperGatesOpen > 0:
		if resElev > elevs[18]:  # All pts submerged
			if numLevelsOpen == 1:
				inletFlowMin[16] = 0.10 * tcdMinFlow
			else:
				inletFlowMin[16] = 0.05 * tcdMinFlow
			inletFlowMax[16] = tcdMinFlow
			if numLevelsOpen == 1:
				inletFlowMin[17] = 0.02 * tcdMinFlow
			else:
				inletFlowMin[17] = 0.01 * tcdMinFlow
			inletFlowMax[17] = tcdMinFlow
			if numLevelsOpen == 1:
				inletFlowMin[18] = 0.02 * tcdMinFlow
			else:
				inletFlowMin[18] = 0.01 * tcdMinFlow
			inletFlowMax[18] = tcdMinFlow
		elif resElev > elevs[17]:  # Lower 2 pts submerged
			if numLevelsOpen == 1:
				inletFlowMin[16] = 0.10 * tcdMinFlow
			else:
				inletFlowMin[16] = 0.05 * tcdMinFlow
			inletFlowMax[16] = tcdMinFlow
			if numLevelsOpen == 1:
				inletFlowMin[17] = 0.02 * tcdMinFlow
			else:
				inletFlowMin[17] = 0.01 * tcdMinFlow
			inletFlowMax[17] = tcdMinFlow
		elif resElev > elevs[16]:  # Only lower pt submerged
			# Use weir eqn limitation for this one
			hGateSubmerged = min(45., resElev - elevs[16])
			weirMaxEstimate = calcWeirFlow(hGateSubmerged, numUpperGatesOpen)
			if numLevelsOpen == 1:
				qmin = 0.10 * tcdMinFlow
			else:
				qmin = 0.05 * tcdMinFlow
			inletFlowMin[16] = min(qmin, weirMaxEstimate)
			inletFlowMax[16] = min(tcdMinFlow, weirMaxEstimate)
		
	wqRun = network.getRssRun().getWQRun()
	engineAdapter = wqRun.getWqEngineAdapter()
	resWQGeoSubdom = getReservoirWQSubdomain(currentRule, network)
	sdId = resWQGeoSubdom.getId()
	resOp = currentRule.getController().getReservoirOp()
	releaseElemId = resOp.getWQCDReleaseElemId(currentRule)
	tcdId = resWQGeoSubdom.getWqControlDeviceId(releaseElemId)
	tempConstitId = 1
	tcdFlows = engineAdapter.computeWQCDFlows(sdId, tcdId, tempConstitId, nInletLevels, inletFlowMin, inletFlowMax, tcdMinFlow, targetTemp)
	tcdResult = engineAdapter.getConstitResultWQCDOptimized(sdId, tcdId)
	#print("TCD Result: {0:.2f}".format(tcdResult))
	#for j in range(nInletLevels):
	#	print("TCD level {0}".format(j+1))
	#	print("Flow {0:.2f}".format(tcdFlows[j]))

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
