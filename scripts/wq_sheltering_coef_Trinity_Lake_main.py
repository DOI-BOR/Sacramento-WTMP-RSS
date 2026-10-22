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
# This is another seasonal StateVariable script using the same
# SeasonalRecord mechanism as the companion shading-fraction and vertical-
# diffusion (DZ) scripts elsewhere in this project, but here the
# interpolated quantity is SSC (suspended sediment concentration, in
# mg/L) rather than a shading fraction or mixing coefficient. Unlike the
# shading-fraction script, there is no disabled/commented-out alternative
# vals array here -- only the single active schedule below. The computed
# interpolated value is applied directly to currentVariable with nothing
# discarded.

from hec.model import SeasonalRecord

# Breakpoints are given as minutes-from-start-of-year, i.e. Julian day
# number multiplied by 1440 minutes/day. The six breakpoints define a
# schedule with two symmetric plateaus: a higher SSC value (0.4 mg/L)
# early and late in the year, dropping to zero across a middle stretch
# (roughly day 90 to day 300).
times =[1, 60 * 1440, 90 * 1440, 300 * 1440, 330 * 1440, 365 * 1440]
# These are the SSC (mg/L)

vals = [0.4, 0.4, 0.0, 0.0, 0.4, 0.4]

# Build the seasonal lookup table and interpolate it at the current time
# step's date, then apply the resulting value directly to the
# StateVariable.
sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)