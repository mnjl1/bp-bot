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
    conn = sqlite3.connect('bp.db')
    cur = conn.cursor()
    cur.execute(create_readings_table)
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_db()