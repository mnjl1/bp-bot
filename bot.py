import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update, BotCommand
from db import add_reading, get_last, get_avg, get_user_language, set_user_language
from utils import get_period_of_day
from messages import get_text
from admin import show_admin_stats


load_dotenv()

BOT_TOKEN = os.environ['BOT_TOKEN']

READING_PATTERN = r'^\d{2,3}/\d{2,3}(/\d{2,3})?$'


async def start(update, context):
    user_id = update.effective_user.id
    lang = get_user_language(user_id=user_id)
    welcome = get_text(lang=lang, key='welcome_detailed')
    await update.message.reply_text(welcome)


async def help(update, context):
    user_id = update.effective_user.id
    lang = get_user_language(user_id=user_id)
    help_text = get_text(lang=lang, key='help_text')
    await update.message.reply_text(help_text)


async def handle_reading(update, context):
    user_id = update.effective_user.id
    lang = get_user_language(user_id=user_id)
    text = update.message.text
    text = text.split('/')
    systolic = int(text[0])
    diastolic = int(text[1])
    pulse = None
    try:
        pulse = int(text[2])
    except:
        pass

    user_id = update.effective_user.id
    add_reading(user_id, systolic, diastolic, pulse)
    await update.message.reply_text(f"""{get_text(lang=lang, key='saved')} {systolic}/{diastolic},
                                     {get_text(lang=lang, key='pulse')} {pulse}""")


async def show_last_readings(update, context):
    user_id = update.effective_user.id
    lang = get_user_language(user_id=user_id)
    records = get_last(user_id=user_id)
    report = """"""

    for record in records:
        date = record[2]
        part_of_the_day = get_period_of_day(date=date, lang=lang)
        systolic = record[3]
        diastolic = record[4]
        pulse = record[5]
        report += f"""{date} ({part_of_the_day}) {systolic}/{diastolic},
                    {get_text(lang=lang, key='pulse')}: {pulse}\n"""

    await update.message.reply_text(report)


async def show_avg(update, context):
    user_id = update.effective_user.id
    lang = get_user_language(user_id=user_id)
    user_id = update.effective_user.id
    data = get_avg(user_id=user_id)
    avr_systolic = data[0][0]
    avr_diastolic = data[0][1]
    avr_pulse = data[0][2]
    record = f"""{get_text(lang=lang, key='average')}:
            {avr_systolic:.0f}/{avr_diastolic:.0f}/{avr_pulse:.0f}"""
    await update.message.reply_text(record)


async def set_english(update, context):
    user_id = update.effective_user.id
    set_user_language(user_id=user_id, language='EN')
    await update.message.reply_text('English is set')


async def set_ukrainian(update, context):
    user_id = update.effective_user.id
    set_user_language(user_id=user_id, language='UA')
    await update.message.reply_text('Українська мова встановлена')


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand('start', 'Welcome message and instructions'),
        BotCommand('help', 'Show all commands'),
        BotCommand('last', 'Show 5 last records'),
        BotCommand('avg', 'Show average for last 7 days')
    ])


if __name__ == '__main__':
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help))
    app.add_handler(MessageHandler(filters.Regex(READING_PATTERN), handle_reading))
    app.add_handler(CommandHandler('last', show_last_readings))
    app.add_handler(CommandHandler('avg', show_avg))
    app.add_handler(CommandHandler('en', set_english))
    app.add_handler(CommandHandler('ua', set_ukrainian))
    app.add_handler(CommandHandler('admin_stats', show_admin_stats))
    app.run_polling()