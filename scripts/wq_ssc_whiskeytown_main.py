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

# NOTES ON THIS SCRIPT AS A WHOLE
# -----------------------------------------------------------------------
# This is another SSC (suspended sediment concentration) StateVariable
# script using the same day-270 breakpoint schedule and SeasonalRecord
# mechanism as the companion Trinity SSC script and the earlier
# day-270 SSC script elsewhere in this project. Like the Trinity script,
# this one carries an explicit developer caveat -- "Note these aren't
# calibrated as of 21Jun2021" -- flagging that the numeric values below
# are placeholders pending calibration, not validated final values.
#
# The active vals array here is a flat constant (0.01 at every
# breakpoint), identical in value to the companion day-270 SSC script
# seen elsewhere in this project, but that other script lacked this
# calibration caveat and instead carried a disabled month-based
# alternative on a very different numeric scale (1.0/10.0). This script
# has no such disabled alternative. Given the shared 0.01 flat value, it
# is plausible both scripts represent placeholder SSC settings for
# different reservoir locations awaiting the same pending calibration
# effort, though that connection is inferred from the shared caveat/value
# rather than stated directly in either script.

from hec.model import SeasonalRecord

# Breakpoints are given as minutes-from-start-of-year, i.e. Julian day
# number multiplied by 1440 minutes/day.
times =[1, 60 * 1440, 90 * 1440, 270 * 1440, 330 * 1440, 365 * 1440]
# These are the SSC (mg/L)
# Note these aren't calibrated as of 21Jun2021
# ACTIVE: every breakpoint shares the same value, so this schedule is
# effectively a flat constant (0.01) across the whole year -- a
# placeholder pending the calibration noted above.
vals = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01]

# Build the seasonal lookup table and interpolate it at the current time
# step's date, then apply the resulting value directly to the
# StateVariable.
sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)