import asyncio
import logging
from datetime import datetime, timedelta
from functools import wraps
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os
import sqlite3
import matplotlib.pyplot as plt
import io
import shutil
import re
from dotenv import load_dotenv

# Завантаження змінних середовища
load_dotenv()

log_filename = 'bot.log'
# Налаштування логування
logger = logging.getLogger("bot")
hdlr = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
hdlr.setFormatter(logging.Formatter("%(asctime)s %(funcName)s %(levelname)s %(message)s"))
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)

# Ініціалізація бота та диспетчера
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Ініціалізація планувальника
scheduler = AsyncIOScheduler()

# Шляхи до файлів даних
DB_FILE = 'bot_data.db'

# ID суперадміністратора
SUPERADMIN_ID = int(os.getenv("SUPERADMIN_ID"))


# Ініціалізація бази даних
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS channels
                 (id INTEGER PRIMARY KEY, channel_id INTEGER, expiry_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS filters
                 (id INTEGER PRIMARY KEY, channel_id INTEGER, filter_type TEXT, filter_value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins
                 (user_id INTEGER PRIMARY KEY, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS main_channels
                 (channel_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS spam_settings
                 (id INTEGER PRIMARY KEY, max_messages INTEGER, time_window INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analytics
                 (date TEXT, action TEXT, count INTEGER, UNIQUE(date,action))''')
    conn.commit()
    conn.close()

init_db()

# Функції для роботи з базою даних
def execute_db(query, params=()):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    result = c.fetchall()
    conn.close()
    return result

def get_channels():
    channels = execute_db("SELECT * FROM channels")
    return {channel[1]: {'id': channel[0], 'expiry_date': channel[2]} for channel in channels}

def get_filters():
    filters = execute_db("SELECT * FROM filters")
    return filters

def get_admins():
    admins = execute_db("SELECT * FROM admins")
    admin_dict = {str(admin[0]): admin[1] for admin in admins}
    if str(SUPERADMIN_ID) not in admin_dict:
        execute_db("INSERT OR REPLACE INTO admins (user_id, role) VALUES (?, ?)", (SUPERADMIN_ID, 'superadmin'))
        admin_dict[str(SUPERADMIN_ID)] = 'superadmin'
    return admin_dict

def get_main_channels():
    main_channels = execute_db("SELECT * FROM main_channels")
    return {str(channel[0]): True for channel in main_channels}

def get_spam_settings():
    settings = execute_db("SELECT * FROM spam_settings")
    return settings[0] if settings else None

# Декоратори для перевірки прав доступу
def admin_required(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = message.from_user.id
        admins = get_admins()
        if str(user_id) not in admins:
            await message.reply("У вас немає прав для виконання цієї команди.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

def superadmin_required(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id != SUPERADMIN_ID:
            await message.reply("Ця команда доступна тільки для суперадміністратора.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

# Функції для роботи з каналами та фільтрами
def add_channel(channel_id, days):
    expiry_date = (datetime.now() + timedelta(days=days)).isoformat()
    execute_db("INSERT INTO channels (channel_id, expiry_date) VALUES (?, ?)", (channel_id, expiry_date))

def remove_channel(channel_id):
    execute_db("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    execute_db("DELETE FROM filters WHERE channel_id = ?", (channel_id,))

def add_filter(channel_id, filter_type, filter_value):
    execute_db("INSERT INTO filters (channel_id, filter_type, filter_value) VALUES (?, ?, ?)",
               (channel_id, filter_type, filter_value))

def remove_filter(filter_id):
    execute_db("DELETE FROM filters WHERE id = ?", (filter_id,))

# Функції для роботи з адміністраторами
def add_admin(user_id, role='admin'):
    execute_db("INSERT OR REPLACE INTO admins (user_id, role) VALUES (?, ?)", (user_id, role))

# Функції для роботи з основними каналами
def add_main_channel(channel_id):
    execute_db("INSERT OR REPLACE INTO main_channels (channel_id) VALUES (?)", (channel_id,))

def remove_main_channel(channel_id):
    execute_db("DELETE FROM main_channels WHERE channel_id = ?", (channel_id,))

# Функції для роботи з налаштуваннями спаму
def set_spam_settings(max_messages, time_window):
    execute_db("INSERT OR REPLACE INTO spam_settings (id, max_messages, time_window) VALUES (1, ?, ?)",
               (max_messages, time_window))

def is_spam(user_id):
    # Реалізуйте логіку перевірки спаму
    return False

# Функції для роботи з аналітикою
def log_action(action):
    date = datetime.now().strftime('%Y-%m-%d')
    execute_db("INSERT INTO analytics (date, action, count) VALUES (?, ?, 1) ON CONFLICT(date, action) DO UPDATE SET count = count + 1",
               (date, action))

def get_analytics():
    return execute_db("SELECT * FROM analytics ORDER BY date DESC LIMIT 30")

# Створення клавіатури з кнопками
def get_admin_keyboard() -> ReplyKeyboardMarkup:
    keyboard = []
    keyboard.append([KeyboardButton(text="📊 Список каналів")])
    keyboard.append([KeyboardButton(text="➕ Додати канал"), KeyboardButton(text="➖ Видалити канал")])
    keyboard.append([KeyboardButton(text="🏷 Додати фільтр"), KeyboardButton(text="🗑 Видалити фільтр")])
    keyboard.append([KeyboardButton(text="👥 Список адміністраторів")])
    keyboard.append([KeyboardButton(text="📈 Аналітика")])
    keyboard.append([KeyboardButton(text="📋 Допомога")])
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True)

# Команди бота
@dp.message(Command("start"))
@admin_required
async def start(message: types.Message):
    keyboard = get_admin_keyboard()
    await message.reply("Вітаю! Я бот для пересилання повідомлень. Використовуйте кнопки нижче для керування.", reply_markup=keyboard)
    log_action("start")

@dp.message(Command("help"))
@admin_required
async def help_command(message: types.Message):
    help_text = """
    Доступні команди:
    /start - Запустити бота
    /help - Показати це повідомлення
    /add_channel channel_id days - Додати новий канал
    /remove_channel channel_id - Видалити канал
    /list_channels - Показати список активних каналів
    /add_filter channel_id filter_type filter_value - Додати фільтр до каналу
    /remove_filter filter_id - Видалити фільтр
    /list_filters - Показати список фільтрів
    /set_admin user_id role - Встановити адміністратора (тільки для суперадміна)
    /list_admins - Показати список адміністраторів
    /add_main_channel channel_id - Додати основний канал (тільки для суперадміна)
    /remove_main_channel channel_id - Видалити основний канал (тільки для суперадміна)
    /list_main_channels - Показати список основних каналів
    /set_spam_settings max_messages time_window - Встановити налаштування захисту від спаму (тільки для суперадміна)
    /get_spam_settings - Показати поточні налаштування захисту від спаму
    /get_logs - Отримати файл логів (тільки для суперадміна)
    /analytics - Показати аналітику використання бота
    """
    await message.reply(help_text)
    log_action("help")

@dp.message(lambda message: message.text == "📊 Список каналів")
@admin_required
async def list_channels_button(message: types.Message):
    channels = get_channels()
    if channels:
        channel_list = "\n".join([f"{channel_id}: до {info['expiry_date']}" for channel_id, info in channels.items()])
        await message.reply(f"Список активних каналів:\n{channel_list}")
    else:
        await message.reply("Список активних каналів порожній.")
    log_action("list_channels")

@dp.message(lambda message: message.text == "➕ Додати канал")
@admin_required
async def add_channel_button(message: types.Message):
    await message.reply("Для додавання каналу використовуйте команду:\n/add_channel channel_id days")

@dp.message(lambda message: message.text == "➖ Видалити канал")
@admin_required
async def remove_channel_button(message: types.Message):
    await message.reply("Для видалення каналу використовуйте команду:\n/remove_channel channel_id")

@dp.message(lambda message: message.text == "🏷 Додати фільтр")
@admin_required
async def add_filter_button(message: types.Message):
    await message.reply("Для додавання фільтру використовуйте команду:\n/add_filter channel_id filter_type filter_value (filter_type = tag, word, phrase, combination)")

@dp.message(lambda message: message.text == "🗑 Видалити фільтр")
@admin_required
async def remove_filter_button(message: types.Message):
    await message.reply("Для видалення фільтру використовуйте команду:\n/remove_filter filter_id")

@dp.message(lambda message: message.text == "👥 Список адміністраторів")
@admin_required
async def list_admins_button(message: types.Message):
    admins = get_admins()
    if admins:
        admin_list = "\n".join([f"{user_id}: {role}" for user_id, role in admins.items()])
        await message.reply(f"Список адміністраторів:\n{admin_list}")
    else:
        await message.reply("Список адміністраторів порожній.")
    log_action("list_admins")

@dp.message(lambda message: message.text == "📈 Аналітика")
@admin_required
async def analytics_button(message: types.Message):
    await analytics_command(message)

@dp.message(lambda message: message.text == "📋 Допомога")
@admin_required
async def help_button(message: types.Message):
    await help_command(message)

@dp.message(Command("add_channel"))
@admin_required
async def add_channel_command(message: types.Message):
    try:
        _, channel_id, days = message.text.split()
        add_channel(int(channel_id), int(days))
        await message.reply(f"Канал {channel_id} успішно додано.")
        logger.info(f"Канал {channel_id} додано користувачем {message.from_user.id}")
        log_action("add_channel")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /add_channel channel_id days")

@dp.message(Command("remove_channel"))
@admin_required
async def remove_channel_command(message: types.Message):
    try:
        _, channel_id = message.text.split()
        remove_channel(int(channel_id))
        await message.reply(f"Канал {channel_id} успішно видалено.")
        logger.info(f"Канал {channel_id} видалено користувачем {message.from_user.id}")
        log_action("remove_channel")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /remove_channel channel_id")

@dp.message(Command("add_filter"))
@admin_required
async def add_filter_command(message: types.Message):
    try:
        _, channel_id, filter_type, *filter_value = message.text.split()
        filter_value = ' '.join(filter_value)
        add_filter(int(channel_id), filter_type, filter_value)
        await message.reply(f"Фільтр {filter_type}: {filter_value} успішно додано до каналу {channel_id}.")
        logger.info(f"Фільтр {filter_type}: {filter_value} додано до каналу {channel_id} користувачем {message.from_user.id}")
        log_action("add_filter")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /add_filter channel_id filter_type filter_value")

@dp.message(Command("remove_filter"))
@admin_required
async def remove_filter_command(message: types.Message):
    try:
        _, filter_id = message.text.split()
        remove_filter(int(filter_id))
        await message.reply(f"Фільтр {filter_id} успішно видалено.")
        logger.info(f"Фільтр {filter_id} видалено користувачем {message.from_user.id}")
        log_action("remove_filter")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /remove_filter filter_id")

@dp.message(Command("list_filters"))
@admin_required
async def list_filters_command(message: types.Message):
    filters = get_filters()
    if filters:
        filter_list = "\n".join([f"ID: {f[0]}, Канал: {f[1]}, Тип: {f[2]}, Значення: {f[3]}" for f in filters])
        await message.reply(f"Список фільтрів:\n{filter_list}")
    else:
        await message.reply("Список фільтрів порожній.")
    log_action("list_filters")

@dp.message(Command("set_admin"))
@superadmin_required
async def set_admin_command(message: types.Message):
    try:
        _, user_id, role = message.text.split()
        add_admin(int(user_id), role)
        await message.reply(f"Адміністратор {user_id} з роллю {role} успішно додано.")
        logger.info(f"Додано нового адміністратора {user_id} з роллю {role}")
        log_action("set_admin")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /set_admin user_id role")

@dp.message(Command("backup"))
@superadmin_required
async def backup_command(message: types.Message):
    return
    try:
        backup_filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        shutil.make_archive(backup_filename[:-4], 'zip', root_dir='.', base_dir='.')
        
        await message.reply_document(FSInputFile(backup_filename))
        
        os.remove(backup_filename)
        
        logger.info(f"Створено резервну копію користувачем {message.from_user.id}")
        log_action("backup")
    except Exception as e:
        await message.reply(f"Помилка при створенні резервної копії: {str(e)}")
        logger.error(f"Помилка при створенні резервної копії: {str(e)}")

@dp.message(Command("restore"))
@superadmin_required
async def restore_command(message: types.Message):
    return
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("Будь ласка, відповідайте на повідомлення з файлом резервної копії.")
        return

    try:
        file = await bot.get_file(message.reply_to_message.document.file_id)
        file_path = file.file_path
        await bot.download_file(file_path, "restore.zip")

        shutil.unpack_archive("restore.zip", ".")

        os.remove("restore.zip")

        await message.reply("Дані успішно відновлено з резервної копії.")
        logger.info(f"Відновлено дані з резервної копії користувачем {message.from_user.id}")
        log_action("restore")
    except Exception as e:
        await message.reply(f"Помилка при відновленні даних: {str(e)}")
        logger.error(f"Помилка при відновленні даних: {str(e)}")

@dp.message(Command("add_main_channel"))
@superadmin_required
async def add_main_channel_command(message: types.Message):
    try:
        _, channel_id = message.text.split()
        add_main_channel(int(channel_id))
        await message.reply(f"Основний канал {channel_id} успішно додано.")
        logger.info(f"Додано основний канал {channel_id} користувачем {message.from_user.id}")
        log_action("add_main_channel")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /add_main_channel channel_id")

@dp.message(Command("remove_main_channel"))
@superadmin_required
async def remove_main_channel_command(message: types.Message):
    try:
        _, channel_id = message.text.split()
        remove_main_channel(int(channel_id))
        await message.reply(f"Основний канал {channel_id} успішно видалено.")
        logger.info(f"Видалено основний канал {channel_id} користувачем {message.from_user.id}")
        log_action("remove_main_channel")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /remove_main_channel channel_id")

@dp.message(Command("list_main_channels"))
@admin_required
async def list_main_channels_command(message: types.Message):
    main_channels = get_main_channels()
    if main_channels:
        channel_list = "\n".join(main_channels.keys())
        await message.reply(f"Список основних каналів:\n{channel_list}")
    else:
        await message.reply("Список основних каналів порожній.")
    log_action("list_main_channels")

@dp.message(Command("set_spam_settings"))
@superadmin_required
async def set_spam_settings_command(message: types.Message):
    try:
        _, max_messages, time_window = message.text.split()
        set_spam_settings(int(max_messages), int(time_window))
        await message.reply(f"Налаштування захисту від спаму оновлено: {max_messages} повідомлень за {time_window} секунд.")
        logger.info(f"Оновлено налаштування захисту від спаму користувачем {message.from_user.id}")
        log_action("set_spam_settings")
    except ValueError:
        await message.reply("Неправильний формат команди. Використовуйте: /set_spam_settings max_messages time_window")

@dp.message(Command("get_spam_settings"))
@admin_required
async def get_spam_settings_command(message: types.Message):
    spam_settings = get_spam_settings()
    if spam_settings:
        await message.reply(f"Поточні налаштування захисту від спаму: {spam_settings[1]} повідомлень за {spam_settings[2]} секунд.")
    else:
        await message.reply("Налаштування захисту від спаму не встановлені.")
    log_action("get_spam_settings")

@dp.message(Command("get_logs"))
@superadmin_required
async def get_logs_command(message: types.Message):
    try:
        await message.reply_document(FSInputFile(log_filename))
        logger.info(f"Відправлено файл логів користувачу {message.from_user.id}")
        log_action("get_logs")
    except Exception as e:
        await message.reply(f"Помилка при відправленні файлу логів: {str(e)}")
        logger.error(f"Помилка при відправленні файлу логів: {str(e)}")

@dp.message(Command("analytics"))
@admin_required
async def analytics_command(message: types.Message):
    try:
        data = get_analytics()
        
        # Створення графіку
        plt.figure(figsize=(10, 6))
        actions = list(set([row[1] for row in data]))
        for action in actions:
            action_data = [row for row in data if row[1] == action]
            dates = [datetime.strptime(row[0], '%Y-%m-%d').date() for row in action_data]
            counts = [row[2] for row in action_data]
            plt.plot(dates, counts, label=action)

        plt.title("Аналітика використання бота")
        plt.xlabel("Дата")
        plt.ylabel("Кількість дій")
        plt.legend()
        plt.xticks(rotation=45)
        plt.tight_layout()

        # Зберігаємо графік у буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)

        # Відправляємо графік
        await message.reply_photo(types.BufferedInputFile(buf.getvalue(), filename="analytics.png"))
        
        logger.info(f"Відправлено аналітику користувачу {message.from_user.id}")
        log_action("analytics")
    except Exception as e:
        await message.reply(f"Помилка при створенні аналітики: {str(e)}")
        logger.error(f"Помилка при створенні аналітики: {str(e)}")

@dp.channel_post()
async def forward_message(message: types.Message):
    """Пересилає повідомлення у відповідні канали на основі фільтрів."""

    main_channels = get_main_channels()
    
    if str(message.chat.id) not in main_channels:
        return  # Ігноруємо повідомлення, які не з основних каналів

    user_id = message.from_user.id if message.from_user else None
    
    if user_id and is_spam(user_id):
        #await message.reply("Ви відправляєте повідомлення занадто часто. Будь ласка, спробуйте пізніше.")
        logger.warning(f"Spam detected from user {user_id}")
        return

    text = message.text or message.caption or ""
    current_time = datetime.now()

    channels = get_channels()
    filters = get_filters()

    for channel_id, info in list(channels.items()):
        if datetime.fromisoformat(info['expiry_date']) < current_time:
            remove_channel(channel_id)
            await notify_admins(f"Канал {channel_id} видалено через закінчення терміну дії.")
            continue

        channel_filters = [f for f in filters if f[1] == channel_id]
        should_forward = False

        for filter_id, _, filter_type, filter_value in channel_filters:
            if filter_type == 'tag':
                if filter_value.lower() in text.lower():
                    should_forward = True
                    break
            elif filter_type == 'word':
                if re.search(r'\b' + re.escape(filter_value.lower()) + r'\b', text.lower()):
                    should_forward = True
                    break
            elif filter_type == 'phrase':
                if filter_value.lower() in text.lower():
                    should_forward = True
                    break
            elif filter_type == 'combination':
                elements = filter_value.split('&')
                if all(element.strip().lower() in text.lower() for element in elements):
                    should_forward = True
                    break

        if should_forward:
            try:
                await message.forward(chat_id=channel_id)
                logger.info(f"Message forwarded to channel {channel_id}")
                log_action("forward_message")
            except Exception as e:
                logger.error(f"Error forwarding message to channel {channel_id}: {e}")
                await notify_admins(f"Помилка при пересиланні повідомлення до каналу {channel_id}: {e}")

async def notify_admins(message: str):
    """Надсилає сповіщення всім адміністраторам."""
    admins = get_admins()
    for admin_id in admins:
        try:
            await bot.send_message(chat_id=admin_id, text=message)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

async def check_expired_channels():
    """Перевіряє та видаляє прострочені канали."""
    logger.info(f"start check_expired_channels")
    channels = get_channels()
    current_time = datetime.now()
    for channel_id, info in list(channels.items()):
        if datetime.fromisoformat(info['expiry_date']) < current_time:
            remove_channel(channel_id)
            await notify_admins(f"Канал {channel_id} видалено через закінчення терміну дії.")


# Планування задач
scheduler.add_job(check_expired_channels, 'interval', hours=1)


async def main():
    # Запуск планувальника
    scheduler.start()
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())