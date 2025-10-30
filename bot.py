# bot.py
import logging
import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat
)
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
from data_logger import (
    log_order, 
    get_unfulfilled_orders, 
    get_order_user_id, 
    mark_order_completed
)
from menu_builder import build_menu_message
from config import ADMIN_CHAT_ID, MENU

# Setup logger
logger = logging.getLogger(__name__)

def generate_time_slots(start_time_str: str, end_time_str: str) -> list[str]:
    """Generates 15-minute time slots between a start and end time."""
    slots = []
    try:
        start_time = datetime.datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.datetime.strptime(end_time_str, "%H:%M").time()
        
        current_time = datetime.datetime.combine(datetime.date.today(), start_time)
        end_datetime = datetime.datetime.combine(datetime.date.today(), end_time)
        
        # Also check current time to not show past slots
        now = datetime.datetime.now()

        while current_time <= end_datetime:
            # Only add the slot if it's in the future
            if current_time > now:
                slots.append(current_time.strftime("%H:%M"))
            current_time += datetime.timedelta(minutes=15)
        
        return slots
    except ValueError as e:
        logger.error(f"Error generating time slots: {e}")
        return []
    
class OrderBot:
    """
    Encapsulates all logic for the Telegram Order Bot.
    """
    # Define conversation states as class attributes for clarity
    (
        STATE_NAME,
        STATE_MENU_SELECTION,
        STATE_TIME_SELECTION,
        STATE_SCREENSHOT,
        STATE_SET_TIME_ENTRY,
        STATE_SET_ORDER_WINDOW_ENTRY
    ) = range(6)

    def __init__(self, token: str):
        """Initializes the bot with its token and admin ID."""
        self.token = token
        self.admin_chat_id = ADMIN_CHAT_ID
        self.admin_filter = filters.User(user_id=self.admin_chat_id)

        self.application = Application.builder().token(self.token).post_init(self._setup_bot_commands).build()
        self._setup_handlers()

    def _setup_handlers(self):
        """Creates and registers all handlers for the bot."""
        # Conversation handler for taking the order
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                self.STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_name)],
                self.STATE_MENU_SELECTION: [CallbackQueryHandler(self.menu_button_handler, pattern="^(add_|clear_cart|done_ordering)")],
                self.STATE_TIME_SELECTION: [CallbackQueryHandler(self.time_slot_handler, pattern="^slot_")], # <-- NEW HANDLER
                self.STATE_SCREENSHOT: [MessageHandler(filters.PHOTO, self.get_screenshot)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )

        # Handler for the admin's buttons
        approval_handler = CallbackQueryHandler(self.handle_approval, pattern="^(approve_|decline_)")
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(approval_handler)
        
        # --- (Handler for /set_time remains the same) ---
        set_time_handler = ConversationHandler(
            entry_points=[CommandHandler("set_time", self.start_set_time, filters=self.admin_filter)],
            states={
                self.STATE_SET_TIME_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_collection_time)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action)],
        )
        self.application.add_handler(set_time_handler)
        
        # --- 5. ADD NEW HANDLER for /set_order_window ---
        set_window_handler = ConversationHandler(
            entry_points=[CommandHandler("set_order_window", self.start_set_order_window, filters=self.admin_filter)],
            states={
                self.STATE_SET_ORDER_WINDOW_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_order_window)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action)],
        )
        self.application.add_handler(set_window_handler)
        
        # --- NEW: Handler for /orders ---
        self.application.add_handler(CommandHandler("orders", self.show_unfulfilled_orders, filters=self.admin_filter))

        # --- NEW: Handler for the "Mark Completed" button ---
        # This must only be triggered by the admin
        self.application.add_handler(CallbackQueryHandler(
            self.mark_completed_handler, 
            pattern="^complete_",
            # Note: We can't use self.admin_filter here directly,
            # but the /orders command that *generates* these
            # buttons is already admin-only, which provides security.
        ))
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
        await query.answer()  
        
        data = query.data
        cart = context.user_data.get('cart', {})
        
        if data.startswith("add_"):
            # A more robust way to get item_id, handling spaces/underscores
            item_id = data[len("add_"):] 
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
            # ... (this part is unchanged)
            context.user_data['cart'] = {}
            text, reply_markup, _ = build_menu_message({})
            await query.edit_message_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode=ParseMode.MARKDOWN
            )
            return self.STATE_MENU_SELECTION

        elif data == "done_ordering":
            # --- THIS IS THE NEW LOGIC ---
            # 1. Get the order window from bot data
            start_time = context.bot_data.get('order_window_start')
            end_time = context.bot_data.get('order_window_end')
            
            if not start_time or not end_time:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="Apologies, we are not accepting new orders at this time. Please try again later."
                )
                return ConversationHandler.END

            # 2. Generate time slots
            slots = generate_time_slots(start_time, end_time)
            
            if not slots:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"Sorry, all collection slots for today (between {start_time} and {end_time}) have passed. Please try again tomorrow."
                )
                return ConversationHandler.END
            
            # 3. Build keyboard for time slots
            keyboard = []
            # Create rows of 3 buttons
            row = []
            for slot in slots:
                row.append(InlineKeyboardButton(slot, callback_data=f"slot_{slot}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row: # Add any remaining buttons
                keyboard.append(row)
                
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 4. Store final order details (from your old code)
            order_details = ""
            total_price = 0
            for item_id, quantity in cart.items():
                item = MENU[item_id]
                order_details += f"{quantity}x {item['name']}\n"
                total_price += item['price'] * quantity
            
            context.user_data['order'] = order_details.strip()
            context.user_data['total'] = total_price

            # 5. Ask user to select a time
            await query.edit_message_text(
                "Great! Your order is confirmed.\n\n"
                "**Please select a collection time:**",
                reply_markup=reply_markup
            )
            
            # 6. Transition to the new time selection state
            return self.STATE_TIME_SELECTION

    async def time_slot_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the user pressing a time slot button."""
        query = update.callback_query
        await query.answer()
        
        selected_time = query.data[len("slot_"):] # e.g., "16:15"
        context.user_data['collection_time'] = selected_time
        
        # Now, retrieve the stored order info
        order_details = context.user_data.get('order', 'No order details')
        total_price = context.user_data.get('total', 0)
        
        # Build the final payment instructions
        payment_instructions = (
            f"Thank you! You have selected **{selected_time}** for collection.\n\n"
            f"Your final order is:\n{order_details}\n"
            f"**Total: ${total_price}**\n\n"
            "Please send the payment to:\n"
            "Paynow No.: 97929869\n"
            "Name: DamienFoo\n\n"
            "After paying, please send a screenshot of the transaction."
        )
        
        # Send payment instructions as a NEW message
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=payment_instructions,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Edit the time slot message to clean up
        await query.edit_message_text(
            f"Time confirmed: **{selected_time}**. \n\nPlease see the message above for payment instructions."
        )
        
        # Transition to the screenshot state
        return self.STATE_SCREENSHOT

    async def get_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Receives screenshot, forwards to admin."""
        customer_name = context.user_data.get('name', 'Unknown')
        order_details = context.user_data.get('order', 'No order details')
        total_price = context.user_data.get('total', 0)
        collection_time = context.user_data.get('collection_time', 'Not specified') # <-- NEW
        user_id = update.message.from_user.id
        
        await update.message.reply_text(
            "Thank you! We have received your screenshot.\n"
            "We will verify your payment and send a confirmation message shortly."
        )
        
        # Add collection_time to the admin caption
        admin_caption = (
            f"New Order for Verification\n\n"
            f"User Name: {customer_name}\n"
            f"User ID: {user_id}\n"
            f"**Collection Time: {collection_time}**\n" # <-- NEW
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

        await context.bot.send_photo(
            chat_id=self.admin_chat_id,
            photo=update.message.photo[-1].file_id,
            caption=admin_caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Store collection_time for the logger
        context.bot_data[f"order_for_{user_id}"] = {
            'name': customer_name,
            'order': order_details,
            'total': total_price,
            'collection_time': collection_time # <-- NEW
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
        user_id = int(user_id_str) 
        
        order_data_key = f"order_for_{user_id}"
        order_data = context.bot_data.pop(order_data_key, None)
        
        if not order_data:
            await query.edit_message_text(text="Error: Order data not found (maybe already processed).")
            return

        customer_name = order_data['name']
        order_details = order_data['order']
        total_price = order_data.get('total', 0)
        collection_time = order_data.get('collection_time', 'Not specified') # <-- NEW

        if action == "approve":
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Payment Verified! Your order is confirmed and is now being processed. Thank you!"
            )
            # Add collection time to the admin's approved message
            await query.edit_message_caption(
                caption=(
                    f"✅ APPROVED\n\n"
                    f"Name: {customer_name}\n"
                    f"Time: {collection_time}\n" # <-- NEW
                    f"Total: ${total_price}\n"
                    f"Order:\n{order_details}\n\n"
                    f"User has been notified."
                ),
                parse_mode=ParseMode.MARKDOWN
            )
            
            # --- UPDATE LOG_ORDER CALL ---
            log_order(
                user_id=user_id,
                user_name=customer_name,
                order_details=order_details,
                total_price=total_price,
                collection_time=collection_time # <-- NEW
            )
            
        elif action == "decline":
            # ... (this part is unchanged)
            await context.bot.send_message(
                chat_id=user_id,
                text="Payment Issue. There was an issue with your payment. Please contact @DamienFxx."
            )
            await query.edit_message_caption(
                caption=f"DECLINED\n\nName: {customer_name}\nTotal: ${total_price}\nOrder:\n{order_details}\n\nUser has been notified.",
                parse_mode=ParseMode.MARKDOWN
            )

    async def _setup_bot_commands(self, application: Application):
        """Sets the bot's commands for default users and the admin."""
        
        # --- 1. Define commands for regular users ---
        user_commands = [
            BotCommand("start", "Start a new order"),
            BotCommand("cancel", "Cancel your current order"),
        ]
        
        # --- 2. Set default commands for all users ---
        await application.bot.set_my_commands(
            user_commands, 
            scope=BotCommandScopeDefault()
        )
        
        # --- 3. Define commands for the admin (includes all user commands) ---
        admin_commands = user_commands + [
            BotCommand("orders", "View unfulfilled orders"),
            BotCommand("set_time", "Set the 'order ready' message"),
            BotCommand("set_order_window", "Set 15-min collection slots (e.g., 16:00-18:00)"),
        ]
        
        # --- 4. Set special commands just for your chat ---
        await application.bot.set_my_commands(
            admin_commands, 
            scope=BotCommandScopeChat(chat_id=self.admin_chat_id)
        )
        logger.info("Custom bot commands set for users and admin.")

    async def start_set_order_window(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Asks the admin to enter the order window."""
        await update.message.reply_text(
            "Please enter the new order window in 24H format (e.g., 16:00-18:00)\n"
            "This will generate 15-min slots for users.\n\n"
            "Or /cancel to stop."
        )
        return self.STATE_SET_ORDER_WINDOW_ENTRY

    async def receive_order_window(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Saves the new order window start and end times."""
        try:
            time_range = update.message.text
            start_str, end_str = time_range.split('-')
            
            # Validate the format
            datetime.datetime.strptime(start_str.strip(), "%H:%M")
            datetime.datetime.strptime(end_str.strip(), "%H:%M")
            
            context.bot_data['order_window_start'] = start_str.strip()
            context.bot_data['order_window_end'] = end_str.strip()
            
            await update.message.reply_text(
                f"✅ Order window updated. Users can now select slots between {start_str} and {end_str}."
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Failed to parse order window: {e}")
            await update.message.reply_text(
                "Invalid format. Please use HH:MM-HH:MM (e.g., 16:00-18:00).\n"
                "Please try again or send /cancel."
            )
            return self.STATE_SET_ORDER_WINDOW_ENTRY # Ask again
        

    async def start_set_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Asks the admin to enter the collection time."""
        await update.message.reply_text(
            "Please enter the new collection time text.\n"
            "Example: 'Today between 4 PM and 6 PM'\n\nOr /cancel to stop."
        )
        return self.STATE_SET_TIME_ENTRY

    async def receive_collection_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Saves the new collection time to the bot's memory."""
        collection_time = update.message.text
        context.bot_data['collection_time'] = collection_time

        await update.message.reply_text(
            f"✅ Collection time updated to:\n{collection_time}"
        )
        return ConversationHandler.END

    async def cancel_admin_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels an admin-only conversation."""
        await update.message.reply_text("Admin action cancelled.")
        return ConversationHandler.END

    async def show_unfulfilled_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows the admin a list of all 'approved' orders."""
        orders = get_unfulfilled_orders() # This now returns collection_time

        if not orders:
            await update.message.reply_text("There are no unfulfilled orders.")
            return

        await update.message.reply_text("--- 🔔 Unfulfilled Orders ---")

        # Send each order as a separate message with its own button
        for (order_id, user_name, order_details, collection_time) in orders:
            time_str = collection_time or "Not specified" # Handle missing time
            text = (
                f"**Order ID: {order_id}**\n"
                f"Name: {user_name}\n"
                f"**Time: {time_str}**\n" # <-- NEW
                f"Items:\n{order_details}"
            )

            keyboard = [[
                InlineKeyboardButton(
                    "✅ Mark Completed", 
                    callback_data=f"complete_{order_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def mark_completed_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the admin's 'Mark Completed' button press."""
        query = update.callback_query

        # Check if the person clicking is the admin
        if query.from_user.id != self.admin_chat_id:
            await query.answer("This is an admin-only button.", show_alert=True)
            return

        await query.answer("Processing...")

        try:
            order_id = int(query.data.split("_")[1])
        except (ValueError, IndexError):
            await query.edit_message_text("Error: Invalid order ID in callback.")
            return

        # 1. Get the customer's user_id from the DB
        user_id_to_notify = get_order_user_id(order_id)

        if user_id_to_notify:
            # 2. Mark as completed in the DB
            success = mark_order_completed(order_id)

            if success:
                # 3. Get the collection time
                collection_time = context.bot_data.get(
                    'collection_time', 
                    'Ready for collection now. Please check with us for timing.'
                )

                # 4. Notify the user
                try:
                    await context.bot.send_message(
                        chat_id=user_id_to_notify,
                        text=(
                            "🎉 Your order is ready for collection!\n\n"
                            f"**Collection Info:**\n{collection_time}"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Failed to send 'order ready' message to user {user_id_to_notify}: {e}")
                    # Don't stop, the admin still needs confirmation

                # 5. Update the admin's message
                original_text = query.message.text
                await query.edit_message_text(
                    f"✅ **COMPLETED**\n{original_text}\n\nUser has been notified.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text(f"Error: Failed to update order {order_id} in database.")
        else:
            await query.edit_message_text(f"Error: Could not find user for order {order_id}.")
    # --- Public Run Method ---

    def run(self):
        """Runs the bot."""
        logger.info("Bot is running...")
        self.application.run_polling()