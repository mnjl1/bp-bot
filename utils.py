from datetime import datetime


def get_period_of_day(date):
    date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    hour = date_obj.hour
    day_time = ''
    if hour >= 0 and hour < 12:
        day_time = 'Morning'
    elif hour >=12 and hour < 18:
        day_time = 'Midday'
    else: day_time = 'Evening'

    return day_time