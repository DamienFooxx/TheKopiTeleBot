# main.py
import logging
from dotenv import load_dotenv

load_dotenv()

from bot import OrderBot
from config import TELEGRAM_BOT_TOKEN
from data_logger import setup_database

def main():
    """Main entry point for the bot."""
    
    # Enable logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
        level=logging.INFO
    )
    
    # --- Setup database ---
    setup_database()
    
    # Simple check to make sure the token is set
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "TELEGRAM_BOT_TOKEN":
        logging.error(
            "TELEGRAM_BOT_TOKEN is not set! Please set it in config.py or as an environment variable."
        )
        return

    # Initialize and run the bot
    bot = OrderBot(token=TELEGRAM_BOT_TOKEN)
    bot.run()

if __name__ == "__main__":
    main()