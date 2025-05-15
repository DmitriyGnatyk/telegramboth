import logging
import re
import json
import os
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, ContextTypes,
    CommandHandler, CallbackQueryHandler, ConversationHandler
    )

TOKEN = '8199311639:AAEqfXh9dX8MYyNy0cuDE-RrMKRHfAtfeUY'

app = Flask(__name__)

@app.route('/')
def home():
    return 'Бот працює!'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = 'data.json'

# Структура збереження даних: {chat_id: { 'filters': {word_to_replace: replacement}, 'admin_ids': set() } }
groups_data = {}
user_states = {}

# --- Функції збереження/завантаження ---
def save_data():
    # При збереженні множини перетворюємо у списки, бо JSON не підтримує set
    to_save = {}
    for chat_id, data in groups_data.items():
        to_save[chat_id] = {
            'filters': data.get('filters', {}),
            'admin_ids': list(data.get('admin_ids', set()))
        }
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

def load_data():
    global groups_data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            groups_data_loaded = json.load(f)
            # Повертаємо множини
            for chat_id, data in groups_data_loaded.items():
                data['admin_ids'] = set(data.get('admin_ids', []))
            groups_data = groups_data_loaded
    else:
        groups_data = {}

# Стани для ConversationHandler
(
    CHOOSING_ACTION,
    ADD_FILTER_ASK_WORD,
    ADD_FILTER_ASK_REPLACEMENT,
) = range(3)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("Мої групи", callback_data="my_groups")],
        [InlineKeyboardButton("Фільтр слів", callback_data="filter_words")]
    ]
    await update.message.reply_text(
        "Ви в головному меню, виберіть дію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "my_groups":
        groups = [str(chat_id) for chat_id, data in groups_data.items() if user_id in data.get('admin_ids', set())]
        if not groups:
            await query.edit_message_text("У вас немає груп, де ви додали бота.")
        else:
            text = "Ваші групи:\n" + "\n".join(groups)
            await query.edit_message_text(text)

    elif query.data == "filter_words":
        keyboard = [
            [InlineKeyboardButton("Додати фільтр", callback_data="add_filter")],
            [InlineKeyboardButton("Всі фільтри", callback_data="list_filters")],
            [InlineKeyboardButton("Повернутись у меню", callback_data="back_main")]
        ]
        await query.edit_message_text(
            "Привіт, виберіть дію:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "back_main":
        keyboard = [
            [InlineKeyboardButton("Мої групи", callback_data="my_groups")],
            [InlineKeyboardButton("Фільтр слів", callback_data="filter_words")]
        ]
        await query.edit_message_text(
            "Ви в головному меню, виберіть дію:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "add_filter":
        await query.edit_message_text("Введіть слово, яке хочете замінити:")
        user_states[user_id] = {'action': 'add_filter'}
        return ADD_FILTER_ASK_WORD

    elif query.data == "list_filters":
        user_filters = []
        for chat_id, data in groups_data.items():
            if user_id in data.get('admin_ids', set()):
                for k, v in data.get('filters', {}).items():
                    user_filters.append(f"{k} -> {v} (група {chat_id})")

        if not user_filters:
            await query.edit_message_text("Фільтрів немає.")
        else:
            buttons = []
            for f in user_filters:
                parts = f.split()
                group_id = parts[-1].strip("група ")
                word = parts[0]
                buttons.append([InlineKeyboardButton(f, callback_data=f"delfilter:{group_id}:{word}")])
            buttons.append([InlineKeyboardButton("Повернутись", callback_data="filter_words")])
            await query.edit_message_text(
                "Ваші фільтри (натисніть щоб видалити):",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
    elif query.data.startswith("delfilter:"):
        _, chat_id_str, word = query.data.split(":")
        chat_id = int(chat_id_str)
        if chat_id in groups_data and 'filters' in groups_data[chat_id]:
            if word in groups_data[chat_id]['filters']:
                del groups_data[chat_id]['filters'][word]
                save_data()  # Зберігаємо зміни
                await query.answer(f"Фільтр '{word}' видалено", show_alert=True)
            else:
                await query.answer("Фільтр не знайдено", show_alert=True)
        else:
            await query.answer("Група або фільтр не знайдено", show_alert=True)

        # Оновлюємо список після видалення
        await button_handler(update, context)  # повторний виклик з list_filters

    return ConversationHandler.END


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id in user_states and user_states[user_id].get('action') == 'add_filter':
        state = user_states[user_id]
        if 'word_to_replace' not in state:
            state['word_to_replace'] = text.lower()
            await update.message.reply_text("Тепер введіть слово, на яке замінювати:")
            return ADD_FILTER_ASK_REPLACEMENT
        else:
            replacement = text
            word = state['word_to_replace']
            added_to_groups = []
            for chat_id, data in groups_data.items():
                if user_id in data.get('admin_ids', set()):
                    data.setdefault('filters', {})[word] = replacement
                    added_to_groups.append(str(chat_id))
            save_data()  # Зберігаємо після додавання фільтра
            await update.message.reply_text(f"Фільтр '{word}' -> '{replacement}' додано в групи: {', '.join(added_to_groups)}")
            user_states.pop(user_id)
            keyboard = [
                [InlineKeyboardButton("Додати фільтр", callback_data="add_filter")],
                [InlineKeyboardButton("Всі фільтри", callback_data="list_filters")],
                [InlineKeyboardButton("Повернутись у меню", callback_data="back_main")]
            ]
            await update.message.reply_text(
                "Привіт, виберіть дію:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END

    return


async def echo_and_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.is_bot:
        return

    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    user_id = update.effective_user.id

    if chat_id not in groups_data:
        groups_data[chat_id] = {'filters': {}, 'admin_ids': set()}
    groups_data[chat_id]['admin_ids'].add(user_id)
    save_data()  # Зберігаємо після додавання адміністраторів

    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(f"Не вдалося видалити повідомлення: {e}")

    msg = update.message
    text = msg.text or ""

    for word, replacement in groups_data[chat_id].get('filters', {}).items():
        text = re.sub(re.escape(word), replacement, text, flags=re.IGNORECASE)
    try:
        if msg.text:
            await context.bot.send_message(chat_id, text, entities=msg.entities)
        elif msg.photo:
            photo = msg.photo[-1]
            await context.bot.send_photo(chat_id, photo.file_id, caption=msg.caption)
        elif msg.sticker:
            await context.bot.send_sticker(chat_id, msg.sticker.file_id)
        elif msg.document:
            await context.bot.send_document(chat_id, msg.document.file_id, caption=msg.caption)
        elif msg.video:
            await context.bot.send_video(chat_id, msg.video.file_id, caption=msg.caption)
        elif msg.voice:
            await context.bot.send_voice(chat_id, msg.voice.file_id, caption=msg.caption)
        elif msg.audio:
            await context.bot.send_audio(chat_id, msg.audio.file_id, caption=msg.caption)
    except Exception as e:
        logger.warning(f"Не вдалося відправити копію повідомлення: {e}")


def main():
    load_data()  # Завантажуємо дані при старті бота

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^(filter_words|add_filter|list_filters|back_main)$')],
        states={
            ADD_FILTER_ASK_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
            ADD_FILTER_ASK_REPLACEMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern='^back_main$')]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, echo_and_delete))

    app.run_polling()


if __name__ == '__main__':
    threading.Thread(target=start_bot).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
