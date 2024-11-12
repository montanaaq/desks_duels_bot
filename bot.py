import asyncio
import logging
import os
from datetime import datetime, timedelta

import httpx
import uvicorn
from aiogram import Bot, Dispatcher, types
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           WebAppInfo)
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ==========================
# Configuration and Settings
# ==========================

# Fetch environment variables for security
API_TOKEN = '7421252065:AAGFWO70HPOSPkS8BU-CczsM5Pa5tBM3JO8'
BASE_URL = "https://desks-duels-backend.onrender.com/auth"
PORT = 8000

# ==========================
# Initialize Bot and Dispatcher
# ==========================

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ==========================
# Logging Configuration
# ==========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================
# Initialize Scheduler
# ==========================

scheduler = AsyncIOScheduler()

# ==========================
# Initialize FastAPI
# ==========================

app = FastAPI()

# ==========================
# Utility Functions
# ==========================

async def get_all_users():
    """
    Fetch all users from the backend API asynchronously.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://desks-duels-backend.onrender.com/users")
            response.raise_for_status()
            return response.json()  # Assuming API returns list of user dictionaries
        except httpx.RequestError as e:
            logger.error(f"Failed to fetch users: {e}")
            return []

async def notify_user(telegram_id):
    """
    Send a notification to a single user.
    """
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
        logger.info(f"Notification sent to user {telegram_id}")
    except Exception as e:
        logger.error(f"Error sending notification to user {telegram_id}: {e}")

async def send_notifications():
    """
    Send notifications to all users.
    """
    users = await get_all_users()
    if not users:
        logger.warning("No users to notify.")
        return
    
    tasks = []
    for user in users:
        telegram_id = user.get('telegramId')
        if telegram_id:
            tasks.append(notify_user(telegram_id))
        else:
            logger.warning(f"User data missing 'telegramId': {user}")
    
    if tasks:
        await asyncio.gather(*tasks)

def schedule_notifications():
    """
    Schedule notifications at specified lesson end times.
    """
    # Define lesson end times (hour, minute) - adjust as needed
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
        scheduler.add_job(
            job,
            "cron",
            hour=hour,
            minute=minute,
            day_of_week="mon-fri",
            id=f"notification_{hour}_{minute}"
        )
        logger.info(f"Scheduled notification at {hour}:{minute} on weekdays")

# ==========================
# Bot Command Handlers
# ==========================

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    logger.info(f"User {message.from_user.id} started the bot.")
    user_data = {
        "telegramId": str(message.from_user.id),
        "username": message.from_user.username,
        "firstName": message.from_user.first_name
    }
    webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
    )
    
    # Send registration request to the backend
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f'{BASE_URL}/register', json=user_data)
            response.raise_for_status()
            logger.info(f"User {message.from_user.id} registered successfully.")
        except httpx.RequestError as e:
            logger.error(f"Error registering user {message.from_user.id}: {e}")
            await message.reply("Произошла ошибка при регистрации. Попробуйте снова позже.")
            return
    
    welcome_text = (
        f"Привет, <b>{message.from_user.first_name}</b>! Добро пожаловать в 🎉 <b>Desks Duels</b> 🎉 \n"
        "Это захватывающая игра, где ты можешь наконец-то занять место в классе\n"
        "\n👇 <b>Нажми на кнопку ниже, чтобы начать игру</b> 👇"
    )
    
    await message.reply(welcome_text, reply_markup=keyboard, parse_mode='html')

@dp.message_handler(commands=['restart'])
async def delete_user(message: types.Message):
    logger.info(f"User {message.from_user.id} requested account deletion.")
    data = {"telegramId": message.from_user.id}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(f'{BASE_URL}/delete', json=data)
            response.raise_for_status()
            await message.reply(
                'Ваш аккаунт успешно удалён!\n<b>Чтобы зарегистрироваться нажмите /start</b>',
                parse_mode='html'
            )
            logger.info(f"User {message.from_user.id} deleted successfully.")
        except httpx.RequestError as e:
            logger.error(f"Error deleting user {message.from_user.id}: {e}")
            await message.reply(
                f'Сервер не отвечает.\n<b>Ошибка удаления пользователя: {e}</b>',
                parse_mode='html'
            )

# ==========================
# FastAPI Routes
# ==========================

@app.get("/health")
async def health_check():
    """
    Health check endpoint for Render.
    """
    return JSONResponse(content={"status": "ok"}, status_code=200)

# Optionally, add more routes as needed
# Example:
# @app.get("/another-route")
# async def another_route():
#     return {"message": "Another route"}

# ==========================
# Startup and Shutdown Events
# ==========================

async def on_startup(dp):
    """
    Actions to perform on startup.
    """
    logger.info("Starting up the bot and scheduler...")
    schedule_notifications()
    scheduler.start()
    logger.info("Scheduler started.")

async def on_shutdown(dp):
    """
    Actions to perform on shutdown.
    """
    logger.info("Shutting down bot and scheduler...")
    await bot.close()
    scheduler.shutdown()
    logger.info("Bot and scheduler shut down.")

# ==========================
# Main Entry Point
# ==========================

def start_bot():
    """
    Start the aiogram bot and FastAPI server.
    """
    loop = asyncio.get_event_loop()

    # Create a task for aiogram's polling
    loop.create_task(executor.start_polling(
        dp,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True
    ))

    # Run the FastAPI app with Uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    loop.run_until_complete(server.serve())

if __name__ == '__main__':
    start_bot()