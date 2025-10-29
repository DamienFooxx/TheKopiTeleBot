# menu_builder.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import MENU  # Import the menu from our config file

def build_menu_message(cart: dict) -> (str, InlineKeyboardMarkup, float):
    """
    Builds the text, buttons, and calculates the total for the menu message.
    """
    text = "Here's our menu. Click items to add them to your cart:\nIf you are ordering multiple items, please enter the according number of sugar and cups needed as well!\n\n"
    text += "--- **YOUR CART** ---\n"
    
    total_price = 0
    
    if not cart:
        text += "Your cart is empty.\n"
    else:
        # List items in cart
        for item_id, quantity in cart.items():
            if item_id in MENU:
                item = MENU[item_id]
                item_total = item['price'] * quantity
                text += f"{quantity}x {item['name']} = ${item_total}\n"
                total_price += item_total
            
    text += f"\n**Total: ${total_price}**\n"
    text += "-------------------"
    
    # Create the buttons
    keyboard = []
    
    # Add a button for each menu item
    for item_id, item_data in MENU.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{item_data['name']} (${item_data['price']})", 
                callback_data=f"add_{item_id}"  # e.g., "add_burger"
            )
        ])
    
    # Add control buttons
    control_buttons = []
    if cart:  # Only show Clear Cart if cart is not empty
        control_buttons.append(
            InlineKeyboardButton("🛒 Clear Cart", callback_data="clear_cart")
        )
        
    # Only show "Done" if the cart has items
    if cart:
        control_buttons.append(
            InlineKeyboardButton("✅ Done Ordering", callback_data="done_ordering")
        )
    keyboard.append(control_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return text, reply_markup, total_price