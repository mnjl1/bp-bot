
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


# Reusable report output limits.
MAX_NOTE_LENGTH = 120
REPORT_NOTE_COLUMN_WIDTH = 24
REPORT_MESSAGE_LIMIT = 3500

SUPPORT_AMOUNTS = (25, 50, 100)
SUPPORT_CALLBACK_PATTERN = r'\Asupport:(25|50|100)\Z'
# Mandatory before production: configure a real public payment-support contact.
PAYMENT_SUPPORT_CONTACT = None
