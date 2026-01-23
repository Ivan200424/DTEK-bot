import asyncio
import json
import logging
import os
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import aiohttp
from aiohttp import web
import socket

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
Application, CommandHandler, MessageHandler,
ContextTypes, ConversationHandler, filters
)
from telegram.error import TelegramError
from telegram.constants import ParseMode

# Налаштування логування

logging.basicConfig(
level=logging.INFO,
format=’%(asctime)s - %(name)s - %(levelname)s - %(message)s’
)
logger = logging.getLogger(**name**)

# Константи

BOT_TOKEN = os.getenv(‘BOT_TOKEN’)
ADMIN_USER_ID = int(os.getenv(‘ADMIN_USER_ID’, ‘1026177113’))
SUPPORT_USERNAME = os.getenv(‘SUPPORT_USERNAME’, ‘@Ivan200424’)
SUPPORT_EMAIL = os.getenv(‘SUPPORT_EMAIL’, ‘support@example.com’)
HEALTHCHECK_PORT = int(os.getenv(‘HEALTHCHECK_PORT’, ‘8080’))
DEBOUNCE_SECONDS = int(os.getenv(‘DEBOUNCE_SECONDS’, ‘300’))
RATE_LIMIT_COMMANDS = int(os.getenv(‘RATE_LIMIT_COMMANDS’, ‘10’))
RATE_LIMIT_WINDOW = int(os.getenv(‘RATE_LIMIT_WINDOW’, ‘60’))

# Константи для мониторинга графіків

GRAPHENKO_CHECK_INTERVAL = int(os.getenv(‘GRAPHENKO_CHECK_INTERVAL’, ‘300’))  # 5 хвилин
MAX_RETRIES = int(os.getenv(‘MAX_RETRIES’, ‘3’))
RETRY_DELAY = int(os.getenv(‘RETRY_DELAY’, ‘10’))

# Константи для меню

(SELECTING_ACTION, ADDING_CHANNEL, WAITING_CHAT_ID, WAITING_IMAGE_URL,
WAITING_CAPTION, WAITING_REGION, WAITING_GROUP) = range(7)

CONFIG_FILE = ‘graphenko-chats.json’
BACKUP_DIR = ‘backups’
app = None
http_runner = None

class GraphenkoConfig:
“”“Клас для роботи з конфігурацією”””

```
def __init__(self, filepath: str = CONFIG_FILE):
    self.filepath = filepath
    self.backup_dir = Path(BACKUP_DIR)
    self.backup_dir.mkdir(exist_ok=True)
    self.lock = asyncio.Lock()
    self.load()

def load(self):
    """Завантажити конфігурацію з файлу"""
    try:
        if Path(self.filepath).exists():
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        else:
            self.data = {'chats': {}}
            self.save()
    except Exception as e:
        logger.error(f"Помилка при завантаженні конфігурації: {e}")
        self.data = {'chats': {}}

async def save(self):
    """Зберегти конфігурацію в файл"""
    async with self.lock:
        try:
            # Створити бекап
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = self.backup_dir / f'backup_{timestamp}.json'
            if Path(self.filepath).exists():
                import shutil
                shutil.copy2(self.filepath, backup_file)
            
            # Видалити старі бекапи (залишити останніх 10)
            backups = sorted(self.backup_dir.glob('backup_*.json'))
            for old_backup in backups[:-10]:
                old_backup.unlink()
            
            # Зберегти конфігурацію
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            logger.info("Конфігурація успішно збережена")
        except Exception as e:
            logger.error(f"Помилка при збереженні конфігурації: {e}")

def get_chat(self, chat_id: str) -> Dict[str, Any]:
    """Отримати дані чату"""
    return self.data['chats'].get(str(chat_id), {})

def set_chat(self, chat_id: str, data: Dict[str, Any]):
    """Встановити дані чату"""
    self.data['chats'][str(chat_id)] = data

def delete_chat(self, chat_id: str):
    """Видалити чат з конфігурації"""
    if str(chat_id) in self.data['chats']:
        del self.data['chats'][str(chat_id)]
```

class GraphenkoMonitor:
“”“Клас для моніторингу змін графіків”””

```
def __init__(self, config: GraphenkoConfig):
    self.config = config
    self.image_hashes = {}
    self.last_update_time = {}
    self.session: Optional[aiohttp.ClientSession] = None

async def init_session(self):
    """Ініціалізувати HTTP сесію"""
    if self.session is None:
        self.session = aiohttp.ClientSession()

async def close_session(self):
    """Закрити HTTP сесію"""
    if self.session:
        await self.session.close()

async def fetch_image(self, url: str, retries: int = MAX_RETRIES) -> Optional[bytes]:
    """Завантажити зображення з URL"""
    await self.init_session()
    
    for attempt in range(retries):
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.warning(f"HTTP {resp.status} при завантаженні {url}")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout при завантаженні {url} (спроба {attempt + 1}/{retries})")
        except Exception as e:
            logger.error(f"Помилка при завантаженні {url}: {e}")
        
        if attempt < retries - 1:
            await asyncio.sleep(RETRY_DELAY)
    
    return None

def calculate_hash(self, data: bytes) -> str:
    """Розрахувати SHA256 хеш зображення"""
    return hashlib.sha256(data).hexdigest()

async def check_updates(self) -> Dict[str, list]:
    """Перевірити оновлення всіх графіків"""
    updates = {
        'updated': [],
        'new': [],
        'errors': []
    }
    
    for chat_id, chat_data in self.config.data['chats'].items():
        image_url = chat_data.get('image_url')
        if not image_url:
            continue
        
        try:
            image_data = await self.fetch_image(image_url)
            if not image_data:
                updates['errors'].append({
                    'chat_id': chat_id,
                    'reason': 'Не вдалося завантажити зображення'
                })
                continue
            
            current_hash = self.calculate_hash(image_data)
            prev_hash = self.image_hashes.get(chat_id)
            
            if prev_hash is None:
                # Перший запуск
                self.image_hashes[chat_id] = current_hash
                updates['new'].append({
                    'chat_id': chat_id,
                    'image_data': image_data,
                    'chat_data': chat_data
                })
            elif prev_hash != current_hash:
                # Графік оновлено!
                logger.info(f"Графік оновлено для чату {chat_id}")
                self.image_hashes[chat_id] = current_hash
                self.last_update_time[chat_id] = datetime.now()
                updates['updated'].append({
                    'chat_id': chat_id,
                    'image_data': image_data,
                    'chat_data': chat_data
                })
            else:
                logger.debug(f"Графік без змін для чату {chat_id}")
        
        except Exception as e:
            logger.error(f"Помилка при перевірці графіка для {chat_id}: {e}")
            updates['errors'].append({
                'chat_id': chat_id,
                'reason': str(e)
            })
    
    return updates
```

# Глобальні об’єкти

config = GraphenkoConfig()
monitor = GraphenkoMonitor(config)
user_rate_limits = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
“”“Обробник команди /start”””
user_id = update.effective_user.id

```
keyboard = [
    ['📊 Додати канал', '⚙️ Налаштування'],
    ['📜 Мої канали', '📋 Довідка'],
    ['☎️ Підтримка']
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

await update.message.reply_text(
    f"Привіт, {update.effective_user.first_name}! 👋\n\n"
    f"Я допоможу тобі автоматично оновлювати графіки відключень ДТЕК в каналі.\n\n"
    f"Що ти хочеш зробити?",
    reply_markup=reply_markup
)
return SELECTING_ACTION
```

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
“”“Початок додавання нового каналу”””
if update.effective_user.id != ADMIN_USER_ID:
await update.message.reply_text(“❌ Ця команда доступна тільки адміністратору”)
return SELECTING_ACTION

```
await update.message.reply_text(
    "📝 Введи ID каналу (формат: -1001234567890)\n"
    "Як знайти ID каналу: @username_to_id_bot",
    reply_markup=ReplyKeyboardRemove()
)
return WAITING_CHAT_ID
```

async def receive_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
“”“Отримати та перевірити ID каналу”””
chat_id_str = update.message.text.strip()

```
# Перевірка формату
try:
    chat_id = int(chat_id_str)
    if not str(chat_id_str).startswith('-100'):
        raise ValueError("ID повинна починатися з -100")
except ValueError:
    await update.message.reply_text(
        "❌ Неправильний формат!\n"
        "Спробуй ще раз. ID повинна мати формат: -1001234567890"
    )
    return WAITING_CHAT_ID

context.user_data['chat_id'] = str(chat_id)

await update.message.reply_text(
    "✅ Спасибо! Тепер надішли URL графіка (PNG)\n"
    "Приклад: https://example.com/schedule.png"
)
return WAITING_IMAGE_URL
```

async def receive_image_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
“”“Отримати та перевірити URL зображення”””
url = update.message.text.strip()

```
# Перевірка URL
if not url.startswith(('http://', 'https://')):
    await update.message.reply_text(
        "❌ URL повинен починатися з http:// або https://\n"
        "Спробуй ще раз"
    )
    return WAITING_IMAGE_URL

# Спробуємо завантажити зображення
await update.message.reply_text("⏳ Перевіряю URL...")

image_data = await monitor.fetch_image(url, retries=2)
if not image_data:
    await update.message.reply_text(
        "❌ Не вдалося завантажити зображення за цією URL\n"
        "Переконайся, що URL правильна та доступна"
    )
    return WAITING_IMAGE_URL

context.user_data['image_url'] = url
context.user_data['image_hash'] = monitor.calculate_hash(image_data)

keyboard = [
    ['📝 Власний підпис'],
    ['➕ Стандартний підпис']
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

await update.message.reply_text(
    "✅ URL перевірена!\n\n"
    "Тепер виберіть підпис для повідомлення:",
    reply_markup=reply_markup
)
return WAITING_CAPTION
```

async def receive_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
“”“Отримати або встановити стандартний підпис”””
choice = update.message.text.strip()

```
if choice == '📝 Власний підпис':
    await update.message.reply_text(
        "Введи текст для підпису:",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data['custom_caption'] = True
    return WAITING_CAPTION
elif choice == '➕ Стандартний підпис':
    context.user_data['caption'] = get_default_caption()
else:
    # Власний текст
    context.user_data['caption'] = update.message.text

# Зберегти конфігурацію
chat_id = context.user_data['chat_id']
config.set_chat(chat_id, {
    'image_url': context.user_data['image_url'],
    'caption': context.user_data.get('caption', get_default_caption()),
    'added_date': datetime.now().isoformat(),
    'added_by': update.effective_user.id
})
await config.save()

# Завантажити зображення в канал
await send_graph_to_channel(context.bot, chat_id, context.user_data)

keyboard = [
    ['📊 Додати канал', '⚙️ Налаштування'],
    ['📜 Мої канали', '📋 Довідка'],
    ['☎️ Підтримка']
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

await update.message.reply_text(
    f"✅ Канал успішно додано!\n"
    f"ID: {chat_id}\n\n"
    f"Графік буде автоматично оновлюватися кожні {GRAPHENKO_CHECK_INTERVAL // 60} хвилин.",
    reply_markup=reply_markup
)

# Очистити user_data
context.user_data.clear()
return SELECTING_ACTION
```

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
“”“Показати список каналів”””
if not config.data[‘chats’]:
await update.message.reply_text(“📭 Каналів ще не додано”)
return SELECTING_ACTION

```
message = "📜 Ваші канали:\n\n"
for chat_id, data in config.data['chats'].items():
    added_date = data.get('added_date', 'N/A')
    message += f"🔹 {chat_id}\n"
    message += f"   📅 Додано: {added_date}\n"
    message += f"   🖼️ URL: {data.get('image_url', 'N/A')[:50]}...\n\n"

await update.message.reply_text(message)
return SELECTING_ACTION
```

def get_default_caption() -> str:
“”“Отримати стандартний підпис”””
tz = ‘Europe/Kyiv’
now = datetime.now()
timestamp = now.strftime(’%d.%m.%Y %H:%M’)
return f”📊 Графік ДТЕК\n⏰ Оновлено: {timestamp} ({tz})\n\n🔄 Оновлення кожні 5 хвилин”

async def send_graph_to_channel(bot, chat_id: str, data: dict):
“”“Надіслати графік в канал”””
try:
image_url = data.get(‘image_url’)
caption = data.get(‘caption’, get_default_caption())

```
    # Додаємо cache-busting параметр
    cache_bust = f"?v={datetime.now().timestamp()}"
    final_url = f"{image_url}{cache_bust}" if '?' not in image_url else f"{image_url}&v={datetime.now().timestamp()}"
    
    # Завантажуємо зображення
    image_data = await monitor.fetch_image(image_url)
    if not image_data:
        logger.error(f"Не вдалося завантажити графік для {chat_id}")
        return
    
    # Надсилаємо в канал
    message = await bot.send_photo(
        chat_id=int(chat_id),
        photo=image_data,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Закріплюємо повідомлення
    try:
        await message.pin(disable_notification=True)
    except TelegramError as e:
        logger.warning(f"Не вдалося закріпити повідомлення: {e}")
    
    logger.info(f"Графік успішно надіслано в канал {chat_id}")
except Exception as e:
    logger.error(f"Помилка при надісланні графіка в {chat_id}: {e}")
```

async def monitor_graphs_task(application: Application):
“”“Фонова задача для моніторингу графіків”””
await monitor.init_session()
logger.info(“Задача моніторингу графіків стартована”)

```
try:
    while True:
        await asyncio.sleep(GRAPHENKO_CHECK_INTERVAL)
        
        logger.info("Перевіряю оновлення графіків...")
        updates = await monitor.check_updates()
        
        # Обробляємо оновлені графіки
        for item in updates['updated']:
            await send_graph_to_channel(
                application.bot,
                item['chat_id'],
                item['chat_data']
            )
            
            # Надсилаємо сповіщення до адміна
            try:
                await application.bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text=f"📢 Графік оновлено!\nКанал: {item['chat_id']}"
                )
            except:
                pass
        
        # Логуємо помилки
        for error in updates['errors']:
            logger.warning(f"Помилка для {error['chat_id']}: {error['reason']}")

except asyncio.CancelledError:
    logger.info("Задача моніторингу припинена")
except Exception as e:
    logger.error(f"Помилка в задачі моніторингу: {e}")
finally:
    await monitor.close_session()
```

async def healthcheck_handler(request):
“”“HTTP handler для healthcheck”””
return web.json_response({
‘status’: ‘ok’,
‘version’: ‘3.0.0’,
‘timestamp’: datetime.now().isoformat(),
‘chats_count’: len(config.data[‘chats’]),
‘monitoring’: bool(monitor.image_hashes)
})

async def post_init(application: Application):
“”“Ініціалізація після запуску бота”””
logger.info(“Бот запущен”)

```
# Запустити моніторинг графіків
asyncio.create_task(monitor_graphs_task(application))

# Запустити HTTP сервер для healthcheck
global http_runner
app = web.Application()
app.router.add_get('/health', healthcheck_handler)
app.router.add_get('/', healthcheck_handler)

http_runner = web.AppRunner(app)
await http_runner.setup()
site = web.TCPSite(http_runner, '0.0.0.0', HEALTHCHECK_PORT)
await site.start()
logger.info(f"HTTP сервер запущен на порту {HEALTHCHECK_PORT}")
```

async def post_stop(application: Application):
“”“Очистка при зупинці бота”””
logger.info(“Бот зупинається”)
await monitor.close_session()

```
if http_runner:
    await http_runner.cleanup()
```

def main():
“”“Головна функція”””
if not BOT_TOKEN:
logger.error(“BOT_TOKEN не встановлено!”)
return

```
# Створюємо Application
application = Application.builder().token(BOT_TOKEN).build()

# Додаємо обробники
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('start', start),
        MessageHandler(filters.TEXT & filters.Regex('^📊 Додати канал$'), add_channel),
        MessageHandler(filters.TEXT & filters.Regex('^📜 Мої канали$'), list_channels),
    ],
    states={
        SELECTING_ACTION: [
            MessageHandler(filters.TEXT & filters.Regex('^📊 Додати канал$'), add_channel),
            MessageHandler(filters.TEXT & filters.Regex('^📜 Мої канали$'), list_channels),
        ],
        WAITING_CHAT_ID: [MessageHandler(filters.TEXT, receive_chat_id)],
        WAITING_IMAGE_URL: [MessageHandler(filters.TEXT, receive_image_url)],
        WAITING_CAPTION: [MessageHandler(filters.TEXT, receive_caption)],
    },
    fallbacks=[CommandHandler('start', start)]
)

application.add_handler(conv_handler)
application.post_init = post_init
application.post_stop = post_stop

# Запускаємо бота
logger.info("Запуск бота...")
application.run_polling(allowed_updates=Update.ALL_TYPES)
```

if **name** == ‘**main**’:
main()