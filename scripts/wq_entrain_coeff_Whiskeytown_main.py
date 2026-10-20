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

# NOTES ON THIS SCRIPT AS A WHOLE
# -----------------------------------------------------------------------
# This is another entrainment-ratio StateVariable script, closely related
# to (and sharing most of its disabled code with) the Shasta Lake
# entrainment-switch script elsewhere in this project. The large
# commented-out block below is the same catalog of disabled Shasta-based
# strategies seen in that other script (mixed-layer temperature
# comparison, elevation-tiered cutoff, inflow-volume threshold, a
# shading-record sketch, calendar-based value, elevation-linear scaling).
# None of that Shasta logic is active here.
#
# The ACTIVE logic in this script is entirely different and targets
# Whiskeytown Lake, not Shasta: it computes a 24-step (assumed hourly,
# i.e. prior-day) rolling average outflow, linearly interpolates an
# entrainment coefficient between fixed min/max flow and min/max
# entrainment bounds, clamps it to that range -- and then discards that
# computed value entirely, unconditionally setting currentVariable to a
# fixed constant (3.0e-5) instead. This mirrors the discarded-result
# pattern seen in the Whiskeytown WQCD forecast rule script elsewhere in
# this project, where a computed decision is overridden by a fixed
# placeholder right before being applied. This is preserved exactly
# rather than corrected, but is almost certainly not the intended final
# behavior -- it looks like debugging/testing code where the real
# calculation was temporarily bypassed with a constant and never restored.

# to set the StateVariable's value use:
# 	currentVariable.setValue(currentRuntimestep, newValue)
# where newValue is the value you want to set it to.

# DISABLED: the entire block below (through the date-based strategy near
# the end) is the same catalog of disabled Shasta Lake entrainment
# strategies documented in the companion Shasta entrainment-switch
# script -- a mixed-layer-temperature vs. inflow-temperature comparison
# using the WQ engine's vertical profile, an elevation-tiered
# temperature cutoff, an inflow-volume (CFS) threshold, an unfinished
# sketch of a seasonal shading record (SeasonalRecord with Julian-day
# breakpoints and shading fractions, never wired into any decision
# logic), and a calendar month-based value with nested elevation-linear
# scaling options. None of it executes in this version of the script.
#inflowT_ts = network.getGlobalVariable("Shasta_entrainment_switch_temperature")
#inflowT = inflowT_ts.getCurrentValue(currentRuntimestep)

###try:

#wqRun = network.getRssRun().getWQRun()
#rssWQGeometry = wqRun.getRssWQGeometry()
#resWQGeoSubdom = rssWQGeometry.getSubdom("Shasta Lake")
#resLayerElevs = resWQGeoSubdom.getResVerticalLayerBoundaries()
#numLayers = len(resLayerElevs)-1
#engineAdapter = wqRun.getWqEngineAdapter()
#layerTemps = engineAdapter.getReservoirLayerTemperatures(resWQGeoSubdom)
#
#e_ts = network.getTimeSeries("Reservoir","Shasta Lake", "Pool", "Elev", "")
#resElev = e_ts.getCurrentValue(currentRuntimestep)
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

#inflowTCutoff = 10.
#if resElev < 960.:
#	inflowTCutoff = 10.
#if resElev < 940.:
#	inflowTCutoff = 9.	



#if inflowT < inflowTCutoff: 
	#currentVariable.setValue(currentRuntimestep, 0.00005)
#	currentVariable.setValue(currentRuntimestep, -1)
#else:
#	currentVariable.setValue(currentRuntimestep, -1)
		#currentVariable.setValue(currentRuntimestep, 0.0018)

### Use elevation of 
#f_ts = network.getTimeSeries("Reservoir","Shasta Lake", "Pool", "Flow-IN", "")
#inFlow = f_ts.getCurrentValue(currentRuntimestep)
#if inFlow >= 5000: # CFS
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#else:
#	currentVariable.setValue(currentRuntimestep, 0.0010)

### Use flow-weighted inflow temperature to set entrainment

#from hec.model import SeasonalRecord

# These are minutes from the start of the year (in format Julian day * 1440 min/day)
#times =[1, 120 * 1440, 151 * 1440, 274 * 1440, 304 * 1440, 365 * 1440]
# These are the fractional shading amount
#vals = [0.0, 0.0, 0.35, 0.35, 0.0, 0.0]
#vals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]



### Use date to set entrainment
#curMon = currentRuntimestep.getHecTime().month()
#curDay = currentRuntimestep.getHecTime().day()
#if curMon >= 11: # or curMon >= 11 and curDay >=15:
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#elif curMon < 6:
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#else:
	#### static
#	currentVariable.setValue(currentRuntimestep, 0.00000005)

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

# ACTIVE LOGIC BELOW: Whiskeytown Lake rolling-average-outflow-based
# entrainment calculation. Despite the calculation being carried out in
# full, its result (entrainment_coef) is never actually applied -- see
# the final line of this script.

# Get time series records
tsInflow = network.getTimeSeries("Reservoir","Whiskeytown Lake", "Pool", "Flow-IN", "")
tsOutflow = network.getTimeSeries("Reservoir","Whiskeytown Lake", "Pool", "Flow-OUT", "")

# Search over previous day. window=24 assumes hourly time steps, so this
# spans the prior 24 hours (1 day) of outflow record.
jCurrent = currentRuntimestep.getStep()
n = currentRuntimestep.getTotalNumSteps()
window = 24  # assume 1 hour time steps
qInMin = 1.e10
qInMax = -1.e10
qOutMin = 1.e10
qOutMax = -1.e10
qsum = 0.0
# Walk backward over the lookback window, clamping each step index to the
# valid [0, n-1] range so the search never runs off either end of the
# simulation. Inflow min/max tracking (qInMin/qInMax) is initialized but
# never actually updated in this loop -- only the outflow record is read
# and accumulated; the commented-out inflow lines directly above the
# active outflow lines show where the equivalent inflow tracking would
# have gone, but it was disabled and qInMin/qInMax are simply unused
# dead variables as a result.
for i in range(window):
	j = jCurrent - i
	j = min(max(j, 0), n-1)
	# Inflow record
	#val = tsInflow.getValue(j)
	#qInMin = min(qInMin, val)
	#qInMax = max(qInMax, val)
	# Outflow record
	val = tsOutflow.getValue(j)
	qOutMin = min(qOutMin, val)
	qOutMax = max(qOutMax, val)
	qsum = qsum + val
qave = qsum/window

# First cut at this logic
# Linear interpolation mapping average outflow (qave) to an entrainment
# coefficient: at or below min_q (300 cfs), entrainment is capped at its
# maximum (0.001); at or above max_q (1200 cfs), it's capped at its
# minimum (3e-5); flows in between scale linearly.
max_entrainment = 0.001
min_entrainment = 3.e-5
max_q = 1200
min_q = 300

# linear between thse points
slope = (min_entrainment-max_entrainment)/(max_q-min_q)
b = min_entrainment - slope*max_q
entrainment_coef = qave*slope + b
entrainment_coef = max(min_entrainment,entrainment_coef)
entrainment_coef = min(max_entrainment,entrainment_coef)
	
# NOTE: entrainment_coef, computed above from the actual rolling-average
# outflow calculation, is never used here. currentVariable is instead
# set to a fixed constant (3.0e-5, which happens to equal min_entrainment
# but is written as a literal rather than a reference to that variable or
# to entrainment_coef). This means the entire flow-based calculation
# above currently has no effect on the simulation's entrainment ratio;
# the StateVariable is always set to the same fixed minimum value
# regardless of actual Whiskeytown outflow. This is preserved exactly
# rather than corrected, consistent with this project's broader pattern
# of computed-but-discarded decision logic (see also the Whiskeytown
# WQCD forecast rule script).
currentVariable.setValue(currentRuntimestep, 3.0e-5)