# no return values are used by the compute from this script.
#
# variables that are available to this script during the compute:
# 	currentVariable - the StateVariable that holds this script
# 	currentRuntimestep - the current RunTime step 
# 	network - the ResSim network

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



