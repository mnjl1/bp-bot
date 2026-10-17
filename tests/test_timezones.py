import ast
import html
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
from constants import TIMEZONE_REGIONS, TIMEZONE_CALLBACK_PATTERN
from messages import get_text
from utils import (local_datetime, effective_timezone, get_period_of_day, convert_date,
                   get_report_date_range, get_report_candidate_range, format_report)
from test_db_migrations import LEGACY_READINGS, LEGACY_SETTINGS


NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def row(timestamp, zone=None, number=1):
    return (number, 42, timestamp, 120, 80, None, None, zone)


class TimezoneDatabaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'timezone.sqlite'
        patcher = patch.object(db, 'DB_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def v2(self):
        # Independent v2 fixture. Historical constants remain v0/v1 definitions.
        with sqlite3.connect(self.path) as conn:
            conn.executescript(LEGACY_READINGS + ';' + LEGACY_SETTINGS + ''';
                CREATE TABLE users (user_id INTEGER PRIMARY KEY,
                    language TEXT NOT NULL DEFAULT 'UA',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY CHECK(version > 0),
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX idx_readings_user_datetime ON readings(user_id, datetime);
                INSERT INTO schema_migrations(version) VALUES (1), (2);
                INSERT INTO users VALUES (42, 'EN', '2020-01-01 00:00:00');
                INSERT INTO user_settings VALUES (42, 'EN');
                INSERT INTO readings VALUES (1, 42, '2020-01-01 23:30:00', 120, 80, NULL, 'legacy');
            ''')
            conn.execute(db.CREATE_PAYMENTS)
            conn.execute("INSERT INTO payments(user_id, currency, amount, invoice_payload, "
                         "telegram_payment_charge_id) VALUES (42, 'XTR', 25, 'support:25', 'synthetic')")

    def snapshot(self):
        with sqlite3.connect(self.path) as conn:
            return list(conn.iterdump())

    def fresh(self):
        db.init_db(self.path, initialize=True)

    def test_v2_to_v3_preserves_all_existing_values_and_no_backfill(self):
        self.v2()
        with sqlite3.connect(self.path) as conn:
            before = {table: conn.execute(f'SELECT * FROM {table}').fetchall()
                      for table in ('users', 'readings', 'user_settings', 'payments', 'schema_migrations')}
        db.init_db(self.path)
        db.check_database(self.path)
        with sqlite3.connect(self.path) as conn:
            for table in ('users', 'readings'):
                self.assertEqual(conn.execute(f'SELECT * FROM {table}').fetchall(),
                                 [record + (None,) for record in before[table]])
                self.assertEqual(conn.execute(f'PRAGMA table_info({table})').fetchall()[-1][1:],
                                 ('timezone', 'TEXT', 0, None, 0))
            for table in ('user_settings', 'payments'):
                self.assertEqual(conn.execute(f'SELECT * FROM {table}').fetchall(), before[table])
            self.assertEqual(conn.execute('SELECT * FROM schema_migrations WHERE version < 3').fetchall(),
                             before['schema_migrations'])
            self.assertEqual(db._version(conn), 3)
        before = self.snapshot()
        db.init_db(self.path)
        self.assertEqual(self.snapshot(), before)

    def test_v2_startup_rejected_without_migration(self):
        self.v2()
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'migration required'):
            db.check_database(self.path)
        self.assertEqual(self.snapshot(), before)

    def test_v3_failure_rolls_back_exact_schema_rows_and_history(self):
        self.v2()
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TRIGGER fail_v3 BEFORE INSERT ON schema_migrations "
                         "WHEN NEW.version = 3 BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            db.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with sqlite3.connect(self.path) as conn:
            conn.execute('DROP TRIGGER fail_v3')
        db.init_db(self.path)
        db.check_database(self.path)

    def test_second_alter_failure_rolls_back_first_alter(self):
        self.v2()
        before = self.snapshot()

        class FailSecondAlter(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.startswith('ALTER TABLE readings'):
                    raise sqlite3.OperationalError('synthetic alter failure')
                return super().execute(sql, parameters)

        conn = sqlite3.connect(self.path, factory=FailSecondAlter)
        with patch.object(db, '_connect', return_value=conn):
            with self.assertRaises(sqlite3.OperationalError):
                db.init_db(self.path)
        self.assertEqual(self.snapshot(), before)

    def test_v3_requires_exact_columns_types_nullability_and_defaults(self):
        self.v2()
        for table in ('users', 'readings'):
            for declaration in ('zone TEXT', 'timezone INTEGER', "timezone TEXT NOT NULL DEFAULT 'Europe/Kyiv'",
                                "timezone TEXT DEFAULT 'Europe/Kyiv'"):
                with self.subTest(table=table, declaration=declaration):
                    with sqlite3.connect(self.path) as conn:
                        conn.execute('BEGIN')
                        for target in ('users', 'readings'):
                            column = declaration if target == table else 'timezone TEXT NULL'
                            conn.execute(f'ALTER TABLE {target} ADD COLUMN {column}')
                        with self.assertRaises(RuntimeError):
                            db._check_schema(conn, 3)
                        conn.rollback()
        with sqlite3.connect(self.path) as conn:
            with self.assertRaises(RuntimeError):
                db._check_schema(conn, 3)
            conn.execute('ALTER TABLE users ADD COLUMN timezone TEXT NULL')
            with self.assertRaises(RuntimeError):
                db._check_schema(conn, 2)

    def test_v3_rejects_extra_columns_bad_index_and_payment_constraints(self):
        self.fresh()
        with sqlite3.connect(self.path) as conn:
            for sql in ('ALTER TABLE readings ADD COLUMN unexpected TEXT',
                        'DROP INDEX idx_readings_user_datetime'):
                conn.execute('BEGIN')
                conn.execute(sql)
                with self.assertRaises(RuntimeError):
                    db._check_schema(conn, 3)
                conn.rollback()
            conn.execute('BEGIN')
            conn.execute('DROP TABLE payments')
            conn.execute(db.CREATE_PAYMENTS.replace('CHECK(amount > 0)', ''))
            with self.assertRaisesRegex(RuntimeError, 'constraints'):
                db._check_schema(conn, 3)
            conn.rollback()

    def test_avg_default_clock_is_explicitly_utc(self):
        self.fresh()
        db.add_reading(42, 120, 80, measured_at=NOW)
        with patch.object(db, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = NOW
            self.assertEqual(db.get_avg(42), [(120.0, 80.0, None)])
            clock.now.assert_called_once_with(timezone.utc)

    def test_new_reading_explicit_utc_snapshot_and_no_zone(self):
        self.fresh()
        measured = datetime(2026, 7, 1, 0, 30, tzinfo=ZoneInfo('Europe/Kyiv'))
        db.add_reading(42, 120, 80, measured_at=measured)
        self.assertEqual(db.get_last(42)[0][2], '2026-06-30 21:30:00')
        self.assertIsNone(db.get_last(42)[0][7])
        db.set_user_timezone(42, 'Europe/Kyiv')
        db.add_reading(42, 121, 81, measured_at=NOW)
        db.set_user_timezone(42, 'Europe/London')
        records = db.get_last(42)
        self.assertEqual(records[0][7], 'Europe/Kyiv')
        self.assertIsNone(records[1][7])
        self.assertEqual(effective_timezone(records[0], db.get_user_timezone(42)), 'Europe/Kyiv')
        self.assertEqual(effective_timezone(records[1], db.get_user_timezone(42)), 'Europe/London')
        with self.assertRaises(ValueError), patch.object(db, '_connect') as connect:
            db.add_reading(42, 120, 80, measured_at=datetime(2026, 1, 1))
        connect.assert_not_called()

    def test_snapshot_writer_lock_prevents_interleaving_timezone_change(self):
        self.fresh()
        db.set_user_timezone(42, 'Europe/Kyiv')
        original = db._ensure_user

        def ensure_and_try_competing_writer(conn, user_id):
            original(conn, user_id)
            with sqlite3.connect(self.path, timeout=0) as other:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    other.execute("UPDATE users SET timezone = 'Europe/London' WHERE user_id = 42")

        with patch.object(db, '_ensure_user', side_effect=ensure_and_try_competing_writer):
            db.add_reading(42, 120, 80, measured_at=NOW)
        self.assertEqual(db.get_last(42)[0][7], 'Europe/Kyiv')

    def test_invalid_zone_does_not_write(self):
        self.fresh()
        before = self.snapshot()
        for zone in ('other', 'UTC', 'Invalid/Zone', None):
            with self.assertRaises(ValueError):
                db.set_user_timezone(42, zone)
        self.assertEqual(self.snapshot(), before)

    def test_avg_rolling_168_hours_independent_of_host_and_user_zone(self):
        self.fresh()
        for offset, value in ((-168 * 3600 - 1, 200), (-168 * 3600, 200),
                              (-168 * 3600 + 1, 120), (0, 140), (1, 200)):
            db.add_reading(42, value, 80, measured_at=NOW + timedelta(seconds=offset))
        old_tz = os.environ.get('TZ')
        try:
            for host in ('Pacific/Honolulu', 'Asia/Tokyo'):
                os.environ['TZ'] = host
                if hasattr(time, 'tzset'):
                    time.tzset()
                for zone in TIMEZONE_REGIONS.values():
                    db.set_user_timezone(42, zone)
                    self.assertEqual(db.get_avg(42, now=NOW), [(130.0, 80.0, None)])
                    self.assertEqual(db.get_avg(42, now=NOW.astimezone(ZoneInfo(zone))),
                                     [(130.0, 80.0, None)])
        finally:
            if old_tz is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = old_tz
            if hasattr(time, 'tzset'):
                time.tzset()


class TimezoneFormattingTests(unittest.TestCase):
    def test_all_three_zones_dst_and_transition_instants(self):
        for zone, winter, summer in (('Europe/London', 0, 1), ('Europe/Berlin', 1, 2),
                                     ('Europe/Kyiv', 2, 3)):
            with self.subTest(zone=zone):
                self.assertEqual(local_datetime('2026-01-01 12:00:00', zone).hour, 12 + winter)
                self.assertEqual(local_datetime('2026-07-01 12:00:00', zone).hour, 12 + summer)
                self.assertEqual(local_datetime('2026-03-29 00:59:59', zone).utcoffset(), timedelta(hours=winter))
                self.assertEqual(local_datetime('2026-03-29 01:00:00', zone).utcoffset(), timedelta(hours=summer))
                self.assertEqual(local_datetime('2026-10-25 00:59:59', zone).utcoffset(), timedelta(hours=summer))
                self.assertEqual(local_datetime('2026-10-25 01:00:00', zone).utcoffset(), timedelta(hours=winter))

    def test_midnight_and_local_period_boundaries(self):
        self.assertEqual(convert_date('2026-07-01 21:30:00', 'Europe/Kyiv'), '02/07/26')
        for lang in ('UA', 'EN'):
            for stamp, period in (('08:59:59', 'morning'), ('09:00:00', 'midday'),
                                  ('14:59:59', 'midday'), ('15:00:00', 'evening')):
                self.assertEqual(get_period_of_day('2026-07-01 ' + stamp, lang, 'Europe/Kyiv'),
                                 get_text(lang, period))

    def test_snapshot_then_legacy_current_zone_precedence(self):
        current = 'Europe/London'
        for snapshot, expected in (('Europe/Kyiv', '02/07/26'), (None, '01/07/26')):
            record = row('2026-07-01 21:30:00', snapshot)
            self.assertEqual(convert_date(record[2], effective_timezone(record, current)), expected)

    def test_report_today_uses_current_zone_or_explicit_utc_fallback(self):
        now = datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc)
        self.assertEqual(get_report_date_range(user_timezone='Europe/Kyiv', now=now),
                         ('2026-06-03 00:00:00', '2026-07-03 00:00:00'))
        self.assertEqual(get_report_date_range(now=now),
                         ('2026-06-02 00:00:00', '2026-07-02 00:00:00'))
        self.assertEqual(get_report_date_range(now=now.astimezone(ZoneInfo('Europe/Kyiv'))),
                         get_report_date_range(now=now))

    def test_report_filters_by_displayed_date_and_snapshot(self):
        start, end = get_report_date_range(date(2026, 7, 30))
        rows = [row('2026-06-30 20:59:59', 'Europe/Kyiv', 1),
                row('2026-06-30 21:00:00', 'Europe/Kyiv', 2),
                row('2026-06-30 21:00:00', 'Europe/London', 3),
                row('2026-07-30 20:59:59', 'Europe/Kyiv', 4),
                row('2026-07-30 21:00:00', 'Europe/Kyiv', 5),
                row('2026-07-30 21:00:00', None, 6)]
        lower, upper = get_report_candidate_range(start, end)
        self.assertTrue(all(lower <= record[2] < upper for record in rows))
        for lang in ('UA', 'EN'):
            text = html.unescape(''.join(format_report(rows, start, end, lang, 'Europe/London')))
            self.assertIn('01.07.2026 – 30.07.2026', text)
            self.assertIn(get_text(lang, 'report_count') + ': 3', text)
            self.assertNotIn('30.06.26 ', text)
            self.assertNotIn('31.07.26 ', text)

    def test_report_dst_calendar_range_and_candidate_query(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.sqlite'
            db.init_db(path, initialize=True)
            with patch.object(db, 'DB_PATH', path):
                db.set_user_timezone(42, 'Europe/Kyiv')
                for timestamp in ('2026-03-28 21:59:59', '2026-03-28 22:00:00',
                                  '2026-04-27 20:59:59', '2026-04-27 21:00:00'):
                    db.add_reading(42, 120, 80, measured_at=local_datetime(timestamp))
                start, end = get_report_date_range(date(2026, 4, 27))
                rows = db.get_readings_by_date_range(42, *get_report_candidate_range(start, end))
                text = ''.join(format_report(rows, start, end, 'EN', 'Europe/Kyiv'))
                self.assertIn('29.03.2026 – 27.04.2026', text)
                self.assertIn('Number of readings: 2', text)
                self.assertNotIn('28.03.26 ', text)
                self.assertNotIn('28.04.26 ', text)

    def test_unset_zone_neutral_report_has_setup_and_no_false_period(self):
        for lang in ('UA', 'EN'):
            start, end = get_report_date_range(date(2026, 7, 1))
            text = ''.join(format_report([row('2026-07-01 09:00:00')], start, end, lang))
            self.assertIn('/timezone', text)
            self.assertIn(get_text(lang, 'time_neutral'), text)
            for key in ('morning', 'midday', 'evening'):
                self.assertNotIn(get_text(lang, key), text)
            self.assertNotIn('UTC', text)
            self.assertNotIn('Europe/', text)


class TimezoneHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'bot.py'
        tree = ast.parse(source.read_text())
        names = {'show_timezone', 'timezone_callback', 'start', 'show_last_readings'}
        nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
        self.ns = dict(get_text=get_text, get_user_language=Mock(return_value='EN'),
                       get_user_timezone=Mock(return_value=None), set_user_timezone=Mock(),
                       ensure_user=Mock(), set_chat_commands=AsyncMock(),
                       TIMEZONE_REGIONS=TIMEZONE_REGIONS, InlineKeyboardButton=InlineKeyboardButton,
                       InlineKeyboardMarkup=InlineKeyboardMarkup, get_last=Mock(),
                       effective_timezone=effective_timezone, convert_date=convert_date,
                       get_period_of_day=get_period_of_day)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.ns)
        self.update = NS(effective_user=NS(id=42), effective_chat=NS(id=42),
                         message=NS(reply_text=AsyncMock()),
                         callback_query=NS(data='', answer=AsyncMock(), edit_message_text=AsyncMock()))

    async def test_four_short_buttons_and_localized_country_explanations(self):
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            await self.ns['show_timezone'](self.update, None)
            call = self.update.message.reply_text.await_args
            self.assertEqual(call.args, (get_text(lang, 'timezone_setup'),))
            buttons = [r[0] for r in call.kwargs['reply_markup'].inline_keyboard]
            self.assertEqual([b.callback_data for b in buttons],
                             ['timezone:west', 'timezone:central', 'timezone:east', 'timezone:other'])
            self.assertEqual([b.text for b in buttons],
                             [get_text(lang, 'timezone_' + key) for key in ('west', 'central', 'east', 'other')])
            self.assertIn('Португалія' if lang == 'UA' else 'Portugal', call.args[0])
            self.assertIn('Україна' if lang == 'UA' else 'Ukraine', call.args[0])
            for technical in ('UTC', 'IANA', 'Europe/'):
                self.assertNotIn(technical, call.args[0] + ''.join(b.text for b in buttons))
            self.assertIn('/timezone', get_text(lang, 'help_text'))

    async def test_three_callback_mappings_in_both_languages(self):
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            for key, zone in (('west', 'Europe/London'), ('central', 'Europe/Berlin'), ('east', 'Europe/Kyiv')):
                self.update.callback_query.data = 'timezone:' + key
                await self.ns['timezone_callback'](self.update, None)
                self.ns['set_user_timezone'].assert_called_with(42, zone)
                self.update.callback_query.edit_message_text.assert_awaited_with(
                    get_text(lang, 'timezone_saved').format(region=get_text(lang, 'timezone_' + key)))

    async def test_other_region_and_unknown_callback_do_not_write(self):
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            self.update.callback_query.data = 'timezone:other'
            await self.ns['timezone_callback'](self.update, None)
            self.update.callback_query.edit_message_text.assert_awaited_with(get_text(lang, 'timezone_other_message'))
        for data in ('timezone:Asia/Tokyo', 'east', None):
            self.update.callback_query.data = data
            await self.ns['timezone_callback'](self.update, None)
        self.ns['set_user_timezone'].assert_not_called()

    async def test_start_welcome_then_setup_only_when_unset(self):
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            for zone in (None, 'Europe/Kyiv'):
                self.ns['get_user_timezone'].return_value = zone
                self.update.message.reply_text.reset_mock()
                await self.ns['start'](self.update, None)
                calls = self.update.message.reply_text.await_args_list
                self.assertEqual(calls[0].args, (get_text(lang, 'welcome_detailed'),))
                self.assertEqual(len(calls), 2 if zone is None else 1)
                if zone is None:
                    self.assertEqual(calls[1].args, (get_text(lang, 'timezone_setup'),))

    async def test_last_snapshot_legacy_and_neutral(self):
        for lang in ('UA', 'EN'):
            self.ns['get_user_language'].return_value = lang
            for snapshot, current, expected_date in (('Europe/Kyiv', 'Europe/London', '02/07/26'),
                                                       (None, 'Europe/Kyiv', '02/07/26'),
                                                       (None, None, '01/07/26')):
                self.ns['get_user_timezone'].return_value = current
                self.ns['get_last'].return_value = [row('2026-07-01 21:30:00', snapshot)]
                await self.ns['show_last_readings'](self.update, None)
                text = self.update.message.reply_text.await_args.args[0]
                self.assertIn(expected_date, text)
                if current is None:
                    self.assertIn('/timezone', text)
                    self.assertIn(get_text(lang, 'time_neutral'), text)
                    for key in ('morning', 'midday', 'evening'):
                        self.assertNotIn(get_text(lang, key), text)
                else:
                    self.assertIn(get_text(lang, 'morning'), text)

    def test_callback_registration_is_exact(self):
        import re
        for key in (*TIMEZONE_REGIONS, 'other'):
            self.assertIsNotNone(re.fullmatch(TIMEZONE_CALLBACK_PATTERN, 'timezone:' + key))
        for text in ('timezone:east:extra', 'timezone:east\n', 'support:25'):
            self.assertIsNone(re.fullmatch(TIMEZONE_CALLBACK_PATTERN, text))
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'bot.py').read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertTrue(any(isinstance(c.func, ast.Name) and c.func.id == 'CommandHandler'
                            and isinstance(c.args[0], ast.Constant) and c.args[0].value == 'timezone'
                            for c in calls))
        self.assertTrue(any(isinstance(c.func, ast.Name) and c.func.id == 'CallbackQueryHandler'
                            and isinstance(c.args[0], ast.Name) and c.args[0].id == 'timezone_callback'
                            for c in calls))


if __name__ == '__main__':
    unittest.main()
