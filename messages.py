UA = {
    'note_too_long': 'Вимір не збережено. Примітка має містити не більше {limit} символів.',
    'report_private': 'Звіт доступний лише в приватному чаті з ботом.',
    'report_title': 'Безкоштовний звіт: {start} – {end}',
    'report_date': 'Дата / період',
    'report_sys': 'СИС',
    'report_dia': 'ДІА',
    'report_pulse': 'Пульс',
    'report_note': 'Примітка',
    'report_empty': 'За цей період немає вимірів.',
    'report_averages': 'Середні показники за весь період',
    'report_avg_sys': 'Систолічний',
    'report_avg_dia': 'Діастолічний',
    'report_count': 'Кількість вимірів',
    'report_invalid': 'Деякі записи мають некоректні дані та не включені у звіт.',
    'welcome': 'Вітаю! Я трекер артеріального тиску. Пиши в форматі 120/80/72',
    'saved': 'Збережено',
    'morning': 'Ранок',
    'midday': 'День',
    'evening': 'Вечір',
    'pulse': 'пульс:',
    'average': 'Середні показники за останні 7 днів',
    'wrong_input': 'Не реальні показники',
    'welcome_detailed': """
      Вітаю! Я трекер артеріального тиску.

      📝 Як користуватись:
      Надсилай показники: 120/80 або 120/80/72

      📊 Команди:
      /report - безкоштовний звіт за 30 днів
      /last - останні 5 вимірів
      /avg - середнє за тиждень
      /help - список всіх команд
      /en - English
      /ua - Українська

      Приклад: 120/80/72
          """,
    'help_text': '''Доступні команди:

                  /start - Вітальне повідомлення
                  /help - Показати цю довідку
                  /report - Безкоштовний звіт за 30 днів
                  /last - Останні 5 вимірів
                  /avg - Середнє за 7 днів
                  /en - Перемкнути на English
                  /ua - Перемкнути на Українську

                  Формат вимірів: 120/80 або 120/80/72
                  Примітка через пробіл або /, наприклад: 120/80/72 після прогулянки
                  Примітка: максимум 120 символів.''',
}

EN = {
    'note_too_long': 'Reading not saved. Notes must be no longer than {limit} characters.',
    'report_private': 'Reports are available only in a private chat with the bot.',
    'report_title': 'Free report: {start} – {end}',
    'report_date': 'Date / period',
    'report_sys': 'SYS',
    'report_dia': 'DIA',
    'report_pulse': 'Pulse',
    'report_note': 'Note',
    'report_empty': 'No readings for this period.',
    'report_averages': 'Averages for the whole period',
    'report_avg_sys': 'Systolic',
    'report_avg_dia': 'Diastolic',
    'report_count': 'Number of readings',
    'report_invalid': 'Some records contain invalid data and were excluded from the report.',
    'welcome': 'Welcome! I am a blood pressure tracker. Send readings as 120/80/72',
    'saved': 'Saved',
    'morning': 'Morning',
    'midday': 'Midday',
    'evening': 'Evening',
    'pulse': 'pulse:',
    'average': 'Average for the last 7 days',
    'wrong_input': 'Input is not correct',
    'welcome_detailed': '''Welcome! I'm your blood pressure tracker.

                        📝 How to use:
                        Send readings: 120/80 or 120/80/72

                        📊 Commands:
                        /report - free 30-day report
                        /last - show last 5 readings
                        /avg - weekly average
                        /help - list all commands
                        /en - English
                        /ua - Українська

                        Example: 120/80/72''',
    'help_text': '''Available commands:

                      /start - Welcome message
                      /help - Show this help
                      /report - Free 30-day report
                      /last - Last 5 readings
                      /avg - 7-day average
                      /en - Switch to English
                      /ua - Switch to Ukrainian

                      Reading format: 120/80 or 120/80/72
                      Note after a space or /, e.g. 120/80/72 after a walk
                      Note: maximum 120 characters.''',
}


def get_text(lang, key):
    if lang == 'EN':
        return EN[key]
    return UA[key]