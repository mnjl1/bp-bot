"""Deletion flow uses real production queries and synthetic temporary SQLite only."""
import ast
import logging
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update,
                      CallbackQuery, InaccessibleMessage)
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler

import db
from messages import get_text
from utils import (convert_date, effective_timezone, format_report, get_period_of_day,
                   get_report_candidate_range)


NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


class DeleteLastTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'synthetic.sqlite'
        db.init_db(self.path, initialize=True)
        patcher = patch.object(db, 'DB_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        db.ensure_user(42)
        db.set_user_timezone(42, 'Europe/London')
        self.source = Path(__file__).resolve().parents[1] / 'bot.py'
        tree = ast.parse(self.source.read_text())
        names = {'delete_last', 'delete_last_callback', 'show_last_readings',
                 'show_avg', 'show_report'}
        nodes = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in names]
        self.ns = dict(
            InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup,
            TelegramError=TelegramError, logger=logging.getLogger('delete-last-test'),
            get_text=get_text, get_user_language=db.get_user_language,
            get_user_timezone=db.get_user_timezone, get_last=Mock(wraps=db.get_last),
            delete_reading=Mock(wraps=db.delete_reading), convert_date=convert_date,
            effective_timezone=effective_timezone, get_period_of_day=get_period_of_day,
            get_avg=lambda user_id: db.get_avg(user_id, now=NOW),
            get_readings_by_date_range=db.get_readings_by_date_range,
            get_report_date_range=lambda **kw: ('2026-08-08 00:00:00', '2026-09-07 00:00:00'),
            get_report_candidate_range=get_report_candidate_range, format_report=format_report,
        )
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(self.source), 'exec'), self.ns)
        self.user = SimpleNamespace(id=42)
        self.chat = SimpleNamespace(id=42, type='private')
        self.message = SimpleNamespace(reply_text=AsyncMock(
            return_value=SimpleNamespace(message_id=100)))
        self.update = SimpleNamespace(effective_user=self.user, effective_chat=self.chat,
                                      effective_message=self.message, message=self.message)
        self.context = SimpleNamespace(user_data={}, bot=SimpleNamespace(send_message=AsyncMock()))

    def insert(self, reading_id=1, user_id=42, timestamp='2026-09-06 08:00:00',
               pulse=72, note=None, zone='Europe/London', systolic=120):
        with sqlite3.connect(self.path) as conn:
            conn.execute('INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         (reading_id, user_id, timestamp, systolic, 80, pulse, note, zone))

    def rows(self, user_id=42):
        return db.get_last(user_id, n=100)

    async def prompt(self, message_id=100):
        self.message.reply_text.return_value = SimpleNamespace(message_id=message_id)
        await self.ns['delete_last'](self.update, self.context)
        return self.message.reply_text.await_args

    def callback(self, data='delete_last:confirm:1', *, user_id=42, chat_id=42,
                 message_id=100, chat_type='private'):
        user = SimpleNamespace(id=user_id)
        chat = SimpleNamespace(id=chat_id, type=chat_type)
        query = SimpleNamespace(
            data=data, from_user=user, message=SimpleNamespace(message_id=message_id, chat=chat),
            answer=AsyncMock(), edit_message_text=AsyncMock(), edit_message_reply_markup=AsyncMock())
        update = SimpleNamespace(callback_query=query, effective_user=user, effective_chat=chat)
        return update, query

    async def act(self, data='delete_last:confirm:1', **kw):
        update, query = self.callback(data, **kw)
        await self.ns['delete_last_callback'](update, self.context)
        return query

    async def test_empty_localized_without_buttons_or_delete(self):
        for lang in ('UA', 'EN'):
            db.set_user_language(42, lang)
            self.context.user_data['delete_last_pending'] = (42, 1, 42, 99)
            call = await self.prompt()
            self.assertEqual(call.args, (get_text(lang, 'delete_empty'),))
            self.assertEqual(call.kwargs, {})
            self.assertEqual(self.context.user_data, {})
        self.ns['delete_reading'].assert_not_called()

    async def test_prompt_exact_target_no_delete_optional_values_and_buttons(self):
        self.insert(1, note='after a walk')
        self.insert(2, user_id=99, timestamp='2026-09-06 11:00:00')
        for lang in ('UA', 'EN'):
            db.set_user_language(42, lang)
            call = await self.prompt()
            self.assertIn('06/09/26 (' + get_text(lang, 'morning') + ') 120/80', call.args[0])
            self.assertIn(get_text(lang, 'pulse') + ' 72', call.args[0])
            self.assertIn('after a walk', call.args[0])
            buttons = call.kwargs['reply_markup'].inline_keyboard[0]
            self.assertEqual([b.text for b in buttons],
                             [get_text(lang, 'delete_confirm'), get_text(lang, 'delete_keep')])
            self.assertEqual([b.callback_data for b in buttons],
                             ['delete_last:confirm:1', 'delete_last:keep:1'])
            self.assertEqual(self.context.user_data['delete_last_pending'], (42, 1, 42, 100))
        self.ns['get_last'].assert_called_with(42, n=1)
        self.ns['delete_reading'].assert_not_called()
        self.assertEqual(len(self.rows()), 1)
        self.insert(3, timestamp='2026-09-06 09:00:00', pulse=None)
        call = await self.prompt()
        self.assertNotIn(get_text('EN', 'pulse'), call.args[0])
        self.assertNotIn('after a walk', call.args[0])

    async def test_timezone_snapshot_fallback_and_unset(self):
        self.insert(timestamp='2026-07-01 21:30:00', zone='Europe/Kyiv')
        call = await self.prompt()
        self.assertIn('02/07/26', call.args[0])
        self.assertNotIn('Europe/', call.args[0])
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE readings SET timezone = NULL')
        call = await self.prompt()
        self.assertIn('01/07/26', call.args[0])
        self.assertIn(get_text('UA', 'evening'), call.args[0])
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE users SET timezone = NULL WHERE user_id = 42')
        call = await self.prompt()
        self.assertIn(get_text('UA', 'time_neutral'), call.args[0])
        self.assertIn(get_text('UA', 'timezone_neutral_notice'), call.args[0])
        self.assertNotIn(get_text('UA', 'evening'), call.args[0])

    async def test_long_legacy_note_safe_in_both_languages_and_unchanged(self):
        note = '<b>&😀\n' * 5000
        self.insert(note=note)
        for lang in ('UA', 'EN'):
            db.set_user_language(42, lang)
            call = await self.prompt()
            self.assertLessEqual(len(call.args[0].encode('utf-16-le')) // 2, 4096)
            self.assertIn(note[:1000] + '…', call.args[0])
            self.assertEqual(self.rows()[0][6], note)

    async def test_confirm_only_original_target_new_reading_survives(self):
        self.insert()
        await self.prompt()
        self.insert(2, timestamp='2026-09-06 09:00:00')
        query = await self.act()
        self.assertEqual([r[0] for r in self.rows()], [2])
        self.ns['delete_reading'].assert_called_once_with(42, 1)
        query.edit_message_text.assert_awaited_once_with(
            get_text('UA', 'delete_success'), reply_markup=None)
        self.assertEqual(self.context.user_data, {})
        await self.act()
        self.assertEqual([r[0] for r in self.rows()], [2])
        self.ns['delete_reading'].assert_called_once()

    async def test_keep_and_stale_confirm_preserve_everything(self):
        self.insert()
        before = self.rows()
        await self.prompt()
        query = await self.act('delete_last:keep:1')
        query.edit_message_text.assert_awaited_once_with(
            get_text('UA', 'delete_cancelled'), reply_markup=None)
        query = await self.act()
        query.answer.assert_awaited_once_with(get_text('UA', 'delete_expired'))
        self.assertEqual(self.rows(), before)
        self.ns['delete_reading'].assert_not_called()

    async def test_keep_missing_target_uses_neutral_localized_cancellation(self):
        for lang, expected in (('UA', 'Видалення скасовано.'),
                               ('EN', 'Deletion cancelled.')):
            with self.subTest(lang=lang):
                db.set_user_language(42, lang)
                self.insert()
                await self.prompt()
                db.delete_reading(42, 1)
                self.insert(2)
                query = await self.act('delete_last:keep:1')
                query.edit_message_text.assert_awaited_once_with(expected, reply_markup=None)
                self.assertEqual([r[0] for r in self.rows()], [2])
                self.assertEqual(self.context.user_data, {})
                db.delete_reading(42, 2)
        self.ns['delete_reading'].assert_not_called()

    async def test_invalid_user_ids_never_reach_sqlite_or_consume_pending(self):
        self.insert()
        await self.prompt()
        pending = self.context.user_data.copy()
        invalid_ids = (None, True, False, 0, -1, -(2 ** 63), 2 ** 63,
                       10 ** 100, 42.0, 1.5, '42', b'42', [], {})
        for user_id in invalid_ids:
            with self.subTest(user_id=repr(user_id)):
                self.update.effective_user = SimpleNamespace(id=user_id)
                self.message.reply_text.reset_mock()
                with patch.object(db, '_connect') as connect:
                    await self.ns['delete_last'](self.update, self.context)
                    for action in ('confirm', 'keep'):
                        query = await self.act(f'delete_last:{action}:1', user_id=user_id)
                        query.answer.assert_awaited_once_with(get_text('UA', 'delete_expired'))
                        query.edit_message_text.assert_not_awaited()
                    connect.assert_not_called()
                self.message.reply_text.assert_not_awaited()
                self.assertEqual(self.context.user_data, pending)
        self.ns['delete_reading'].assert_not_called()
        self.assertEqual([r[0] for r in self.rows()], [1])

    async def test_positive_signed_64_bit_user_id_boundaries(self):
        for user_id in (1, 2 ** 63 - 1):
            with self.subTest(user_id=user_id):
                db.ensure_user(user_id)
                self.insert(user_id=user_id)
                self.update.effective_user = SimpleNamespace(id=user_id)
                self.update.effective_chat = SimpleNamespace(id=user_id, type='private')
                await self.prompt()
                self.assertEqual(self.context.user_data['delete_last_pending'],
                                 (user_id, 1, user_id, 100))
                await self.act(user_id=user_id, chat_id=user_id)
                self.assertEqual(self.rows(user_id), [])
        self.assertEqual(self.ns['delete_reading'].call_count, 2)

    async def test_command_without_user_never_reaches_sqlite(self):
        self.update.effective_user = None
        with patch.object(db, '_connect') as connect:
            await self.ns['delete_last'](self.update, self.context)
            connect.assert_not_called()
        self.message.reply_text.assert_not_awaited()

    async def test_latest_datetime_takes_priority_over_id_then_id_breaks_ties(self):
        self.insert(10, timestamp='2026-09-05 23:59:59')
        self.insert(1, timestamp='2026-09-06 08:00:00')
        self.insert(2, timestamp='2026-09-06 08:00:00')
        await self.prompt()
        self.assertEqual(self.context.user_data['delete_last_pending'], (42, 2, 42, 100))
        await self.act('delete_last:confirm:2')
        self.assertEqual([r[0] for r in self.rows()], [1, 10])

    async def test_missing_target_localized_and_never_deletes_latest(self):
        for lang in ('UA', 'EN'):
            with self.subTest(lang=lang):
                db.set_user_language(42, lang)
                self.insert()
                await self.prompt()
                db.delete_reading(42, 1)
                self.insert(2)
                query = await self.act()
                query.edit_message_text.assert_awaited_once_with(
                    get_text(lang, 'delete_missing'), reply_markup=None)
                self.assertEqual([r[0] for r in self.rows()], [2])
                db.delete_reading(42, 2)

    async def test_new_prompt_replaces_old_even_same_reading(self):
        self.insert()
        await self.prompt()
        await self.prompt(message_id=101)
        pending = self.context.user_data.copy()
        await self.act()
        self.assertEqual(self.context.user_data, pending)
        self.assertEqual(len(self.rows()), 1)
        await self.act(message_id=101)
        self.assertEqual(self.rows(), [])

    async def test_prompt_send_failure_invalidates_previous(self):
        self.insert()
        await self.prompt()
        self.message.reply_text.side_effect = TelegramError('cannot send')
        with self.assertRaises(TelegramError):
            await self.prompt(message_id=101)
        self.assertEqual(self.context.user_data, {})
        await self.act()
        self.assertEqual(len(self.rows()), 1)

    async def test_state_loss_expires_old_buttons(self):
        self.insert()
        await self.prompt()
        self.context.user_data.clear()
        query = await self.act()
        query.answer.assert_awaited_once_with(get_text('UA', 'delete_expired'))
        self.assertEqual(len(self.rows()), 1)
        self.ns['delete_reading'].assert_not_called()

    async def test_malformed_and_out_of_range_payloads_do_not_consume_pending(self):
        self.insert()
        await self.prompt()
        pending = self.context.user_data.copy()
        payloads = [None, 1, [], '', 'delete_last', 'delete_last:confirm',
                    'delete_last:confirm:1:extra', 'other:confirm:1',
                    'delete_last:unknown:1', 'delete_last:confirm:',
                    'delete_last:confirm:+1', 'delete_last:confirm:01',
                    'delete_last:confirm: 1', 'delete_last:confirm:1.0',
                    'delete_last:confirm:١', 'delete_last:confirm:²',
                    'delete_last:confirm:--1', 'delete_last:confirm:-0',
                    'delete_last:confirm:9223372036854775808',
                    'delete_last:confirm:-9223372036854775809',
                    'delete_last:confirm:' + '9' * 5000,
                    'delete_last:confirm:2']
        for payload in payloads:
            with self.subTest(payload=repr(payload)[:100]):
                await self.act(payload)
                self.assertEqual(self.context.user_data, pending)
                self.assertEqual(len(self.rows()), 1)
        self.ns['delete_reading'].assert_not_called()
        await self.act()
        self.assertEqual(self.rows(), [])

    async def test_foreign_callback_bindings_do_not_consume_pending(self):
        self.insert()
        await self.prompt()
        pending = self.context.user_data.copy()
        for kw in ({'user_id': 99}, {'chat_id': 99}, {'message_id': 101},
                   {'chat_type': 'group'}, {'chat_type': 'supergroup'}):
            await self.act(**kw)
            self.assertEqual(self.context.user_data, pending)
            self.assertEqual(len(self.rows()), 1)
        for field in ('from_user', 'message_chat', 'message_type', 'no_message', 'no_user', 'no_chat'):
            update, query = self.callback()
            if field == 'from_user':
                query.from_user = SimpleNamespace(id=99)
            elif field == 'message_chat':
                query.message.chat = SimpleNamespace(id=99, type='private')
            elif field == 'message_type':
                query.message.chat = SimpleNamespace(id=42, type='group')
            elif field == 'no_message':
                query.message = None
            elif field == 'no_user':
                update.effective_user = None
            else:
                update.effective_chat = None
            await self.ns['delete_last_callback'](update, self.context)
            self.assertEqual(self.context.user_data, pending)
        self.ns['delete_reading'].assert_not_called()
        await self.act()
        self.assertEqual(self.rows(), [])

    async def test_group_command_cannot_read_or_change_pending(self):
        self.insert()
        self.context.user_data['delete_last_pending'] = (42, 1, 42, 100)
        self.update.effective_chat = SimpleNamespace(id=-100, type='group')
        call = await self.prompt()
        self.assertEqual(call.args, (get_text('UA', 'delete_private'),))
        self.ns['get_last'].assert_not_called()
        self.ns['delete_reading'].assert_not_called()
        self.assertEqual(self.context.user_data['delete_last_pending'], (42, 1, 42, 100))

    async def test_ack_failure_still_finishes_once(self):
        self.insert()
        await self.prompt()
        update, query = self.callback()
        query.answer.side_effect = TelegramError('query expired')
        await self.ns['delete_last_callback'](update, self.context)
        self.assertEqual(self.rows(), [])
        query.edit_message_text.assert_awaited_once_with(
            get_text('UA', 'delete_success'), reply_markup=None)
        await self.act()
        self.ns['delete_reading'].assert_called_once()

    async def test_duplicate_during_answer_cannot_delete_another_reading(self):
        self.insert()
        await self.prompt()
        self.insert(2)
        update, query = self.callback()
        async def duplicate(*args):
            await self.act()
        query.answer.side_effect = duplicate
        await self.ns['delete_last_callback'](update, self.context)
        self.ns['delete_reading'].assert_called_once_with(42, 1)
        self.assertEqual([r[0] for r in self.rows()], [2])

    async def test_edit_failure_removes_keyboard_sends_result_and_never_retries_delete(self):
        for lang in ('UA', 'EN'):
            for removal_fails in (False, True):
                with self.subTest(lang=lang, removal_fails=removal_fails):
                    db.set_user_language(42, lang)
                    self.insert()
                    await self.prompt()
                    update, query = self.callback()
                    query.edit_message_text.side_effect = TelegramError('cannot edit')
                    if removal_fails:
                        query.edit_message_reply_markup.side_effect = TelegramError('cannot remove')
                    await self.ns['delete_last_callback'](update, self.context)
                    self.assertEqual(self.rows(), [])
                    query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
                    self.context.bot.send_message.assert_awaited_with(
                        chat_id=42, text=get_text(lang, 'delete_success'))
                    await self.act()
        self.assertEqual(self.ns['delete_reading'].call_count, 4)

    async def test_all_telegram_failures_still_do_not_repeat_delete(self):
        self.insert()
        await self.prompt()
        update, query = self.callback()
        query.answer.side_effect = TelegramError('cannot answer')
        query.edit_message_text.side_effect = TelegramError('cannot edit')
        query.edit_message_reply_markup.side_effect = TelegramError('cannot remove')
        self.context.bot.send_message.side_effect = TelegramError('cannot send')
        await self.ns['delete_last_callback'](update, self.context)
        await self.act()
        self.ns['delete_reading'].assert_called_once()
        self.assertEqual(self.rows(), [])

    async def test_real_telegram_callback_and_inaccessible_message(self):
        for message_date in (1, 0):
            with self.subTest(inaccessible=message_date == 0):
                self.insert()
                await self.prompt()
                bot = SimpleNamespace(answer_callback_query=AsyncMock(),
                                      edit_message_text=AsyncMock())
                update = Update.de_json({
                    'update_id': 1,
                    'callback_query': {
                        'id': 'synthetic-query', 'chat_instance': 'synthetic-chat',
                        'from': {'id': 42, 'is_bot': False, 'first_name': 'Synthetic'},
                        'data': 'delete_last:confirm:1',
                        'message': {'message_id': 100, 'date': message_date,
                                    'chat': {'id': 42, 'type': 'private'}, 'text': 'Synthetic'},
                    },
                }, bot)
                if not message_date:
                    query = CallbackQuery(
                        'synthetic-query', update.effective_user, 'synthetic-chat',
                        message=InaccessibleMessage(chat=update.effective_chat, message_id=100),
                        data='delete_last:confirm:1')
                    query.set_bot(bot)
                    update = Update(update_id=1, callback_query=query)
                await self.ns['delete_last_callback'](update, self.context)
                bot.answer_callback_query.assert_awaited_once()
                self.assertEqual(self.rows(), [])
                if message_date:
                    bot.edit_message_text.assert_awaited_once()
                else:
                    bot.edit_message_text.assert_not_awaited()
                    self.context.bot.send_message.assert_awaited_with(
                        chat_id=42, text=get_text('UA', 'delete_success'))

    async def test_signed_sqlite_boundary_targets(self):
        for number in (-(2 ** 63), 0, 2 ** 63 - 1):
            self.insert(number)
            await self.prompt()
            await self.act(f'delete_last:confirm:{number}')
            self.assertEqual(self.rows(), [])

    async def test_last_avg_report_reflect_target_then_final_deletion(self):
        self.insert(systolic=120)
        self.insert(2, timestamp='2026-09-06 09:00:00', systolic=140)
        await self.prompt()
        await self.act('delete_last:confirm:2')
        for handler in ('show_last_readings', 'show_avg', 'show_report'):
            self.message.reply_text.reset_mock()
            await self.ns[handler](self.update, self.context)
            output = '\n'.join(c.args[0] for c in self.message.reply_text.await_args_list)
            self.assertIn('120', output)
            self.assertNotIn('140', output)
        await self.prompt(message_id=101)
        await self.act(message_id=101)
        for handler, key in (('show_last_readings', 'last_empty'),
                             ('show_avg', 'avg_empty'), ('show_report', 'report_empty')):
            self.message.reply_text.reset_mock()
            await self.ns[handler](self.update, self.context)
            output = '\n'.join(c.args[0] for c in self.message.reply_text.await_args_list)
            self.assertIn(get_text('UA', key), output)

    def test_database_deletion_owner_exact_id_boolean_and_deterministic_order(self):
        self.insert(1)
        self.insert(2)
        self.insert(3, user_id=99)
        before = self.rows(99)
        self.assertEqual([r[0] for r in db.get_last(42, n=1)], [2])
        self.assertIs(db.delete_reading(42, 3), False)
        self.assertIs(db.delete_reading(99, 2), False)
        self.assertIs(db.delete_reading(42, 2), True)
        self.assertIs(db.delete_reading(42, 2), False)
        self.assertEqual([r[0] for r in self.rows()], [1])
        self.assertEqual(self.rows(99), before)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(db._version(conn), 3)
        db.check_database(self.path)
        self.assertEqual(db.SCHEMA_VERSION, 3)

    async def test_database_ownership_defense_even_if_pending_target_foreign(self):
        self.insert(user_id=99)
        self.context.user_data['delete_last_pending'] = (42, 1, 42, 100)
        query = await self.act()
        self.assertEqual(len(self.rows(99)), 1)
        query.edit_message_text.assert_awaited_once_with(
            get_text('UA', 'delete_missing'), reply_markup=None)

    def test_help_and_actual_registration(self):
        for lang in ('UA', 'EN'):
            self.assertIn('/delete_last - ' + get_text(lang, 'command_delete_last'),
                          get_text(lang, 'help_text'))
        tree = ast.parse(self.source.read_text())
        registrations = [n for n in ast.walk(tree)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertTrue(any(n.func.id == 'CommandHandler'
                            and ast.literal_eval(n.args[0]) == 'delete_last'
                            and n.args[1].id == 'delete_last'
                            for n in registrations if n.func.id == 'CommandHandler'))
        main = next(n for n in tree.body if isinstance(n, ast.If)
                    and ast.unparse(n.test) == "__name__ == '__main__'")
        callbacks = [n.value.args[0] for n in main.body
                     if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                     and isinstance(n.value.func, ast.Attribute)
                     and n.value.func.attr == 'add_handler'
                     and isinstance(n.value.args[0], ast.Call)
                     and n.value.args[0].func.id == 'CallbackQueryHandler'
                     and n.value.args[0].args[0].id == 'delete_last_callback']
        self.assertEqual(len(callbacks), 1)
        # Evaluate only the real handler constructor, never application startup.
        handler = eval(compile(ast.Expression(callbacks[0]), str(self.source), 'eval'),
                       dict(CallbackQueryHandler=CallbackQueryHandler,
                            delete_last_callback=self.ns['delete_last_callback']))
        self.assertEqual(handler.pattern.pattern, r'\Adelete_last(?::|\Z)')
        def callback_update(payload):
            query = CallbackQuery('synthetic-query', self.user, 'synthetic-chat', data=payload)
            return Update(1, callback_query=query)

        for action in ('confirm', 'keep'):
            for target in (1, -(2 ** 63), 2 ** 63 - 1):
                self.assertTrue(handler.check_update(callback_update(f'delete_last:{action}:{target}')))
        for payload in ('support:agree', 'support:25', 'timezone:other', 'other:confirm:1',
                        'xdelete_last:confirm:1', 'delete_last_other:keep:1'):
            with self.subTest(payload=payload):
                self.assertFalse(handler.check_update(callback_update(payload)))
        self.assertFalse(handler.check_update(Update(1, callback_query=CallbackQuery(
            'synthetic-query', self.user, 'synthetic-chat', game_short_name='synthetic-game'))))
        # PTB routes callbacks without data regardless of regex. The malformed
        # payload test above verifies that our handler rejects those safely.
        self.assertIsNone(handler.pattern.match(''))


if __name__ == '__main__':
    unittest.main()
