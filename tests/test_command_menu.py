import ast
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import BotCommand, BotCommandScopeChat
from telegram.error import TelegramError

import db
from messages import get_text


COMMANDS = ['start', 'help', 'last', 'avg', 'report', 'support', 'paysupport', 'terms', 'timezone']
DESCRIPTIONS = {
    'UA': ['Почати', 'Допомога', 'Останні 5 вимірів', 'Середнє за 7 днів',
           'Звіт за 30 днів', 'Підтримати бота', 'Допомога з оплатою', 'Умови підтримки', 'Налаштувати місцевий час'],
    'EN': ['Start', 'Help', 'Last 5 readings', '7-day average',
           '30-day report', 'Support the bot', 'Payment support', 'Support terms', 'Set local time'],
}


class CommandMenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Extract functions only: importing bot would load environment config.
        source = Path(__file__).resolve().parents[1] / 'bot.py'
        tree = ast.parse(source.read_text())
        names = {'get_commands', 'set_chat_commands', 'start', 'set_english',
                 'set_ukrainian', 'help', 'post_init'}
        nodes = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in names]
        self.ns = dict(BotCommand=BotCommand, BotCommandScopeChat=BotCommandScopeChat,
                       TelegramError=TelegramError, logger=logging.getLogger('command-menu-test'),
                       get_text=get_text, ensure_user=db.ensure_user,
                       get_user_language=db.get_user_language,
                       set_user_language=db.set_user_language,
                       get_user_timezone=db.get_user_timezone, show_timezone=AsyncMock())
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.ns)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'commands.sqlite'
        patcher = patch.object(db, 'DB_PATH', path)
        patcher.start()
        self.addCleanup(patcher.stop)
        db.init_db(path, initialize=True)
        self.update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42, language_code='fr'),
            effective_chat=SimpleNamespace(id=123),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        self.context = SimpleNamespace(bot=SimpleNamespace(set_my_commands=AsyncMock()))

    def assert_menu(self, lang):
        call = self.context.bot.set_my_commands.await_args
        self.assertEqual([command.command for command in call.args[0]], COMMANDS)
        self.assertEqual([command.description for command in call.args[0]], DESCRIPTIONS[lang])
        # No client language filter: the internal setting applies to this chat.
        self.assertEqual(call.kwargs, {'scope': BotCommandScopeChat(chat_id=123)})

    async def test_ua_menu(self):
        await self.ns['set_chat_commands'](self.update, self.context, 'UA')
        self.assert_menu('UA')

    async def test_en_menu(self):
        await self.ns['set_chat_commands'](self.update, self.context, 'EN')
        self.assert_menu('EN')

    def test_command_names_identical(self):
        for lang in DESCRIPTIONS:
            self.assertEqual([command.command for command in self.ns['get_commands'](lang)], COMMANDS)

    async def test_ua_updates_language_and_menu(self):
        db.set_user_language(42, 'EN')
        await self.ns['set_ukrainian'](self.update, self.context)
        self.assertEqual(db.get_user_language(42), 'UA')
        self.assert_menu('UA')
        self.update.message.reply_text.assert_awaited_once_with('Українська мова встановлена')

    async def test_en_updates_language_and_menu(self):
        db.set_user_language(42, 'UA')
        await self.ns['set_english'](self.update, self.context)
        self.assertEqual(db.get_user_language(42), 'EN')
        self.assert_menu('EN')
        self.update.message.reply_text.assert_awaited_once_with('English is set')

    async def test_start_uses_stored_language(self):
        for lang in DESCRIPTIONS:
            with self.subTest(lang=lang):
                db.set_user_language(42, lang)
                await self.ns['start'](self.update, self.context)
                self.assertEqual(db.get_user_language(42), lang)
                self.assert_menu(lang)
                self.update.message.reply_text.assert_awaited_with(get_text(lang, 'welcome_detailed'))

    async def test_start_new_user_default_language(self):
        await self.ns['start'](self.update, self.context)
        self.assertEqual(db.get_user_language(42), 'UA')
        self.assert_menu('UA')

    async def test_help_preserves_text(self):
        for lang in DESCRIPTIONS:
            db.set_user_language(42, lang)
            await self.ns['help'](self.update, self.context)
            self.update.message.reply_text.assert_awaited_with(get_text(lang, 'help_text'))
        self.context.bot.set_my_commands.assert_not_awaited()

    async def run_with_menu_failure(self, handler):
        self.context.bot.set_my_commands.side_effect = TelegramError(
            'private-user=42 private-chat=123 private-exception-details')
        with self.assertLogs('command-menu-test', level='WARNING') as captured:
            await self.ns[handler](self.update, self.context)
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(record.getMessage(), 'Could not update Telegram command menu')
        self.assertFalse(record.args)
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        for sensitive in ('42', '123', 'private-user', 'private-chat', 'private-exception-details'):
            self.assertNotIn(sensitive, ''.join(captured.output))

    async def test_ua_menu_failure_preserves_language_and_confirmation(self):
        db.set_user_language(42, 'EN')
        await self.run_with_menu_failure('set_ukrainian')
        self.assertEqual(db.get_user_language(42), 'UA')
        self.assert_menu('UA')
        self.update.message.reply_text.assert_awaited_once_with('Українська мова встановлена')

    async def test_en_menu_failure_preserves_language_and_confirmation(self):
        db.set_user_language(42, 'UA')
        await self.run_with_menu_failure('set_english')
        self.assertEqual(db.get_user_language(42), 'EN')
        self.assert_menu('EN')
        self.update.message.reply_text.assert_awaited_once_with('English is set')

    async def test_start_menu_failure_preserves_language_and_welcome(self):
        for lang in DESCRIPTIONS:
            with self.subTest(lang=lang):
                db.set_user_language(42, lang)
                self.update.message.reply_text.reset_mock()
                await self.run_with_menu_failure('start')
                self.assertEqual(db.get_user_language(42), lang)
                self.assert_menu(lang)
                self.update.message.reply_text.assert_awaited_once_with(
                    get_text(lang, 'welcome_detailed'))

    async def test_new_user_start_menu_failure_still_sends_welcome(self):
        await self.run_with_menu_failure('start')
        self.assertEqual(db.get_user_language(42), 'UA')
        self.assert_menu('UA')
        self.update.message.reply_text.assert_awaited_once_with(get_text('UA', 'welcome_detailed'))

    async def test_global_fallback_uses_english_menu(self):
        await self.ns['post_init'](self.context)
        self.context.bot.set_my_commands.assert_awaited_once_with(self.ns['get_commands']('EN'))


if __name__ == '__main__':
    unittest.main()
