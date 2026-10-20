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
# This is another SSC (suspended sediment concentration) StateVariable
# script in the same family as the companion SSC scripts elsewhere in
# this project, but it differs from both of them in two ways: the
# breakpoint schedule uses a slightly different fourth control point (day
# 270 here vs. day 300 in the companion scripts), and -- more
# significantly -- the active vals array is a flat constant (0.01 at
# every breakpoint), so the SeasonalRecord interpolation always returns
# 0.01 regardless of day-of-year; there is no seasonal variation
# currently in effect here, unlike the plateau/dip pattern used in the
# companion SSC script.
#
# A completely separate, disabled alternative strategy follows the active
# SeasonalRecord call: a simple month-based lookup that would set much
# larger values (1.0 for Jan-Mar and Dec, 10.0 for Apr-Nov) -- two orders
# of magnitude larger than the active 0.01 constant, and not expressed as
# an interpolated/smooth transition the way the SeasonalRecord approach
# is. This suggests the month-based approach was an earlier or
# alternative scaling for this same quantity, abandoned in favor of the
# much smaller flat SeasonalRecord-based value currently active. Both are
# preserved exactly rather than reconciled or corrected.

# to set the StateVariable's value use:
from hec.model import SeasonalRecord

# Breakpoints are given as minutes-from-start-of-year, i.e. Julian day
# number multiplied by 1440 minutes/day.
times =[1, 60 * 1440, 90 * 1440, 270 * 1440, 330 * 1440, 365 * 1440]
# These are the SSC (mg/L)

# ACTIVE: every breakpoint shares the same value, so this schedule is
# effectively constant (0.01) across the whole year despite being
# expressed via a seasonal interpolation mechanism.
vals = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01]

# Build the seasonal lookup table and interpolate it at the current time
# step's date, then apply the resulting value directly to the
# StateVariable.
sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)

# DISABLED: an alternative month-based approach, operating on a very
# different numeric scale (1.0 / 10.0) than the active constant 0.01
# above. Would set 1.0 during Jan-Mar and December, and 10.0 during
# Apr-Nov.
#curMon = currentRuntimestep.getHecTime().month()
#if curMon <= 3:
#	currentVariable.setValue(currentRuntimestep, 1.0)
#elif curMon <= 11:
#	currentVariable.setValue(currentRuntimestep, 10.0)
#else:
#	currentVariable.setValue(currentRuntimestep, 1.0)