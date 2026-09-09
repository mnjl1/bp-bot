import ast
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


# Independent fixture for the schema used before migration v1.
LEGACY_READINGS = '''
    CREATE TABLE readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        datetime TEXT DEFAULT CURRENT_TIMESTAMP,
        systolic INTEGER,
        diastolic INTEGER,
        pulse INTEGER NULL,
        note TEXT NULL
    )
'''
LEGACY_SETTINGS = '''
    CREATE TABLE user_settings (
        user_id INTEGER PRIMARY KEY,
        language TEXT DEFAULT 'UA'
    )
'''
DEFAULT_DB_PATH = db.DB_PATH


class DatabaseFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.sqlite'
        self.path.touch()
        self.conn = sqlite3.connect(self.path)
        self.addCleanup(self.conn.close)
        patcher = patch.object(db, 'DB_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def legacy(self):
        self.conn.execute(LEGACY_READINGS)
        self.conn.execute(LEGACY_SETTINGS)
        self.conn.commit()

    def fresh(self):
        db.init_db(self.path, initialize=True)

    def snapshot(self):
        return list(self.conn.iterdump())

    def test_default_path_is_anchored_to_module(self):
        # Check the path value only; never open the actual default database.
        expected = Path(db.__file__).resolve().parent / 'bp.db'
        previous = Path.cwd()
        try:
            os.chdir(self.temp.name)
            self.assertEqual(DEFAULT_DB_PATH, expected)
            self.assertTrue(DEFAULT_DB_PATH.is_absolute())
        finally:
            os.chdir(previous)

    def test_explicit_path_survives_working_directory_change(self):
        previous = Path.cwd()
        try:
            os.chdir(self.temp.name)
            self.fresh()
            db.check_database(self.path)
            db.ensure_user(42)
        finally:
            os.chdir(previous)
        self.assertEqual(self.conn.execute('SELECT user_id FROM users').fetchall(), [(42,)])

    def test_none_id_is_rejected_without_writes(self):
        self.fresh()
        before = self.snapshot()
        operations = (
            lambda: db.ensure_user(None),
            lambda: db.add_reading(None, 120, 80),
            lambda: db.set_user_language(None, 'EN'),
        )
        for operation in operations:
            with self.assertRaisesRegex(ValueError, 'user_id must not be None'):
                operation()
            self.assertEqual(before, self.snapshot())

    def test_legacy_missing_or_wrong_timestamp_default_is_rejected(self):
        for default in ('', ' DEFAULT NULL', " DEFAULT 'CURRENT_TIMESTAMP'", ' DEFAULT CURRENT_DATE'):
            with self.subTest(default=default):
                path = Path(self.temp.name) / ('legacy-' + str(len(default)) + '.sqlite')
                with sqlite3.connect(path) as conn:
                    conn.execute(LEGACY_READINGS.replace(' DEFAULT CURRENT_TIMESTAMP', default))
                    conn.execute(LEGACY_SETTINGS)
                    before = list(conn.iterdump())
                    with self.assertRaisesRegex(RuntimeError, 'readings.datetime'):
                        db.init_db(path)
                    self.assertEqual(before, list(conn.iterdump()))

    def test_v1_missing_or_wrong_timestamp_defaults_are_rejected(self):
        for table, ddl in (('readings', LEGACY_READINGS), ('users', db.CREATE_USERS)):
            for index, default in enumerate(('', ' DEFAULT NULL', " DEFAULT 'CURRENT_TIMESTAMP'", ' DEFAULT CURRENT_DATE')):
                with self.subTest(table=table, default=default):
                    path = Path(self.temp.name) / f'{table}-{index}.sqlite'
                    db.init_db(path, initialize=True)
                    with sqlite3.connect(path) as conn:
                        # Alter only synthetic, empty test databases.
                        conn.execute(f'DROP TABLE {table}')
                        conn.execute(ddl.replace(' DEFAULT CURRENT_TIMESTAMP', default))
                        if table == 'readings':
                            conn.execute('CREATE INDEX idx_readings_user_datetime ON readings(user_id, datetime)')
                        conn.commit()
                        before = list(conn.iterdump())
                        for operation in (db.check_database, db.init_db):
                            with self.assertRaisesRegex(RuntimeError, table):
                                operation(path)
                        self.assertEqual(before, list(conn.iterdump()))

    def test_parenthesized_lowercase_timestamp_default_is_accepted(self):
        self.conn.execute(LEGACY_READINGS.replace('CURRENT_TIMESTAMP', '(current_timestamp)'))
        self.conn.execute(LEGACY_SETTINGS)
        self.conn.commit()
        db.init_db(self.path)
        db.check_database(self.path)

    def test_rollback_failure_preserves_original_exception(self):
        self.legacy()
        before = self.snapshot()
        original = RuntimeError('original migration failure')
        rollback_attempted = []

        class RollbackFailureConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql == 'ROLLBACK':
                    rollback_attempted.append(True)
                    raise sqlite3.OperationalError('injected rollback failure')
                return super().execute(sql, parameters)

        connection = sqlite3.connect(self.path, factory=RollbackFailureConnection)
        self.addCleanup(connection.close)

        def fail_after_index(conn, version):
            if version == 1:
                raise original

        with patch.object(db, '_connect', return_value=connection), patch.object(
            db, '_check_schema', side_effect=fail_after_index
        ):
            with self.assertRaises(RuntimeError) as caught:
                db.init_db(self.path)
        self.assertIs(caught.exception, original)
        self.assertEqual(rollback_attempted, [True])
        # Closing the connection rolls back the still-open transaction.
        self.assertEqual(before, self.snapshot())

    def test_fresh_and_repeat(self):
        self.fresh()
        db.check_database()
        self.assertEqual(self.conn.execute('SELECT version FROM schema_migrations').fetchall(), [(1,), (2,)])
        self.assertEqual(self.conn.execute('SELECT * FROM users').fetchall(), [])
        before = self.snapshot()
        db.init_db(self.path)
        self.assertEqual(before, self.snapshot())

    def test_legacy_backfill_preserves_rows_and_languages(self):
        self.legacy()
        self.conn.executemany('INSERT INTO readings (user_id, datetime, systolic) VALUES (?, ?, 120)',
                              [(1, '2020-01-01 00:00:00'), (1, None), (2, 'bad-date'),
                               (None, None), (2**50, '2021-01-01 00:00:00')])
        self.conn.executemany('INSERT INTO user_settings VALUES (?, ?)',
                              [(1, 'EN'), (3, 'UA'), (4, None), (5, 'legacy')])
        self.conn.commit()
        readings = self.conn.execute('SELECT * FROM readings').fetchall()
        settings = self.conn.execute('SELECT * FROM user_settings').fetchall()
        structure = self.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'readings'").fetchone()
        before = self.conn.execute('SELECT CURRENT_TIMESTAMP').fetchone()[0]
        db.init_db(self.path)
        after = self.conn.execute('SELECT CURRENT_TIMESTAMP').fetchone()[0]
        self.assertEqual(self.conn.execute('SELECT user_id, language FROM users ORDER BY user_id').fetchall(),
                         [(1, 'EN'), (2, 'UA'), (3, 'UA'), (4, 'UA'), (5, 'legacy'), (2**50, 'UA')])
        for (created,) in self.conn.execute('SELECT created_at FROM users'):
            self.assertTrue(before <= created <= after)
        self.assertEqual(readings, self.conn.execute('SELECT * FROM readings').fetchall())
        self.assertEqual(settings, self.conn.execute('SELECT * FROM user_settings').fetchall())
        self.assertEqual(structure, self.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'readings'").fetchone())
        self.assertEqual(db.get_last(1), sorted(readings[:2], key=lambda row: row[2] or '', reverse=True))
        plan = self.conn.execute('EXPLAIN QUERY PLAN SELECT * FROM readings WHERE user_id = 1 ORDER BY datetime DESC LIMIT 5').fetchall()
        self.assertIn('idx_readings_user_datetime', str(plan))
        before = self.snapshot()
        db.init_db(self.path)
        self.assertEqual(before, self.snapshot())

    def test_empty_legacy(self):
        self.legacy()
        db.init_db(self.path)
        db.check_database()

    def test_ensure_never_overwrites_language_or_timestamp(self):
        self.fresh()
        db.ensure_user(1)
        self.conn.execute("UPDATE users SET language = 'EN', created_at = '2020-01-01 00:00:00' WHERE user_id = 1")
        self.conn.commit()
        db.ensure_user(1)
        db.add_reading(1, 120, 80)
        self.assertEqual(self.conn.execute('SELECT * FROM users').fetchall(), [(1, 'EN', '2020-01-01 00:00:00')])
        self.assertEqual(db.get_user_language(1), 'EN')

    def test_ensure_uses_legacy_language_and_reading_creates_user(self):
        self.fresh()
        self.conn.execute("INSERT INTO user_settings VALUES (1, 'EN')")
        self.conn.commit()
        db.ensure_user(1)
        db.add_reading(2, 120, 80)
        self.assertEqual(self.conn.execute('SELECT user_id, language FROM users ORDER BY user_id').fetchall(), [(1, 'EN'), (2, 'UA')])

    def test_language_transition(self):
        self.fresh()
        self.assertEqual(db.get_user_language(99), 'UA')
        db.set_user_language(1, 'EN')
        created = self.conn.execute('SELECT created_at FROM users WHERE user_id = 1').fetchone()
        self.conn.execute("UPDATE user_settings SET language = 'UA' WHERE user_id = 1")
        self.conn.commit()
        self.assertEqual(db.get_user_language(1), 'UA')
        db.set_user_language(1, 'EN')
        self.assertEqual(created, self.conn.execute('SELECT created_at FROM users WHERE user_id = 1').fetchone())
        self.assertEqual(self.conn.execute('SELECT language FROM user_settings').fetchone(), ('EN',))
        with self.assertRaises(ValueError):
            db.set_user_language(1, 'unknown')

    def test_language_write_rolls_back_both_tables(self):
        self.fresh()
        db.set_user_language(1, 'UA')
        self.conn.execute("CREATE TRIGGER reject_settings BEFORE INSERT ON user_settings BEGIN SELECT RAISE(ABORT, 'test'); END")
        self.conn.commit()
        before = self.snapshot()
        for user_id in (1, 2):
            with self.assertRaises(sqlite3.IntegrityError):
                db.set_user_language(user_id, 'EN')
            self.assertEqual(before, self.snapshot())

    def test_reading_failure_rolls_back_new_user(self):
        self.fresh()
        self.conn.execute("CREATE TRIGGER reject_reading BEFORE INSERT ON readings BEGIN SELECT RAISE(ABORT, 'test'); END")
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            db.add_reading(1, 120, 80)
        self.assertEqual(self.conn.execute('SELECT * FROM users').fetchall(), [])

    def test_migration_failure_rolls_back_and_retry_succeeds(self):
        self.legacy()
        self.conn.execute('INSERT INTO readings (user_id) VALUES (1)')
        self.conn.commit()
        before = self.snapshot()
        original = db._check_schema

        def fail_after_index(conn, version):
            original(conn, version)
            if version == 1:
                raise RuntimeError('injected failure')

        with patch.object(db, '_check_schema', side_effect=fail_after_index):
            with self.assertRaises(RuntimeError):
                db.init_db(self.path)
        self.assertEqual(before, self.snapshot())
        db.init_db(self.path)
        db.check_database()

    def test_fresh_failure_rolls_back(self):
        with patch.object(db, 'CREATE_USERS', 'invalid SQL'):
            with self.assertRaises(sqlite3.Error):
                db.init_db(self.path, initialize=True)
        self.assertEqual(self.conn.execute('SELECT name FROM sqlite_master').fetchall(), [])

    def test_startup_rejects_legacy_without_writing(self):
        self.legacy()
        before = self.snapshot()
        with self.assertRaises(RuntimeError):
            db.check_database()
        self.assertEqual(before, self.snapshot())

    def test_missing_path_is_not_created(self):
        missing = Path(self.temp.name) / 'missing.sqlite'
        for operation in (db.init_db, db.check_database):
            with self.assertRaises(sqlite3.OperationalError):
                operation(missing)
            self.assertFalse(missing.exists())

    def test_newer_version_is_rejected_without_changes(self):
        self.fresh()
        self.conn.execute('INSERT INTO schema_migrations (version) VALUES (3)')
        self.conn.commit()
        before = self.snapshot()
        for operation in (db.init_db, db.check_database):
            with self.assertRaisesRegex(RuntimeError, 'newer'):
                operation(self.path)
        self.assertEqual(before, self.snapshot())

    def test_bad_legacy_id_rolls_back(self):
        self.legacy()
        self.conn.execute("INSERT INTO readings (user_id) VALUES ('bad-id')")
        self.conn.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'non-integer'):
            db.init_db(self.path)
        self.assertEqual(before, self.snapshot())

    def test_unexpected_schema_is_rejected(self):
        self.conn.execute('CREATE TABLE readings (id INTEGER)')
        self.conn.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'schema'):
            db.init_db(self.path)
        self.assertEqual(before, self.snapshot())

    def test_unversioned_users_are_rejected(self):
        self.legacy()
        self.conn.execute(db.CREATE_USERS)
        self.conn.commit()
        with self.assertRaisesRegex(RuntimeError, 'Unversioned'):
            db.init_db(self.path)

    def test_initialization_rejects_existing_legacy(self):
        self.legacy()
        with self.assertRaisesRegex(RuntimeError, 'empty'):
            db.init_db(self.path, initialize=True)

    def test_old_application_writes_still_work(self):
        self.fresh()
        self.conn.execute("INSERT OR REPLACE INTO user_settings VALUES (1, 'EN')")
        self.conn.execute('INSERT INTO readings (user_id, systolic, diastolic) VALUES (1, 120, 80)')
        self.conn.commit()
        self.assertEqual(db.get_user_language(1), 'EN')
        self.assertEqual(len(db.get_last(1)), 1)

    def test_start_ensures_user_without_importing_bot(self):
        # Extract only the handler: importing bot would load environment config.
        tree = ast.parse(Path(db.__file__).with_name('bot.py').read_text())
        start = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'start')
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        self.fresh()
        namespace = {'ensure_user': db.ensure_user, 'get_user_language': db.get_user_language,
                     'get_text': lambda **kwargs: 'welcome'}
        exec(compile(ast.Module(body=[start], type_ignores=[]), '<start handler>', 'exec'), namespace)
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42),
                                 message=SimpleNamespace(reply_text=AsyncMock()))
        asyncio.run(namespace['start'](update, None))
        self.assertEqual(self.conn.execute('SELECT user_id, language FROM users').fetchall(), [(42, 'UA')])


if __name__ == '__main__':
    unittest.main()
