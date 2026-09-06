import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from messages import get_text
from utils import convert_date, get_period_of_day, process_user_input, validate_reading


class ReadingDisplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Follow the existing handler-test pattern: never import bot, which loads .env.
        source = Path(__file__).resolve().parents[1] / 'bot.py'
        tree = ast.parse(source.read_text())
        names = {'handle_reading', 'show_last_readings', 'show_avg'}
        handlers = [node for node in tree.body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
        self.namespace = {
            'get_text': get_text,
            'convert_date': convert_date,
            'get_period_of_day': get_period_of_day,
            'process_user_input': process_user_input,
            'validate_reading': validate_reading,
            'get_user_language': Mock(),
            'add_reading': Mock(),
            'get_last': Mock(),
            'get_avg': Mock(),
        }
        exec(compile(ast.Module(body=handlers, type_ignores=[]), str(source), 'exec'),
             self.namespace)
        self.update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(text='', reply_text=AsyncMock()),
        )

    async def check_last(self, pulse):
        for lang, period, label in [('UA', 'Ранок', 'пульс:'),
                                    ('EN', 'Morning', 'pulse:')]:
            for note in (None, 'after breakfast'):
                with self.subTest(lang=lang, pulse=pulse, note=note):
                    self.namespace['get_user_language'].return_value = lang
                    self.namespace['get_last'].return_value = [
                        (1, 42, '2026-09-06 08:00:00', 129, 90, pulse, note),
                    ]
                    await self.namespace['show_last_readings'](self.update, None)
                    expected = '06/09/26 (' + period + ') 129/90'
                    if pulse is not None:
                        expected += ', ' + label + ' 79'
                    expected += ' ' + (note or '') + '\n\n'
                    self.update.message.reply_text.assert_awaited_with(expected)

    async def test_last_with_pulse(self):
        await self.check_last(79)

    async def test_last_without_pulse(self):
        await self.check_last(None)

    async def check_saved(self, pulse):
        for lang, saved, label in [('UA', 'Збережено', 'пульс:'),
                                   ('EN', 'Saved', 'pulse:')]:
            for note in (None, 'after breakfast'):
                with self.subTest(lang=lang, pulse=pulse, note=note):
                    self.namespace['get_user_language'].return_value = lang
                    self.update.message.text = '129/90'
                    if pulse is not None:
                        self.update.message.text += '/79'
                    if note:
                        self.update.message.text += ' ' + note
                    await self.namespace['handle_reading'](self.update, None)
                    expected = saved + '\n' + ' ' * 36 + '129/90'
                    if pulse is not None:
                        expected += ',\n' + ' ' * 36 + label + '79'
                    expected += '\n' + ' ' * 36 + (note or '')
                    self.update.message.reply_text.assert_awaited_with(expected)
                    self.namespace['add_reading'].assert_called_with(
                        42, 129, 90, pulse, note)

    async def test_saved_with_pulse(self):
        await self.check_saved(79)

    async def test_saved_without_pulse(self):
        await self.check_saved(None)

    async def check_avg(self, pulse):
        for lang, heading in [('UA', 'Середні показники за останні 7 днів'),
                              ('EN', 'Average for the last 7 days')]:
            with self.subTest(lang=lang, pulse=pulse):
                self.namespace['get_user_language'].return_value = lang
                self.namespace['get_avg'].return_value = [(128.5, 89.6, pulse)]
                await self.namespace['show_avg'](self.update, None)
                expected = heading + ':\n' + ' ' * 12 + '128/90'
                if pulse is not None:
                    expected += '/80'
                self.update.message.reply_text.assert_awaited_with(expected)

    async def test_avg_with_pulse(self):
        await self.check_avg(79.5)

    async def test_avg_without_pulse(self):
        await self.check_avg(None)


if __name__ == '__main__':
    unittest.main()
