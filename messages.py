UA = {
    'welcome': 'Вітаю! Я трекер артеріального тиску. Пиши в форматі 120/80/72',
    'saved': 'Збережено',
    'morning': 'Ранок',
    'midday': 'День',
    'evening': 'Вечір',
    'pulse': 'пульс',
    'average': 'Середні показники за останні 7 днів',
    'welcome_detailed': """
      Вітаю! Я трекер артеріального тиску.

      📝 Як користуватись:
      Надсилай показники: 120/80 або 120/80/72

      📊 Команди:
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
                  /last - Останні 5 вимірів
                  /avg - Середнє за 7 днів
                  /en - Перемкнути на English
                  /ua - Перемкнути на Українську

                  Формат вимірів: 120/80 або 120/80/72''',
}

EN = {
    'welcome': 'Welcome! I am a blood pressure tracker. Send readings as 120/80/72',
    'saved': 'Saved',
    'morning': 'Morning',
    'midday': 'Midday',
    'evening': 'Evening',
    'pulse': 'pulse',
    'average': 'Average for the last 7 days',
    'welcome_detailed': '''Welcome! I'm your blood pressure tracker.

                        📝 How to use:
                        Send readings: 120/80 or 120/80/72

                        📊 Commands:
                        /last - show last 5 readings
                        /avg - weekly average
                        /help - list all commands
                        /en - English
                        /ua - Українська

                        Example: 120/80/72''',
    'help_text': '''Available commands:

                      /start - Welcome message
                      /help - Show this help
                      /last - Last 5 readings
                      /avg - 7-day average
                      /en - Switch to English
                      /ua - Switch to Ukrainian

                      Reading format: 120/80 or 120/80/72''',
}


def get_text(lang, key):
    if lang == 'EN':
        return EN[key]
    return UA[key]