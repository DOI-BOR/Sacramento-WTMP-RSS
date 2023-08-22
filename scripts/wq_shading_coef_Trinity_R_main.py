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

from hec.model import SeasonalRecord

# These are minutes from the start of the year (in format Julian day * 1440 min/day)
times =[1, 120 * 1440, 151 * 1440, 274 * 1440, 304 * 1440, 365 * 1440]
# These are the fractional shading amount
#vals = [0.0, 0.0, 0.35, 0.35, 0.0, 0.0]
vals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)

# to set the StateVariable's value use:
# 	currentVariable.setValue(currentRuntimestep, newValue)
# where newValue is the value you want to set it to.
