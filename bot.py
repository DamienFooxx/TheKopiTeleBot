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
    get_order_info_for_notify,
    mark_order_completed,
    DATABASE_FILE
)
from menu_builder import build_menu_message
from config import ADMIN_CHAT_ID, MENU

# Setup logger
logger = logging.getLogger(__name__)

def generate_time_slots(start_time_str: str, end_time_str: str) -> list[str]:
    """Generates 15-minute time slots strictly in the future (SG Time)."""
    slots = []
    try:
        # 1. Define Singapore Timezone (UTC+8)
        sg_tz = datetime.timezone(datetime.timedelta(hours=8))
        
        # 2. Get current time in SG
        now_sg = datetime.datetime.now(sg_tz)
        current_date = now_sg.date() # Important: Use SG date, not server date

        start_time = datetime.datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.datetime.strptime(end_time_str, "%H:%M").time()
        
        # 3. Create timezone-aware datetimes for comparison
        current_slot = datetime.datetime.combine(current_date, start_time).replace(tzinfo=sg_tz)
        end_datetime = datetime.datetime.combine(current_date, end_time).replace(tzinfo=sg_tz)
        
        while current_slot <= end_datetime:
            # STRICT CHECK: Compare SG time vs SG time
            if current_slot > now_sg:
                slots.append(current_slot.strftime("%H:%M"))
            
            current_slot += datetime.timedelta(minutes=15)
        
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
        STATE_SET_ORDER_WINDOW_ENTRY
    ) = range(5)

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
            allow_reentry=True,          # Allows /start to reset the conversation at any point
            conversation_timeout=3600,   # 1 hour timeout
        )

        # Handler for the admin's buttons
        approval_handler = CallbackQueryHandler(self.handle_approval, pattern="^(approve_|decline_)")
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(approval_handler)
        self.application.add_handler(CommandHandler("export_db", self.export_database, filters=self.admin_filter))
        
        # --- 5. ADD NEW HANDLER for /set_order_window ---
        set_window_handler = ConversationHandler(
            entry_points=[CommandHandler("set_order_window", self.start_set_order_window, filters=self.admin_filter)],
            states={
                self.STATE_SET_ORDER_WINDOW_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_order_window)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action)],
            allow_reentry=True,
        )
        self.application.add_handler(set_window_handler)
        
        # --- NEW: Handler for /orders ---
        self.application.add_handler(CommandHandler("orders", self.show_unfulfilled_orders, filters=self.admin_filter))

        # --- NEW: Handler for the "Mark Completed" button ---
        # This must only be triggered by the admin
        self.application.add_handler(CallbackQueryHandler(
            self.mark_completed_handler, 
            pattern="^complete_",
        ))

        # --- NEW: Handler for the "Silent Complete" button ---
        self.application.add_handler(CallbackQueryHandler(
            self.silent_complete_handler, 
            pattern="^silent_",
        ))
    # --- Conversation Handler Methods ---

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation, shows available time ranges (SG Time)."""
        
        windows = context.bot_data.get('order_windows')
        
        if not windows:
            start_t = context.bot_data.get('order_window_start')
            end_t = context.bot_data.get('order_window_end')
            if start_t and end_t:
                windows = [(start_t, end_t)]
        
        if not windows:
            msg_text = "Hello! We haven't configured our collection times for today yet.\n\nCan we get your name?"
        else:
            valid_ranges = []
            
            # 1. Define SG Time
            sg_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_sg = datetime.datetime.now(sg_tz)
            
            for start_str, end_str in windows:
                try:
                    end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
                    
                    # 2. Make end time aware (SG)
                    end_dt = datetime.datetime.combine(now_sg.date(), end_time).replace(tzinfo=sg_tz)
                    
                    # 3. Compare
                    if end_dt > now_sg:
                        valid_ranges.append(f"{start_str} to {end_str}")
                except ValueError:
                    continue
            
            if not valid_ranges:
                msg_text = "Hello! All collection windows for today have ended.\n\nCan we get your name?"
            else:
                ranges_text = ",\n".join(valid_ranges)
                msg_text = (
                    f"Hello! Today our collection time is from\n"
                    f"**{ranges_text}**,\n\n"
                    f"Can we get your name?"
                )

        await update.message.reply_text(msg_text, parse_mode=ParseMode.MARKDOWN)
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
            # --- UPDATED LOGIC FOR MULTIPLE WINDOWS ---
            # 1. Get the order windows (list of tuples)
            windows = context.bot_data.get('order_windows')
            
            # Backward compatibility: check if old single variables exist if list doesn't
            if not windows:
                start = context.bot_data.get('order_window_start')
                end = context.bot_data.get('order_window_end')
                if start and end:
                    windows = [(start, end)]

            if not windows:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="Apologies, we are not accepting new orders at this time (No time slots configured)."
                )
                return ConversationHandler.END

            # 2. Generate time slots for ALL windows
            all_slots = []
            for start_time, end_time in windows:
                # Use existing helper function
                slots = generate_time_slots(start_time, end_time) 
                all_slots.extend(slots)
            
            # Remove duplicates (if ranges overlap) and sort them
            all_slots = sorted(list(set(all_slots)))
            
            if not all_slots:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="Sorry, all collection slots for today have passed. Please try again tomorrow."
                )
                return ConversationHandler.END
            
            # 3. Build keyboard for time slots
            keyboard = []
            row = []
            for slot in all_slots:
                row.append(InlineKeyboardButton(slot, callback_data=f"slot_{slot}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row: 
                keyboard.append(row)
                
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 4. Store final order details (unchanged)
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
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            return self.STATE_TIME_SELECTION

    async def time_slot_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the user pressing a time slot button with VALIDATION."""
        query = update.callback_query
        
        selected_time_str = query.data[len("slot_"):] # e.g., "16:15"
        # --- VALIDATION: Check if this time has passed (SG Time) ---
        # 1. Define SG Time
        sg_tz = datetime.timezone(datetime.timedelta(hours=8))
        now_sg = datetime.datetime.now(sg_tz)

        try:
            selected_time = datetime.datetime.strptime(selected_time_str, "%H:%M").time()
            
            # 2. Make selected time aware (assigned to SG zone)
            selected_dt = datetime.datetime.combine(now_sg.date(), selected_time).replace(tzinfo=sg_tz)
            
            # 3. Compare
            if selected_dt <= now_sg:
                await query.answer("⚠️ This time slot has passed! Refreshing...", show_alert=True)
                
                # --- REGENERATE SLOTS (Standard logic) ---
                windows = context.bot_data.get('order_windows', [])
                if not windows:
                    start = context.bot_data.get('order_window_start')
                    end = context.bot_data.get('order_window_end')
                    if start and end: windows = [(start, end)]
                
                all_slots = []
                for s, e in windows:
                    all_slots.extend(generate_time_slots(s, e)) # This now uses the new SG-aware function
                
                all_slots = sorted(list(set(all_slots)))
                
                if not all_slots:
                    await query.edit_message_text("Sorry, all collection slots have passed for today.")
                    return ConversationHandler.END

                keyboard = []
                row = []
                for slot in all_slots:
                    row.append(InlineKeyboardButton(slot, callback_data=f"slot_{slot}"))
                    if len(row) == 3:
                        keyboard.append(row)
                        row = []
                if row: keyboard.append(row)
                
                await query.edit_message_text(
                    "⚠️ **That slot just passed.**\n\nPlease select a new time:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
                return self.STATE_TIME_SELECTION
                
        except ValueError:
            logger.error("Error parsing selected time slot.")
            await query.answer("Error validating time.", show_alert=True)
            return self.STATE_TIME_SELECTION

        # --- IF VALID, PROCEED AS NORMAL ---
        await query.answer()
        context.user_data['collection_time'] = selected_time_str
        
        # Retrieve order info
        order_details = context.user_data.get('order', 'No order details')
        total_price = context.user_data.get('total', 0)
        
        payment_instructions = (
            f"Thank you! You have selected **{selected_time_str}** for collection.\n\n"
            f"Your final order is:\n{order_details}\n"
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
            BotCommand("set_order_window", "Set 15-min collection slots (e.g., 16:00-18:00)"),
            BotCommand("export_db", "📥 Download Database File"), # <-- Add this
        ]
        
        # --- 4. Set special commands just for your chat ---
        await application.bot.set_my_commands(
            admin_commands, 
            scope=BotCommandScopeChat(chat_id=self.admin_chat_id)
        )
        logger.info("Custom bot commands set for users and admin.")
    
    # --- NEW Admin Methods for /set_order_window ---
    async def start_set_order_window(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Asks the admin to enter the order window."""
        await update.message.reply_text(
            "Please enter the order windows in 24H format, separated by commas.\n"
            "Example: 10:00-13:00, 15:00-18:00\n\n"
            "Or /cancel to stop."
        )
        return self.STATE_SET_ORDER_WINDOW_ENTRY

    async def receive_order_window(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Saves the new order windows."""
        try:
            text = update.message.text
            # Split by comma to get multiple ranges
            ranges_raw = text.split(',')
            valid_ranges = []

            for r in ranges_raw:
                # Clean up whitespace
                r = r.strip()
                start_str, end_str = r.split('-')
                
                # Validate the format for both times
                datetime.datetime.strptime(start_str.strip(), "%H:%M")
                datetime.datetime.strptime(end_str.strip(), "%H:%M")
                
                valid_ranges.append((start_str.strip(), end_str.strip()))
            
            # Store the list of ranges
            context.bot_data['order_windows'] = valid_ranges
            
            # Create a readable confirmation string
            readable_ranges = ", ".join([f"{s}-{e}" for s, e in valid_ranges])
            
            await update.message.reply_text(
                f"✅ Order windows updated.\nUsers can now select slots between:\n{readable_ranges}"
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Failed to parse order window: {e}")
            await update.message.reply_text(
                "Invalid format. Please use HH:MM-HH:MM, separated by commas.\n"
                "Example: 10:00-13:00, 16:00-18:00\n"
                "Please try again or send /cancel."
            )
            return self.STATE_SET_ORDER_WINDOW_ENTRY
        

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

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ Notify & Complete", 
                        callback_data=f"complete_{order_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔕 Silent Complete (No Msg)", 
                        callback_data=f"silent_{order_id}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def mark_completed_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the admin's 'Mark Completed' button press."""
        query = update.callback_query

        if query.from_user.id != self.admin_chat_id:
            await query.answer("This is an admin-only button.", show_alert=True)
            return

        await query.answer("Processing...")

        try:
            order_id = int(query.data.split("_")[1])
        except (ValueError, IndexError):
            await query.edit_message_text("Error: Invalid order ID in callback.")
            return

        # 1. Get the customer's user_id AND their selected time
        order_info = get_order_info_for_notify(order_id) # <-- Use new function

        if order_info:
            user_id_to_notify, user_collection_time = order_info # <-- Unpack both values
            
            # 2. Mark as completed in the DB
            success = mark_order_completed(order_id)

            if success:
                # --- UPDATED LOGIC ---
                if user_collection_time:
                    collection_message = f"Your selected time: **{user_collection_time}**\nCollect at 08-12 Suite!"
                else:
                    # Simple default fallback if no time was found in DB
                    collection_message = "Ready for collection! Please head to 08-12 Suite."

                # 4. Notify the user
                try:
                    await context.bot.send_message(
                        chat_id=user_id_to_notify,
                        text=(
                            "🎉 Your order is ready for collection!\n\n"
                            f"**Collection Info:**\n{collection_message}"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Failed to send 'order ready' message: {e}")

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

    async def silent_complete_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the admin's 'Silent Complete' button press.
        Marks the order as completed in the DB but DOES NOT send a message to the user.
        """
        query = update.callback_query

        # Security check
        if query.from_user.id != self.admin_chat_id:
            await query.answer("This is an admin-only button.", show_alert=True)
            return

        await query.answer("Silently completing...")

        try:
            order_id = int(query.data.split("_")[1])
        except (ValueError, IndexError):
            await query.edit_message_text("Error: Invalid order ID in callback.")
            return

        # 1. Mark as completed in the DB (so it vanishes from the list)
        success = mark_order_completed(order_id)

        if success:
            # 2. Update the admin's message to show it's done
            original_text = query.message.text
            
            # We strip the buttons and add a note
            await query.edit_message_text(
                f"🔕 **SILENTLY COMPLETED**\n{original_text}\n\n(User was NOT notified)",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text(f"Error: Failed to update order {order_id} in database.")

    async def export_database(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Sends the current SQLite database file to the admin."""
        try:
            await update.message.reply_document(
                document=open(DATABASE_FILE, 'rb'),
                filename="orders.db",
                caption=f"📂 Here is your database backup.\nTime: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
        except Exception as e:
            logger.error(f"Failed to export database: {e}")
            await update.message.reply_text("❌ Failed to export database file.")
    # --- Public Run Method ---

    def run(self):
        """Runs the bot."""
        logger.info("Bot is running...")
        self.application.run_polling()