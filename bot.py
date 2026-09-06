import logging
import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update, BotCommand
from db import (add_reading, get_last, get_avg, get_user_language,
                set_user_language, ensure_user, check_database, get_readings_by_date_range)
from utils import get_period_of_day, validate_reading, process_user_input, convert_date
from utils import get_report_date_range, format_report
from messages import get_text
from admin import show_admin_stats
from constants import READING_PATTERN, MAX_NOTE_LENGTH


logger = logging.getLogger(__name__)

load_dotenv()


def setup_logging():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
    )
    logging.getLogger('httpx').setLevel(logging.WARNING)


async def error_handler(update, context):
    logger.error(
        'Unhandled exception while processing a Telegram update',
        exc_info=context.error,
    )


BOT_TOKEN = os.environ['BOT_TOKEN']


async def start(update, context):
    user_id = update.effective_user.id
    ensure_user(user_id)
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
    try:
        records, note = process_user_input(text)
    except ValueError:
        await update.message.reply_text(get_text(lang, 'wrong_input'))
        return
    if note is not None and len(note) > MAX_NOTE_LENGTH:
        await update.message.reply_text(
            get_text(lang, 'note_too_long').format(limit=MAX_NOTE_LENGTH))
        return
    note = ' '.join(note.split()) if note else None
    systolic = records['systolic']
    diastolic = records['diastolic']
    pulse = records['pulse']

    validated_values = validate_reading(systolic, diastolic, pulse)

    if validated_values:
        systolic, diastolic, pulse = validated_values
        add_reading(user_id, systolic, diastolic, pulse, note)
        pulse_part = ''
        if pulse is not None:
            pulse_part = f",\n                                    {get_text(lang=lang, key='pulse')}{pulse}"
        await update.message.reply_text(f"""{get_text(lang=lang, key='saved')}
                                    {systolic}/{diastolic}{pulse_part}
                                    {note if note else ''}""")
    else:
        await update.message.reply_text(get_text(lang=lang, key='wrong_input'))


async def show_last_readings(update, context):
    user_id = update.effective_user.id
    lang = get_user_language(user_id=user_id)
    records = get_last(user_id=user_id)
    report = """"""

    for record in records:
        date = convert_date(record[2])
        part_of_the_day = get_period_of_day(date=record[2], lang=lang)
        systolic = record[3]
        diastolic = record[4]
        pulse = record[5]
        note = record[6]
        pulse_part = f", {get_text(lang=lang, key='pulse')} {pulse}" if pulse is not None else ''
        report += f"{date} ({part_of_the_day}) {systolic}/{diastolic}{pulse_part} {note if note else ''}\n\n"

    await update.message.reply_text(report)


async def show_avg(update, context):
    user_id = update.effective_user.id
    lang = get_user_language(user_id=user_id)
    user_id = update.effective_user.id
    data = get_avg(user_id=user_id)
    avr_systolic = data[0][0]
    avr_diastolic = data[0][1]
    avr_pulse = data[0][2]
    pulse_part = f"/{avr_pulse:.0f}" if avr_pulse is not None else ''
    record = f"""{get_text(lang=lang, key='average')}:
            {avr_systolic:.0f}/{avr_diastolic:.0f}{pulse_part}"""
    await update.message.reply_text(record)


async def show_report(update, context):
    user = update.effective_user
    lang = get_user_language(user_id=user.id) if user is not None else 'UA'
    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(get_text(lang, 'report_private'))
        return
    if user is None:
        return
    start, end = get_report_date_range()
    records = get_readings_by_date_range(user.id, start, end)
    for message in format_report(records, start, end, lang):
        await update.effective_message.reply_text(message, parse_mode='HTML')


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
        BotCommand('avg', 'Show average for last 7 days'),
        BotCommand('report', 'Free report for the last 30 days')
    ])


if __name__ == '__main__':
    setup_logging()
    check_database()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help))
    app.add_handler(MessageHandler(filters.Regex(READING_PATTERN), handle_reading))
    app.add_handler(CommandHandler('last', show_last_readings))
    app.add_handler(CommandHandler('avg', show_avg))
    app.add_handler(CommandHandler('report', show_report))
    app.add_handler(CommandHandler('en', set_english))
    app.add_handler(CommandHandler('ua', set_ukrainian))
    app.add_handler(CommandHandler('admin_stats', show_admin_stats))
    app.run_polling()
