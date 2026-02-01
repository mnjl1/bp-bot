import sqlite3


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


def init_db():
    with sqlite3.connect('bp.db') as conn:
        cur = conn.cursor()
        cur.execute(create_readings_table)


def add_reading(user_id, systolic, diastolic, pulse=None, note=None):
    with sqlite3.connect('bp.db') as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO readings (user_id, systolic, diastolic, pulse, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, systolic, diastolic, pulse, note))


if __name__ == '__main__':
    init_db()