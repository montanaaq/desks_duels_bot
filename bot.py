import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import requests
import asyncio

# Настройки бота
API_TOKEN = '7421252065:AAGFWO70HPOSPkS8BU-CczsM5Pa5tBM3JO8'
BASE_URL = "https://desks-duels-backend.onrender.com/auth"

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Логирование
logging.basicConfig(level=logging.INFO)

# Scheduler initialization
scheduler = AsyncIOScheduler()

# Получение всех пользователей из базы данных (пример)
def get_all_users():
    # Замените это реальным запросом к базе данных
    # Здесь просто пример со статичными user_id
    response = requests.get("https://desks-duels-backend.onrender.com/users")  # Update to match your API endpoint
    if response.status_code == 200:
        return response.json()  # Assuming API returns list of user IDs
    else:
        logging.error("Не удалось получить список пользователей")
        return []

# Функция отправки уведомления пользователю
async def notify_user(telegram_id):
    webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
    )
    
    try:
        await bot.send_message(
            telegram_id,
            "Готовься к битве, она состоится через 5 минут!",
            reply_markup=keyboard
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления пользователю {telegram_id}: {e}")

# Функция для массовой отправки уведомлений всем пользователям
async def send_notifications():
    users = [984383301]
    for user in users:
        await notify_user(user)  # Assuming "telegramId" is the key for user IDs

# Настройка расписания уведомлений перед уроками
def schedule_notifications():
    # Schedule notifications 5 minutes before the end of each lesson
    lesson_times = [
        ("07:35", send_notifications),  # Before 1st lesson ends at 8:40
        ("09:25", send_notifications),  # Before 2nd lesson ends at 9:30
        ("10:15", send_notifications),  # Before 3rd lesson ends at 10:20
        ("11:15", send_notifications),  # Before 4th lesson ends at 11:20
        ("12:15", send_notifications),  # Before 5th lesson ends at 12:20
        ("13:05", send_notifications),  # Before 6th lesson ends at 13:10
        ("13:55", send_notifications),  # Before 7th lesson ends at 14:00
    ]

    for time_str, job in lesson_times:
        hour, minute = map(int, time_str.split(":"))
        scheduler.add_job(job, "cron", hour=hour, minute=minute, day_of_week="mon-fri")

@dp.message_handler(commands=['restart'])
async def delete_user(message: types.Message):
    data = {"telegramId": message.from_user.id}
    try:
        response = requests.delete(f'{BASE_URL}/delete', json=data)
        response.raise_for_status()
        await message.reply('Ваш аккаунт успешно удалён!\n<b>Чтобы зарегистрироваться нажмите /start</b>', parse_mode='html')
    except requests.exceptions.RequestException as e:
        print(f"Error deleting user: {e}")
        await message.reply(f'Сервер не отвечает.\n<b>Ошибка удаления пользователя: {e}</b>', parse_mode='html')

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    print(message.from_user.id)
    user_data = {
        "telegramId": str(message.from_user.id),
        "username": message.from_user.username,
        "firstName": message.from_user.first_name
    }
    webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
    )
    
    # Отправка запроса на регистрацию пользователя
    try:
        response = requests.post(f'{BASE_URL}/register', json=user_data)
        print(response.json())
        response.raise_for_status()  # Проверка на ошибки

        # Инлайн-кнопка с ссылкой на приложение (пока что localhost)
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при регистрации пользователя: {e}")
        await message.reply("Произошла ошибка при регистрации. Попробуйте снова позже.")
    welcome_text = (
    f"Привет, <b>{message.from_user.first_name}</b>! Добро пожаловать в 🎉 <b>Desks Duels</b> 🎉 \nЭто захватывающая игра, где ты можешь наконец-то занять место в классе\n"
    "\n👇 <b>Нажми на кнопку ниже, чтобы начать игру</b> 👇"
)

    await message.reply(welcome_text, reply_markup=keyboard, parse_mode='html')
# scheduler.add_job(send_notifications, "interval", minutes=1)  # Sends notifications every minute for testing

if __name__ == '__main__':
    # Запуск планировщика и добавление задач
    schedule_notifications()
    scheduler.start()

    # Запуск бота
    executor.start_polling(dp, skip_updates=True)
