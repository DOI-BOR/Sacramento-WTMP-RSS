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
from hec.model import SeasonalRecord

# These are minutes from the start of the year (in format day-of-year * 1440 min/day)
times =[1,	32*1440, 60*1440, 91*1440, 121*1440, 152*1440, 182*1440, 213*1440, 244*1440, 274*1440, 305*1440, 335*1440, 365*1440] 
# These are heating degrees C
vals = [1.02,1.06,1.0,0.92,1.13,0.93,1.02,1.38,1.40,1.11,1.13,1.14,1.02]

sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)
#currentVariable.setValue(currentRuntimestep, 0.0)
