
#example 120/80/70
READING_PATTERN = r'^\d{2,3}/\d{2,3}(/\d{2,3})?.*'

# Period of day hour boundaries
MORNING_END = 12
MIDDAY_END = 18

#input validation
#user realistic input must be in limits
limits = {
    'systolic': (60, 300),
    'diastolic': (30, 140),
    'pulse': (30, 220)
}

