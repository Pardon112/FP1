import asyncio
import logging
import sqlite3
import os
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramNetworkError

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Токен бота и ID администратора (НОВЫЕ ДАННЫЕ)
BOT_TOKEN = "8643812650:AAFoSrNVkmlnr-mZCCd1IfQ7FmU9Olsktes"
ADMIN_ID = 8394493239

# Настройки для стабильности
RECONNECT_DELAY = 5
MAX_RECONNECT_ATTEMPTS = 10

# ====================== Работа с базой данных ======================
DB_PATH = os.path.join(os.path.dirname(__file__), 'users.db')
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')

def init_db():
    """Инициализация базы данных"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                phone TEXT NOT NULL,
                full_name TEXT NOT NULL,
                username TEXT,
                registered_date TIMESTAMP
            )
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                photo_path TEXT,
                sale_date TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES employees (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database init error: {e}")

def get_employee(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('SELECT * FROM employees WHERE user_id = ?', (user_id,))
        employee = cur.fetchone()
        conn.close()
        return employee
    except Exception as e:
        logger.error(f"Error getting employee: {e}")
        return None

def add_employee(user_id, phone, full_name, username=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''
            INSERT OR REPLACE INTO employees (user_id, phone, full_name, username, registered_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, phone, full_name, username, datetime.now()))
        conn.commit()
        conn.close()
        logger.info(f"New employee added: {user_id}")
    except Exception as e:
        logger.error(f"Error adding employee: {e}")

def add_sale(user_id, photo_path):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO sales (user_id, photo_path, sale_date)
            VALUES (?, ?, ?)
        ''', (user_id, photo_path, datetime.now()))
        conn.commit()
        conn.close()
        logger.info(f"New sale added: {user_id}")
    except Exception as e:
        logger.error(f"Error adding sale: {e}")

def get_sales_stats(user_id, date):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''
            SELECT COUNT(*) as count
            FROM sales 
            WHERE user_id = ? AND DATE(sale_date) = ?
        ''', (user_id, date))
        stats = cur.fetchone()
        conn.close()
        return stats[0] if stats else 0
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return 0

def get_all_employees():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('SELECT user_id, full_name, phone, username FROM employees ORDER BY full_name')
        employees = cur.fetchall()
        conn.close()
        return employees
    except Exception as e:
        logger.error(f"Error getting employees: {e}")
        return []

def get_sales_by_date(user_id, date):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''
            SELECT photo_path, sale_date 
            FROM sales 
            WHERE user_id = ? AND DATE(sale_date) = ?
            ORDER BY sale_date DESC
        ''', (user_id, date))
        sales = cur.fetchall()
        conn.close()
        return sales
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return []

# ====================== Машина состояний ======================
class Form(StatesGroup):
    phone = State()
    full_name = State()
    screenshot = State()

# ====================== Клавиатуры ======================
def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Список сотрудников")],
            [KeyboardButton(text="📊 Статистика за сегодня")],
            [KeyboardButton(text="📅 Статистика за дату")],
            [KeyboardButton(text="📸 Все продажи")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_employee_list_keyboard():
    employees = get_all_employees()
    keyboard = []
    for emp in employees:
        keyboard.append([InlineKeyboardButton(text=emp[1], callback_data=f"emp_{emp[0]}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_date_keyboard(employee_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data=f"date_today_{employee_id}")],
        [InlineKeyboardButton(text="📆 Вчера", callback_data=f"date_yesterday_{employee_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_employees")]
    ])
    return keyboard

# ====================== Создание бота ======================
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# ====================== Обработчики ======================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    
    if user_id == ADMIN_ID:
        await message.answer(
            "👋 Здравствуйте, Администратор!\n\nИспользуйте кнопки для управления:",
            reply_markup=get_admin_keyboard()
        )
        return
    
    employee = get_employee(user_id)
    if employee:
        await state.set_state(Form.screenshot)
        await message.answer(
            f"Здравствуйте, {employee[2]}!\n\n"
            "Пришлите фото активации подписки СберПрайм.\n"
            "Каждый скриншот будет засчитан как одна продажа."
        )
    else:
        contact_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await state.set_state(Form.phone)
        await message.answer(
            "Добро пожаловать!\n\n"
            "Для регистрации отправьте номер телефона:",
            reply_markup=contact_keyboard
        )

@dp.message(Form.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.contact:
        await state.update_data(phone=message.contact.phone_number)
        await state.set_state(Form.full_name)
        await message.answer(
            "Спасибо! Теперь отправьте ваше ФИО (Фамилия Имя Отчество).",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await message.answer("Пожалуйста, используйте кнопку для отправки номера телефона.")

@dp.message(Form.full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    full_name = message.text.strip()
    
    if not full_name:
        await message.answer("Пожалуйста, введите ФИО.")
        return
    
    add_employee(message.from_user.id, data['phone'], full_name, message.from_user.username)
    
    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ Новый сотрудник зарегистрирован:\n"
            f"ID: {message.from_user.id}\n"
            f"Username: @{message.from_user.username or 'нет'}\n"
            f"ФИО: {full_name}\n"
            f"Телефон: {data['phone']}"
        )
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")
    
    await state.set_state(Form.screenshot)
    await message.answer(
        "Регистрация завершена!\n\n"
        "Теперь отправляйте фото активации подписки СберПрайм.\n"
        "Каждый скриншот будет засчитан как одна продажа.",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Form.screenshot)
async def process_screenshot(message: types.Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправьте фото (скриншот активации СберПрайм).")
        return
    
    employee = get_employee(message.from_user.id)
    if not employee:
        await message.answer("Ошибка! Пожалуйста, перезапустите бота командой /start")
        return
    
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(SCREENSHOTS_DIR, f"{message.from_user.id}_{timestamp}.jpg")
        await bot.download_file(file.file_path, filename)
        
        add_sale(message.from_user.id, filename)
        
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = get_sales_stats(message.from_user.id, today)
        
        await message.answer(f"✅ Скриншот принят!\n📊 Сегодня продаж: {today_count}")
        
        with open(filename, 'rb') as photo_file:
            await bot.send_photo(
                ADMIN_ID,
                types.BufferedInputFile(photo_file.read(), filename=f"sale_{message.from_user.id}_{timestamp}.jpg"),
                caption=f"📸 **Новая продажа!**\n\n"
                        f"👤 Сотрудник: {employee[2]}\n"
                        f"🆔 ID: {message.from_user.id}\n"
                        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                        f"📊 Продаж сегодня: {today_count}",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error processing screenshot: {e}")
        await message.answer("Произошла ошибка при обработке скриншота. Попробуйте еще раз.")

# ====================== Админ-команды ======================
@dp.message(lambda message: message.text == "👥 Список сотрудников")
async def admin_employees(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    employees = get_all_employees()
    if not employees:
        await message.answer("Пока нет зарегистрированных сотрудников.")
        return
    
    text = "👥 **Список сотрудников:**\n\n"
    for i, emp in enumerate(employees, 1):
        text += f"{i}. {emp[1]} (ID: {emp[0]})\n   📱 @{emp[3] or 'нет'}\n"
    
    await message.answer(text, parse_mode="Markdown", reply_markup=get_employee_list_keyboard())

@dp.message(lambda message: message.text == "📊 Статистика за сегодня")
async def admin_today_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    employees = get_all_employees()
    
    if not employees:
        await message.answer("Пока нет данных.")
        return
    
    text = f"📊 **Статистика за сегодня**\n📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    total = 0
    
    for emp in employees:
        count = get_sales_stats(emp[0], today)
        total += count
        text += f"👤 {emp[1]}: {count} шт.\n"
    
    text += f"\n📈 **Всего продаж: {total}**"
    await message.answer(text, parse_mode="Markdown")

@dp.message(lambda message: message.text == "📅 Статистика за дату")
async def admin_ask_date(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    await message.answer(
        "Введите дату в формате **ГГГГ-ММ-ДД**\n\nПример: 2026-03-21",
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "📸 Все продажи")
async def admin_all_sales(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    employees = get_all_employees()
    if not employees:
        await message.answer("Пока нет данных.")
        return
    
    text = "📸 **Все продажи по сотрудникам**\n\n"
    total_all = 0
    
    for emp in employees:
        text += f"👤 **{emp[1]}**\n"
        # Получаем продажи за все время
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM sales WHERE user_id = ?', (emp[0],))
        total = cur.fetchone()[0]
        conn.close()
        total_all += total
        text += f"   📊 Всего продаж: {total}\n\n"
    
    text += f"📈 **Общее количество продаж: {total_all}**"
    await message.answer(text, parse_mode="Markdown")

@dp.message()
async def handle_date_input(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        date = message.text.strip()
        datetime.strptime(date, "%Y-%m-%d")
        
        employees = get_all_employees()
        text = f"📊 **Статистика за {date}**\n\n"
        total = 0
        
        for emp in employees:
            count = get_sales_stats(emp[0], date)
            total += count
            text += f"👤 {emp[1]}: {count} шт.\n"
        
        text += f"\n📈 **Всего: {total}**"
        await message.answer(text, parse_mode="Markdown")
        
    except ValueError:
        pass  # Игнорируем, если это не дата

# ====================== Callback handlers ======================
@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    data = callback.data
    
    if data.startswith("emp_"):
        employee_id = int(data.split("_")[1])
        employee = get_employee(employee_id)
        if employee:
            await callback.message.edit_text(
                f"📊 **{employee[2]}**\n\nВыберите период:",
                parse_mode="Markdown",
                reply_markup=get_date_keyboard(employee_id)
            )
    
    elif data.startswith("date_today_"):
        employee_id = int(data.split("_")[2])
        employee = get_employee(employee_id)
        today = datetime.now().strftime("%Y-%m-%d")
        count = get_sales_stats(employee_id, today)
        
        await callback.message.edit_text(
            f"📊 **{employee[2]}**\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
            f"📸 Продаж сегодня: {count}",
            parse_mode="Markdown",
            reply_markup=get_date_keyboard(employee_id)
        )
    
    elif data.startswith("date_yesterday_"):
        employee_id = int(data.split("_")[2])
        employee = get_employee(employee_id)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        count = get_sales_stats(employee_id, yesterday)
        
        await callback.message.edit_text(
            f"📊 **{employee[2]}**\n"
            f"📅 {(datetime.now() - timedelta(days=1)).strftime('%d.%m.%Y')}\n\n"
            f"📸 Продаж вчера: {count}",
            parse_mode="Markdown",
            reply_markup=get_date_keyboard(employee_id)
        )
    
    elif data == "back_employees":
        employees = get_all_employees()
        text = "👥 **Список сотрудников:**\n\n"
        for i, emp in enumerate(employees, 1):
            text += f"{i}. {emp[1]} (ID: {emp[0]})\n   📱 @{emp[3] or 'нет'}\n"
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_employee_list_keyboard()
        )
    
    elif data == "back":
        await callback.message.delete()
        await callback.message.answer(
            "👋 Здравствуйте, Администратор!\n\nИспользуйте кнопки для управления:",
            reply_markup=get_admin_keyboard()
        )
    
    await callback.answer()

# ====================== Запуск ======================
async def main():
    """Основная функция с обработкой ошибок"""
    attempt = 0
    
    while attempt < MAX_RECONNECT_ATTEMPTS:
        try:
            # Инициализация БД
            init_db()
            
            logger.info("Starting bot polling...")
            
            # Запускаем поллинг
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                skip_updates=True
            )
            
        except TelegramNetworkError as e:
            attempt += 1
            logger.error(f"Network error (attempt {attempt}/{MAX_RECONNECT_ATTEMPTS}): {e}")
            await asyncio.sleep(RECONNECT_DELAY * attempt)
            
        except Exception as e:
            attempt += 1
            logger.error(f"Unexpected error (attempt {attempt}/{MAX_RECONNECT_ATTEMPTS}): {e}")
            await asyncio.sleep(RECONNECT_DELAY * attempt)
    
    logger.critical("Max reconnect attempts reached. Exiting...")

if __name__ == "__main__":
    asyncio.run(main())
