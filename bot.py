import asyncio
import logging
import os
from contextlib import asynccontextmanager

import aiohttp
import requests
import socketio
import uvicorn
from aiogram import Bot, Dispatcher, types
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           WebAppInfo)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sio = socketio.Client()

# Загрузка переменных окружения из .env файла
load_dotenv()

# ==========================
# Конфигурация и Настройки
# ==========================

API_TOKEN = os.getenv('API_TOKEN')
BASE_URL = os.getenv('BASE_URL')
PORT = int(os.getenv('PORT', 8000))
WEBHOOK_PATH = "/webhook"

def connect_to_socket():
    try:
        sio.connect(BASE_URL, 
            headers={
                'Origin': BASE_URL
            },
            transports=['polling'],
            wait_timeout=10
        )
        logger.info('Подключено к сокетам')
        
        # Emit join event for all connected users
        try:
            response = requests.get(f"{BASE_URL}/users")
            if response.status_code == 200:
                users = response.json()
                for user in users:
                    telegram_id = str(user.get('telegramId'))
                    if telegram_id:
                        sio.emit('join', telegram_id)
                        logger.info(f'Присоединился к комнате пользователя: {telegram_id}')
        except Exception as e:
            logger.error(f'Ошибка при присоединении к комнатам пользователей: {e}')
            
    except Exception as e:
        logger.error(f'Ошибка подключения к сокетам: {e}')

# Добавим глобальную переменную для хранения ID текущего пользователя
CURRENT_USER_ID = None

# Переменная для состояния уведомлений
notifications_state = {}  # Dictionary to store notification state per user

# Remove async from the socket event handler
@sio.event
def duelRequest(data):
    try:
        # Debug logging
        logger.info('==================== НОВЫЙ ВЫЗОВ НА ДУЭЛЬ ====================')
        logger.info(f'Получены данные: {data}')
        
        telegram_id = str(data.get('challengedId'))
        seat_id = data.get('seatId')
        challenger_name = data.get('challengerName')
        
        logger.info(f'ID получателя: {telegram_id}')
        logger.info(f'ID места: {seat_id}')
        logger.info(f'Имя вызывающего: {challenger_name}')

        # Create and run a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_duel_notification(telegram_id, seat_id, challenger_name))
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f'Ошибка обработки duelRequestSent: {e}')

# Separate async function for sending notifications
async def send_duel_notification(telegram_id, seat_id, challenger_name):
    if not notifications_state.get(telegram_id, True):  # Default to enabled if not set
        logger.info(f'Уведомления отключены для пользователя {telegram_id}')
        return
        
    try:
        webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
        keyboard = InlineKeyboardMarkup().add(
            InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
        )
        
        await bot.send_message(
            chat_id=telegram_id,
            text=f"🎯 Вас вызвали на дуэль!\n"
                 f"<b>{challenger_name}</b> бросил вам вызов за место №{seat_id}!\n"
                 f"У вас есть 1 минута чтобы принять вызов, иначе вы потеряете своё место ⚔️",
            reply_markup=keyboard,
            parse_mode='html'
        )
        logger.info('✅ Сообщение успешно отправлено!')
    except Exception as e:
        logger.error(f'❌ Ошибка отправки сообщения: {e}')

@sio.event
def duelDeclined(data):
    try:
        logger.info('==================== ДУЭЛЬ ОТКЛОНЕНА ====================')
        logger.info(f'Получены данные: {data}')
        
        duel = data.get('duel', {})
        telegram_id = str(duel.get('player2'))  # ID того, кто отклонил
        seat_id = duel.get('seatId')
        challenger_name = data.get('challengerName', 'Соперник')
        
        logger.info(f'ID получателя: {telegram_id}')
        logger.info(f'ID места: {seat_id}')
        logger.info(f'Имя вызывающего: {challenger_name}')
        
        # Create and run a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_decline_notification(telegram_id, seat_id, challenger_name))
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f'Ошибка обработки duelDeclined: {e}')

async def send_decline_notification(telegram_id, seat_id, challenger_name):
    if not notifications_state.get(telegram_id, True):  # Default to enabled if not set
        logger.info(f'Уведомления отключены для пользователя {telegram_id}')
        return
        
    try:
        webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
        keyboard = InlineKeyboardMarkup().add(
            InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
        )
        
        await bot.send_message(
            chat_id=telegram_id,
            text=f"❌ Вы отклонили вызов на дуэль от <b>{challenger_name}</b>!\n"
                 f"В результате вы потеряли место №{seat_id}!\n"
                 f"Теперь оно принадлежит вашему сопернику 🏆",
            reply_markup=keyboard,
            parse_mode='html'
        )
        logger.info('✅ Сообщение об отклонении успешно отправлено!')
    except Exception as e:
        logger.error(f'❌ Ошибка отправки сообщения об отклонении: {e}')


# Добавим обработчик для всех событий, чтобы видеть, какие события приходят
@sio.on('*')
def catch_all(event, data):
    logger.info(f'🔍 Получено событие: {event}')
    logger.info(f'📦 Данные события: {data}')

# Обновим обработчики подключения с более подробным логированием
@sio.event
def connect():
    logger.info('🟢 Соединение с сокет-сервером установлено')
    logger.info(f'🔗 URL соединения: {sio.connection_url}')
    # Re-emit join event for all users when reconnected
    try:
        response = requests.get(f"{BASE_URL}/users")
        if response.status_code == 200:
            users = response.json()
            for user in users:
                telegram_id = str(user.get('telegramId'))
                if telegram_id:
                    sio.emit('join', telegram_id)
                    logger.info(f'Переподключился к комнате пользователя: {telegram_id}')
    except Exception as e:
        logger.error(f'Ошибка при переподключении к комнатам пользователей: {e}')

@sio.event
def disconnect():
    logger.info('🔴 Соединение с сокет-сервером разорвано')

@sio.event
def connect_error(error):
    logger.error(f'⚠️ Ошибка подключения к сокет-серверу: {error}')

# Конструируем WEBHOOK_URL
RENDER_EXTERNAL_HOSTNAME = os.getenv('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    if RENDER_EXTERNAL_HOSTNAME.startswith("http://") or RENDER_EXTERNAL_HOSTNAME.startswith("https://"):
        RENDER_EXTERNAL_HOSTNAME = RENDER_EXTERNAL_HOSTNAME.split("://")[1]
    WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"
else:
    # Для локальной разработки используйте ngrok URL если необходимо
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', "https://6f06-95-26-82-58.ngrok-free.app/webhook")  # Замените на ваш реальный ngrok URL

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

async def make_request(method, *args, **kwargs):
    try:
        logger.info(f"Received HTTP method: {method}")

        if isinstance(method, str):
            method = method.upper()
        else:
            raise ValueError("The 'method' argument should be a string representing an HTTP method.")
        
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            async with session.request(method, *args, **kwargs) as response:
                print(response)
                if 'application/json' in response.headers.get('Content-Type', ''):
                    return await response.json()
                else:
                    logger.warning(f"Non-JSON response received: {response.headers.get('Content-Type')}")
                    return await response.text()
    except aiohttp.ClientError as e:
        logger.error(f"HTTP ошибка в make_request: {e}")
        raise
    except Exception as e:
        logger.error(f"Неизвестная ошибка в make_request: {e}")
        raise

async def get_all_users():
    try:
        response = await make_request("GET", f"{BASE_URL}/users")
        print(response)
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

# ==========================
# Обработчики Команд Бота
# ==========================

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    global CURRENT_USER_ID
    CURRENT_USER_ID = str(message.from_user.id)  # Сохраняем ID пользователя
    logger.info(f"Текущий пользователь: {CURRENT_USER_ID}")
    logger.info(f"Пользователь {message.from_user.id} запустил бота.")
    
    try:
        # Проверяем, есть ли пользователь уже в базе данных
        response = requests.post(
            f"{BASE_URL}/auth/check",
            json={"telegramId": str(message.from_user.id)}
        )
        response.raise_for_status()
        
        # Create a loading animation
        loading_message = await bot.send_message(chat_id=message.from_user.id, text="Инициализация системы")
        loading_frames = [
            "Подключение к базе данных ⚡",
            "Проверка данных 📊",
            "Настройка профиля 👤",
            "Подготовка игрового пространства 🎮",
        ]
        
        # Animate the loading message
        for frame in loading_frames:
            await asyncio.sleep(0.7)  # Add delay between frames
            await loading_message.edit_text(frame)
        
        # Final success message
        await loading_message.edit_text("Система готова к работе! 🚀")
        await asyncio.sleep(1)  # Brief pause before continuing
        
        user = response.json()
        
        if user:
            logger.info(f"Пользователь {message.from_user.id} уже зарегистрирован.")
            
            # Отправляем сообщение с Telegram Web App на ваше приложение
            webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
            )
            await bot.send_message(
                chat_id=message.from_user.id, 
                text="Вы уже зарегистрированы! Нажмите на кнопку ниже, чтобы перейти в приложение.", 
                reply_markup=keyboard
            )
            return
    except requests.RequestException as e:
        logger.error(f"Ошибка проверки пользователя {message.from_user.id}: {e}")
    
    # Если пользователь не найден, регистрируем его
    user_data = {
        "telegramId": str(message.from_user.id),
        "username": message.from_user.username,
        "firstName": message.from_user.first_name
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/register",
            json=user_data
        )
        response.raise_for_status()

        logger.info(f"Пользователь {message.from_user.id} успешно зарегистрирован.")
        
        # Отправляем сообщение с Telegram Web App на ваше приложение
        webAppKeyboard = WebAppInfo(url="https://desks-duels.netlify.app/")
        keyboard = InlineKeyboardMarkup().add(
            InlineKeyboardButton(text="Перейти в приложение", web_app=webAppKeyboard)
        )
        welcome_text = (
            f"Привет, <b>{message.from_user.first_name}</b>! Добро пожаловать в 🎉 <b>Desks Duels</b> 🎉 \n"
            "Это захватывающая игра, где ты можешь наконец-то занять место в классе\n"
            "\n👇 <b>Нажми на кнопку ниже, чтобы начать игру</b> 👇"
        )
        await bot.send_message(chat_id=message.from_user.id, text=welcome_text, reply_markup=keyboard, parse_mode='html')
    except requests.RequestException as e:
        logger.error(f"Ошибка регистрации пользователя {message.from_user.id}: {e}")
        await message.reply("Произошла ошибка при регистрации. Попробуйте позже.")
        
@dp.message_handler(commands=['notify'])
async def toggle_notifications(message: types.Message):
    try:
        user_id = str(message.from_user.id)
        
        # Toggle notifications state for this user
        notifications_state[user_id] = not notifications_state.get(user_id, True)
        
        # Create keyboard with current status
        status_keyboard = InlineKeyboardMarkup(row_width=1)
        status_text = "🔔 Включены" if notifications_state[user_id] else "🔕 Отключены"
        status_keyboard.add(
            InlineKeyboardButton(
                text=f"Статус уведомлений: {status_text}",
                callback_data="notification_status"
            )
        )
        
        # Send response message
        await message.reply(
            f"{'🔔 Уведомления включены!' if notifications_state[user_id] else '🔕 Уведомления отключены!'}\n\n"
            f"{'Теперь вы будете получать уведомления о дуэлях.' if notifications_state[user_id] else 'Теперь вы не будете получать уведомления о дуэлях.'}\n"
            f"Используйте /notify чтобы {'отключить' if notifications_state[user_id] else 'включить'} уведомления.",
            reply_markup=status_keyboard
        )
        
        logger.info(f'Пользователь {user_id} {"включил" if notifications_state[user_id] else "отключил"} уведомления')
        
    except Exception as e:
        logger.error(f'Ошибка при изменении настроек уведомлений: {e}')
        await message.reply("Произошла ошибка при изменении настроек уведомлений. Попробуйте позже.")

@dp.message_handler(commands=['restart'])
async def delete_user(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} запросил удаление аккаунта.")
    data = {"telegramId": message.from_user.id}
    
    try:
        # Отправка запроса на удаление аккаунта
        response = await make_request(
            "DELETE",
            f"{BASE_URL}/auth/delete",
            json=data
        )

        print(response)
        
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

@dp.message_handler(commands=['socket_status'])
async def socket_status(message: types.Message):
    status = "🟢 Подключено" if sio.connected else "🔴 Отключено"
    await message.reply(
        f"Статус сокет-соединения: {status}\n"
        f"Текущий ID: {CURRENT_USER_ID}\n"
        f"URL: {sio.connection_url if sio.connected else 'Нет соединения'}"
    )

# ==========================
# Маршруты FastAPI
# ==========================

@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "ok"}, status_code=200)

@app.get("/webhook/status")
async def webhook_status():
    try:
        # Получаем информацию о текущем вебхуке
        webhook_info = await bot.get_webhook_info()
        
        return {
            "url": webhook_info.url,
            "is_set": bool(webhook_info.url),
            "pending_update_count": webhook_info.pending_update_count,
            "last_error_date": webhook_info.last_error_date,
            "last_error_message": webhook_info.last_error_message,
            "max_connections": webhook_info.max_connections
        }
    except Exception as e:
        logger.error(f"Error checking webhook status: {e}")
        return JSONResponse(
            status_code=500, 
            content={"error": "Failed to retrieve webhook status"}
        )

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
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
    # Инициализация планировщика
    scheduler = AsyncIOScheduler()
    
    # Добавляем задачу для отправки уведомлений
    schedule_notifications()
    
    # Запускаем планировщик
    scheduler.start()
    
    # Настраиваем вебхук
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook установлен на {WEBHOOK_URL}")
    
    yield
    
    # Очистка
    scheduler.shutdown()
    await bot.session.close()

@dp.message_handler(content_types=['text'])
async def func(message: types.Message):
    if message.text not in ['/start', '/restart', '/notify']:
        await message.reply('Не понимаю, что вы хотите сделать. Воспользуйтесь командой /start для начала работы с ботом.')

# ==========================
# Запуск Приложения
# ==========================

if __name__ == '__main__':
    try:
        connect_to_socket()
        uvicorn.run("bot:app", host="0.0.0.0", port=PORT, log_level="info")
    except KeyboardInterrupt:
        pass