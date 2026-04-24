import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.use_postgres = self.db_url is not None and self.db_url.startswith("postgresql")
        self.init_db()

    def get_connection(self):
        if self.use_postgres:
            # Connect to Supabase/PostgreSQL
            conn = psycopg2.connect(self.db_url)
            return conn
        else:
            # Fallback to local SQLite
            conn = sqlite3.connect("tracking_system.db")
            conn.row_factory = sqlite3.Row
            return conn

    def init_db(self):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS trackings (
                            id SERIAL PRIMARY KEY,
                            item_code TEXT UNIQUE,
                            resi_number TEXT NOT NULL,
                            courier TEXT,
                            last_status TEXT,
                            history_json TEXT,
                            last_updated TIMESTAMP,
                            is_delivered BOOLEAN DEFAULT FALSE
                        )
                    """)
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trackings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_code TEXT UNIQUE,
                        resi_number TEXT NOT NULL,
                        courier TEXT,
                        last_status TEXT,
                        history_json TEXT,
                        last_updated DATETIME,
                        is_delivered INTEGER DEFAULT 0
                    )
                """)
                conn.commit()

    def add_or_update_tracking(self, item_code, resi_number, courier=None):
        now = datetime.now().isoformat()
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO trackings (item_code, resi_number, courier, last_updated)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(item_code) DO UPDATE SET
                            resi_number = EXCLUDED.resi_number,
                            courier = EXCLUDED.courier,
                            last_updated = EXCLUDED.last_updated
                    """, (item_code, resi_number, courier, now))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO trackings (item_code, resi_number, courier, last_updated)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(item_code) DO UPDATE SET
                        resi_number = excluded.resi_number,
                        courier = excluded.courier,
                        last_updated = excluded.last_updated
                """, (item_code, resi_number, courier, now))
                conn.commit()

    def update_tracking_status(self, item_code, status, history, is_delivered):
        now = datetime.now().isoformat()
        history_str = json.dumps(history)
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE trackings 
                        SET last_status = %s, history_json = %s, is_delivered = %s, last_updated = %s
                        WHERE item_code = %s
                    """, (status, history_str, is_delivered, now, item_code))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    UPDATE trackings 
                    SET last_status = ?, history_json = ?, is_delivered = ?, last_updated = ?
                    WHERE item_code = ?
                """, (status, history_str, 1 if is_delivered else 0, now, item_code))
                conn.commit()

    def get_all_active_trackings(self):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM trackings WHERE is_delivered = FALSE")
                    return [dict(row) for row in cur.fetchall()]
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM trackings WHERE is_delivered = 0")
                return [dict(row) for row in cursor.fetchall()]

    def get_tracking_by_item(self, item_code):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM trackings WHERE item_code = %s", (item_code,))
                    row = cur.fetchone()
                    if row:
                        data = dict(row)
                        if data['history_json']:
                            data['history'] = json.loads(data['history_json'])
                        return data
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM trackings WHERE item_code = ?", (item_code,))
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    if data['history_json']:
                        data['history'] = json.loads(data['history_json'])
                    return data
        return None

    def get_all_trackings(self):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM trackings")
                    return [dict(row) for row in cur.fetchall()]
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM trackings")
                return [dict(row) for row in cursor.fetchall()]
