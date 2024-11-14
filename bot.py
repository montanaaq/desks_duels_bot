import asyncio
import logging
import os
from contextlib import asynccontextmanager

import requests
import uvicorn
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Загрузка переменных окружения из .env файла
load_dotenv()

# ==========================
# Конфигурация и Настройки
# ==========================

API_TOKEN = os.getenv('API_TOKEN')
BASE_URL = os.getenv('BASE_URL')
PORT = int(os.getenv('PORT', 8000))
WEBHOOK_PATH = "/webhook"

# Конструируем WEBHOOK_URL
RENDER_EXTERNAL_HOSTNAME = os.getenv('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    if RENDER_EXTERNAL_HOSTNAME.startswith("http://") or RENDER_EXTERNAL_HOSTNAME.startswith("https://"):
        RENDER_EXTERNAL_HOSTNAME = RENDER_EXTERNAL_HOSTNAME.split("://")[1]
    WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"
else:
    # Для локальной разработки используйте ngrok URL если необходимо
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', "https://abcd1234.ngrok.io/webhook")  # Замените на ваш реальный ngrok URL

# ==========================
# Инициализация Бота и Диспетчера
# ==========================

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ==========================
# Конфигурация Логирования
# ==========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================
# Инициализация Планировщика
# ==========================

scheduler = AsyncIOScheduler()

# ==========================
# Инициализация FastAPI с Lifespan
# ==========================

app = FastAPI(lifespan=lambda app: lifespan(app))

# ==========================
# Переменная для состояния уведомлений
# ==========================
notifications_enabled = True  # Флаг для включения/выключения уведомлений

# ==========================
# Вспомогательные Функции
# ==========================

async def make_request(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    except Exception as e:
        logger.error(f"Ошибка в make_request: {e}")
        raise

async def get_all_users():
    try:
        response = await make_request(requests.get, f"{BASE_URL}/users")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Не удалось получить пользователей: {e}")
        return []

async def notify_user(telegram_id):
    if not notifications_enabled:
        logger.info("Уведомления отключены. Пропускаем отправку уведомления.")
        return
    
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
        logger.info(f"Уведомление отправлено пользователю {telegram_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю {telegram_id}: {e}")

async def send_notifications():
    if not notifications_enabled:
        logger.info("Уведомления отключены. Пропускаем отправку уведомлений.")
        return

    try:
        users = await get_all_users()
        if not users:
            logger.warning("Нет пользователей для уведомления.")
            return
        
        tasks = []
        for user in users:
            telegram_id = user.get('telegramId')
            if telegram_id:
                tasks.append(notify_user(telegram_id))
            else:
                logger.warning(f"Данные пользователя без 'telegramId': {user}")
        
        if tasks:
            await asyncio.gather(*tasks)
    except Exception as e:
        logger.error(f"Ошибка в send_notifications: {e}")

def schedule_notifications():
    lesson_times = [
        ("07:35", send_notifications),
        ("09:25", send_notifications),
        ("10:15", send_notifications),
        ("11:15", send_notifications),
        ("12:15", send_notifications),
        ("13:05", send_notifications),
        ("13:55", send_notifications),
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
        logger.info(f"Запланировано уведомление в {hour}:{minute} по будням")

# ==========================
# Обработчики Команд Бота
# ==========================

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} запустил бота.")
    user_data = {
        "telegramId": str(message.from_user.id),
        "username": message.from_user.username,
        "firstName": message.from_user.first_name
    }
    webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
    )
    
    try:
        response = await make_request(
            requests.post,
            f'{BASE_URL}/register',
            json=user_data
        )
        response.raise_for_status()
        logger.info(f"Пользователь {message.from_user.id} успешно зарегистрирован.")
    except requests.RequestException as e:
        logger.error(f"Ошибка регистрации пользователя {message.from_user.id}: {e}")
        await message.reply("Произошла ошибка при регистрации. Попробуйте позже.")
        return
    
    welcome_text = (
        f"Привет, <b>{message.from_user.first_name}</b>! Добро пожаловать в 🎉 <b>Desks Duels</b> 🎉 \n"
        "Это захватывающая игра, где ты можешь наконец-то занять место в классе\n"
        "\n👇 <b>Нажми на кнопку ниже, чтобы начать игру</b> 👇"
    )
    
    await message.reply(welcome_text, reply_markup=keyboard, parse_mode='html')

@dp.message_handler(commands=['notify'])
async def toggle_notifications(message: types.Message):
    global notifications_enabled
    notifications_enabled = not notifications_enabled  # Переключаем состояние флага
    
    if notifications_enabled:
        await message.reply("Уведомления включены. Вы будете получать уведомления.")
        logger.info(f"Пользователь {message.from_user.id} включил уведомления.")
    else:
        await message.reply("Уведомления отключены. Вы больше не будете получать уведомления.")
        logger.info(f"Пользователь {message.from_user.id} отключил уведомления.")

@dp.message_handler(commands=['restart'])
async def delete_user(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} запросил удаление аккаунта.")
    data = {"telegramId": message.from_user.id}
    
    try:
        # Отправка запроса на удаление аккаунта
        response = await make_request(
            requests.delete,
            f'{BASE_URL}/delete',
            json=data
        )
        response.raise_for_status()
        
        await message.reply(
            'Ваш аккаунт успешно удалён!\n<b>Чтобы зарегистрироваться снова, нажмите /start</b>',
            parse_mode='html'
        )
        logger.info(f"Пользователь {message.from_user.id} успешно удалён.")
    except requests.HTTPError as e:
        status_code = e.response.status_code
        response_text = e.response.text
        logger.error(f"HTTP ошибка при удалении пользователя {message.from_user.id}: {status_code} - {response_text}")
        await message.reply(
            f'Ошибка удаления пользователя: {status_code} - {response_text}',
            parse_mode='html'
        )
    except requests.RequestException as e:
        logger.error(f"Ошибка при удалении пользователя {message.from_user.id}: {e}")
        await message.reply(
            f'Сервер не отвечает.\n<b>Ошибка удаления пользователя: {e}</b>',
            parse_mode='html'
        )

# ==========================
# Маршруты FastAPI
# ==========================

@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "ok"}, status_code=200)

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        logger.info(f"Получено обновление вебхука: {update_data}")
        
        update = types.Update(**update_data)
        
        Dispatcher.set_current(dp)
        Bot.set_current(bot)
        
        await dp.process_update(update)
        
        return JSONResponse(content={"status": "ok"}, status_code=200)
    except Exception as e:
        logger.error(f"Не удалось обработать обновление: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=400)

# ==========================
# Lifespan Event Handlers
# ==========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Действия при запуске
    logger.info("Запуск бота и планировщика...")
    schedule_notifications()
    scheduler.start()
    logger.info("Планировщик запущен.")
    
    # Установка вебхука
    try:
        response = await make_request(
            requests.post,
            f'https://api.telegram.org/bot{API_TOKEN}/setWebhook',
            json={"url": WEBHOOK_URL}
        )
        response.raise_for_status()
        logger.info(f"Вебхук установлен на {WEBHOOK_URL}")
    except requests.RequestException as e:
        logger.error(f"Не удалось установить вебхук: {e}")
    
    yield
    
    # Действия при завершении
    logger.info("Завершение работы бота и планировщика...")
    await bot.close()
    scheduler.shutdown()
    logger.info("Бот и планировщик остановлены.")
    
    # Удаление вебхука
    try:
        response = await make_request(
            requests.post,
            f'https://api.telegram.org/bot{API_TOKEN}/deleteWebhook'
        )
        response.raise_for_status()
        logger.info("Вебхук успешно удалён.")
    except requests.RequestException as e:
        logger.error(f"Не удалось удалить вебхук: {e}")

# ==========================
# Запуск Приложения
# ==========================

if __name__ == '__main__':
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT, log_level="info")
