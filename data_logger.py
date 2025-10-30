# data_logger.py
import sqlite3
from datetime import datetime
import logging
from typing import List, Tuple, Optional

DATABASE_FILE = "orders.db"
logger = logging.getLogger(__name__)

def setup_database():
    """
    Creates/updates the 'orders' table in the SQLite database.
    Adds 'status' and 'collection_time' columns if they don't exist.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        
        # Create table with the new columns
        c.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                order_details TEXT NOT NULL,
                total_price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                collection_time TEXT  -- Stores the user-selected time, e.g., "16:15"
            )
        ''')
        
        # --- Handle adding 'status' column (idempotent) ---
        try:
            c.execute("ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'")
            logger.info("Added 'status' column to 'orders' table.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e): pass
            else: raise e
            
        # --- Handle adding 'collection_time' column (idempotent) ---
        try:
            c.execute("ALTER TABLE orders ADD COLUMN collection_time TEXT")
            logger.info("Added 'collection_time' column to 'orders' table.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e): pass # Column already exists
            else: raise e
        
        conn.commit()
        conn.close()
        logger.info(f"Database setup complete. Using '{DATABASE_FILE}'")
    except sqlite3.Error as e:
        logger.error(f"Database error during setup: {e}")

def log_order(user_id: int, user_name: str, order_details: str, total_price: float, collection_time: str):
    """
    Logs a single approved order to the SQLite database.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        
        timestamp = datetime.now().isoformat()
        
        # Insert a row of data, now including the status and collection_time
        c.execute(
            "INSERT INTO orders (timestamp, user_id, user_name, order_details, total_price, status, collection_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, user_id, user_name, order_details, total_price, 'approved', collection_time)
        )
        
        conn.commit()
        conn.close()
        logger.info(f"Successfully logged order for user {user_id} with status 'approved'")
    except sqlite3.Error as e:
        logger.error(f"Failed to log order for user {user_id}: {e}")

# --- UPDATED FUNCTION FOR FULFILLMENT ---

def get_unfulfilled_orders() -> List[Tuple[int, str, str, str]]:
    """
    Retrieves all orders with the status 'approved'.
    Returns a list of tuples: (order_id, user_name, order_details, collection_time)
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute(
            "SELECT order_id, " \
            "user_name, " \
            "order_details, " \
            "collection_time " \
            "FROM orders WHERE status = 'approved' " \
            "ORDER BY collection_time ASC"
        )
        orders = c.fetchall()
        conn.close()
        return orders
    except sqlite3.Error as e:
        logger.error(f"Failed to get unfulfilled orders: {e}")
        return []

def get_order_user_id(order_id: int) -> Optional[int]:
    """
    Gets the user_id for a given order_id to send them a notification.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute("SELECT user_id FROM orders WHERE order_id = ?", (order_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None
    except sqlite3.Error as e:
        logger.error(f"Failed to get user_id for order {order_id}: {e}")
        return None

def mark_order_completed(order_id: int) -> bool:
    """
Moves an order's status from 'approved' to 'completed'.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute(
            "UPDATE orders SET status = 'completed' WHERE order_id = ?", (order_id,)
        )
        conn.commit()
        conn.close()
        logger.info(f"Marked order {order_id} as 'completed'")
        return True
    except sqlite3.Error as e:
        logger.error(f"Failed to mark order {order_id} as 'completed': {e}")
        return False