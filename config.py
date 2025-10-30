# config.py
import os
from dotenv import load_dotenv

# load_dotenv() # This is already called in main.py, no need to call it twice.

# --- Bot Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Ensure ADMIN_CHAT_ID is an integer
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0")) 

# --- Menu Definition ---
# This is your "database" for menu items and prices.
MENU = {
    # Using simple keys is safer for callback_data
    'prem_matcha': {'name': '🍵 Premium Matcha Latte', 'price': 3},
    'cere_matcha': {'name': '🍵 Ceremonial Matcha Latte', 'price': 4},
    'houjicha': {'name': '🍵 Houjicha Latte', 'price': 2.5},
    'nespresso_s': {'name': '☕ Single Shot Nespresso', 'price': 2.5},
    'nespresso_d': {'name': '☕ Double Shot Nespresso', 'price': 3.5},
    'dirty_matcha': {'name': '🍵 Dirty Matcha', 'price': 3.5},
    'cup': {'name': '🥤 Plastic Cup', 'price': 0.2},
    'sugar_0': {'name': '🍬 0% Sugar', 'price': 0},
    'sugar_25': {'name': '🍬 25% Sugar', 'price': 0},
    'sugar_50': {'name': '🍬 50% Sugar', 'price': 0},
    'sugar_75': {'name': '🍬 75% Sugar', 'price': 0},
    'sugar_100': {'name': '🍬 100% Sugar', 'price': 0},
}