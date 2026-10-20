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
# This is a seasonal shading-fraction StateVariable script, using the
# same SeasonalRecord mechanism as the companion vertical-diffusion (DZ)
# script elsewhere in this project, and the same times breakpoint array
# (Julian day * 1440 minutes/day). Unlike the scripts that compute a real
# value and then discard it in favor of a hardcoded constant, this script
# does apply its interpolated result (v) to currentVariable -- nothing
# computed here is thrown away.
#
# However, the shading schedule itself has effectively been disabled:
# the commented-out vals array directly above the active one describes a
# real mid-year shading period (0.35 fractional shading roughly between
# day 151 and day 274), while the active vals array below it replaces
# every breakpoint with 0.0, meaning the interpolated shading fraction is
# always zero regardless of day-of-year. This is preserved exactly rather
# than corrected -- it may reflect an intentional decision to turn
# shading off for this run/configuration, or may be leftover from testing
# with the real schedule simply never restored. Either way, the original,
# presumably "live" seasonal values remain available as a one-line
# edit away, which is likely why they were commented out rather than
# deleted.

from hec.model import SeasonalRecord

# Breakpoints are given as minutes-from-start-of-year, i.e. Julian day
# number multiplied by 1440 minutes/day.
times =[1, 120 * 1440, 151 * 1440, 274 * 1440, 304 * 1440, 365 * 1440]
# These are the fractional shading amount.
# DISABLED (see Notes above): the real shading schedule would ramp shading
# up to 0.35 between roughly day 151 and day 274 (a mid-year plateau) and
# back down to 0 outside that window.
#vals = [0.0, 0.0, 0.35, 0.35, 0.0, 0.0]
# ACTIVE: shading is flattened to zero across the entire year.
vals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

# Build the seasonal lookup table and interpolate it at the current time
# step's date, then apply the resulting value directly to the
# StateVariable.
sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)

# to set the StateVariable's value use:
# 	currentVariable.setValue(currentRuntimestep, newValue)
# where newValue is the value you want to set it to.