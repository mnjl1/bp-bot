import ast
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import CallbackQueryHandler

import db
from constants import SUPPORT_AMOUNTS, SUPPORT_CALLBACK_PATTERN
from messages import get_text
from test_db_migrations import LEGACY_READINGS, LEGACY_SETTINGS


class PaymentDatabaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'payments.sqlite'
        self.conn = sqlite3.connect(self.path)
        self.addCleanup(self.conn.close)
        patcher = patch.object(db, 'DB_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def v1(self):
        # Independent production-style v1 fixture; never open a real database.
        self.conn.executescript(LEGACY_READINGS + ';' + LEGACY_SETTINGS + ''';
            CREATE TABLE users (user_id INTEGER PRIMARY KEY,
                language TEXT NOT NULL DEFAULT 'UA',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY CHECK(version > 0),
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO schema_migrations(version) VALUES (1);
            CREATE INDEX idx_readings_user_datetime ON readings(user_id, datetime);
            INSERT INTO users VALUES (42, 'EN', '2020-01-01');
            INSERT INTO user_settings VALUES (42, 'EN');
            INSERT INTO readings(user_id, systolic, diastolic, note)
                VALUES (42, 120, 80, 'synthetic test note');
        ''')

    def receipt(self, **changes):
        values = dict(user_id=42, currency='XTR', amount=25, invoice_payload='support:25',
                      telegram_payment_charge_id='test-charge', provider_payment_charge_id='')
        values.update(changes)
        return db.record_payment(**values)

    def test_v1_migration_preserves_existing_data_and_schema(self):
        self.v1()
        tables = ('users', 'readings', 'user_settings')
        before = {t: self.conn.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        ddl = self.conn.execute("SELECT name, sql FROM sqlite_master WHERE name IN ('users', 'readings', 'user_settings') ORDER BY name").fetchall()
        db.init_db(self.path)
        db.check_database(self.path)
        self.assertEqual(before, {t: self.conn.execute(f'SELECT * FROM {t}').fetchall() for t in tables})
        self.assertEqual(ddl, self.conn.execute("SELECT name, sql FROM sqlite_master WHERE name IN ('users', 'readings', 'user_settings') ORDER BY name").fetchall())
        self.assertEqual(self.conn.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(1,), (2,)])
        self.assertEqual(self.conn.execute('PRAGMA table_info(payments)').fetchall(), [
            (0, 'id', 'INTEGER', 0, None, 1), (1, 'user_id', 'INTEGER', 1, None, 0),
            (2, 'currency', 'TEXT', 1, None, 0), (3, 'amount', 'INTEGER', 1, None, 0),
            (4, 'invoice_payload', 'TEXT', 1, None, 0),
            (5, 'telegram_payment_charge_id', 'TEXT', 1, None, 0),
            (6, 'provider_payment_charge_id', 'TEXT', 0, None, 0),
            (7, 'created_at', 'TEXT', 1, 'CURRENT_TIMESTAMP', 0)])
        self.receipt()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO payments(user_id,currency,amount,invoice_payload,telegram_payment_charge_id) VALUES(42,'XTR',0,'support:0','other')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO payments(user_id,currency,amount,invoice_payload,telegram_payment_charge_id) VALUES(42,'XTR',25,'support:25','test-charge')")

    def test_v1_startup_is_read_only_and_refuses_old_schema(self):
        self.v1()
        before = list(self.conn.iterdump())
        with patch.object(db, '_connect', wraps=db._connect) as connect:
            with self.assertRaisesRegex(RuntimeError, 'migration required'):
                db.check_database(self.path)
            connect.assert_called_once_with(self.path, 'ro')
        self.assertEqual(before, list(self.conn.iterdump()))

    def test_v2_failure_rolls_back_table_and_version(self):
        self.v1()
        self.conn.execute("CREATE TRIGGER fail_v2 BEFORE INSERT ON schema_migrations WHEN NEW.version = 2 BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        self.conn.commit()
        before = list(self.conn.iterdump())
        with self.assertRaises(sqlite3.IntegrityError):
            db.init_db(self.path)
        self.assertEqual(before, list(self.conn.iterdump()))

    def test_idempotency_conflicts_and_no_entitlements(self):
        self.v1()
        db.init_db(self.path)
        users = self.conn.execute('SELECT * FROM users').fetchall()
        readings = self.conn.execute('SELECT * FROM readings').fetchall()
        self.assertTrue(self.receipt())
        self.assertFalse(self.receipt())
        for changes in (dict(user_id=43), dict(currency='USD'), dict(amount=50),
                        dict(invoice_payload='support:50'),
                        dict(amount=50, invoice_payload='support:50'),
                        dict(provider_payment_charge_id='different'),
                        dict(provider_payment_charge_id=None)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.receipt(**changes)
        self.assertTrue(self.receipt(telegram_payment_charge_id='second'))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone(), (2,))
        self.assertEqual(users, self.conn.execute('SELECT * FROM users').fetchall())
        self.assertEqual(readings, self.conn.execute('SELECT * FROM readings').fetchall())

    def test_required_values_validated_before_database_access(self):
        for changes in (dict(user_id=None), dict(user_id=True), dict(user_id=0),
                        dict(amount=25.0), dict(amount=-1), dict(currency='USD'),
                        dict(telegram_payment_charge_id=' '), dict(invoice_payload='support:025'),
                        dict(provider_payment_charge_id=123)):
            with patch.object(db, '_connect') as connect:
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.receipt(**changes)
                connect.assert_not_called()


class StarsHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Extract handlers only: importing bot would load .env and runtime config.
        source = Path(__file__).resolve().parents[1] / 'bot.py'
        self.tree = ast.parse(source.read_text())
        names = {'valid_support_payment', 'support', 'support_agree', 'support_callback', 'support_precheckout',
                 'successful_support_payment', 'paysupport', 'terms', 'help', 'post_init'}
        nodes = [n for n in self.tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        self.ns = dict(get_text=get_text, get_user_language=Mock(return_value='UA'),
                       record_payment=Mock(return_value=True), SUPPORT_AMOUNTS=SUPPORT_AMOUNTS,
                       PAYMENT_SUPPORT_CONTACT=None, logger=logging.getLogger('stars-test'),
                       InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup,
                       LabeledPrice=LabeledPrice, BotCommand=BotCommand)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.ns)
        self.message = NS(reply_text=AsyncMock(), successful_payment=None)
        self.update = NS(message=self.message, effective_message=self.message,
                         effective_chat=NS(id=42, type='private'), effective_user=NS(id=42),
                         callback_query=NS(data='support:25', answer=AsyncMock(), edit_message_text=AsyncMock()))
        self.context = NS(bot=NS(send_invoice=AsyncMock(spec=Bot.send_invoice)))

    async def test_support_localization_and_exact_buttons(self):
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            await self.ns['support'](self.update, self.context)
            call = self.message.reply_text.await_args
            self.assertEqual(call.args, (get_text(lang, 'support_text'),))
            self.assertIn('/terms', call.args[0])
            buttons = call.kwargs['reply_markup'].inline_keyboard
            label = '✅ Погоджуюсь з умовами' if lang == 'UA' else '✅ I agree to the terms'
            self.assertEqual([[(b.text, b.callback_data) for b in row] for row in buttons],
                             [[(label, 'support:agree')]])
            self.update.callback_query.data = 'support:agree'
            await self.ns['support_agree'](self.update, self.context)
            call = self.update.callback_query.edit_message_text.await_args
            self.assertEqual(call.args, (get_text(lang, 'support_choose'),))
            buttons = call.kwargs['reply_markup'].inline_keyboard
            self.assertEqual([[(b.text, b.callback_data) for b in row] for row in buttons],
                             [[('25 ⭐', 'support:25'), ('50 ⭐', 'support:50'), ('100 ⭐', 'support:100')]])
        self.ns['record_payment'].assert_not_called()
        self.context.bot.send_invoice.assert_not_called()

    async def test_agreement_rejects_invalid_callback_and_non_private_chat(self):
        for data in ('support:agree\n', 'support:25', None, {}, 25):
            self.update.callback_query.data = data
            await self.ns['support_agree'](self.update, self.context)
        self.update.callback_query.data = 'support:agree'
        for chat in ('group', 'supergroup', 'channel'):
            self.update.effective_chat.type = chat
            await self.ns['support_agree'](self.update, self.context)
        self.update.callback_query.edit_message_text.assert_not_called()
        self.context.bot.send_invoice.assert_not_called()
        self.ns['record_payment'].assert_not_called()

    async def test_private_only_commands_and_callbacks(self):
        for chat in ('group', 'supergroup', 'channel'):
            for lang in ('UA', 'EN'):
                self.ns['get_user_language'].return_value = lang
                self.update.effective_chat.type = chat
                await self.ns['support'](self.update, self.context)
                self.message.reply_text.assert_awaited_with(get_text(lang, 'support_private'))
                await self.ns['support_callback'](self.update, self.context)
        self.context.bot.send_invoice.assert_not_called()

    async def test_invoice_fields_for_each_amount_and_language(self):
        import inspect
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            for amount in (25, 50, 100):
                self.update.callback_query.data = f'support:{amount}'
                await self.ns['support_callback'](self.update, self.context)
                kwargs = self.context.bot.send_invoice.await_args.kwargs
                inspect.signature(Bot.send_invoice).bind(None, **kwargs)
                self.assertEqual(kwargs['currency'], 'XTR')
                self.assertEqual(kwargs['payload'], f'support:{amount}')
                self.assertEqual(len(kwargs['prices']), 1)
                self.assertEqual(kwargs['prices'][0].amount, amount)
                self.assertEqual(kwargs['title'], get_text(lang, 'support_title'))
                self.assertEqual(kwargs['description'], get_text(lang, 'support_description'))
                self.assertNotIn('provider_token', kwargs)
        self.ns['record_payment'].assert_not_called()

    async def test_invalid_callbacks_cannot_invoice(self):
        handler = CallbackQueryHandler(self.ns['support_callback'], pattern=SUPPORT_CALLBACK_PATTERN)
        for data in ('support:0', 'support:26', 'support:025', 'support:25\n', 'support:1000', '', None, {}, 25):
            self.update.callback_query.data = data
            await self.ns['support_callback'](self.update, self.context)
            if isinstance(data, str):
                self.assertIsNone(handler.pattern.match(data))
        self.context.bot.send_invoice.assert_not_called()
        self.assertEqual(self.update.callback_query.answer.await_count, 9)

    async def test_precheckout_approval_and_rejections_without_database(self):
        for currency, amount, payload, valid in (
            ('XTR', 25, 'support:25', True), ('XTR', 50, 'support:50', True),
            ('XTR', 100, 'support:100', True), ('USD', 25, 'support:25', False),
            ('XTR', 26, 'support:26', False), ('XTR', 25, 'support:50', False),
            ('XTR', 25, 'support:25\n', False), ('XTR', 25.0, 'support:25', False)):
            query = NS(currency=currency, total_amount=amount, invoice_payload=payload,
                       from_user=NS(language_code='uk'), answer=AsyncMock())
            self.update.pre_checkout_query = query
            await self.ns['support_precheckout'](self.update, self.context)
            self.assertEqual(query.answer.await_args.kwargs['ok'], valid)
            if not valid:
                self.assertEqual(query.answer.await_args.kwargs['error_message'], get_text('UA', 'support_invalid'))
        self.ns['get_user_language'].assert_not_called()
        self.ns['record_payment'].assert_not_called()

    async def test_successful_receipt_and_duplicate_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.sqlite'
            db.init_db(path, initialize=True)
            self.ns['record_payment'] = db.record_payment
            self.message.successful_payment = NS(currency='XTR', total_amount=25,
                invoice_payload='support:25', telegram_payment_charge_id='test-charge',
                provider_payment_charge_id='')
            with patch.object(db, 'DB_PATH', path):
                for lang in ('UA', 'EN'):
                    self.ns['get_user_language'].return_value = lang
                    await self.ns['successful_support_payment'](self.update, self.context)
                    self.message.reply_text.assert_awaited_with(get_text(lang, 'support_thanks'))
                self.message.successful_payment.provider_payment_charge_id = 'conflict'
                self.message.reply_text.reset_mock()
                with self.assertRaises(ValueError):
                    await self.ns['successful_support_payment'](self.update, self.context)
                self.message.reply_text.assert_not_called()
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute('SELECT user_id,currency,amount,invoice_payload,telegram_payment_charge_id,provider_payment_charge_id FROM payments').fetchall(),
                                 [(42, 'XTR', 25, 'support:25', 'test-charge', '')])
                self.assertEqual(conn.execute('SELECT * FROM users').fetchall(), [])
                self.assertEqual(conn.execute('SELECT * FROM readings').fetchall(), [])

    async def test_no_receipt_without_valid_successful_payment(self):
        await self.ns['successful_support_payment'](self.update, self.context)
        for currency, amount, payload in (('USD', 25, 'support:25'), ('XTR', 26, 'support:26'), ('XTR', 25, 'support:50')):
            self.message.successful_payment = NS(currency=currency, total_amount=amount, invoice_payload=payload)
            with self.assertLogs('stars-test', level='WARNING'):
                await self.ns['successful_support_payment'](self.update, self.context)
        self.ns['record_payment'].assert_not_called()
        self.message.reply_text.assert_not_called()

    async def test_storage_failure_does_not_send_thanks(self):
        self.message.successful_payment = NS(currency='XTR', total_amount=25,
            invoice_payload='support:25', telegram_payment_charge_id='test', provider_payment_charge_id='')
        self.ns['record_payment'].side_effect = sqlite3.OperationalError('synthetic failure')
        with self.assertRaises(sqlite3.OperationalError):
            await self.ns['successful_support_payment'](self.update, self.context)
        self.message.reply_text.assert_not_called()

    async def test_paysupport_terms_help_and_menu(self):
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            for contact in (None, '', '  ', 'test-only contact'):
                self.ns['PAYMENT_SUPPORT_CONTACT'] = contact
                await self.ns['paysupport'](self.update, self.context)
                expected = get_text(lang, 'payment_contact').format(contact=contact) if contact and contact.strip() else get_text(lang, 'payment_contact_pending')
                self.message.reply_text.assert_awaited_with(expected)
            await self.ns['terms'](self.update, self.context)
            self.message.reply_text.assert_awaited_with(get_text(lang, 'support_terms'))
            await self.ns['help'](self.update, self.context)
            for command in ('/support', '/paysupport', '/terms'):
                self.assertIn(command, self.message.reply_text.await_args.args[0])
        app = NS(bot=NS(set_my_commands=AsyncMock()))
        await self.ns['post_init'](app)
        commands = [c.command for c in app.bot.set_my_commands.await_args.args[0]]
        self.assertTrue({'support', 'paysupport', 'terms'} <= set(commands))

    def test_handler_registration_without_starting_application(self):
        main = next(n for n in self.tree.body if isinstance(n, ast.If))
        calls = [n.value.args[0] for n in main.body if isinstance(n, ast.Expr)
                 and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                 and n.value.func.attr == 'add_handler']
        payments = next(c for c in calls if c.func.id == 'MessageHandler'
                        and isinstance(c.args[0], ast.Attribute) and c.args[0].attr == 'SUCCESSFUL_PAYMENT')
        self.assertEqual(payments.args[1].id, 'successful_support_payment')
        self.assertTrue(any(c.func.id == 'PreCheckoutQueryHandler' and c.args[0].id == 'support_precheckout' for c in calls))
        agreement = next(c for c in calls if c.func.id == 'CallbackQueryHandler' and c.args[0].id == 'support_agree')
        self.assertEqual(agreement.keywords[0].value.value, r'\Asupport:agree\Z')
        callback = next(c for c in calls if c.func.id == 'CallbackQueryHandler' and c.args[0].id == 'support_callback')
        self.assertEqual(callback.keywords[0].value.id, 'SUPPORT_CALLBACK_PATTERN')
        for command in ('support', 'paysupport', 'terms'):
            self.assertTrue(any(c.func.id == 'CommandHandler' and c.args[0].value == command for c in calls))
