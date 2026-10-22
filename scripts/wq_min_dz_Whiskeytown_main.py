# no return values are used by the compute from this script.
#
# variables that are available to this script during the compute:
# 	currentVariable - the StateVariable that holds this script
# 	currentRuntimestep - the current RunTime step 
# 	network - the ResSim network

# NOTES ON THIS SCRIPT AS A WHOLE
# -----------------------------------------------------------------------
# This script sets currentVariable using a seasonal (day-of-year)
# interpolated schedule via HEC-ResSim's SeasonalRecord utility, rather
# than any flow- or temperature-based calculation. This is the
# implemented version of the "flow-weighted inflow temperature" /
# SeasonalRecord sketch left disabled in the companion Whiskeytown
# entrainment script, though the values here represent minimum DZ
# (vertical diffusion/mixing) values rather than a shading fraction.
#
# The commented-out line directly below references a variable
# (entrainment_coef) that is never defined or computed anywhere in this
# script -- it appears to be a leftover copy-pasted line from the
# companion Whiskeytown rolling-average-outflow entrainment script
# (where entrainment_coef is a real computed value), left here as
# inactive scratch text rather than functional code.
#currentVariable.setValue(currentRuntimestep, entrainment_coef)

from hec.model import SeasonalRecord

# Breakpoints are given as minutes-from-start-of-year, i.e. Julian day
# number multiplied by 1440 minutes/day. The seven breakpoints below
# define a schedule with two "plateau" periods: a higher DZ value
# (2e-4) early and late in the year, dropping to a lower value (1.5e-5)
# across a middle stretch (roughly day 120 to day 320), with a short
# ramp back up between day 320 and day 335.
times =[1, 120 * 1440, 151 * 1440, 274 * 1440, 320 * 1440, 335 * 1440, 365 * 1440]
# These are the minimum DZ values
vals = [2e-4, 2e-4, 1.5e-5, 1.5e-5, 1.5e-5, 2e-4, 2e-4]
# Disabled alternative: an all-zero schedule, presumably for testing with
# DZ-driven entrainment effectively turned off entirely.
#vals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

# Build the seasonal lookup table and interpolate it at the current time
# step's date, then apply the resulting value directly to the
# StateVariable -- this is the only value-setting call in the script, and
# it is active (not discarded, unlike the pattern seen in the companion
# Whiskeytown entrainment script).
sr = SeasonalRecord()
sr.setArrays(times, vals)
v = sr.interpolate(currentRuntimestep.getHecTime())
currentVariable.setValue(currentRuntimestep, v)