# bot.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# Import our separated logic and config
from data_logger import log_order
from menu_builder import build_menu_message
from config import ADMIN_CHAT_ID, MENU

# Setup logger
logger = logging.getLogger(__name__)

class OrderBot:
    """
    Encapsulates all logic for the Telegram Order Bot.
    """
    # Define conversation states as class attributes for clarity
    STATE_NAME, STATE_MENU_SELECTION, STATE_SCREENSHOT = range(3)

    def __init__(self, token: str):
        """Initializes the bot with its token and admin ID."""
        self.token = token
        self.admin_chat_id = ADMIN_CHAT_ID  # Get from config
        self.application = Application.builder().token(self.token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        """Creates and registers all handlers for the bot."""
        # Conversation handler for taking the order
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                self.STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_name)],
                self.STATE_MENU_SELECTION: [CallbackQueryHandler(self.menu_button_handler, pattern="^(add_|clear_cart|done_ordering)")],
                self.STATE_SCREENSHOT: [MessageHandler(filters.PHOTO, self.get_screenshot)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )

        # Handler for the admin's buttons
        approval_handler = CallbackQueryHandler(self.handle_approval, pattern="^(approve_|decline_)")

        self.application.add_handler(conv_handler)
        self.application.add_handler(approval_handler)

    # --- Conversation Handler Methods ---

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation and asks for the user's name."""
        await update.message.reply_text(
            "Welcome! Let's take your order. What is your full name?"
        )
        return self.STATE_NAME

    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Stores the name and SHOWS THE MENU."""
        context.user_data['name'] = update.message.text
        context.user_data['cart'] = {}  # Initialize an empty cart

        text, reply_markup, _ = build_menu_message(context.user_data['cart'])
        
        await update.message.reply_text(
            f"Thanks, {context.user_data['name']}! Here is our menu.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return self.STATE_MENU_SELECTION

    async def menu_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles all button clicks from the menu."""
        query = update.callback_query
        await query.answer()  # Acknowledge the button press
        
        data = query.data
        cart = context.user_data.get('cart', {})
        
        if data.startswith("add_"):
            item_id = data.split("_")[1]  # e.g., 'burger'
            cart[item_id] = cart.get(item_id, 0) + 1
            context.user_data['cart'] = cart
            
            text, reply_markup, _ = build_menu_message(cart)
            await query.edit_message_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode=ParseMode.MARKDOWN
            )
            return self.STATE_MENU_SELECTION

        elif data == "clear_cart":
            context.user_data['cart'] = {}
            text, reply_markup, _ = build_menu_message({})
            await query.edit_message_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode=ParseMode.MARKDOWN
            )
            return self.STATE_MENU_SELECTION

        elif data == "done_ordering":
            # Cart is guaranteed to not be empty due to logic in build_menu_message
            order_details = ""
            total_price = 0
            for item_id, quantity in cart.items():
                item = MENU[item_id]
                order_details += f"{quantity}x {item['name']}\n"
                total_price += item['price'] * quantity
            
            context.user_data['order'] = order_details.strip()
            context.user_data['total'] = total_price
            
            payment_instructions = (
                f"Great! Your final order is:\n{order_details}\n"
                f"**Total: ${total_price}**\n\n"
                "Please send the payment to:\n"
                "Paynow No.: 97929869\n"
                "Name: DamienFoo\n\n"
                "After paying, please send a screenshot of the transaction."
            )
            
            await context.bot.send_message(
                chat_id=query.from_user.id, 
                text=payment_instructions,
                parse_mode=ParseMode.MARKDOWN
            )
            
            await query.edit_message_text(
                f"Order confirmed. Your total is **${total_price}**.\n\n"
                "Please see the message below for payment instructions.",
                parse_mode=ParseMode.MARKDOWN
            )
            return self.STATE_SCREENSHOT

    async def get_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Receives screenshot, forwards to admin."""
        customer_name = context.user_data.get('name', 'Unknown')
        order_details = context.user_data.get('order', 'No order details')
        total_price = context.user_data.get('total', 0)
        user_id = update.message.from_user.id
        
        await update.message.reply_text(
            "Thank you! We have received your screenshot.\n"
            "We will verify your payment and send a confirmation message shortly."
        )
        
        admin_caption = (
            f"New Order for Verification\n\n"
            f"User Name: {customer_name}\n"
            f"User ID: {user_id}\n"
            f"**Total: ${total_price}**\n\n"
            f"Order:\n{order_details}"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ Decline", callback_data=f"decline_{user_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Use self.admin_chat_id
        await context.bot.send_photo(
            chat_id=self.admin_chat_id,
            photo=update.message.photo[-1].file_id,
            caption=admin_caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.bot_data[f"order_for_{user_id}"] = {
            'name': customer_name,
            'order': order_details,
            'total': total_price
        }
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels and ends the conversation."""
        await update.message.reply_text(
            "Order cancelled. Feel free to start over with /start."
        )
        return ConversationHandler.END

    # --- Admin Handler Method ---

    async def handle_approval(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the admin's 'Approve' or 'Decline' button press."""
        query = update.callback_query
        await query.answer() 

        action, user_id_str = query.data.split("_")
        user_id = int(user_id_str) # Convert user_id to integer
        
        order_data_key = f"order_for_{user_id}"
        order_data = context.bot_data.pop(order_data_key, None)
        
        if not order_data:
            await query.edit_message_text(text="Error: Order data not found (maybe already processed).")
            return

        customer_name = order_data['name']
        order_details = order_data['order']
        total_price = order_data.get('total', 0)

        if action == "approve":
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Payment Verified! Your order is confirmed and is now being processed. Thank you!"
            )
            await query.edit_message_caption(
                caption=f"✅ APPROVED\n\nName: {customer_name}\nTotal: ${total_price}\nOrder:\n{order_details}\n\nUser has been notified.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # --- 2. LOG THE ORDER TO OUR DATABASE ---
            log_order(
                user_id=user_id,
                user_name=customer_name,
                order_details=order_details,
                total_price=total_price
            )
            
        elif action == "decline":
            # ... (no changes to the decline part)
            await context.bot.send_message(
                chat_id=user_id,
                text="Payment Issue. There was an issue with your payment. Please contact @DamienFxx."
            )
            await query.edit_message_caption(
                caption=f"DECLINED\n\nName: {customer_name}\nTotal: ${total_price}\nOrder:\n{order_details}\n\nUser has been notified.",
                parse_mode=ParseMode.MARKDOWN
            )

    # --- Public Run Method ---

    def run(self):
        """Runs the bot."""
        logger.info("Bot is running...")
        self.application.run_polling()