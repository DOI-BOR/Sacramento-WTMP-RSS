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
# This is a Shasta Lake entrainment-ratio StateVariable script. Its job is
# to set currentVariable (the entrainment ratio used elsewhere in the WQ
# model) each time step based on some condition. Several different
# strategies for deciding that value have been tried over time and are
# preserved below as commented-out code, but only one simple fixed-cutoff
# comparison is currently active -- and as written, that comparison
# currently has no effect on the result (see below). Disabled strategies,
# in the order they appear in the file: (1) a reservoir-layer "mixed
# layer temperature" vs. inflow-temperature comparison using the WQ
# engine's vertical profile; (2) an elevation-tiered inflow-temperature
# cutoff; (3) an inflow-volume (CFS) threshold; (4) a calendar
# month-based fixed value; (5) two elevation-based linear scaling
# formulas. None of these are deleted, per the project's documentation
# conservatism policy; they are described here so a reader does not have
# to mentally execute each one to know what it was for.

# to set the StateVariable's value use:
# 	currentVariable.setValue(currentRuntimestep, newValue)
# where newValue is the value you want to set it to.

# Read the externally-specified entrainment switch temperature, used
# below as the comparison threshold for the (currently inert) cutoff check.
inflowT_ts = network.getGlobalVariable("Shasta_entrainment_switch_temperature")
inflowT = inflowT_ts.getCurrentValue(currentRuntimestep)

###try:

# DISABLED STRATEGY 1: reservoir-layer "mixed layer temperature" approach.
# This block would have read the WQ engine's per-layer temperatures for
# Shasta Lake, walked down from the surface to find the first layer whose
# bottom elevation sits more than 5 ft below the current pool elevation
# (taken as the "mixed layer" temperature), then compared that against
# inflowT: if the two were within 7 degrees of each other, entrainment
# was set very low (0.00005); otherwise it was turned off (-1). This
# entire comparison-and-decision path is commented out and not executed.
#wqRun = network.getRssRun().getWQRun()
#rssWQGeometry = wqRun.getRssWQGeometry()
#resWQGeoSubdom = rssWQGeometry.getSubdom("Shasta Lake")
#resLayerElevs = resWQGeoSubdom.getResVerticalLayerBoundaries()
#numLayers = len(resLayerElevs)-1
#engineAdapter = wqRun.getWqEngineAdapter()
#layerTemps = engineAdapter.getReservoirLayerTemperatures(resWQGeoSubdom)
#
# Reservoir pool elevation is still read live below, but (with Strategy 1
# disabled) resElev is never actually used by any currently active logic
# in this script -- it is a leftover read from when Strategy 1 was active.
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

# ACTIVE LOGIC: fixed inflow-temperature cutoff.
# inflowTCutoff is hard-coded to 10 here; the two commented-out
# elevation-tiered overrides below it (9 or 10 depending on resElev) are
# disabled, so the cutoff never actually varies with reservoir elevation
# despite resElev having been read above.
inflowTCutoff = 10.
#if resElev < 960.:
#	inflowTCutoff = 10.
#if resElev < 940.:
#	inflowTCutoff = 9.	


# NOTE: both branches of this comparison currently set currentVariable to
# the same value (-1), so as written the inflowT < inflowTCutoff test has
# no effect on the outcome -- currentVariable is unconditionally set to
# -1 regardless of inflowT. The commented-out 0.00005 alternative
# directly above the active -1 in the "if" branch strongly suggests this
# differentiated behavior was intentionally disabled at some point (e.g.
# for testing or because entrainment was being turned off project-wide)
# and the surrounding if/else structure was simply left in place rather
# than being simplified to a single unconditional assignment. This is
# preserved exactly rather than corrected or simplified.
if inflowT < inflowTCutoff: 
	#currentVariable.setValue(currentRuntimestep, 0.00005)
	currentVariable.setValue(currentRuntimestep, -1)
else:
	currentVariable.setValue(currentRuntimestep, -1)
		#currentVariable.setValue(currentRuntimestep, 0.0018)

### Use elevation of 
# DISABLED STRATEGY 3: inflow-volume (CFS) threshold. Would have read
# Shasta's inflow time series directly and set a low entrainment value
# above a 5000 cfs threshold, a higher one below it.
#f_ts = network.getTimeSeries("Reservoir","Shasta Lake", "Pool", "Flow-IN", "")
#inFlow = f_ts.getCurrentValue(currentRuntimestep)
#if inFlow >= 5000: # CFS
#	currentVariable.setValue(currentRuntimestep, 0.00005)
#else:
#	currentVariable.setValue(currentRuntimestep, 0.0010)

### Use flow-weighted inflow temperature to set entrainment
# DISABLED STRATEGY (unimplemented): this heading describes a
# flow-weighted inflow-temperature approach, but no code follows it --
# the idea was never implemented, only noted as a heading for a future
# strategy.





### Use date to set entrainment
# DISABLED STRATEGY 4: calendar-based entrainment. Would have set a low
# entrainment value (0.00005) during the Nov-Apr window (curMon >= 11 or
# curMon < 5) and a higher static value (0.0015) the rest of the year,
# with two further elevation-based linear-scaling alternatives nested
# inside the "else" branch (also disabled) that would have replaced the
# static 0.0015 with a value computed from current pool elevation.
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