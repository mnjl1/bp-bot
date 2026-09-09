import logging
import os
from dotenv import load_dotenv
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          CallbackQueryHandler, PreCheckoutQueryHandler)
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from db import (add_reading, get_last, get_avg, get_user_language,
                set_user_language, ensure_user, check_database, get_readings_by_date_range,
                record_payment)
from utils import get_period_of_day, validate_reading, process_user_input, convert_date
from utils import get_report_date_range, format_report
from messages import get_text
from admin import show_admin_stats
from constants import (READING_PATTERN, MAX_NOTE_LENGTH, SUPPORT_AMOUNTS,
                       SUPPORT_CALLBACK_PATTERN, PAYMENT_SUPPORT_CONTACT)


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


def valid_support_payment(currency, amount, payload):
    return (currency == 'XTR' and type(amount) is int
            and amount in SUPPORT_AMOUNTS and payload == f'support:{amount}')


async def support(update, context):
    user = update.effective_user
    lang = get_user_language(user.id) if user else 'UA'
    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(get_text(lang, 'support_private'))
        return
    if user is None:
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(get_text(lang, 'support_agree'), callback_data='support:agree')
    ]])
    await update.message.reply_text(get_text(lang, 'support_text'), reply_markup=keyboard)


async def support_agree(update, context):
    query = update.callback_query
    await query.answer()
    if (query.data != 'support:agree' or update.effective_chat is None
            or update.effective_chat.type != 'private' or update.effective_user is None):
        return
    lang = get_user_language(update.effective_user.id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f'{amount} ⭐', callback_data=f'support:{amount}')
        for amount in SUPPORT_AMOUNTS
    ]])
    await query.edit_message_text(get_text(lang, 'support_choose'), reply_markup=keyboard)


async def support_callback(update, context):
    query = update.callback_query
    await query.answer()
    if (update.effective_chat is None or update.effective_chat.type != 'private'
            or update.effective_user is None):
        return
    amounts = {f'support:{amount}': amount for amount in SUPPORT_AMOUNTS}
    if not isinstance(query.data, str) or query.data not in amounts:
        return
    amount = amounts[query.data]
    lang = get_user_language(update.effective_user.id)
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=get_text(lang, 'support_title'),
        description=get_text(lang, 'support_description'),
        payload=f'support:{amount}', currency='XTR',
        prices=[LabeledPrice(get_text(lang, 'support_title'), amount)],
    )


async def support_precheckout(update, context):
    query = update.pre_checkout_query
    # No database access on Telegram's time-sensitive approval path.
    if valid_support_payment(query.currency, query.total_amount, query.invoice_payload):
        await query.answer(ok=True)
    else:
        lang = 'UA' if (query.from_user.language_code or '').lower().startswith('uk') else 'EN'
        await query.answer(ok=False, error_message=get_text(lang, 'support_invalid'))


async def successful_support_payment(update, context):
    message = update.message
    if message is None or message.successful_payment is None:
        return
    payment = message.successful_payment
    if not valid_support_payment(payment.currency, payment.total_amount, payment.invoice_payload):
        logger.warning('Rejected unexpected successful support payment')
        return
    if update.effective_user is None:
        return
    record_payment(update.effective_user.id, payment.currency, payment.total_amount,
                   payment.invoice_payload, payment.telegram_payment_charge_id,
                   payment.provider_payment_charge_id)
    lang = get_user_language(update.effective_user.id)
    await message.reply_text(get_text(lang, 'support_thanks'))


async def paysupport(update, context):
    lang = get_user_language(update.effective_user.id)
    contact = (PAYMENT_SUPPORT_CONTACT or '').strip()
    text = (get_text(lang, 'payment_contact').format(contact=contact)
            if contact else get_text(lang, 'payment_contact_pending'))
    await update.message.reply_text(text)


async def terms(update, context):
    lang = get_user_language(update.effective_user.id)
    await update.message.reply_text(get_text(lang, 'support_terms'))


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
        BotCommand('report', 'Free report for the last 30 days'),
        BotCommand('support', 'Voluntary support for the free bot'),
        BotCommand('paysupport', 'Payment support'),
        BotCommand('terms', 'Stars support terms')
    ])


if __name__ == '__main__':
    setup_logging()
    check_database()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler('support', support))
    app.add_handler(CommandHandler('paysupport', paysupport))
    app.add_handler(CommandHandler('terms', terms))
    app.add_handler(CallbackQueryHandler(support_agree, pattern=r'\Asupport:agree\Z'))
    app.add_handler(CallbackQueryHandler(support_callback, pattern=SUPPORT_CALLBACK_PATTERN))
    app.add_handler(PreCheckoutQueryHandler(support_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_support_payment))
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
