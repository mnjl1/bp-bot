from datetime import datetime
from messages import UA, EN, get_text


def get_period_of_day(date, lang):
    date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    hour = date_obj.hour
    day_time = ''
    if hour >= 0 and hour < 12:
        day_time = get_text(lang, 'morning')
    elif hour >=12 and hour < 18:
        day_time = get_text(lang, 'midday')
    else: day_time = get_text(lang, 'evening')

    return day_time