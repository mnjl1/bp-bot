import sqlite3
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


def init_db():
    with sqlite3.connect('bp.db') as conn:
        cur = conn.cursor()
        cur.execute(create_readings_table)
        cur.execute(create_user_settings_table)


def add_reading(user_id, systolic, diastolic, pulse=None, note=None):
    with sqlite3.connect('bp.db') as conn:
        cur = conn.cursor()
        cur.execute("""
                    INSERT INTO readings (user_id, systolic, diastolic, pulse, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, systolic, diastolic, pulse, note)
        )


def get_last(user_id, n=5):
    with sqlite3.connect('bp.db') as conn:
        cur = conn.cursor()
        cur.execute(
                    """
                    SELECT * FROM readings WHERE user_id = ?
                    ORDER BY datetime DESC LIMIT ?
                    """,
                    (user_id, n)
        )
        return cur.fetchall()


def get_avg(user_id, days=7):
    with sqlite3.connect('bp.db') as conn:
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
    with sqlite3.connect('bp.db') as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT language FROM user_settings WHERE user_id = ?
            """,
            (user_id,)
        )
        lang = cur.fetchall()
        try:
            return lang[0][0]
        except:
            return 'UA'


def set_user_language(user_id, language):
    with sqlite3.connect('bp.db') as con:
        cur = con.cursor()
        cur.execute(
                """
                INSERT or REPLACE INTO user_settings (user_id, language) VALUES (?, ?)
                """,
                (user_id, language)
            )


def get_total_users():
    with sqlite3.connect('bp.db') as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) FROM readings
            """
        )
        return cur.fetchall()[0][0]


def get_total_readings():
    with sqlite3.connect('bp.db') as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM readings
            """
        )
        return cur.fetchall()[0][0]


if __name__ == '__main__':
    init_db()