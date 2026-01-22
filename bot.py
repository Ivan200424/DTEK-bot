#!/usr/bin/env python3
"""
DTEK Bot - Interactive Telegram Bot for Power Monitoring and Graphenko Updates
Features: TCP monitoring, Graphenko updates, interactive menu-based UX
"""

import asyncio
import hashlib
import json
import os
import socket
import sys
import threading
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

try:
    import requests
except ImportError:
    print('ERROR: requests library not found. Install with: pip install requests>=2.31.0')
    sys.exit(1)

try:
    from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
    from telegram.constants import ParseMode
    from telegram.error import TelegramError
except ImportError:
    print('ERROR: python-telegram-bot library not found. Install with: pip install python-telegram-bot>=20.0,<21.0')
    sys.exit(1)

# Configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
DEFAULT_CHAT_ID = os.getenv('CHAT_ID', '-1003523279109')
CONFIG_FILE = 'graphenko-chats.json'
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '1026177113'))

# Constants
DEFAULT_HOST = '93.127.118.86'
DEFAULT_PORT = 443
DEFAULT_INTERVAL = 30
GRAPHENKO_UPDATE_INTERVAL = 60  # Default: 1 minute (configurable per-chat via graph_check_interval)
OUTAGE_IMAGES_BASE = 'https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/images/'
DEFAULT_CAPTION = '⚡️ Графік стабілізаційних вімкнень. Це повідомлення оновлюється щогодини автоматично.'

# Regions mapping
REGIONS_MAP = {
    'kyiv-region': 'Київська область',
    'kyiv': 'м. Київ',
    'dnipro': 'Дніпро',
    'odesa': 'Одеса'
}

# Ukrainian weekdays
WEEKDAYS_UK = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця", 'Субота', 'Неділя']

# Time unit constants
MILLISECONDS_PER_SECOND = 1000
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24

if not BOT_TOKEN:
    print('ERROR: BOT_TOKEN environment variable is required')
    sys.exit(1)

# Randomized phrases for monitoring notifications
PHRASES_POWER_APPEARED_BASE = [
    "Повернулось після",
    "Очікували",
    "Світла не було",
    "Дочекались за",
    "Без світла:",
    "Час без електроенергії:",
    "Відключення тривало",
    "Період знеструмлення:"
]

PHRASES_POWER_APPEARED_VARIATIONS = [
    "Без світла були",
    "Нарешті зʼявилось після",
    "Світло взяло паузу на",
    "Зробило перерву на"
]

PHRASES_POWER_GONE_BASE = [
    "Світло трималось",
    "Світло було",
    "Протрималось",
    "Пішло на паузу після",
    "Зі світлом було",
    "Період зі світлом:",
    "Електроенергія була"
]

PHRASES_POWER_GONE_VARIATIONS = [
    "Було, але недовго —",
    "Тайм-аут після",
    "Світло сказало \"па-па\" через",
    "Протрималось, скільки змогло —",
    "Пішло на перерву через",
    "Знову пішло після",
    "Вистачило рівно на",
    "Побуло з нами",
    "Подача тривала",
    "Інтервал зі світлом:"
]

# Menu keyboards
MAIN_MENU_KEYBOARD = [
    ['📊 Статус', '💡 Моніторинг'],
    ['📈 Графіки', '⚙️ Налаштування'],
    ['❓ Допомога']
]

MONITORING_MENU_KEYBOARD = [
    ['▶️ Запустити', '⏸️ Зупинити'],
    ['📊 Статистика'],
    ['🔙 Головне меню']
]

GRAPHS_MENU_KEYBOARD = [
    ['📥 Отримати зараз', '⚙️ Налаштування'],
    ['📅 Мій графік'],
    ['🔙 Головне меню']
]

HELP_MENU_KEYBOARD = [
    ['🔙 Головне меню']
]

# ============================================================================
# Configuration Management
# ============================================================================

def load_config() -> Dict[str, Dict]:
    """Load configuration from JSON file"""
    if not os.path.exists(CONFIG_FILE):
        return {}
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Convert from array format to dict
        if isinstance(data, list):
            config = {}
            for item in data:
                if isinstance(item, dict):
                    for chat_id, settings in item.items():
                        config[str(chat_id)] = settings
            return config
        return data
    except Exception as e:
        print(f'ERROR: Failed to load config: {e}')
        return {}


def save_config(config: Dict[str, Dict]) -> bool:
    """Save configuration to JSON file"""
    try:
        # Convert to array format matching the original schema
        data = []
        for chat_id in sorted(config.keys()):
            data.append({chat_id: config[chat_id]})
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        return True
    except Exception as e:
        print(f'ERROR: Failed to save config: {e}')
        return False


def get_chat_config(chat_id: str) -> Dict:
    """Get configuration for a specific chat, creating if needed"""
    config = load_config()
    if chat_id not in config:
        # Initialize with defaults
        config[chat_id] = {
            'region': 'kyiv',
            'group': '3.1',
            'format_preference': 'image',
            'creation_date': datetime.now(timezone.utc).isoformat(),
            'user_count': 0,
            'monitor_host': DEFAULT_HOST,
            'monitor_port': DEFAULT_PORT,
            'monitor_interval_sec': DEFAULT_INTERVAL,
            'monitor_enabled': False,
            'fallback_host': None,
            'fallback_port': None,
            'light_paused': False,
            'graphs_paused': False,
            'channel_title': '',
            'channel_description': '',
            'light_check_interval': DEFAULT_INTERVAL,
            'graph_check_interval': GRAPHENKO_UPDATE_INTERVAL
        }
        save_config(config)
    return config[chat_id]


def update_chat_config(chat_id: str, updates: Dict):
    """Update configuration for a specific chat"""
    config = load_config()
    if chat_id not in config:
        config[chat_id] = get_chat_config(chat_id)
    config[chat_id].update(updates)
    save_config(config)


# ============================================================================
# Utility Functions
# ============================================================================

def calculate_kyiv_offset() -> int:
    """Calculate the UTC offset for Kyiv timezone (accounting for DST)"""
    now = datetime.now(timezone.utc)
    year = now.year
    
    # Last Sunday of March at 01:00 UTC
    march_last_day = datetime(year, 3, 31, 1, 0, 0, tzinfo=timezone.utc)
    dst_start = march_last_day - timedelta(days=(march_last_day.weekday() + 1) % 7)
    
    # Last Sunday of October at 01:00 UTC
    oct_last_day = datetime(year, 10, 31, 1, 0, 0, tzinfo=timezone.utc)
    dst_end = oct_last_day - timedelta(days=(oct_last_day.weekday() + 1) % 7)
    
    # Determine offset
    if dst_start <= now < dst_end:
        return 3  # DST (summer)
    else:
        return 2  # Standard (winter)


def get_kyiv_time() -> str:
    """Get current time in Kyiv timezone (HH:MM format)"""
    now = datetime.now(timezone.utc)
    offset_hours = calculate_kyiv_offset()
    kyiv_time = datetime.fromtimestamp(now.timestamp() + offset_hours * 3600)
    return kyiv_time.strftime('%H:%M')


def get_kyiv_datetime() -> datetime:
    """Get current datetime in Kyiv timezone"""
    now = datetime.now(timezone.utc)
    offset_hours = calculate_kyiv_offset()
    return datetime.fromtimestamp(now.timestamp() + offset_hours * 3600)


def format_duration(milliseconds: int) -> str:
    """Format duration in Ukrainian"""
    seconds = milliseconds // MILLISECONDS_PER_SECOND
    minutes = seconds // SECONDS_PER_MINUTE
    hours = minutes // MINUTES_PER_HOUR
    days = hours // HOURS_PER_DAY
    
    def plural_days(n):
        if n % 10 == 1 and n % 100 != 11:
            return 'день'
        if n % 10 in [2, 3, 4] and n % 100 not in [12, 13, 14]:
            return 'дні'
        return 'днів'
    
    def plural_hours(n):
        if n % 10 == 1 and n % 100 != 11:
            return 'година'
        if n % 10 in [2, 3, 4] and n % 100 not in [12, 13, 14]:
            return 'години'
        return 'годин'
    
    def plural_minutes(n):
        if n % 10 == 1 and n % 100 != 11:
            return 'хвилина'
        if n % 10 in [2, 3, 4] and n % 100 not in [12, 13, 14]:
            return 'хвилини'
        return 'хвилин'
    
    if days > 0:
        remaining_hours = hours % HOURS_PER_DAY
        if remaining_hours > 0:
            return f'{days} {plural_days(days)} {remaining_hours} {plural_hours(remaining_hours)}'
        return f'{days} {plural_days(days)}'
    
    if hours > 0:
        remaining_minutes = minutes % MINUTES_PER_HOUR
        if remaining_minutes > 0:
            return f'{hours} {plural_hours(hours)} {remaining_minutes} {plural_minutes(remaining_minutes)}'
        return f'{hours} {plural_hours(hours)}'
    
    if minutes > 0:
        return f'{minutes} {plural_minutes(minutes)}'
    
    return f'{seconds} секунд'


def format_duration_short(milliseconds: int) -> str:
    """Format duration in short format (Xгод Yхв)"""
    seconds = milliseconds // MILLISECONDS_PER_SECOND
    minutes = seconds // SECONDS_PER_MINUTE
    hours = minutes // MINUTES_PER_HOUR
    
    remaining_minutes = minutes % MINUTES_PER_HOUR
    
    parts = []
    if hours > 0:
        parts.append(f'{hours}год')
    if remaining_minutes > 0:
        parts.append(f'{remaining_minutes}хв')
    if not parts:
        parts.append(f'{seconds}с')
    
    return ' '.join(parts)


def get_random_phrase(base_phrases: List[str], variation_phrases: List[str]) -> str:
    """Get a random phrase with 70% base, 30% variations"""
    if random.random() < 0.7:
        return random.choice(base_phrases)
    else:
        return random.choice(variation_phrases)


def convert_group_to_url_format(group: str) -> str:
    """Convert group format from 3.1 to 3-1 for URL"""
    return group.replace('.', '-')


def check_tcp_connection(host: str, port: int, timeout: int = 5) -> bool:
    """Check if TCP connection to host:port succeeds"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            return result == 0
    except Exception as e:
        print(f'ERROR: TCP check failed for {host}:{port}: {e}')
        return False


# ============================================================================
# Menu Handlers
# ============================================================================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu"""
    keyboard = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(
        '🏠 Головне меню\n\nОберіть опцію:',
        reply_markup=keyboard
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    # Initialize config if needed
    config = get_chat_config(chat_id)
    
    # Update user info
    update_chat_config(chat_id, {
        'last_user_name': user.full_name if user else 'Unknown',
        'last_user_username': user.username if user else None,
        'last_user_id': user.id if user else None
    })
    
    keyboard = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
    
    welcome_text = (
        f'👋 Вітаю, {user.full_name if user else "користувач"}!\n\n'
        '🤖 Це бот для моніторингу електроенергії та графіків відключень.\n\n'
        'Оберіть опцію з меню:'
    )
    
    await update.message.reply_text(welcome_text, reply_markup=keyboard)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Status screen"""
    chat_id = str(update.effective_chat.id)
    config = get_chat_config(chat_id)
    
    # Calculate status
    monitor_status = config.get('monitor_last_status', 'unknown')
    status_emoji = '🟢' if monitor_status == 'online' else '🔴'
    status_text = 'світло є' if monitor_status == 'online' else 'світла немає'
    
    # Last successful connection
    last_change = config.get('monitor_last_change')
    last_change_emoji = '🟢' if monitor_status == 'online' else '🔴'
    if last_change:
        duration = int(time.time() * MILLISECONDS_PER_SECOND) - last_change
        last_conn_text = f'{format_duration_short(duration)} тому {last_change_emoji}'
        last_conn_dt = datetime.fromtimestamp(last_change / MILLISECONDS_PER_SECOND)
        last_conn_date = last_conn_dt.strftime('%Y-%m-%d %H:%M:%S')
    else:
        last_conn_text = 'немає даних'
        last_conn_date = 'немає даних'
    
    # Last status change
    if last_change:
        status_change_text = f'{format_duration_short(duration)} тому'
        status_change_date = last_conn_date
    else:
        status_change_text = 'немає даних'
        status_change_date = 'немає даних'
    
    # IP addresses
    primary_ip = config.get('monitor_host', DEFAULT_HOST)
    fallback_ip = config.get('fallback_host', 'немає')
    
    # Creation date
    creation_date = config.get('creation_date')
    if creation_date:
        try:
            created_dt = datetime.fromisoformat(creation_date)
            creation_str = created_dt.strftime('%Y-%m-%d %H:%M:%S')
            days_ago = (datetime.now(timezone.utc) - created_dt).days
            creation_text = f'{creation_str}, ({days_ago}д тому)'
        except:
            creation_text = 'невідомо'
    else:
        creation_text = 'невідомо'
    
    # User count
    user_count = config.get('user_count', 0)
    
    # Author info
    author_name = config.get('last_user_name', '[disabled]')
    author_username = config.get('last_user_username', '[disabled]')
    author_id = config.get('last_user_id', ADMIN_USER_ID)
    
    status_message = f'''💡 Статус світла: {status_emoji} {status_text}

📶 Останній успішний зв'язок:
    {last_conn_text}
    {last_conn_date}

🔄 Остання зміна статусу:
    {status_change_text}
    {status_change_date}

🌐 IP-адреса / DDNS:
    {primary_ip}
🌐 Запасна IP-адреса / DDNS:
    {fallback_ip}
📅 Дата створення каналу:
    {creation_text}
👤 Кількість юзерів у каналі: {user_count}
👨‍💻 Автор телеграм каналу:
      Ім'я: {author_name}
      Username: @{author_username}
      Telegram ID: {author_id}'''
    
    await update.message.reply_text(status_message)


async def handle_monitoring_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Monitoring menu"""
    keyboard = ReplyKeyboardMarkup(MONITORING_MENU_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(
        '💡 Моніторинг електроенергії\n\nОберіть дію:',
        reply_markup=keyboard
    )


async def handle_monitoring_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle monitoring start"""
    chat_id = str(update.effective_chat.id)
    config = get_chat_config(chat_id)
    
    if not config.get('light_paused'):
        update_chat_config(chat_id, {'monitor_enabled': True})
        await update.message.reply_text('✅ Моніторинг запущено')
    else:
        await update.message.reply_text('⚠️ Моніторинг призупинено через налаштування каналу')


async def handle_monitoring_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle monitoring stop"""
    chat_id = str(update.effective_chat.id)
    update_chat_config(chat_id, {'monitor_enabled': False})
    await update.message.reply_text('⏸️ Моніторинг зупинено')


async def handle_monitoring_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle monitoring statistics"""
    chat_id = str(update.effective_chat.id)
    config = get_chat_config(chat_id)
    
    status = config.get('monitor_last_status', 'unknown')
    last_change = config.get('monitor_last_change')
    
    if last_change:
        duration = int(time.time() * MILLISECONDS_PER_SECOND) - last_change
        duration_text = format_duration(duration)
    else:
        duration_text = 'немає даних'
    
    stats_text = f'''📊 Статистика моніторингу:

Поточний статус: {'🟢 Онлайн' if status == 'online' else '🔴 Офлайн'}
Тривалість поточного стану: {duration_text}
Моніторинг: {'✅ Увімкнено' if config.get('monitor_enabled') else '❌ Вимкнено'}'''
    
    await update.message.reply_text(stats_text)


async def handle_graphs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Graphs menu"""
    keyboard = ReplyKeyboardMarkup(GRAPHS_MENU_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(
        '📈 Графіки відключень\n\nОберіть дію:',
        reply_markup=keyboard
    )


async def handle_graphs_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle get graphs now - show schedule type selection menu"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('📅 Сьогодні + Завтра', callback_data='graph_type_emergency')],
        [InlineKeyboardButton('📆 На тиждень', callback_data='graph_type_week')],
        [InlineKeyboardButton('📊 Все відразу', callback_data='graph_type_all')]
    ])
    await update.message.reply_text(
        '📈 Оберіть тип графіку:',
        reply_markup=keyboard
    )


async def handle_graph_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle graph type selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    config = get_chat_config(chat_id)
    
    region = config.get('region', 'kyiv')
    group = config.get('group', '3.1')
    group_formatted = convert_group_to_url_format(group)
    
    # Determine schedule type suffix
    if query.data == 'graph_type_emergency':
        suffix = '-emergency'
        type_name = 'сьогодні + завтра'
    elif query.data == 'graph_type_week':
        suffix = '-week'
        type_name = 'на тиждень'
    else:  # graph_type_all
        suffix = ''
        type_name = 'повний графік'
    
    # Construct image URL
    image_url = f'{OUTAGE_IMAGES_BASE}{region}/gpv-{group_formatted}{suffix}.png'
    
    # Send image
    cb = int(time.time() * MILLISECONDS_PER_SECOND)
    photo_url = f'{image_url}?cb={cb}'
    region_name = REGIONS_MAP.get(region, region)
    caption = f'⚡️ Графік для черги *{group}*\nРегіон: *{region_name}*\nТип: {type_name}'
    
    try:
        await query.message.reply_photo(photo=photo_url, caption=caption, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await query.message.reply_text(f'❌ Помилка завантаження зображення: {e}')


async def handle_region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle region selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    # Extract region from callback data (format: region_kyiv-region)
    region = query.data.replace('region_', '')
    region_name = REGIONS_MAP.get(region, region)
    
    update_chat_config(chat_id, {'region': region})
    await query.message.reply_text(f'✅ Регіон змінено на: *{region_name}*', parse_mode=ParseMode.MARKDOWN)


async def handle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle group selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    # Extract group from callback data (format: group_3.1)
    group = query.data.replace('group_', '')
    
    update_chat_config(chat_id, {'group': group})
    await query.message.reply_text(f'✅ Групу змінено на: *{group}*', parse_mode=ParseMode.MARKDOWN)


async def handle_graphs_now_old(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle get graphs now"""
    chat_id = str(update.effective_chat.id)
    config = get_chat_config(chat_id)
    
    region = config.get('region', 'kyiv')
    group = config.get('group', '3.1')
    format_pref = config.get('format_preference', 'image')
    group_formatted = convert_group_to_url_format(group)
    
    # Construct image URL
    image_url = f'{OUTAGE_IMAGES_BASE}{region}/gpv-{group_formatted}-emergency.png'
    
    if format_pref in ['image', 'both']:
        # Send image
        cb = int(time.time() * MILLISECONDS_PER_SECOND)
        photo_url = f'{image_url}?cb={cb}'
        caption = f'⚡️ Графік для черги {group}, регіон: {region}'
        
        try:
            await update.message.reply_photo(photo=photo_url, caption=caption)
        except Exception as e:
            await update.message.reply_text(f'❌ Помилка завантаження зображення: {e}')
    
    if format_pref in ['text', 'both']:
        # Send text (stub - would parse actual schedule)
        today = get_kyiv_datetime()
        tomorrow = today + timedelta(days=1)
        
        today_name = WEEKDAYS_UK[today.weekday()]
        tomorrow_name = WEEKDAYS_UK[tomorrow.weekday()]
        
        text_schedule = f'''💡Оновлено графік відключень на *сьогодні, {today.strftime('%d.%m.%Y')} ({today_name})*, для черги {group}:

🪫 *03:30 - 21:00 (~17.5 год)*

💡Оновлено графік відключень на *завтра, {tomorrow.strftime('%d.%m.%Y')} ({tomorrow_name})*, для черги {group}:

🪫 *00:30 - 04:00 (~3.5 год)*
🪫 *06:00 - 07:30 (~1.5 год)*'''
        
        await update.message.reply_text(text_schedule, parse_mode=ParseMode.MARKDOWN)


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Help screen"""
    keyboard = ReplyKeyboardMarkup(HELP_MENU_KEYBOARD, resize_keyboard=True)
    
    help_text = '''❓ Довідка

🤖 Цей бот допомагає відстежувати:
• Наявність електроенергії (моніторинг)
• Графіки планових відключень

📊 **Статус** - показує поточний стан світла та статистику

💡 **Моніторинг** - керування моніторингом електроенергії

📈 **Графіки** - перегляд графіків відключень

⚙️ **Налаштування** - налаштування бота

Для отримання додаткової допомоги зверніться до адміністратора.'''
    
    await update.message.reply_text(help_text, reply_markup=keyboard)


async def handle_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Settings menu"""
    user_id = update.effective_user.id if update.effective_user else 0
    is_admin = user_id == ADMIN_USER_ID
    
    keyboard = [
        [
            InlineKeyboardButton('🌐 Змінити IP', callback_data='settings_ip'),
            InlineKeyboardButton('🌐 Запасна IP', callback_data='settings_fallback_ip')
        ],
        [
            InlineKeyboardButton('📊 Формат графіків', callback_data='settings_format'),
            InlineKeyboardButton('🗺 Змінити регіон', callback_data='settings_region')
        ],
        [
            InlineKeyboardButton('🔢 Змінити групу', callback_data='settings_group'),
            InlineKeyboardButton('🔕 Сповіщення', callback_data='settings_notifications')
        ],
        [
            InlineKeyboardButton('✏️ Заголовок', callback_data='settings_title'),
            InlineKeyboardButton('📝 Опис каналу', callback_data='settings_description')
        ],
        [InlineKeyboardButton('⚒️ Техпідтримка', callback_data='settings_support')],
        [InlineKeyboardButton('🔴 Тимчасово зупинити канал', callback_data='settings_pause')],
        [InlineKeyboardButton('🗑️ Видалити бота з каналу', callback_data='settings_delete')]
    ]
    
    if is_admin:
        keyboard.append([
            InlineKeyboardButton('⏱ Інтервал світла', callback_data='settings_light_interval'),
            InlineKeyboardButton('⏱ Інтервал графік', callback_data='settings_graph_interval')
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        '⚙️ Налаштування бота\n\nОберіть параметр для зміни:',
        reply_markup=reply_markup
    )


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle settings inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    config = get_chat_config(chat_id)
    
    action = query.data
    
    if action == 'settings_ip':
        await query.message.reply_text(
            '🌐 Введіть нову IP-адресу або DDNS:\n\n'
            'Приклад: 93.127.118.86 або myhost.ddns.net'
        )
        context.user_data['awaiting'] = 'ip'
    
    elif action == 'settings_fallback_ip':
        await query.message.reply_text(
            '🌐 Введіть запасну IP-адресу або DDNS:\n\n'
            'Приклад: 192.168.1.1 або backup.ddns.net'
        )
        context.user_data['awaiting'] = 'fallback_ip'
    
    elif action == 'settings_format':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('🖼 Зображення', callback_data='format_image')],
            [InlineKeyboardButton('📝 Текст', callback_data='format_text')],
            [InlineKeyboardButton('🖼📝 Обидва', callback_data='format_both')]
        ])
        await query.message.reply_text(
            '📊 Оберіть формат графіків:',
            reply_markup=keyboard
        )
    
    elif action == 'settings_region':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('🏛 Київська область', callback_data='region_kyiv-region')],
            [InlineKeyboardButton('🏙 м. Київ', callback_data='region_kyiv')],
            [InlineKeyboardButton('🏭 Дніпро', callback_data='region_dnipro')],
            [InlineKeyboardButton('🌊 Одеса', callback_data='region_odesa')]
        ])
        await query.message.reply_text(
            '🗺 Оберіть регіон:',
            reply_markup=keyboard
        )
    
    elif action == 'settings_group':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('1.1', callback_data='group_1.1'), InlineKeyboardButton('1.2', callback_data='group_1.2')],
            [InlineKeyboardButton('2.1', callback_data='group_2.1'), InlineKeyboardButton('2.2', callback_data='group_2.2')],
            [InlineKeyboardButton('3.1', callback_data='group_3.1'), InlineKeyboardButton('3.2', callback_data='group_3.2')],
            [InlineKeyboardButton('4.1', callback_data='group_4.1'), InlineKeyboardButton('4.2', callback_data='group_4.2')],
            [InlineKeyboardButton('5.1', callback_data='group_5.1'), InlineKeyboardButton('5.2', callback_data='group_5.2')],
            [InlineKeyboardButton('6.1', callback_data='group_6.1'), InlineKeyboardButton('6.2', callback_data='group_6.2')]
        ])
        await query.message.reply_text(
            '🔢 Оберіть номер групи:',
            reply_markup=keyboard
        )
    
    elif action == 'settings_notifications':
        current = config.get('notifications_enabled', True)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ Увімкнути', callback_data='notif_on')],
            [InlineKeyboardButton('❌ Вимкнути', callback_data='notif_off')]
        ])
        await query.message.reply_text(
            f'🔕 Сповіщення зараз: {"✅ Увімкнено" if current else "❌ Вимкнено"}\n\n'
            'Оберіть стан:',
            reply_markup=keyboard
        )
    
    elif action == 'settings_title':
        await query.message.reply_text('✏️ Введіть новий заголовок каналу:')
        context.user_data['awaiting'] = 'title'
    
    elif action == 'settings_description':
        await query.message.reply_text('📝 Введіть новий опис каналу:')
        context.user_data['awaiting'] = 'description'
    
    elif action == 'settings_support':
        await query.message.reply_text(
            '⚒️ Техпідтримка\n\n'
            'З питаннями звертайтесь: @support_username\n'
            'Email: support@example.com'
        )
    
    elif action == 'settings_pause':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('💡 Світло', callback_data='pause_light')],
            [InlineKeyboardButton('📈 Графіки', callback_data='pause_graphs')],
            [InlineKeyboardButton('🔴 Все', callback_data='pause_all')],
            [InlineKeyboardButton('❌ Скасувати', callback_data='pause_cancel')]
        ])
        await query.message.reply_text(
            '🔴 Що призупинити?',
            reply_markup=keyboard
        )
    
    elif action == 'settings_delete':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ Так, видалити', callback_data='delete_confirm')],
            [InlineKeyboardButton('❌ Ні, скасувати', callback_data='delete_cancel')]
        ])
        await query.message.reply_text(
            '⚠️ Ви впевнені, що хочете видалити бота з каналу?\n\n'
            'Всі налаштування будуть втрачені!',
            reply_markup=keyboard
        )
    
    elif action == 'settings_light_interval':
        await query.message.reply_text(
            '⏱ Введіть інтервал перевірки світла (секунди):\n\n'
            'Рекомендовано: 30-60'
        )
        context.user_data['awaiting'] = 'light_interval'
    
    elif action == 'settings_graph_interval':
        await query.message.reply_text(
            '⏱ Введіть інтервал оновлення графіків (секунди):\n\n'
            'Рекомендовано: 60-300'
        )
        context.user_data['awaiting'] = 'graph_interval'


async def handle_format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle format selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    format_map = {
        'format_image': 'image',
        'format_text': 'text',
        'format_both': 'both'
    }
    
    new_format = format_map.get(query.data)
    if new_format:
        update_chat_config(chat_id, {'format_preference': new_format})
        await query.message.reply_text(f'✅ Формат змінено на: {new_format}')


async def handle_notification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle notification callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    if query.data == 'notif_on':
        update_chat_config(chat_id, {'notifications_enabled': True})
        await query.message.reply_text('✅ Сповіщення увімкнено')
    elif query.data == 'notif_off':
        update_chat_config(chat_id, {'notifications_enabled': False})
        await query.message.reply_text('❌ Сповіщення вимкнено')


async def handle_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pause callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    if query.data == 'pause_light':
        update_chat_config(chat_id, {'light_paused': True, 'monitor_enabled': False})
        await query.message.reply_text('⏸️ Моніторинг світла призупинено')
    elif query.data == 'pause_graphs':
        update_chat_config(chat_id, {'graphs_paused': True})
        await query.message.reply_text('⏸️ Оновлення графіків призупинено')
    elif query.data == 'pause_all':
        update_chat_config(chat_id, {
            'light_paused': True,
            'graphs_paused': True,
            'monitor_enabled': False
        })
        await query.message.reply_text('⏸️ Весь канал призупинено')
    elif query.data == 'pause_cancel':
        await query.message.reply_text('❌ Скасовано')


async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    if query.data == 'delete_confirm':
        # Remove config
        config = load_config()
        if chat_id in config:
            del config[chat_id]
            save_config(config)
        
        await query.message.reply_text(
            '✅ Бот видалено з каналу. Всі налаштування скинуто.\n\n'
            'Для повторного використання введіть /start'
        )
    elif query.data == 'delete_cancel':
        await query.message.reply_text('❌ Скасовано')


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for settings"""
    chat_id = str(update.effective_chat.id)
    text = update.message.text
    
    awaiting = context.user_data.get('awaiting')
    if not awaiting:
        # Handle menu buttons
        if text == '📊 Статус':
            await handle_status(update, context)
        elif text == '💡 Моніторинг':
            await handle_monitoring_menu(update, context)
        elif text == '📈 Графіки':
            await handle_graphs_menu(update, context)
        elif text == '⚙️ Налаштування':
            await handle_settings_menu(update, context)
        elif text == '❓ Допомога':
            await handle_help(update, context)
        elif text == '🔙 Головне меню':
            await show_main_menu(update, context)
        elif text == '▶️ Запустити':
            await handle_monitoring_start(update, context)
        elif text == '⏸️ Зупинити':
            await handle_monitoring_stop(update, context)
        elif text == '📊 Статистика':
            await handle_monitoring_stats(update, context)
        elif text == '📥 Отримати зараз':
            await handle_graphs_now(update, context)
        elif text == '📅 Мій графік':
            config = get_chat_config(chat_id)
            group = config.get('group', '3.1')
            region = config.get('region', 'kyiv')
            region_name = REGIONS_MAP.get(region, region)
            await update.message.reply_text(
                f'📅 Ваш регіон: *{region_name}*\n📅 Ваша група: *{group}*\n\nГрафік оновлюється автоматично.',
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Process input based on what we're awaiting
    if awaiting == 'ip':
        update_chat_config(chat_id, {'monitor_host': text.strip()})
        await update.message.reply_text(f'✅ IP-адресу змінено на: {text.strip()}')
    elif awaiting == 'fallback_ip':
        update_chat_config(chat_id, {'fallback_host': text.strip()})
        await update.message.reply_text(f'✅ Запасну IP-адресу змінено на: {text.strip()}')
    elif awaiting == 'region':
        update_chat_config(chat_id, {'region': text.strip().lower()})
        await update.message.reply_text(f'✅ Регіон змінено на: {text.strip()}')
    elif awaiting == 'group':
        update_chat_config(chat_id, {'group': text.strip()})
        await update.message.reply_text(f'✅ Групу змінено на: {text.strip()}')
    elif awaiting == 'title':
        update_chat_config(chat_id, {'channel_title': text.strip()})
        # Try to update channel title via Telegram API
        try:
            await context.bot.set_chat_title(chat_id=chat_id, title=text.strip())
            await update.message.reply_text(f'✅ Заголовок каналу змінено')
        except Exception as e:
            await update.message.reply_text(f'✅ Заголовок збережено, але не вдалося змінити в Telegram: {e}')
    elif awaiting == 'description':
        update_chat_config(chat_id, {'channel_description': text.strip()})
        # Try to update channel description via Telegram API
        try:
            await context.bot.set_chat_description(chat_id=chat_id, description=text.strip())
            await update.message.reply_text(f'✅ Опис каналу змінено')
        except Exception as e:
            await update.message.reply_text(f'✅ Опис збережено, але не вдалося змінити в Telegram: {e}')
    elif awaiting == 'light_interval':
        try:
            interval = int(text.strip())
            update_chat_config(chat_id, {'light_check_interval': interval})
            await update.message.reply_text(f'✅ Інтервал світла змінено на: {interval}с')
        except ValueError:
            await update.message.reply_text('❌ Невірне значення. Введіть число.')
            return
    elif awaiting == 'graph_interval':
        try:
            interval = int(text.strip())
            update_chat_config(chat_id, {'graph_check_interval': interval})
            await update.message.reply_text(f'✅ Інтервал графіків змінено на: {interval}с')
        except ValueError:
            await update.message.reply_text('❌ Невірне значення. Введіть число.')
            return
    
    context.user_data['awaiting'] = None


# ============================================================================
# Monitoring Thread
# ============================================================================

class MonitorThread(threading.Thread):
    """Background thread for power monitoring"""
    
    def __init__(self, application, event_loop):
        super().__init__(daemon=True)
        self.running = True
        self.application = application
        self.event_loop = event_loop
    
    def stop(self):
        self.running = False
    
    async def send_status_notification(self, chat_id: str, new_status: str, last_change_time: int):
        """Send power status change notification with randomized phrases"""
        current_time = get_kyiv_time()
        duration = int(time.time() * MILLISECONDS_PER_SECOND) - last_change_time
        formatted_duration = format_duration_short(duration)
        
        # Get config for schedule info
        config = get_chat_config(chat_id)
        
        # TODO: Parse actual schedule and find next outage
        # For now, using placeholder times
        next_outage_time = '00:30 - 04:00'
        expected_time = '18:00'
        
        if new_status == 'online':
            phrase = get_random_phrase(PHRASES_POWER_APPEARED_BASE, PHRASES_POWER_APPEARED_VARIATIONS)
            message = f'*🟢 {current_time} Світло з\'явилося*\n🕓 {phrase} {formatted_duration}\n🗓 Наступне планове: *{next_outage_time}*'
        else:
            phrase = get_random_phrase(PHRASES_POWER_GONE_BASE, PHRASES_POWER_GONE_VARIATIONS)
            message = f'*🔴 {current_time} Світло зникло*\n🕓 {phrase} {formatted_duration}\n🗓 Очікуємо за графіком о *{expected_time}*'
        
        try:
            await self.application.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
            print(f'Status notification sent to {chat_id}: {new_status}')
        except Exception as e:
            print(f'ERROR sending notification to {chat_id}: {e}')
    
    def run(self):
        """Main monitoring loop"""
        print('Monitor thread started')
        
        while self.running:
            try:
                config = load_config()
                
                for chat_id, settings in config.items():
                    if not settings.get('monitor_enabled') or settings.get('light_paused'):
                        continue
                    
                    host = settings.get('monitor_host', DEFAULT_HOST)
                    port = settings.get('monitor_port', DEFAULT_PORT)
                    interval = settings.get('light_check_interval', DEFAULT_INTERVAL)
                    
                    # Check status
                    is_online = check_tcp_connection(host, port)
                    new_status = 'online' if is_online else 'offline'
                    
                    current_time = get_kyiv_time()
                    print(f'[{current_time}] Monitor {chat_id}: {host}:{port} -> {new_status}')
                    
                    # Detect state change
                    previous_status = settings.get('monitor_last_status')
                    last_change = settings.get('monitor_last_change', int(time.time() * MILLISECONDS_PER_SECOND))
                    
                    if previous_status and previous_status != new_status:
                        # Status changed!
                        print(f'Status changed for {chat_id}: {previous_status} -> {new_status}')
                        
                        # Send notification using the application's event loop
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                self.send_status_notification(chat_id, new_status, last_change),
                                self.event_loop
                            )
                            # Wait for completion with timeout to catch errors
                            future.result(timeout=10)
                        except Exception as e:
                            print(f'ERROR in notification: {e}')
                        
                        # Update state
                        settings['monitor_last_status'] = new_status
                        settings['monitor_last_change'] = int(time.time() * MILLISECONDS_PER_SECOND)
                        config[chat_id] = settings
                        save_config(config)
                    elif not previous_status:
                        # First check - initialize without notification
                        print(f'Initializing monitor state for {chat_id}: {new_status}')
                        settings['monitor_last_status'] = new_status
                        settings['monitor_last_change'] = int(time.time() * MILLISECONDS_PER_SECOND)
                        config[chat_id] = settings
                        save_config(config)
                
                # Sleep for the shortest interval among all monitored chats
                time.sleep(DEFAULT_INTERVAL)
            
            except Exception as e:
                print(f'ERROR in monitor thread: {e}')
                time.sleep(DEFAULT_INTERVAL)
        
        print('Monitor thread stopped')


# ============================================================================
# Graphenko Update Thread
# ============================================================================

class GraphenkoThread(threading.Thread):
    """Background thread for periodic Graphenko image updates"""
    
    def __init__(self, application, event_loop):
        super().__init__(daemon=True)
        self.running = True
        self.application = application
        self.event_loop = event_loop
    
    def stop(self):
        self.running = False
    
    async def send_graph_update(self, chat_id: str, settings: Dict):
        """Send graph update to a chat - only if image hash changed"""
        # Skip private chats - only send to channels/groups
        try:
            chat_id_int = int(chat_id)
            if chat_id_int > 0:
                print(f'Skipping private chat {chat_id} for graph updates')
                return
        except (ValueError, TypeError):
            # If chat_id is not numeric (e.g., test data), skip validation
            print(f'Warning: Non-numeric chat_id {chat_id}, proceeding with update')
        
        region = settings.get('region', 'kyiv')
        group = settings.get('group', '3.1')
        format_pref = settings.get('format_preference', 'image')
        group_formatted = convert_group_to_url_format(group)
        
        # Log region for diagnostics
        print(f'Using region: {region} for chat {chat_id}')
        
        image_url = f'{OUTAGE_IMAGES_BASE}{region}/gpv-{group_formatted}-emergency.png'
        
        # Fetch image and compute hash to check if it changed
        try:
            response = requests.get(image_url, timeout=30, verify=True)
            if response.status_code != 200:
                print(f'Failed to fetch image for {chat_id}: HTTP {response.status_code}')
                return
            
            new_hash = hashlib.md5(response.content).hexdigest()
        except Exception as e:
            print(f'Error fetching image for {chat_id}: {e}')
            return
        
        # Compare with previous hash
        last_hash = settings.get('last_graph_hash')
        if new_hash == last_hash:
            # Graph hasn't changed - skip update
            print(f'Graph unchanged for {chat_id}, skipping update')
            return
        
        # Graph changed - publish update
        print(f'Graph changed for {chat_id}, publishing update')
        
        # Update hash in config
        update_chat_config(chat_id, {'last_graph_hash': new_hash})
        
        try:
            if format_pref in ['image', 'both']:
                # Prepare caption with Ukrainian weekday names
                today = get_kyiv_datetime()
                tomorrow = today + timedelta(days=1)
                
                today_name = WEEKDAYS_UK[today.weekday()]
                tomorrow_name = WEEKDAYS_UK[tomorrow.weekday()]
                
                region_name = REGIONS_MAP.get(region, region)
                
                caption = (
                    f'💡Оновлено графік відключень на сьогодні, {today.strftime("%d.%m.%Y")} ({today_name}), '
                    f'для черги {group}'
                )
                
                # Send new photo (not edit) with cache buster
                cb = int(time.time() * MILLISECONDS_PER_SECOND)
                photo_url = f'{image_url}?cb={cb}'
                
                await self.application.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url,
                    caption=caption
                )
            
            if format_pref in ['text', 'both']:
                # Send text schedule
                today = get_kyiv_datetime()
                tomorrow = today + timedelta(days=1)
                
                today_name = WEEKDAYS_UK[today.weekday()]
                tomorrow_name = WEEKDAYS_UK[tomorrow.weekday()]
                
                text_schedule = f'''💡Оновлено графік відключень на *сьогодні, {today.strftime('%d.%m.%Y')} ({today_name})*, для черги {group}:

🪫 *03:30 - 21:00 (~17.5 год)*

💡Оновлено графік відключень на *завтра, {tomorrow.strftime('%d.%m.%Y')} ({tomorrow_name})*, для черги {group}:

🪫 *00:30 - 04:00 (~3.5 год)*
🪫 *06:00 - 07:30 (~1.5 год)*'''
                
                await self.application.bot.send_message(chat_id=chat_id, text=text_schedule, parse_mode=ParseMode.MARKDOWN)
        
        except Exception as e:
            print(f'ERROR sending graph update to {chat_id}: {e}')
    
    def run(self):
        """Main Graphenko update loop"""
        print('Graphenko thread started')
        
        first_run = True
        
        while self.running:
            try:
                if not first_run:
                    # Calculate minimum interval across all chats
                    config = load_config()
                    if config:
                        min_interval = min(
                            settings.get('graph_check_interval', GRAPHENKO_UPDATE_INTERVAL)
                            for settings in config.values()
                        )
                    else:
                        min_interval = GRAPHENKO_UPDATE_INTERVAL
                    
                    print(f'Sleeping for {min_interval} seconds until next graph check')
                    time.sleep(min_interval)
                first_run = False
                
                config = load_config()
                for chat_id, settings in config.items():
                    if settings.get('graphs_paused'):
                        continue
                    
                    image_url = settings.get('image_url')
                    if not image_url and not settings.get('region'):
                        continue
                    
                    # Send update using the application's event loop
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.send_graph_update(chat_id, settings),
                            self.event_loop
                        )
                        # Wait for completion with timeout to catch errors
                        future.result(timeout=30)
                    except Exception as e:
                        print(f'ERROR in graph update: {e}')
                    
                    time.sleep(1)  # Rate limiting
            
            except Exception as e:
                print(f'ERROR in Graphenko thread: {e}')
        
        print('Graphenko thread stopped')


# ============================================================================
# Main
# ============================================================================

def main():
    """Main bot function"""
    print('Starting DTEK Bot with interactive UX...')
    print(f'Bot token: {BOT_TOKEN[:10]}...')
    print(f'Config file: {CONFIG_FILE}')
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(handle_settings_callback, pattern='^settings_'))
    application.add_handler(CallbackQueryHandler(handle_format_callback, pattern='^format_'))
    application.add_handler(CallbackQueryHandler(handle_notification_callback, pattern='^notif_'))
    application.add_handler(CallbackQueryHandler(handle_pause_callback, pattern='^pause_'))
    application.add_handler(CallbackQueryHandler(handle_delete_callback, pattern='^delete_'))
    application.add_handler(CallbackQueryHandler(handle_graph_type_callback, pattern='^graph_type_'))
    application.add_handler(CallbackQueryHandler(handle_region_callback, pattern='^region_'))
    application.add_handler(CallbackQueryHandler(handle_group_callback, pattern='^group_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    # Get or create the event loop for the current thread
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Start background threads with event loop
    monitor_thread = MonitorThread(application, loop)
    monitor_thread.start()
    
    graphenko_thread = GraphenkoThread(application, loop)
    graphenko_thread.start()
    
    # Run bot
    try:
        print('Bot started successfully!')
        application.run_polling(allowed_updates=['message', 'callback_query', 'my_chat_member'])
    except KeyboardInterrupt:
        print('\nStopping bot...')
        monitor_thread.stop()
        graphenko_thread.stop()
        print('Bot stopped')


if __name__ == '__main__':
    main()
