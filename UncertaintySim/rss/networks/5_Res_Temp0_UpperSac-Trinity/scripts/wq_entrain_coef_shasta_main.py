# no return values are used by the compute from this script.
#
# variables that are available to this script during the compute:
# 	currentVariable - the StateVariable that holds this script
# 	currentRuntimestep - the current RunTime step 
# 	network - the ResSim network

# The following represents an undefined value in a time series
# 	Constants.UNDEFINED
# throw a hec.rss.lang.StopComputeException from anywhere in the script to
# have ResSim stop the compute.
# from hec.rss.lang import StopComputeException
# raise StopComputeException("the reason to stop the compute")

# add your code here...


# to set the StateVariable's value use:
# 	currentVariable.setValue(currentRuntimestep, newValue)
# where newValue is the value you want to set it to.

inflowT_ts = network.getGlobalVariable("Shasta_entrainment_switch_temperature")
inflowT = inflowT_ts.getCurrentValue(currentRuntimestep)

###try:

#wqRun = network.getRssRun().getWQRun()
#rssWQGeometry = wqRun.getRssWQGeometry()
#resWQGeoSubdom = rssWQGeometry.getSubdom("Shasta Lake")
#resLayerElevs = resWQGeoSubdom.getResVerticalLayerBoundaries()
#numLayers = len(resLayerElevs)-1
#engineAdapter = wqRun.getWqEngineAdapter()
#layerTemps = engineAdapter.getReservoirLayerTemperatures(resWQGeoSubdom)
#
e_ts = network.getTimeSeries("Reservoir","Shasta Lake", "Pool", "Elev", "")
resElev = e_ts.getCurrentValue(currentRuntimestep)
##
#for k in reversed(range(numLayers)):
#	layerBotElev = resLayerElevs[k]
#	print('Layer', k, 'Temp', layerTemps[k])
#	if layerBotElev < resElev-5.:
#	#if layerBotElev > -1 and layerBotElev < 50.0: # first good temp?
#		mixedLayerTemp = layerTemps[k]
#		break
#
#temp_diff = mixedLayerTemp - inflowT
#d_temp_min = 7.0
#if temp_diff < d_temp_min: 
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#	#print('Nea!! State entrain calc:',mixedLayerTemp,inflowT,d_temp_min)
#else:
#	currentVariable.setValue(currentRuntimestep, -1)
#	#print('Yea!! State entrain calc:',mixedLayerTemp,inflowT,d_temp_min)
##except:

##	print("In except block")

##	inflowT_ts = network.getGlobalVariable("Shasta_entrainment_switch_temperature")
##	inflowT = inflowT_ts.getCurrentValue(currentRuntimestep)

inflowTCutoff = 10.
#if resElev < 960.:
#	inflowTCutoff = 10.
#if resElev < 940.:
#	inflowTCutoff = 9.	


if inflowT < inflowTCutoff: 
	#currentVariable.setValue(currentRuntimestep, 0.00005)
	currentVariable.setValue(currentRuntimestep, -1)
else:
	currentVariable.setValue(currentRuntimestep, -1)
		#currentVariable.setValue(currentRuntimestep, 0.0018)

### Use elevation of 
#f_ts = network.getTimeSeries("Reservoir","Shasta Lake", "Pool", "Flow-IN", "")
#inFlow = f_ts.getCurrentValue(currentRuntimestep)
#if inFlow >= 5000: # CFS
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#else:
#	currentVariable.setValue(currentRuntimestep, 0.0010)

### Use flow-weighted inflow temperature to set entrainment





### Use date to set entrainment
#curMon = currentRuntimestep.getHecTime().month()
#curDay = currentRuntimestep.getHecTime().day()
#if curMon >= 11: # or curMon >= 11 and curDay >=15:
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#elif curMon < 5:
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#else:
	#### static
#	currentVariable.setValue(currentRuntimestep, 0.0015)

	### Use elevation to scale entrainment
	#e_ts = network.getTimeSeries("Reservoir","Shasta Lake", "Pool", "Elev", "")
	#resElev = e_ts.getCurrentValue(currentRuntimestep) 
	## linear 0.002 at 880 ft -> 0.0001 at 1020 ft: -0.00001357*elev + 0.01394
	#currentVariable.setValue(currentRuntimestep,  -0.00001357*resElev + 0.01394)

	## linear 0.002 at 980 ft -> 0.0001 at 1020 ft: -0.0000475*elev + 0.04855
	#e_ratio = -0.0000475*resElev + 0.04855
	#e_ratio = max(0.0001,e_ratio)
	#e_ratio = min(0.002,e_ratio)
	#currentVariable.setValue(currentRuntimestep, e_ratio)
