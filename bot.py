import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from db import add_reading, get_last, get_avg


load_dotenv()

BOT_TOKEN = os.environ['BOT_TOKEN']

READING_PATTERN = r'^\d{2,3}/\d{2,3}(/\d{2,3})?$'


async def start(update, context):
    await update.message.reply_text(
        """Welcome to BP Tracker!
          Send your reading as 120/80 or 120/80/72"""
        )


async def handle_reading(update, context):
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
    await update.message.reply_text(f'Saved {systolic}/{diastolic}, pulse {pulse}')


async def show_last_readings(update, context):
    user_id = update.effective_user.id
    records = get_last(user_id=user_id)

    report = """"""

    for record in records:
        date = record[2]
        systolic = record[3]
        diastolic = record[4]
        pulse = record[5]
        report += f'{date} {systolic}/{diastolic}, pulse: {pulse}\n'

    await update.message.reply_text(report)


async def show_avg(update, context):
    user_id = update.effective_user.id
    data = get_avg(user_id=user_id)
    avr_systolic = data[0][0]
    avr_diastolic = data[0][1]
    avr_pulse = data[0][2]
    record = f'Average: {avr_systolic}/{avr_diastolic}/{avr_pulse}'
    await update.message.reply_text(record)


if __name__ == '__main__':
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.Regex(READING_PATTERN), handle_reading))
    app.add_handler(CommandHandler('last', show_last_readings))
    app.add_handler(CommandHandler('avg', show_avg))
    app.run_polling()