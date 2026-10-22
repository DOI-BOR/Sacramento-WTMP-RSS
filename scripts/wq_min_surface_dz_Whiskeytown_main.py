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

# Script to set Whiskeytown reservoir vertical diffusion coefficient for 
#   surface layers, based on magnitude of pumping

# NOTES ON THIS SCRIPT AS A WHOLE
# -----------------------------------------------------------------------
# This script is a sibling to the Whiskeytown rolling-average-outflow
# entrainment script elsewhere in this project: it reads the same
# Whiskeytown inflow/outflow time series over the same 24-step
# (assumed-hourly, i.e. prior-day) lookback window, but instead of
# computing an average flow, it checks whether either inflow or outflow
# shows a large swing combined with a low minimum -- intended as a proxy
# for detecting active pumping (pumping typically produces sharp,
# intermittent flow spikes rather than smooth variation). However, as
# written, BOTH outcomes of that check (pumping detected vs. not) set the
# vertical diffusion coefficient Dz to the same value (0.0000), so the
# detection logic currently has no effect on the result -- Dz is always
# zero regardless of flow variation. The variable name Dz and the
# surrounding structure (two distinct branches that clearly were meant to
# hold two distinct values) strongly suggest this once set different
# coefficients depending on the pumping check and was later reduced to
# zero in both branches, mirroring the same disabled-differentiation
# pattern seen in the companion Shasta entrainment-switch script. This is
# preserved exactly rather than corrected.

# Get time series records
tsInflow = network.getTimeSeries("Reservoir","Whiskeytown Lake", "Pool", "Flow-IN", "")
tsOutflow = network.getTimeSeries("Reservoir","Whiskeytown Lake", "Pool", "Flow-OUT", "")

# Search over previous day. window=24 assumes hourly time steps, so this
# spans the prior 24 hours (1 day) of flow record.
jCurrent = currentRuntimestep.getStep()
n = currentRuntimestep.getTotalNumSteps()
window = 24  # assume 1 hour time steps
qInMin = 1.e10
qInMax = -1.e10
qOutMin = 1.e10
qOutMax = -1.e10
# Walk backward over the lookback window, clamping each step index to the
# valid [0, n-1] range so the search never runs off either end of the
# simulation, tracking the min/max inflow and outflow seen in that window.
for i in range(window):
	j = jCurrent - i
	j = min(max(j, 0), n-1)
	# Inflow record
	val = tsInflow.getValue(j)
	qInMin = min(qInMin, val)
	qInMax = max(qInMax, val)
	# Outflow record
	val = tsOutflow.getValue(j)
	qOutMin = min(qOutMin, val)
	qOutMax = max(qOutMax, val)

# First cut at this logic
# A flow record is flagged as "having variation" (a proxy for pumping
# activity) if its range over the lookback window exceeds 1000 cfs AND
# its minimum value over that window is below 500 cfs -- i.e. a large
# swing that includes a low-flow baseline, as opposed to e.g. a
# uniformly high and slowly varying flow.
inflowHasVariation = (qInMax - qInMin) > 1000. and qInMin < 500.
outflowHasVariation = (qOutMax - qOutMin) > 1000. and qOutMin < 500.
# NOTE: both branches currently assign the same value (0.0000) to Dz, so
# this if/else has no actual effect on the result as written -- see the
# Notes above.
if inflowHasVariation or outflowHasVariation:
	Dz = 0.0000
else:
	Dz = 0.0000
	
currentVariable.setValue(currentRuntimestep, Dz)