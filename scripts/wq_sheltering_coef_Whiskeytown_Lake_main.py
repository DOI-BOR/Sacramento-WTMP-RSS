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
# This script is structurally identical to the companion SSC
# (suspended sediment concentration) seasonal script elsewhere in this
# project -- same times breakpoints (Julian day * 1440 minutes/day,
# matching the 1/60/90/300/330/365 pattern used there), same
# SeasonalRecord mechanism. The difference is that here the real SSC
# schedule is commented out and replaced with an all-zero vals array, the
# same disabled-schedule pattern seen in the companion shading-fraction
# script. As with that script, the computed interpolated value (v) IS
# applied to currentVariable -- nothing is discarded after the fact here,
# only the schedule's content has been flattened to zero.

from hec.model import SeasonalRecord

# Breakpoints are given as minutes-from-start-of-year, i.e. Julian day
# number multiplied by 1440 minutes/day.
times =[1, 60 * 1440, 90 * 1440, 300 * 1440, 330 * 1440, 365 * 1440]


# DISABLED (see Notes above): the real schedule would plateau at 0.4
# early and late in the year, dropping to 0.0 across a middle stretch
# (roughly day 90 to day 300) -- the same pattern as the companion SSC
# script's active values.
#vals = [0.4, 0.4, 0.0, 0.0, 0.4, 0.4]
# ACTIVE: value is flattened to zero across the entire year.
vals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

# Build the seasonal lookup table and interpolate it at the current time
# step's date, then apply the resulting value directly to the
# StateVariable.
sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)