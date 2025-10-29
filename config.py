# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- Bot Configuration ---
# Load from environment variables (safer) or hardcode here for testing
# To set an environment variable: export TELEGRAM_BOT_TOKEN="your_token" (Linux/macOS)
# or $env:TELEGRAM_BOT_TOKEN="your_token" (Windows PowerShell)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# --- Menu Definition ---
# This is your "database" for menu items and prices.
MENU = {
    'Premium Matcha Latte': {'name': '🍵 Premium Matcha Latte', 'price': 3},
    'Ceremonial Matcha Latte': {'name': '🍵 Ceremonial Matcha Latte', 'price': 4},
    'Houjicha Latte': {'name': '🍵 Houjicha Latte', 'price': 2.5},
    'Single Shot Nespresso': {'name': '☕ Single Shot Nespresso', 'price': 2.5},
    'Double Shot Nespresso': {'name': '☕ Double Shot Nespresso', 'price': 3.5},
    'Dirty Matcha': {'name': '🍵 Dirty Matcha', 'price': 3.5},
    'Plastic Cup': {'name': '🥤 Plastic Cup', 'price': 0.2},
    '0% Sugar': {'name': '🍬 0% Sugar', 'price': 0},
    '25% Sugar': {'name': '🍬 25% Sugar', 'price': 0},
    '50% Sugar': {'name': '🍬 50% Sugar', 'price': 0},
    '75% Sugar': {'name': '🍬 75% Sugar', 'price': 0},
    '100% Sugar': {'name': '🍬 100% Sugar', 'price': 0},
}