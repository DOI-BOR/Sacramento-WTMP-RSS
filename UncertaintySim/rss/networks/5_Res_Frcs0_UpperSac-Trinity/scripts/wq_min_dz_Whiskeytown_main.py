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


#Stephen Andrews:
#So I implemented it like it was the highest priority for any of the Dz methods. So by that I mean, some of the Dz methods have a Dzmin, and one has a Dz max. The Dz min that you pass in as a state variable will supercede all of those. 
#In the compute it looks something like:final_Dz = ...if (state_var_Dz_min > 0) then    final_Dz = max(final_Dz, state_var_Dz_min)
#So you can turn off the functionality and have it revert back to what it was doing originally by setting a negative value.


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
qsum = 0.0
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
max_entrainment = 0.001e-5
min_entrainment = 1.5e-5
max_q = 1200
min_q = 300

# linear between thse points
slope = (min_entrainment-max_entrainment)/(max_q-min_q)
b = min_entrainment - slope*max_q
entrainment_coef = qave*slope + b
entrainment_coef = max(min_entrainment,entrainment_coef)
entrainment_coef = min(max_entrainment,entrainment_coef)


# use alternate high values below 1200 cfs
if qave > max_q:
	entrainment_coef = max_entrainment
else:
	entrainment_coef = -1

#currentVariable.setValue(currentRuntimestep, entrainment_coef)

from hec.model import SeasonalRecord

# These are minutes from the start of the year (in format Julian day * 1440 min/day)
times =[1, 120 * 1440, 151 * 1440, 274 * 1440, 320 * 1440, 335 * 1440, 365 * 1440]
# These are the minimum DZ values
vals = [2e-4, 2e-4, 1.5e-5, 1.5e-5, 1.5e-5, 2e-4, 2e-4]
#vals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)



