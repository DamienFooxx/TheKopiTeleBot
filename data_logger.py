# data_logger.py
import sqlite3
from datetime import datetime
import logging

DATABASE_FILE = "TheKopiorders.db"
logger = logging.getLogger(__name__)

def setup_database():
    """
    Creates the 'orders' table in the SQLite database if it doesn't exist.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        
        # Create table
        # We use "IF NOT EXISTS" to safely run this every time the bot starts
        c.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                order_details TEXT NOT NULL,
                total_price REAL NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database setup complete. Using '{DATABASE_FILE}'")
    except sqlite3.Error as e:
        logger.error(f"Database error during setup: {e}")

def log_order(user_id: int, user_name: str, order_details: str, total_price: float):
    """
    Logs a single approved order to the SQLite database.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        
        timestamp = datetime.now().isoformat() # e.g., "2025-10-29T22:45:00.123456"
        
        # Insert a row of data
        # Using placeholders (?) prevents SQL injection
        c.execute(
            "INSERT INTO orders (timestamp, user_id, user_name, order_details, total_price) VALUES (?, ?, ?, ?, ?)",
            (timestamp, user_id, user_name, order_details, total_price)
        )
        
        conn.commit()
        conn.close()
        logger.info(f"Successfully logged order for user {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Failed to log order for user {user_id}: {e}")