from datetime import datetime
from messages import UA, EN, get_text
from constants import MORNING_END, MIDDAY_END, limits


def get_period_of_day(date, lang):
    date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    hour = date_obj.hour
    day_time = ''
    if hour < MORNING_END:
        day_time = get_text(lang, 'morning')
    elif hour >=MORNING_END and hour < MIDDAY_END:
        day_time = get_text(lang, 'midday')
    else: day_time = get_text(lang, 'evening')

    return day_time


def validate_reading(systolic, diastolic, pulse):
    values = {
    'systolic': systolic,
    'diastolic': diastolic,
    'pulse': pulse
    }

    for name, (min_value, max_value) in limits.items():
        if values[name] is not None:
            if not (min_value <= values[name] <= max_value):
                return
    return (systolic, diastolic, pulse)