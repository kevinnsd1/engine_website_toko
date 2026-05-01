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
                            destination TEXT,
                            last_status TEXT,
                            history_json TEXT,
                            last_updated TIMESTAMP,
                            is_delivered BOOLEAN DEFAULT FALSE
                        );
                        CREATE TABLE IF NOT EXISTS users (
                            id SERIAL PRIMARY KEY,
                            username TEXT UNIQUE NOT NULL,
                            password TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS products (
                            id SERIAL PRIMARY KEY,
                            sku_code TEXT UNIQUE NOT NULL,
                            name TEXT NOT NULL,
                            category TEXT,
                            stock INTEGER DEFAULT 0,
                            status TEXT,
                            image_url TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS returns (
                            id SERIAL PRIMARY KEY,
                            sku_code TEXT NOT NULL,
                            product_name TEXT,
                            status TEXT DEFAULT 'PENDING',
                            reason TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS stock_opnames (
                            id SERIAL PRIMARY KEY,
                            status TEXT DEFAULT 'IN PROGRESS',
                            total_items INTEGER DEFAULT 0,
                            discrepancies INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS stock_opname_items (
                            id SERIAL PRIMARY KEY,
                            opname_id INTEGER REFERENCES stock_opnames(id),
                            sku_code TEXT NOT NULL,
                            product_name TEXT,
                            system_stock INTEGER,
                            physical_stock INTEGER,
                            discrepancy INTEGER
                        );
                    """)
                    # Check if destination column exists in trackings, if not add it
                    try:
                        cur.execute("ALTER TABLE trackings ADD COLUMN IF NOT EXISTS destination TEXT")
                    except:
                        pass
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trackings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_code TEXT UNIQUE,
                        resi_number TEXT NOT NULL,
                        courier TEXT,
                        destination TEXT,
                        last_status TEXT,
                        history_json TEXT,
                        last_updated DATETIME,
                        is_delivered INTEGER DEFAULT 0
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sku_code TEXT UNIQUE NOT NULL,
                        name TEXT NOT NULL,
                        category TEXT,
                        stock INTEGER DEFAULT 0,
                        status TEXT,
                        image_url TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS returns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sku_code TEXT NOT NULL,
                        product_name TEXT,
                        status TEXT DEFAULT 'PENDING',
                        reason TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_opnames (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        status TEXT DEFAULT 'IN PROGRESS',
                        total_items INTEGER DEFAULT 0,
                        discrepancies INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_opname_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        opname_id INTEGER REFERENCES stock_opnames(id),
                        sku_code TEXT NOT NULL,
                        product_name TEXT,
                        system_stock INTEGER,
                        physical_stock INTEGER,
                        discrepancy INTEGER
                    )
                """)
                # SQLite doesn't support ADD COLUMN IF NOT EXISTS easily in old versions, 
                # but since we added it to CREATE TABLE above for new DBs, 
                # we just try to alter for existing ones.
                try:
                    conn.execute("ALTER TABLE trackings ADD COLUMN destination TEXT")
                except:
                    pass
                conn.commit()

    def add_or_update_tracking(self, item_code, resi_number, courier=None, destination=None):
        now = datetime.now().isoformat()
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO trackings (item_code, resi_number, courier, destination, last_updated)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT(item_code) DO UPDATE SET
                            resi_number = EXCLUDED.resi_number,
                            courier = EXCLUDED.courier,
                            destination = EXCLUDED.destination,
                            last_updated = EXCLUDED.last_updated
                    """, (item_code, resi_number, courier, destination, now))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO trackings (item_code, resi_number, courier, destination, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(item_code) DO UPDATE SET
                        resi_number = excluded.resi_number,
                        courier = excluded.courier,
                        destination = excluded.destination,
                        last_updated = excluded.last_updated
                """, (item_code, resi_number, courier, destination, now))
                conn.commit()

    def delete_tracking(self, item_code):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM trackings WHERE item_code = %s", (item_code,))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM trackings WHERE item_code = ?", (item_code,))
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

    # --- USER METHODS ---
    def create_user(self, username, hashed_password):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (username, password)
                        VALUES (%s, %s)
                    """, (username, hashed_password))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO users (username, password)
                    VALUES (?, ?)
                """, (username, hashed_password))
                conn.commit()

    def get_user_by_username(self, username):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                    row = cur.fetchone()
                    return dict(row) if row else None
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_all_users(self):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT id, username, created_at FROM users")
                    return [dict(row) for row in cur.fetchall()]
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT id, username, created_at FROM users")
                return [dict(row) for row in cursor.fetchall()]

    # --- PRODUCT METHODS ---
    def get_products(self):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM products ORDER BY created_at DESC")
                    return [dict(row) for row in cur.fetchall()]
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM products ORDER BY created_at DESC")
                return [dict(row) for row in cursor.fetchall()]

    def add_product(self, sku_code, name, category, stock, status, image_url=None):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO products (sku_code, name, category, stock, status, image_url)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT(sku_code) DO UPDATE SET
                            name = EXCLUDED.name,
                            category = EXCLUDED.category,
                            stock = EXCLUDED.stock,
                            status = EXCLUDED.status,
                            image_url = EXCLUDED.image_url,
                            updated_at = CURRENT_TIMESTAMP
                    """, (sku_code, name, category, stock, status, image_url))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO products (sku_code, name, category, stock, status, image_url)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sku_code) DO UPDATE SET
                        name = excluded.name,
                        category = excluded.category,
                        stock = excluded.stock,
                        status = excluded.status,
                        image_url = excluded.image_url,
                        updated_at = CURRENT_TIMESTAMP
                """, (sku_code, name, category, stock, status, image_url))
                conn.commit()

    # --- RETURN METHODS ---
    def get_returns(self):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM returns ORDER BY created_at DESC")
                    return [dict(row) for row in cur.fetchall()]
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM returns ORDER BY created_at DESC")
                return [dict(row) for row in cursor.fetchall()]

    def add_return(self, sku_code, product_name, reason, status='PENDING'):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO returns (sku_code, product_name, reason, status)
                        VALUES (%s, %s, %s, %s)
                    """, (sku_code, product_name, reason, status))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO returns (sku_code, product_name, reason, status)
                    VALUES (?, ?, ?, ?)
                """, (sku_code, product_name, reason, status))
                conn.commit()

    def return_exists(self, sku_code):
        """Cek apakah sudah ada data retur untuk sku_code ini (hindari duplikat dari worker)."""
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM returns WHERE sku_code = %s", (sku_code,))
                    return cur.fetchone()[0] > 0
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM returns WHERE sku_code = ?", (sku_code,))
                return cursor.fetchone()[0] > 0

    # --- STOCK OPNAME METHODS ---
    def get_stock_opnames(self):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM stock_opnames ORDER BY created_at DESC")
                    return [dict(row) for row in cur.fetchall()]
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM stock_opnames ORDER BY created_at DESC")
                return [dict(row) for row in cursor.fetchall()]

    def create_stock_opname(self, status='IN PROGRESS'):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO stock_opnames (status) VALUES (%s) RETURNING id", (status,))
                    return cur.fetchone()[0]
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("INSERT INTO stock_opnames (status) VALUES (?)", (status,))
                conn.commit()
                return cursor.lastrowid

    def add_opname_item(self, opname_id, sku_code, product_name, system_stock, physical_stock):
        discrepancy = physical_stock - system_stock
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO stock_opname_items (opname_id, sku_code, product_name, system_stock, physical_stock, discrepancy)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (opname_id, sku_code, product_name, system_stock, physical_stock, discrepancy))
                conn.commit()
        else:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO stock_opname_items (opname_id, sku_code, product_name, system_stock, physical_stock, discrepancy)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (opname_id, sku_code, product_name, system_stock, physical_stock, discrepancy))
                conn.commit()

    def complete_stock_opname(self, opname_id):
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*), SUM(ABS(discrepancy)) FROM stock_opname_items WHERE opname_id = %s", (opname_id,))
                    total_items, discrepancies = cur.fetchone()
                    cur.execute("""
                        UPDATE stock_opnames 
                        SET status = 'COMPLETED', total_items = %s, discrepancies = %s
                        WHERE id = %s
                    """, (total_items, discrepancies or 0, opname_id))
                conn.commit()
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*), SUM(ABS(discrepancy)) FROM stock_opname_items WHERE opname_id = ?", (opname_id,))
                total_items, discrepancies = cursor.fetchone()
                conn.execute("""
                    UPDATE stock_opnames 
                    SET status = 'COMPLETED', total_items = ?, discrepancies = ?
                    WHERE id = ?
                """, (total_items, discrepancies or 0, opname_id))
                conn.commit()

    # --- DASHBOARD SUMMARY ---
    def get_dashboard_summary(self):
        summary = {
            "total_inventory": 0,
            "pending_shipments": 0,
            "recent_returns": 0,
            "stock_alerts": 0
        }
        if self.use_postgres:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT SUM(stock) FROM products")
                    summary["total_inventory"] = cur.fetchone()[0] or 0
                    
                    cur.execute("SELECT COUNT(*) FROM trackings WHERE is_delivered = FALSE")
                    summary["pending_shipments"] = cur.fetchone()[0] or 0
                    
                    cur.execute("SELECT COUNT(*) FROM returns WHERE created_at > NOW() - INTERVAL '7 days'")
                    summary["recent_returns"] = cur.fetchone()[0] or 0
                    
                    cur.execute("SELECT COUNT(*) FROM products WHERE stock < 15")
                    summary["stock_alerts"] = cur.fetchone()[0] or 0
        else:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT SUM(stock) FROM products")
                summary["total_inventory"] = cursor.fetchone()[0] or 0
                
                cursor = conn.execute("SELECT COUNT(*) FROM trackings WHERE is_delivered = 0")
                summary["pending_shipments"] = cursor.fetchone()[0] or 0
                
                cursor = conn.execute("SELECT COUNT(*) FROM returns WHERE created_at > datetime('now', '-7 days')")
                summary["recent_returns"] = cursor.fetchone()[0] or 0
                
                cursor = conn.execute("SELECT COUNT(*) FROM products WHERE stock < 15")
                summary["stock_alerts"] = cursor.fetchone()[0] or 0
        return summary
