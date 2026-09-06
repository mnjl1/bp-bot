import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from messages import get_text
from constants import MAX_NOTE_LENGTH, READING_PATTERN
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
            'MAX_NOTE_LENGTH': MAX_NOTE_LENGTH,
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

    async def test_malformed_readings_are_rejected(self):
        for lang in ('UA', 'EN'):
            self.namespace['get_user_language'].return_value = lang
            for text in ('120/80oops', '120/80/', '120/80/72/', '120/80/1234'):
                with self.subTest(lang=lang, text=text):
                    self.assertIsNotNone(re.search(READING_PATTERN, text))
                    with self.assertRaises(ValueError):
                        process_user_input(text)
                    self.update.message.text = text
                    await self.namespace['handle_reading'](self.update, None)
                    self.namespace['add_reading'].assert_not_called()
                    self.update.message.reply_text.assert_awaited_with(get_text(lang, 'wrong_input'))

    def test_parser_rejects_missing_numeric_bp(self):
        for text in ('', 'abc/80', '120/abc', '120'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                process_user_input(text)

    async def test_supported_formats_and_note_slashes(self):
        for lang in ('UA', 'EN'):
            self.namespace['get_user_language'].return_value = lang
            for token, pulse in [('138/88', None), ('138/88/76', 76)]:
                for separator in (' ', '/'):
                    for note in (None, 'after a walk', 'після прогулянки', 'before/after/walk'):
                        self.namespace['add_reading'].reset_mock()
                        self.update.message.text = token + (separator + note if note else '')
                        await self.namespace['handle_reading'](self.update, None)
                        self.namespace['add_reading'].assert_called_once_with(42, 138, 88, pulse, note)

    async def test_slash_note_length_limit(self):
        for lang in ('UA', 'EN'):
            self.namespace['get_user_language'].return_value = lang
            for token, pulse in [('138/88', None), ('138/88/76', 76)]:
                for length in (120, 121):
                    self.namespace['add_reading'].reset_mock()
                    note = 'a/b' + 'x' * (length - 3)
                    self.update.message.text = token + '/' + note
                    await self.namespace['handle_reading'](self.update, None)
                    if length == 120:
                        self.namespace['add_reading'].assert_called_once_with(42, 138, 88, pulse, note)
                    else:
                        self.namespace['add_reading'].assert_not_called()
                        self.update.message.reply_text.assert_awaited_with(
                            get_text(lang, 'note_too_long').format(limit=120))

    def test_numeric_third_field_is_pulse_and_rest_is_note(self):
        for text, pulse, note in [('120/80/72/123', 72, '123'),
                                  ('120/80/extra/value', None, 'extra/value'),
                                  ('120/80/72oops', None, '72oops')]:
            records, actual_note = process_user_input(text)
            self.assertEqual(records['pulse'], pulse)
            self.assertEqual(actual_note, note)

    async def test_note_limit_without_pulse(self):
        for lang in ('UA', 'EN'):
            self.namespace['get_user_language'].return_value = lang
            for length in (120, 121):
                self.namespace['add_reading'].reset_mock()
                note = 'x' * length
                self.update.message.text = '120/80 ' + note
                await self.namespace['handle_reading'](self.update, None)
                if length == 120:
                    self.namespace['add_reading'].assert_called_once_with(42, 120, 80, None, note)
                else:
                    self.namespace['add_reading'].assert_not_called()
                    self.update.message.reply_text.assert_awaited_with(
                        get_text(lang, 'note_too_long').format(limit=120))

    def test_help_note_examples(self):
        self.assertIn('120/80/72 після прогулянки', get_text('UA', 'help_text'))
        self.assertIn('120/80/72 after a walk', get_text('EN', 'help_text'))

    async def test_note_length_limit(self):
        for lang in ('UA', 'EN'):
            for length in (120, 121):
                with self.subTest(lang=lang, length=length):
                    self.namespace['get_user_language'].return_value = lang
                    self.namespace['add_reading'].reset_mock()
                    note = 'я' * length
                    self.update.message.text = '128/83/79 ' + note
                    await self.namespace['handle_reading'](self.update, None)
                    if length == 120:
                        self.namespace['add_reading'].assert_called_once_with(42, 128, 83, 79, note)
                    else:
                        self.namespace['add_reading'].assert_not_called()
                        self.update.message.reply_text.assert_awaited_with(
                            get_text(lang, 'note_too_long').format(limit=120))
                        self.assertIn('120', self.update.message.reply_text.await_args.args[0])

    async def test_note_length_checked_before_normalization(self):
        self.namespace['get_user_language'].return_value = 'EN'
        self.update.message.text = '128/83 poor' + ' ' * 120 + 'sleep'
        await self.namespace['handle_reading'](self.update, None)
        self.namespace['add_reading'].assert_not_called()

    def test_help_note_limit(self):
        for lang in ('UA', 'EN'):
            self.assertIn('120 символів' if lang == 'UA' else '120 characters',
                          get_text(lang, 'help_text'))

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
