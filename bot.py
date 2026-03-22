import asyncio
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton

# Настройка
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токены
BOT_TOKEN = "8643812650:AAFoSrNVkmlnr-mZCCd1IfQ7FmU9Olsktes"
ADMIN_ID = 8394493239

# Пути
DATA_DIR = os.path.join(os.path.dirname(__file__), "sber_data")
DB_PATH = os.path.join(DATA_DIR, "sber_bot.db")
SCREENSHOTS_DIR = os.path.join(DATA_DIR, "sber_screenshots")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# ====================== Flask для Render ======================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "✅ СберПрайм Бот работает!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ====================== База данных ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            user_id INTEGER PRIMARY KEY,
            phone TEXT,
            full_name TEXT,
            username TEXT,
            reg_date TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            photo_path TEXT,
            sale_date TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("DB OK")

def get_employee(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT * FROM employees WHERE user_id = ?', (user_id,))
    emp = cur.fetchone()
    conn.close()
    if emp:
        return {'user_id': emp[0], 'phone': emp[1], 'full_name': emp[2], 'username': emp[3]}
    return None

def add_employee(user_id, phone, full_name, username):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO employees VALUES (?, ?, ?, ?, ?)',
                (user_id, phone, full_name, username, datetime.now()))
    conn.commit()
    conn.close()

def add_sale(user_id, photo_path):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT INTO sales (user_id, photo_path, sale_date) VALUES (?, ?, ?)',
                (user_id, photo_path, datetime.now()))
    conn.commit()
    conn.close()

def get_sales_count(user_id, date):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM sales WHERE user_id = ? AND DATE(sale_date) = ?', (user_id, date))
    count = cur.fetchone()[0]
    conn.close()
    return count

def get_all_employees():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT user_id, full_name, username FROM employees ORDER BY full_name')
    employees = cur.fetchall()
    conn.close()
    return [{'user_id': e[0], 'full_name': e[1], 'username': e[2]} for e in employees]

def get_total_sales(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM sales WHERE user_id = ?', (user_id,))
    total = cur.fetchone()[0]
    conn.close()
    return total

def get_today_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        SELECT e.full_name, COUNT(s.id)
        FROM employees e
        LEFT JOIN sales s ON e.user_id = s.user_id AND DATE(s.sale_date) = ?
        GROUP BY e.full_name
    ''', (today,))
    stats = cur.fetchall()
    conn.close()
    return stats

def get_date_stats(date):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        SELECT e.full_name, COUNT(s.id)
        FROM employees e
        LEFT JOIN sales s ON e.user_id = s.user_id AND DATE(s.sale_date) = ?
        GROUP BY e.full_name
    ''', (date,))
    stats = cur.fetchall()
    conn.close()
    return stats

# ====================== Состояния ======================
class Form(StatesGroup):
    phone = State()
    full_name = State()
    screenshot = State()

# ====================== Клавиатуры ======================
def admin_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Список сотрудников")],
            [KeyboardButton(text="📊 Статистика сегодня")],
            [KeyboardButton(text="📅 Статистика за дату")],
            [KeyboardButton(text="💰 Все продажи")]
        ],
        resize_keyboard=True
    )

def emp_list_kb(employees):
    kb = []
    for emp in employees:
        kb.append([InlineKeyboardButton(text=emp['full_name'], callback_data=f"emp_{emp['user_id']}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def sale_period_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data=f"sale_today_{user_id}")],
        [InlineKeyboardButton(text="📆 Вчера", callback_data=f"sale_yest_{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_emp")]
    ])

# ====================== Бот ======================
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=BOT_TOKEN)

# ====================== Обработчики ======================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id == ADMIN_ID:
        await message.answer("👋 Админ-панель СберПрайм", reply_markup=admin_kb())
        return
    
    emp = get_employee(user_id)
    if emp:
        await state.set_state(Form.screenshot)
        await message.answer(f"👋 {emp['full_name']}!\n\n📸 Отправьте скриншот активации СберПрайм")
    else:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await state.set_state(Form.phone)
        await message.answer("📞 Отправьте номер телефона:", reply_markup=kb)

@dp.message(Form.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.contact:
        await state.update_data(phone=message.contact.phone_number)
        await state.set_state(Form.full_name)
        await message.answer("✍️ Введите ФИО:", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("❌ Нажмите кнопку")

@dp.message(Form.full_name)
async def process_fullname(message: types.Message, state: FSMContext):
    data = await state.get_data()
    full_name = message.text.strip()
    if not full_name:
        return await message.answer("❌ Введите ФИО")
    
    add_employee(message.from_user.id, data['phone'], full_name, message.from_user.username)
    await bot.send_message(ADMIN_ID, f"✅ Новый сотрудник: {full_name}\nID: {message.from_user.id}")
    await state.set_state(Form.screenshot)
    await message.answer("✅ Регистрация завершена!\n📸 Отправляйте скриншоты")

@dp.message(Form.screenshot)
async def process_screenshot(message: types.Message, state: FSMContext):
    if not message.photo:
        return await message.answer("❌ Отправьте фото")
    
    emp = get_employee(message.from_user.id)
    if not emp:
        return await message.answer("❌ Ошибка, /start")
    
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        
        filename = os.path.join(SCREENSHOTS_DIR, f"{message.from_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        await bot.download_file(file.file_path, filename)
        add_sale(message.from_user.id, filename)
        
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = get_sales_count(message.from_user.id, today)
        total = get_total_sales(message.from_user.id)
        
        await message.answer(f"✅ Скриншот принят!\n📊 Сегодня: {today_count}\n📈 Всего: {total}")
        
        with open(filename, 'rb') as f:
            await bot.send_photo(ADMIN_ID, types.BufferedInputFile(f.read(), filename),
                               caption=f"📸 {emp['full_name']}\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    except Exception as e:
        logger.error(e)
        await message.answer("❌ Ошибка")

# ====================== Админ-команды ======================
@dp.message(lambda m: m.text == "📋 Список сотрудников")
async def admin_employees(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    employees = get_all_employees()
    if not employees:
        await message.answer("📭 Нет сотрудников")
        return
    
    text = "👥 **Список сотрудников:**\n\n"
    for emp in employees:
        total = get_total_sales(emp['user_id'])
        text += f"👤 {emp['full_name']}\n   📸 {total} продаж\n   🆔 {emp['user_id']}\n\n"
    
    await message.answer(text, parse_mode="Markdown", reply_markup=emp_list_kb(employees))

@dp.message(lambda m: m.text == "📊 Статистика сегодня")
async def admin_today(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    stats = get_today_stats()
    if not stats:
        await message.answer("📭 Нет данных за сегодня")
        return
    
    text = f"📊 **СберПрайм - {datetime.now().strftime('%d.%m.%Y')}**\n\n"
    total = 0
    for name, count in stats:
        text += f"👤 {name}: {count} шт.\n"
        total += count
    text += f"\n📈 **Всего: {total}**"
    await message.answer(text, parse_mode="Markdown")

@dp.message(lambda m: m.text == "📅 Статистика за дату")
async def admin_ask_date(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    await message.answer("📅 Введите дату в формате **ГГГГ-ММ-ДД**\n\nПример: 2026-03-21", parse_mode="Markdown")

@dp.message(lambda m: m.text == "💰 Все продажи")
async def admin_all_sales(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    employees = get_all_employees()
    if not employees:
        await message.answer("📭 Нет данных")
        return
    
    text = "💰 **Все продажи:**\n\n"
    total_all = 0
    for emp in employees:
        total = get_total_sales(emp['user_id'])
        total_all += total
        text += f"👤 {emp['full_name']}: {total} шт.\n"
    text += f"\n📈 **Итого: {total_all}**"
    await message.answer(text, parse_mode="Markdown")

@dp.message()
async def handle_date(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        date = message.text.strip()
        datetime.strptime(date, "%Y-%m-%d")
        stats = get_date_stats(date)
        formatted = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
        
        if not stats:
            await message.answer(f"📭 Нет данных за {formatted}")
            return
        
        text = f"📊 **СберПрайм - {formatted}**\n\n"
        total = 0
        for name, count in stats:
            text += f"👤 {name}: {count} шт.\n"
            total += count
        text += f"\n📈 **Всего: {total}**"
        await message.answer(text, parse_mode="Markdown")
    except:
        pass

# ====================== Callbacks ======================
@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа")
    
    data = callback.data
    
    if data.startswith("emp_"):
        user_id = int(data.split("_")[1])
        emp = get_employee(user_id)
        if emp:
            total = get_total_sales(user_id)
            await callback.message.edit_text(
                f"📊 **{emp['full_name']}**\n📈 Всего продаж: {total}\n\nВыберите период:",
                parse_mode="Markdown", reply_markup=sale_period_kb(user_id)
            )
    
    elif data.startswith("sale_today_"):
        user_id = int(data.split("_")[2])
        emp = get_employee(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        count = get_sales_count(user_id, today)
        await callback.message.edit_text(
            f"📊 **{emp['full_name']}**\n📅 {datetime.now().strftime('%d.%m.%Y')}\n\n📸 {count} продаж",
            parse_mode="Markdown", reply_markup=sale_period_kb(user_id)
        )
    
    elif data.startswith("sale_yest_"):
        user_id = int(data.split("_")[2])
        emp = get_employee(user_id)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        count = get_sales_count(user_id, yesterday)
        await callback.message.edit_text(
            f"📊 **{emp['full_name']}**\n📅 {(datetime.now() - timedelta(days=1)).strftime('%d.%m.%Y')}\n\n📸 {count} продаж",
            parse_mode="Markdown", reply_markup=sale_period_kb(user_id)
        )
    
    elif data == "back_emp":
        employees = get_all_employees()
        text = "👥 **Список сотрудников:**\n\n"
        for emp in employees:
            total = get_total_sales(emp['user_id'])
            text += f"👤 {emp['full_name']}\n   📸 {total} продаж\n   🆔 {emp['user_id']}\n\n"
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=emp_list_kb(employees))
    
    elif data == "back_main":
        await callback.message.delete()
        await callback.message.answer("👋 Админ-панель СберПрайм", reply_markup=admin_kb())
    
    await callback.answer()

# ====================== Запуск ======================
async def main():
    Thread(target=run_flask, daemon=True).start()
    await asyncio.sleep(1)
    init_db()
    logger.info("🚀 СберПрайм бот запущен")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
