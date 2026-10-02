import io
import logging
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import StarTransaction, TransactionPartnerUser, User

import db
import reconcile_stars


def transaction(charge, incoming=True, kind='invoice_payment'):
    partner = TransactionPartnerUser(kind, User(987654, 'private-name', False),
                                     invoice_payload='private-payload')
    return StarTransaction(charge, 25, datetime.now(timezone.utc),
                           source=partner if incoming else None,
                           receiver=None if incoming else partner)


class ReadOnlyReceiptTests(unittest.TestCase):
    def test_helper_selects_only_ids_and_cannot_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite'
            db.init_db(path, initialize=True)
            with patch.object(db, 'DB_PATH', path):
                db.record_payment(42, 'XTR', 25, 'support:25', 'private-charge')
            before = path.read_bytes()
            statements = []
            original = db._connect

            def connect(database, mode):
                self.assertEqual(mode, 'ro')
                connection = original(database, mode)
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute('DELETE FROM payments')
                connection.set_trace_callback(statements.append)
                return connection

            with patch.object(db, '_connect', side_effect=connect):
                self.assertEqual(db.get_payment_charge_ids(path), {'private-charge'})
            self.assertEqual(statements, ['SELECT telegram_payment_charge_id FROM payments'])
            self.assertEqual(path.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.sqlite'
            with self.assertRaises(sqlite3.OperationalError):
                db.get_payment_charge_ids(path)
            self.assertFalse(path.exists())


class ReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_failure_prevents_api_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.sqlite'
            with patch.object(reconcile_stars, 'Bot') as bot:
                with self.assertRaises(sqlite3.OperationalError):
                    await reconcile_stars.reconcile(path, 'synthetic-token')
                bot.assert_not_called()
            self.assertFalse(path.exists())

    async def test_counts_ignore_refunds_and_non_invoice_transactions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite'
            db.init_db(path, initialize=True)
            with patch.object(db, 'DB_PATH', path):
                db.record_payment(42, 'XTR', 25, 'support:25', 'matched')
            before = path.read_bytes()
            client = AsyncMock()
            client.__aenter__.return_value = client
            client.get_star_transactions.return_value = SimpleNamespace(transactions=[
                transaction('matched'), transaction('missing'), transaction('missing'),
                transaction('refund', incoming=False), transaction('gift', kind='gift_purchase')])
            with patch.object(reconcile_stars, 'Bot', return_value=client):
                result = await reconcile_stars.reconcile(path, 'synthetic-token', offset=100, limit=50)
            self.assertEqual(result, (5, 1, 1))
            client.get_star_transactions.assert_awaited_once_with(offset=100, limit=50)
            self.assertEqual([c[0] for c in client.mock_calls],
                             ['__aenter__', 'get_star_transactions', '__aexit__'])
            self.assertEqual(path.read_bytes(), before)


class CommandTests(unittest.TestCase):
    def test_command_with_temporary_database_and_mocked_telegram(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite'
            db.init_db(path, initialize=True)
            with patch.object(db, 'DB_PATH', path):
                db.record_payment(42, 'XTR', 25, 'support:25', 'private-match')
            before = path.read_bytes()
            client = AsyncMock()
            client.__aenter__.return_value = client
            client.get_star_transactions.return_value = SimpleNamespace(transactions=[
                transaction('private-match'), transaction('private-missing')])
            out, err = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {'BOT_TOKEN': 'synthetic-token'}, clear=True), \
                    patch.object(reconcile_stars, 'Bot', return_value=client), \
                    redirect_stdout(out), redirect_stderr(err):
                code = reconcile_stars.main([str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(err.getvalue(), '')
            self.assertEqual(out.getvalue(), 'Telegram transactions checked: 2\n'
                             'Matching local charge IDs: 1\n'
                             'Telegram charge IDs missing locally: 1\n')
            self.assertEqual(path.read_bytes(), before)

    def run_main(self, result=None, error=None, token='synthetic-token'):
        stdout, stderr = io.StringIO(), io.StringIO()
        environment = {} if token is None else {'BOT_TOKEN': token}
        with patch.dict(os.environ, environment, clear=True), patch.object(
            reconcile_stars, 'reconcile', new_callable=AsyncMock
        ) as reconcile, redirect_stdout(stdout), redirect_stderr(stderr):
            reconcile.return_value = result
            reconcile.side_effect = error
            code = reconcile_stars.main(['synthetic.sqlite'])
        return code, stdout.getvalue(), stderr.getvalue(), reconcile

    def test_default_output_contains_only_counts(self):
        code, out, err, call = self.run_main((3, 1, 2))
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        self.assertEqual(out, 'Telegram transactions checked: 3\nMatching local charge IDs: 1\nTelegram charge IDs missing locally: 2\n')
        call.assert_awaited_once_with('synthetic.sqlite', 'synthetic-token', offset=0, limit=100)

    def test_api_and_database_errors_are_generic(self):
        from telegram.error import TelegramError
        for error in (TelegramError('synthetic-token private-charge'),
                      sqlite3.OperationalError('private-user private-payload')):
            code, out, err, _ = self.run_main(error=error)
            self.assertEqual(code, 1)
            self.assertEqual(out, '')
            self.assertIn('Reconciliation failed', err)
            self.assertNotIn('private', err)
            self.assertNotIn('synthetic-token', err)

    def test_missing_and_blank_token_do_not_call_api_or_db(self):
        for token in (None, '', '  '):
            code, out, err, call = self.run_main(token=token)
            self.assertEqual(code, 1)
            self.assertEqual(out, '')
            call.assert_not_called()

    def test_library_logs_suppressed_and_logging_restored(self):
        async def noisy(*args, **kwargs):
            logging.getLogger('httpx').critical('synthetic-token private-charge')
            return (0, 0, 0)
        previous = logging.root.manager.disable
        code, out, err, _ = self.run_main(error=noisy)
        self.assertEqual(code, 0)
        self.assertNotIn('synthetic-token', out + err)
        self.assertEqual(logging.root.manager.disable, previous)
