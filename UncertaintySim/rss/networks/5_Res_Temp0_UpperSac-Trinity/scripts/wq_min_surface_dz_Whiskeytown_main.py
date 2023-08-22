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

# Get time series records
tsInflow = network.getTimeSeries("Reservoir","Whiskeytown Lake", "Pool", "Flow-IN", "")
tsOutflow = network.getTimeSeries("Reservoir","Whiskeytown Lake", "Pool", "Flow-OUT", "")

# Search over previous day
jCurrent = currentRuntimestep.getStep()
n = currentRuntimestep.getTotalNumSteps()
window = 24  # assume 1 hour time steps
qInMin = 1.e10
qInMax = -1.e10
qOutMin = 1.e10
qOutMax = -1.e10
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
inflowHasVariation = (qInMax - qInMin) > 1000. and qInMin < 500.
outflowHasVariation = (qOutMax - qOutMin) > 1000. and qOutMin < 500.
if inflowHasVariation or outflowHasVariation:
	Dz = 0.0000
else:
	Dz = 0.0000
	
currentVariable.setValue(currentRuntimestep, Dz)
