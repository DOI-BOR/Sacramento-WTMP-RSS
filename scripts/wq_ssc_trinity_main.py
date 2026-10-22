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
# This is a Trinity (location implied by context, not stated by any
# variable name in the script itself) SSC (suspended sediment
# concentration) StateVariable script, using the same breakpoint schedule
# shape (day 1/60/90/270/330/365) as the companion day-270 SSC script
# elsewhere in this project, but with a genuinely seasonal vals pattern
# here (a lower baseline of 3.5 mg/L early/late in the year, rising to
# 8.269 mg/L across a mid-year stretch from roughly day 90 to day 270)
# rather than a flat constant. Unlike every other script in this
# entrainment/SSC/shading family, this one carries its own explicit
# developer caveat: "Note these aren't calibrated as of 21Jun2021." This
# is preserved verbatim and flagged prominently here, since it means the
# numeric values below should not be treated as validated/final without
# checking whether a later calibration update superseded them elsewhere
# in the project.

from hec.model import SeasonalRecord

# Breakpoints are given as minutes-from-start-of-year, i.e. Julian day
# number multiplied by 1440 minutes/day.
times =[1, 60 * 1440, 90 * 1440, 270 * 1440, 330 * 1440, 365 * 1440]
# These are the SSC (mg/L)
# Note these aren't calibrated as of 21Jun2021
vals = [3.5, 3.5, 8.269, 8.269, 8.269, 3.5]

# Build the seasonal lookup table and interpolate it at the current time
# step's date, then apply the resulting value directly to the
# StateVariable.
sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)