import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timedelta


create_readings_table = """
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        datetime TEXT DEFAULT CURRENT_TIMESTAMP,
        systolic INTEGER,
        diastolic INTEGER,
        pulse INTEGER NULL,
        note TEXT NULL
    );
    """

create_user_settings_table = """
    CREATE TABLE IF NOT EXISTS user_settings(
        user_id INTEGER PRIMARY KEY,
        language TEXT DEFAULT 'UA'
    );
"""


DB_PATH = Path(__file__).resolve().parent / 'bp.db'
SCHEMA_VERSION = 2

CREATE_USERS = """
    CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        language TEXT NOT NULL DEFAULT 'UA',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""
CREATE_MIGRATIONS = """
    CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY CHECK (version > 0),
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""

CREATE_PAYMENTS = """
    CREATE TABLE payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        currency TEXT NOT NULL,
        amount INTEGER NOT NULL CHECK(amount > 0),
        invoice_payload TEXT NOT NULL,
        telegram_payment_charge_id TEXT NOT NULL UNIQUE,
        provider_payment_charge_id TEXT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""


def _connect(database, mode='rw'):
    # rw prevents a typo in an existing database path from creating a new file.
    uri = Path(database).resolve().as_uri() + '?mode=' + mode
    return sqlite3.connect(uri, uri=True, timeout=5)


def _check_table(conn, table, expected):
    columns = conn.execute(f'PRAGMA table_info({table})').fetchall()
    actual = [(row[1], row[2].upper(), row[3], row[5]) for row in columns]
    if actual != expected:
        raise RuntimeError(f'Unexpected schema for {table}')


def _version(conn):
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'schema_migrations'"
    ).fetchone()
    if not exists:
        return 0
    _check_table(conn, 'schema_migrations', [
        ('version', 'INTEGER', 0, 1), ('applied_at', 'TEXT', 1, 0),
    ])
    versions = [row[0] for row in conn.execute(
        'SELECT version FROM schema_migrations ORDER BY version'
    )]
    if any(version > SCHEMA_VERSION for version in versions):
        raise RuntimeError('Database version is newer than this application supports')
    if versions not in ([], [1], [1, 2]):
        raise RuntimeError('Unexpected migration history')
    return versions[-1] if versions else 0


def _check_schema(conn, version):
    if version == 2:
        _check_schema(conn, 1)
        _check_table(conn, 'payments', [
            ('id', 'INTEGER', 0, 1), ('user_id', 'INTEGER', 1, 0),
            ('currency', 'TEXT', 1, 0), ('amount', 'INTEGER', 1, 0),
            ('invoice_payload', 'TEXT', 1, 0),
            ('telegram_payment_charge_id', 'TEXT', 1, 0),
            ('provider_payment_charge_id', 'TEXT', 0, 0),
            ('created_at', 'TEXT', 1, 0),
        ])
        # Read-only check of the exact DDL, including UNIQUE and CHECK constraints.
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'payments'"
        ).fetchone()[0]
        if ''.join(ddl.lower().split()) != ''.join(CREATE_PAYMENTS.lower().split()):
            raise RuntimeError('Unexpected constraints for payments')
        return
    if version not in (0, 1):
        raise RuntimeError('Unsupported schema version')
    _check_table(conn, 'readings', [
        ('id', 'INTEGER', 0, 1), ('user_id', 'INTEGER', 0, 0),
        ('datetime', 'TEXT', 0, 0), ('systolic', 'INTEGER', 0, 0),
        ('diastolic', 'INTEGER', 0, 0), ('pulse', 'INTEGER', 0, 0),
        ('note', 'TEXT', 0, 0),
    ])
    _check_table(conn, 'user_settings', [
        ('user_id', 'INTEGER', 0, 1), ('language', 'TEXT', 0, 0),
    ])
    timestamp_columns = [('readings', 'datetime')]
    if version == 1:
        timestamp_columns.append(('users', 'created_at'))
    for table, column in timestamp_columns:
        columns = conn.execute(f'PRAGMA table_info({table})').fetchall()
        default = next((row[4] for row in columns if row[1] == column), None)
        if default is None or default.strip().upper() != 'CURRENT_TIMESTAMP':
            raise RuntimeError(f'Expected CURRENT_TIMESTAMP default for {table}.{column}')
    if version == 1:
        _check_table(conn, 'users', [
            ('user_id', 'INTEGER', 0, 1), ('language', 'TEXT', 1, 0),
            ('created_at', 'TEXT', 1, 0),
        ])
        indexes = conn.execute('PRAGMA index_list(readings)').fetchall()
        if not any(row[1] == 'idx_readings_user_datetime'
                   and row[2] == 0 and row[4] == 0 for row in indexes):
            raise RuntimeError('Missing or incompatible readings index')
        columns = conn.execute(
            'PRAGMA index_info(idx_readings_user_datetime)'
        ).fetchall()
        if [row[2] for row in columns] != ['user_id', 'datetime']:
            raise RuntimeError('Unexpected readings index columns')


def check_database(database=None):
    """Read-only startup check; never initializes or migrates a database."""
    with closing(_connect(database or DB_PATH, 'ro')) as conn:
        if _version(conn) != SCHEMA_VERSION:
            raise RuntimeError('Database migration required; run db.py explicitly')
        _check_schema(conn, SCHEMA_VERSION)


def _migrate_v0_to_v1(conn, *, initialize=False):
    """Original foundation migration; caller owns the transaction."""
    objects = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    )}
    if 'users' in objects or 'idx_readings_user_datetime' in objects:
        raise RuntimeError('Unversioned foundation objects require review')
    if initialize:
        if objects - {'schema_migrations'}:
            raise RuntimeError('Initialization requires an empty database')
        conn.execute(create_readings_table)
        conn.execute(create_user_settings_table)
    _check_schema(conn, 0)
    if conn.execute("""
        SELECT 1 FROM readings
        WHERE user_id IS NOT NULL AND typeof(user_id) != 'integer'
        LIMIT 1
    """).fetchone():
        raise RuntimeError('Legacy readings contain non-integer user IDs')
    if 'schema_migrations' not in objects:
        conn.execute(CREATE_MIGRATIONS)
    conn.execute(CREATE_USERS)
    conn.execute("""
        INSERT INTO users (user_id, language)
        SELECT source.user_id, COALESCE(settings.language, 'UA')
        FROM (
            SELECT user_id FROM readings WHERE user_id IS NOT NULL
            UNION
            SELECT user_id FROM user_settings WHERE user_id IS NOT NULL
        ) AS source
        LEFT JOIN user_settings AS settings
            ON settings.user_id = source.user_id
    """)
    conn.execute('CREATE INDEX idx_readings_user_datetime '
                 'ON readings (user_id, datetime)')
    _check_schema(conn, 1)
    conn.execute('INSERT INTO schema_migrations (version) VALUES (1)')


def _migrate_v1_to_v2(conn):
    """Add receipts without changing users, settings, or readings."""
    _check_schema(conn, 1)
    conn.execute(CREATE_PAYMENTS)
    _check_schema(conn, 2)
    conn.execute('INSERT INTO schema_migrations (version) VALUES (2)')


def init_db(database, *, initialize=False):
    """Explicitly apply required migrations to the latest schema atomically."""
    with closing(_connect(database, 'rwc' if initialize else 'rw')) as conn:
        conn.isolation_level = None
        conn.execute('BEGIN IMMEDIATE')
        try:
            version = _version(conn)
            if version == SCHEMA_VERSION:
                _check_schema(conn, version)
                conn.execute('COMMIT')
                return
            if version == 0:
                _migrate_v0_to_v1(conn, initialize=initialize)
                version = 1
            if version == 1:
                _migrate_v1_to_v2(conn)
            conn.execute('COMMIT')
        except Exception:
            try:
                conn.execute('ROLLBACK')
            except sqlite3.Error:
                # SQLite may already have rolled back; retain the original error.
                pass
            raise


def record_payment(user_id, currency, amount, invoice_payload,
                   telegram_payment_charge_id, provider_payment_charge_id=None):
    """Return True for a new receipt, False for an identical retry; reject conflicts."""
    from constants import SUPPORT_AMOUNTS

    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
        raise ValueError('Invalid payment user_id')
    if (currency != 'XTR' or type(amount) is not int
            or amount not in SUPPORT_AMOUNTS
            or invoice_payload != f'support:{amount}'):
        raise ValueError('Invalid support payment')
    if (not isinstance(telegram_payment_charge_id, str)
            or not telegram_payment_charge_id.strip()):
        raise ValueError('Missing Telegram charge ID')
    if provider_payment_charge_id is not None and not isinstance(provider_payment_charge_id, str):
        raise ValueError('Invalid provider charge ID')
    with closing(_connect(DB_PATH)) as conn, conn:
        cursor = conn.execute("""
            INSERT INTO payments (user_id, currency, amount, invoice_payload,
                                  telegram_payment_charge_id, provider_payment_charge_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_payment_charge_id) DO NOTHING
        """, (user_id, currency, amount, invoice_payload,
              telegram_payment_charge_id, provider_payment_charge_id))
        if cursor.rowcount == 1:
            return True
        existing = conn.execute("""
            SELECT user_id, currency, amount, invoice_payload, provider_payment_charge_id
            FROM payments WHERE telegram_payment_charge_id = ?
        """, (telegram_payment_charge_id,)).fetchone()
        if existing != (user_id, currency, amount, invoice_payload, provider_payment_charge_id):
            raise ValueError('Conflicting data for an existing Telegram charge ID')
        return False


def _ensure_user(conn, user_id):
    if user_id is None:
        raise ValueError('user_id must not be None')
    # DO NOTHING is intentional: ensuring a user must never reset their language.
    conn.execute("""
        INSERT INTO users (user_id, language)
        VALUES (?, COALESCE(
            (SELECT language FROM user_settings WHERE user_id = ?), 'UA'
        ))
        ON CONFLICT(user_id) DO NOTHING
    """, (user_id, user_id))


def ensure_user(user_id):
    with closing(_connect(DB_PATH)) as conn, conn:
        _ensure_user(conn, user_id)


def add_reading(user_id, systolic, diastolic, pulse=None, note=None):
    with closing(_connect(DB_PATH)) as conn, conn:
        _ensure_user(conn, user_id)
        cur = conn.cursor()
        cur.execute("""
                    INSERT INTO readings (user_id, systolic, diastolic, pulse, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, systolic, diastolic, pulse, note)
        )


def get_last(user_id, n=5):
    with closing(_connect(DB_PATH)) as conn, conn:
        cur = conn.cursor()
        cur.execute(
                    """
                    SELECT * FROM readings WHERE user_id = ?
                    ORDER BY datetime DESC LIMIT ?
                    """,
                    (user_id, n)
        )
        return cur.fetchall()


def get_readings_by_date_range(user_id, start_timestamp, end_timestamp):
    """Return one user's readings in [start_timestamp, end_timestamp)."""
    if user_id is None:
        raise ValueError('user_id must not be None')
    with closing(_connect(DB_PATH, 'ro')) as conn:
        return conn.execute("""
            SELECT id, user_id, datetime, systolic, diastolic, pulse, note
            FROM readings
            WHERE user_id = ? AND datetime >= ? AND datetime < ?
            ORDER BY datetime ASC, id ASC
        """, (user_id, start_timestamp, end_timestamp)).fetchall()


def get_avg(user_id, days=7):
    with closing(_connect(DB_PATH)) as conn, conn:
        last_days = datetime.now() - timedelta(days=days)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT AVG(systolic), AVG(diastolic), AVG(pulse)
            FROM readings
            WHERE user_id = ? and datetime > ?
            """,
            (user_id, last_days)
        )
        return cur.fetchall()


def get_user_language(user_id):
    with closing(_connect(DB_PATH)) as conn:
        return conn.execute("""
            SELECT COALESCE(
                (SELECT language FROM user_settings WHERE user_id = ?),
                (SELECT language FROM users WHERE user_id = ?),
                'UA'
            )
        """, (user_id, user_id)).fetchone()[0]


def set_user_language(user_id, language):
    if language not in ('UA', 'EN'):
        raise ValueError('Unsupported language')
    with closing(_connect(DB_PATH)) as conn, conn:
        _ensure_user(conn, user_id)
        conn.execute('UPDATE users SET language = ? WHERE user_id = ?',
                     (language, user_id))
        conn.execute("""
            INSERT INTO user_settings (user_id, language) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET language = excluded.language
        """, (user_id, language))


def get_total_users():
    with closing(_connect(DB_PATH)) as con, con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) FROM readings
            """
        )
        return cur.fetchall()[0][0]


def get_total_readings():
    with closing(_connect(DB_PATH)) as con, con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM readings
            """
        )
        return cur.fetchall()[0][0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Explicit database foundation migration')
    parser.add_argument('database', help='Path to the database to migrate')
    parser.add_argument('--initialize', action='store_true',
                        help='Allow creation of a new, empty database')
    args = parser.parse_args()
    try:
        init_db(args.database, initialize=args.initialize)
    except (RuntimeError, sqlite3.Error):
        # Do not print database values that might appear in an SQLite exception.
        parser.exit(1, 'Migration failed; database changes were rolled back. '
                       'Check schema compatibility, path, and database locks.\n')
    print(f'Database schema is at version {SCHEMA_VERSION}')
