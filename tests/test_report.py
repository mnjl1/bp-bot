import ast
import html
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import db
from constants import REPORT_MESSAGE_LIMIT
from messages import get_text
from utils import format_report, get_report_date_range


START = '2026-08-08 00:00:00'
END = '2026-09-07 00:00:00'


def reading(number=1, pulse=79, note=None, timestamp='2026-09-06 08:00:00'):
    return (number, 42, timestamp, 128, 83, pulse, note)


class ReportQueryTests(unittest.TestCase):
    def test_range_is_read_only_ordered_and_user_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite'
            with sqlite3.connect(path) as conn:
                conn.execute(db.create_readings_table)
                conn.executemany(
                    'INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?, ?)', [
                        reading(4, timestamp=END),
                        reading(3, timestamp='2026-09-06 23:59:59'),
                        reading(2, timestamp=START),
                        reading(1, timestamp=START),
                        reading(5, timestamp='2026-08-07 23:59:59'),
                        (6, 99, START, 120, 80, None, None),
                    ])
                before = list(conn.iterdump())
            original = db._connect
            with patch.object(db, 'DB_PATH', path), patch.object(
                db, '_connect', wraps=original
            ) as connect:
                rows = db.get_readings_by_date_range(42, START, END)
                self.assertEqual([row[0] for row in rows], [1, 2, 3])
                connect.assert_called_once_with(path, 'ro')
                self.assertEqual(db.get_readings_by_date_range(100, START, END), [])
                with self.assertRaises(ValueError):
                    db.get_readings_by_date_range(None, START, END)
            with sqlite3.connect(path) as conn:
                self.assertEqual(before, list(conn.iterdump()))



class ReportFormattingTests(unittest.TestCase):
    def test_calendar_boundaries(self):
        self.assertEqual(get_report_date_range(date(2026, 9, 6)), (START, END))
        self.assertEqual(get_report_date_range(date(2024, 3, 1)),
                         ('2024-02-01 00:00:00', '2024-03-02 00:00:00'))
        self.assertEqual(get_report_date_range(date(2026, 1, 1)),
                         ('2025-12-03 00:00:00', '2026-01-02 00:00:00'))

    def test_localization_missing_values_and_averages(self):
        records = [reading(), reading(2, pulse=None, note='  '),
                   (3, 42, '2026-09-06 18:00:00', 135, 95, 75, 'poor sleep')]
        for lang in ('UA', 'EN'):
            with self.subTest(lang=lang):
                result = html.unescape(''.join(format_report(records, START, END, lang)))
                self.assertIn('08.08.2026 – 06.09.2026', result)
                self.assertIn(get_text(lang, 'morning'), result)
                self.assertIn(get_text(lang, 'evening'), result)
                self.assertIn('—', result)
                self.assertIn(get_text(lang, 'report_avg_sys') + ': 130', result)
                self.assertIn(get_text(lang, 'report_avg_dia') + ': 87', result)
                self.assertIn(get_text(lang, 'report_pulse') + ': 77', result)
                self.assertIn(get_text(lang, 'report_count') + ': 3', result)
                self.assertNotIn('UTC', result)

    def test_no_pulse_average_and_empty(self):
        for lang in ('UA', 'EN'):
            result = ''.join(format_report([reading(pulse=None)], START, END, lang))
            self.assertNotIn(get_text(lang, 'report_pulse') + ':', result)
            self.assertIn(get_text(lang, 'report_count') + ': 1', result)
            empty = ''.join(format_report([], START, END, lang))
            self.assertIn(get_text(lang, 'report_empty'), empty)
            self.assertNotIn(get_text(lang, 'report_averages'), empty)

    def test_existing_period_boundaries(self):
        for lang in ('UA', 'EN'):
            for time, key in [('11:59:59', 'morning'), ('12:00:00', 'midday'),
                              ('17:59:59', 'midday'), ('18:00:00', 'evening')]:
                result = ''.join(format_report(
                    [reading(timestamp='2026-09-06 ' + time)], START, END, lang))
                self.assertIn('06.09.26 ' + get_text(lang, key), result)

    def test_long_legacy_notes_wrap_without_losing_content(self):
        notes = ['<b>long & note</b> 😀' * 1000,
                 'start' + ' ' * 8000 + 'end']
        for lang in ('UA', 'EN'):
            for note in notes:
                parts = format_report([reading(note=note)], START, END, lang)
                self.assertGreater(len(parts), 1)
                recovered = []
                reading_lines = 0
                for part in parts:
                    self.assertTrue(part.strip())
                    self.assertLessEqual(len(part.encode('utf-16-le')) // 2, REPORT_MESSAGE_LIMIT)
                    self.assertNotIn('<b>', part)
                    self.assertNotIn('Full notes', part)
                    self.assertNotIn('Повні примітки', part)
                    if '<pre>' not in part:
                        continue
                    table = html.unescape(part.split('<pre>', 1)[1].split('</pre>', 1)[0])
                    lines = table.split('\n')
                    offset = lines[0].index(get_text(lang, 'report_note'))
                    self.assertIn(get_text(lang, 'report_date'), lines[0])
                    for line in lines[1:]:
                        if line[:offset].strip():
                            reading_lines += 1
                            self.assertIn('06.09.26', line)
                        else:
                            self.assertEqual(line[:offset], ' ' * offset)
                        recovered.append(line[offset:])
                self.assertEqual(reading_lines, 1)
                self.assertEqual(''.join(recovered), note)
                self.assertIn(get_text(lang, 'report_count') + ': 1', ''.join(parts))

    def test_many_long_notes_and_summary(self):
        notes = [f'item{i:04d}' + 'x' * 112 for i in range(100)]
        for lang in ('UA', 'EN'):
            parts = format_report([reading(i, note=note) for i, note in enumerate(notes)],
                                  START, END, lang)
            recovered = []
            for part in parts:
                self.assertLessEqual(len(part.encode('utf-16-le')) // 2, REPORT_MESSAGE_LIMIT)
                if '<pre>' in part:
                    lines = html.unescape(part.split('<pre>', 1)[1].split('</pre>', 1)[0]).split('\n')
                    offset = lines[0].index(get_text(lang, 'report_note'))
                    recovered.extend(line[offset:] for line in lines[1:])
            self.assertEqual(''.join(recovered), ''.join(notes))
            self.assertEqual(''.join(parts).count(get_text(lang, 'report_averages')), 1)
            self.assertIn(get_text(lang, 'report_count') + ': 100', ''.join(parts))

    def test_invalid_legacy_values_warn_and_do_not_affect_average(self):
        rows = [reading(), reading(2, timestamp='bad-date'),
                (3, 42, START, None, 80, None, None),
                reading(4, pulse='bad'), reading(5, note=b'bad')]
        result = ''.join(format_report(rows, START, END, 'EN'))
        self.assertIn(get_text('EN', 'report_invalid'), result)
        self.assertIn('Number of readings: 1', result)
        self.assertIn('Systolic: 128', result)


class ReportHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Extract handlers only: importing bot would load .env.
        source = Path(__file__).resolve().parents[1] / 'bot.py'
        tree = ast.parse(source.read_text())
        handler = next(node for node in tree.body
                       if isinstance(node, ast.AsyncFunctionDef) and node.name == 'show_report')
        self.namespace = {
            'get_user_language': Mock(return_value='EN'),
            'get_text': get_text,
            'get_report_date_range': Mock(return_value=(START, END)),
            'get_readings_by_date_range': Mock(return_value=[reading()]),
            'format_report': Mock(return_value=['first', 'second']),
        }
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'),
             self.namespace)
        self.update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type='private'),
            effective_message=SimpleNamespace(reply_text=AsyncMock()))

    async def test_private_report_immediate_and_sequential(self):
        await self.namespace['show_report'](self.update, None)
        self.namespace['get_readings_by_date_range'].assert_called_once_with(42, START, END)
        self.namespace['format_report'].assert_called_once_with([reading()], START, END, 'EN')
        calls = self.update.effective_message.reply_text.await_args_list
        self.assertEqual([call.args[0] for call in calls], ['first', 'second'])
        self.assertTrue(all(call.kwargs == {'parse_mode': 'HTML'} for call in calls))

    async def test_non_private_never_queries_readings(self):
        for lang in ('UA', 'EN'):
            for chat_type in ('group', 'supergroup', 'channel'):
                self.namespace['get_user_language'].return_value = lang
                self.update.effective_chat.type = chat_type
                await self.namespace['show_report'](self.update, None)
                self.update.effective_message.reply_text.assert_awaited_with(
                    get_text(lang, 'report_private'))
        self.namespace['get_readings_by_date_range'].assert_not_called()
        self.namespace['get_report_date_range'].assert_not_called()
        self.namespace['format_report'].assert_not_called()

    async def test_anonymous_group_uses_ua_without_user_lookup(self):
        self.update.effective_user = None
        self.update.effective_chat.type = 'supergroup'
        await self.namespace['show_report'](self.update, None)
        self.namespace['get_user_language'].assert_not_called()
        self.namespace['get_readings_by_date_range'].assert_not_called()
        self.update.effective_message.reply_text.assert_awaited_with(get_text('UA', 'report_private'))

    async def test_send_failure_stops_remaining_messages(self):
        self.update.effective_message.reply_text.side_effect = RuntimeError('send failed')
        with self.assertRaises(RuntimeError):
            await self.namespace['show_report'](self.update, None)
        self.assertEqual(self.update.effective_message.reply_text.await_count, 1)


if __name__ == '__main__':
    unittest.main()
