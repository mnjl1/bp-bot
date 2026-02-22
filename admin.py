import os
from telegram import Update
from dotenv import load_dotenv
from db import get_total_users, get_total_readings

load_dotenv()

ADMIN_ID = os.environ['ADMIN_ID']


def is_admin(user_id):
    return int(ADMIN_ID) == int(user_id)


async def show_admin_stats(update, context):
    user_id = update.effective_user.id

    if is_admin(user_id=user_id):
        total_users = get_total_users()
        total_records = get_total_readings()
        report = f'Users: {total_users}\n Records: {total_records}'
        await update.message.reply_text(report)
