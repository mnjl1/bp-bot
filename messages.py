UA = {
    'welcome': 'Вітаю! Я трекер артеріального тиску. Пиши в форматі 120/80/72',
    'saved': 'Збережено',
    'morning': 'Ранок',
    'midday': 'День',
    'evening': 'Вечір',
    'pulse': 'пульс',
    'average': 'Середні показники за останні 7 днів',
}

EN = {
    'welcome': 'Welcome! I am a blood pressure tracker. Send readings as 120/80/72',
    'saved': 'Saved',
    'morning': 'Morning',
    'midday': 'Midday',
    'evening': 'Evening',
    'pulse': 'pulse',
    'average': 'Average for the last 7 days',
}


def get_text(lang, key):
    if lang == 'EN':
        return EN[key]
    return UA[key]