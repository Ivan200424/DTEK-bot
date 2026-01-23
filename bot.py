#!/usr/bin/env python3
"""
DTEK Bot - Interactive Telegram Bot for Power Monitoring and Graphenko Updates
Features: TCP monitoring, Graphenko updates, interactive menu-based UX
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sys
import threading
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

try:
    import requests
except ImportError:
    print('ERROR: requests library not found. Install with: pip install requests>=2.31.0')
    sys.exit(1)

try:
    from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, ContextTypes, filters
    from telegram.constants import ParseMode, ChatMemberStatus
    from telegram.error import TelegramError
except ImportError:
    print('ERROR: python-telegram-bot library not found. Install with: pip install python-telegram-bot>=20.0,<21.0')
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot version
BOT_VERSION = '2.1.0'

# Configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
DEFAULT_CHAT_ID = os.getenv('CHAT_ID', '-1003523279109')
CONFIG_FILE = 'graphenko-chats.json'
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '1026177113'))

# Backup settings
BACKUP_DIR = 'backups'
MAX_BACKUPS = 10  # Keep only the last 10 backups

# Support contacts (configure via environment variables)
SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', '@Ivan200424')
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'support@example.com')

# Constants
DEFAULT_HOST = '93.127.118.86'
DEFAULT_PORT = 443
DEFAULT_INTERVAL = 30
GRAPHENKO_UPDATE_INTERVAL = 60  # Default: 1 minute (configurable per-chat via graph_check_interval)
OUTAGE_IMAGES_BASE = 'https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/images/'
OUTAGE_DATA_BASE = 'https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/'
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

# Debounce settings (from environment or defaults)
DEBOUNCE_SECONDS = int(os.getenv('DEBOUNCE_SECONDS', '300'))  # 5 minutes default

# Rate limiting settings
RATE_LIMIT_COMMANDS = int(os.getenv('RATE_LIMIT_COMMANDS', '10'))  # Maximum commands
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '60'))    # Per 60 seconds

# Healthcheck settings
HEALTHCHECK_PORT = int(os.getenv('HEALTHCHECK_PORT', '8080'))

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

# Menu keyboards - base keyboards without dynamic buttons
MAIN_MENU_KEYBOARD_BASE = [
    ['📊 Статус', '💡 Моніторинг'],
    ['📈 Графіки'],
    ['🌐 IP', '🗺 Регіон і Група'],
    ['🔔 Сповіщення', '⏱ Інтервали'],
    ['✏️ Заголовок / Опис каналу'],
    ['➕ Додати канал'],
    ['⚒️ Техпідтримка', '🗑️ Видалити бота'],
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

# Thread-safe configuration lock
_config_lock = threading.Lock()

# Rate limiting
from collections import defaultdict
_user_command_times: Dict[int, list] = defaultdict(list)
_rate_limit_lock = threading.Lock()


# Keep backward compatibility
MAIN_MENU_KEYBOARD = MAIN_MENU_KEYBOARD_BASE

# ============================================================================
# Configuration Management
# ============================================================================

def load_config() -> Dict[str, Dict]:
    """Load configuration from JSON file (thread-safe)"""
    with _config_lock:
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
            logger.error(f'Failed to load config: {e}')
            return {}


def create_backup():
    """Create a backup of the config file"""
    if not os.path.exists(CONFIG_FILE):
        return
    
    # Create backup directory if not exists
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    # Generate backup filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BACKUP_DIR, f'config_backup_{timestamp}.json')
    
    try:
        shutil.copy2(CONFIG_FILE, backup_file)
        logger.info(f'Backup created: {backup_file}')
        
        # Clean old backups (keep only MAX_BACKUPS)
        cleanup_old_backups()
    except Exception as e:
        logger.error(f'Failed to create backup: {e}')


def cleanup_old_backups():
    """Remove old backups, keep only MAX_BACKUPS most recent"""
    if not os.path.exists(BACKUP_DIR):
        return
    
    backups = sorted([
        os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
        if f.startswith('config_backup_') and f.endswith('.json')
    ], key=os.path.getmtime, reverse=True)
    
    for old_backup in backups[MAX_BACKUPS:]:
        try:
            os.remove(old_backup)
            logger.info(f'Removed old backup: {old_backup}')
        except Exception as e:
            logger.error(f'Failed to remove old backup {old_backup}: {e}')


def save_config(config: Dict[str, Dict]) -> bool:
    """Save configuration to JSON file (thread-safe with backup)"""
    with _config_lock:
        try:
            # Create backup before saving
            create_backup()
            
            # Convert to array format matching the original schema
            data = []
            for chat_id in sorted(config.keys()):
                data.append({chat_id: config[chat_id]})
            
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write('\n')
            return True
        except Exception as e:
            logger.error(f'Failed to save config: {e}')
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
# Keyboard Helper Functions
# ============================================================================

def is_channel_paused(chat_id: str) -> bool:
    """Check if channel is paused"""
    config = get_chat_config(chat_id)
    return config.get('light_paused', False) and config.get('graphs_paused', False)


def get_pause_resume_button_text(chat_id: str) -> str:
    """Get the appropriate pause/resume button text based on current state"""
    if is_channel_paused(chat_id):
        return '✅ Відновити роботу каналу'
    else:
        return '🔴 Тимчасово зупинити канал'


def build_settings_keyboard(chat_id: str) -> list:
    """Build settings menu keyboard with dynamic pause/resume button"""
    pause_resume_text = get_pause_resume_button_text(chat_id)
    
    # Copy base keyboard and insert pause/resume button
    keyboard = [row[:] for row in MAIN_MENU_KEYBOARD_BASE]  # Deep copy of rows
    keyboard.insert(6, [pause_resume_text])  # Insert before "⚒️ Техпідтримка і 🗑️ Видалити бота"
    return keyboard


async def toggle_channel_pause(update: Update, chat_id: str, pause: bool):
    """Helper function to pause or resume channel and update keyboard"""
    if pause:
        # Pause entire channel
        update_chat_config(chat_id, {
            'light_paused': True,
            'graphs_paused': True,
            'monitor_enabled': False
        })
        message = '⏸️ Канал призупинено. Моніторинг та оновлення графіків вимкнено.'
    else:
        # Resume channel operation
        update_chat_config(chat_id, {
            'light_paused': False,
            'graphs_paused': False,
            'monitor_enabled': True
        })
        message = '✅ Канал відновлено. Моніторинг та оновлення графіків увімкнено.'
    
    # Update reply keyboard with new button state
    reply_keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
    await update.message.reply_text(message, reply_markup=reply_keyboard)


def build_region_keyboard() -> InlineKeyboardMarkup:
    """Build region selection keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🏛 Київська область', callback_data='region_kyiv-region')],
        [InlineKeyboardButton('🏙 м. Київ', callback_data='region_kyiv')],
        [InlineKeyboardButton('🏭 Дніпро', callback_data='region_dnipro')],
        [InlineKeyboardButton('🌊 Одеса', callback_data='region_odesa')]
    ])


def build_group_keyboard() -> InlineKeyboardMarkup:
    """Build group selection keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('1.1', callback_data='group_1.1'), InlineKeyboardButton('1.2', callback_data='group_1.2')],
        [InlineKeyboardButton('2.1', callback_data='group_2.1'), InlineKeyboardButton('2.2', callback_data='group_2.2')],
        [InlineKeyboardButton('3.1', callback_data='group_3.1'), InlineKeyboardButton('3.2', callback_data='group_3.2')],
        [InlineKeyboardButton('4.1', callback_data='group_4.1'), InlineKeyboardButton('4.2', callback_data='group_4.2')],
        [InlineKeyboardButton('5.1', callback_data='group_5.1'), InlineKeyboardButton('5.2', callback_data='group_5.2')],
        [InlineKeyboardButton('6.1', callback_data='group_6.1'), InlineKeyboardButton('6.2', callback_data='group_6.2')]
    ])


def build_format_keyboard() -> InlineKeyboardMarkup:
    """Build format selection keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🖼 Зображення', callback_data='format_image')],
        [InlineKeyboardButton('📝 Текст', callback_data='format_text')],
        [InlineKeyboardButton('🖼📝 Обидва', callback_data='format_both')]
    ])


def build_notification_keyboard() -> InlineKeyboardMarkup:
    """Build notification toggle keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ Увімкнути', callback_data='notif_on')],
        [InlineKeyboardButton('❌ Вимкнути', callback_data='notif_off')]
    ])


def build_delete_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Build delete confirmation keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ Так, видалити', callback_data='delete_confirm')],
        [InlineKeyboardButton('❌ Ні, скасувати', callback_data='delete_cancel')]
    ])


# ============================================================================
# Utility Functions
# ============================================================================

def is_valid_ip_or_hostname(value: str) -> bool:
    """Validate IP address or hostname/DDNS"""
    # IPv4 pattern - must have exactly 4 octets
    ipv4_pattern = r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$'
    # Hostname pattern - basic DNS validation (alphanumeric, hyphens, dots)
    hostname_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
    
    # Try IPv4 first
    ipv4_match = re.match(ipv4_pattern, value)
    if ipv4_match:
        # Validate each octet is within valid range
        try:
            octets = [int(g) for g in ipv4_match.groups()]
            return all(0 <= octet <= 255 for octet in octets)
        except (ValueError, AttributeError):
            return False
    
    # Check if it looks like a malformed IP (has 3 dots, likely intended as IP)
    if value.count('.') == 3:
        # If it has 3 dots but didn't match IPv4 pattern, it's invalid
        return False
    
    # Validate hostname format
    return bool(re.match(hostname_pattern, value))


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


def fetch_outage_schedule(region: str, group: str) -> Optional[Dict]:
    """Fetch outage schedule data from Baskerville42/outage-data-ua repository"""
    url = f'{OUTAGE_DATA_BASE}{region}.json'
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError as json_error:
                logger.error(f'Error parsing JSON from outage schedule: {json_error}')
                return None
    except Exception as e:
        logger.error(f'Error fetching outage schedule: {e}')
    return None


def parse_outage_periods(schedule_data: Dict, group: str, target_date: datetime) -> List[str]:
    """Parse outage periods for a specific group and date
    
    Returns list of formatted periods like "03:30 - 21:00 (~17.5 год)"
    """
    # Конвертувати групу з формату "3.1" в "GPV3.1"
    # Ключі в JSON мають формат "GPV3.1" з крапкою
    group_key = f'GPV{group}'
    
    # Знайти дані для потрібної дати
    # Timestamp для початку дня (00:00 Kyiv time)
    # JSON використовує UTC timestamp, потрібно врахувати часовий пояс Києва
    kyiv_offset_hours = calculate_kyiv_offset()
    target_timestamp = int(datetime(target_date.year, target_date.month, target_date.day, 0, 0).timestamp()) - kyiv_offset_hours * 3600
    target_key = str(target_timestamp)
    
    if 'fact' not in schedule_data or 'data' not in schedule_data['fact']:
        return []
    
    day_data = schedule_data['fact']['data'].get(target_key)
    if not day_data or group_key not in day_data:
        return []
    
    hours_data = day_data[group_key]
    
    # Парсити години - знаходити послідовності "no" або "maybe"
    periods = []
    start_hour = None
    
    for hour in range(1, 25):
        hour_str = str(hour)
        status = hours_data.get(hour_str, 'yes')
        
        # Вважаємо "no" та "maybe" як відключення
        is_outage = status in ['no', 'maybe']
        
        if is_outage and start_hour is None:
            start_hour = hour
        elif not is_outage and start_hour is not None:
            # Закінчити період
            end_hour = hour
            periods.append((start_hour, end_hour))
            start_hour = None
    
    # Якщо період триває до кінця дня
    if start_hour is not None:
        periods.append((start_hour, 25))
    
    # Форматувати як "HH:30 - HH:00 (~X.X год)"
    # Примітка: кожна година починається з :30 попередньої години
    # Наприклад: година "4" = 03:30-04:30
    formatted_periods = []
    for start, end in periods:
        # start=4 means 03:30
        start_time = f'{(start-1):02d}:30'
        # end=21 means 21:00
        if end == 25:
            end_time = '24:00'
        else:
            end_time = f'{(end-1):02d}:30'
        
        # Розрахувати тривалість
        duration_hours = end - start
        if duration_hours == int(duration_hours):
            duration_str = f'~{int(duration_hours)} год'
        else:
            duration_str = f'~{duration_hours} год'
        
        formatted_periods.append(f'{start_time} - {end_time} ({duration_str})')
    
    return formatted_periods


def format_schedule_text(region: str, group: str) -> str:
    """Format complete schedule text for today and tomorrow"""
    schedule_data = fetch_outage_schedule(region, group)
    if not schedule_data:
        return ""
    
    today = get_kyiv_datetime()
    tomorrow = today + timedelta(days=1)
    
    today_name = WEEKDAYS_UK[today.weekday()]
    tomorrow_name = WEEKDAYS_UK[tomorrow.weekday()]
    
    # Парсити періоди для сьогодні
    today_periods = parse_outage_periods(schedule_data, group, today)
    
    # Парсити періоди для завтра
    tomorrow_periods = parse_outage_periods(schedule_data, group, tomorrow)
    
    text = f'💡Оновлено графік відключень на сьогодні, {today.strftime("%d.%m.%Y")} ({today_name}), для черги {group}:\n\n'
    
    if today_periods:
        for period in today_periods:
            text += f'🪫 {period}\n'
    else:
        text += '✅ Відключень не заплановано\n'
    
    # Only add tomorrow section if data is available
    if tomorrow_periods:
        text += f'\n💡Оновлено графік відключень на завтра, {tomorrow.strftime("%d.%m.%Y")} ({tomorrow_name}), для черги {group}:\n\n'
        for period in tomorrow_periods:
            text += f'🪫 {period}\n'
    
    return text


def check_rate_limit(user_id: int) -> bool:
    """Check if user is within rate limit. Returns True if allowed."""
    with _rate_limit_lock:
        current_time = time.time()
        
        # Clean old entries
        _user_command_times[user_id] = [
            t for t in _user_command_times[user_id]
            if current_time - t < RATE_LIMIT_WINDOW
        ]
        
        # Check limit
        if len(_user_command_times[user_id]) >= RATE_LIMIT_COMMANDS:
            return False
        
        # Record this command
        _user_command_times[user_id].append(current_time)
        return True


async def rate_limit_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check rate limit before processing. Returns True if blocked."""
    user = update.effective_user
    if not user:
        return False
    
    if not check_rate_limit(user.id):
        await update.message.reply_text(
            '⚠️ Занадто багато запитів! Будь ласка, зачекайте хвилину.'
        )
        return True
    return False


def check_tcp_connection(host: str, port: int, timeout: int = 5) -> bool:
    """Check if TCP connection to host:port succeeds"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            return result == 0
    except Exception as e:
        logger.error(f'TCP check failed for {host}:{port}: {e}')
        return False


def check_tcp_connection_with_retry(host: str, port: int, retries: int = 3, delay: float = 2.0, timeout: int = 5) -> bool:
    """Check TCP connection with retry logic to avoid false positives"""
    for attempt in range(retries):
        if check_tcp_connection(host, port, timeout):
            return True
        if attempt < retries - 1:
            logger.debug(f'TCP check attempt {attempt + 1} failed for {host}:{port}, retrying in {delay}s...')
            time.sleep(delay)
    return False


# ============================================================================
# Menu Handlers
# ============================================================================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu"""
    chat_id = str(update.effective_chat.id)
    keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
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
    
    keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
    
    welcome_text = (
        f'👋 Вітаю, {user.full_name if user else "користувач"}!\n\n'
        '🤖 Це бот для моніторингу електроенергії та графіків відключень.\n\n'
        'Оберіть опцію з меню:\n\n'
        f'_Версія: {BOT_VERSION}_'
    )
    
    await update.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command - exit from any awaiting state"""
    if context.user_data.get('awaiting'):
        context.user_data['awaiting'] = None
        chat_id = str(update.effective_chat.id)
        keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
        await update.message.reply_text(
            '❌ Операцію скасовано. Повертаємось до головного меню.',
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text('ℹ️ Немає активної операції для скасування.')


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bot being added/removed from chat or channel"""
    try:
        # Get the chat member update
        my_chat_member = update.my_chat_member
        if not my_chat_member:
            return
        
        chat = my_chat_member.chat
        new_status = my_chat_member.new_chat_member.status
        old_status = my_chat_member.old_chat_member.status
        
        # Check if bot was added to a channel as administrator
        if (chat.type == 'channel' and 
            new_status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER] and 
            old_status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]):
            chat_id = str(chat.id)
            logger.info(f'Bot added to channel: {chat.title} (ID: {chat_id})')
            
            # Initialize or update config for this channel
            update_chat_config(chat_id, {
                'channel_title': chat.title or '',
                'channel_description': chat.description or '',
                'last_updated': datetime.now(timezone.utc).isoformat()
            })
            
            # Try to send a confirmation message if possible
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f'✅ Бот успішно додано до каналу "{chat.title}"!\n\n'
                         f'Chat ID каналу ({chat_id}) збережено в конфігурації.\n\n'
                         'Тепер ви можете використовувати меню для налаштування моніторингу та графіків.'
                )
            except Exception as e:
                logger.warning(f'Could not send confirmation to channel {chat_id}: {e}')
                
        elif (chat.type == 'channel' and 
              new_status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED] and 
              old_status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]):
            chat_id = str(chat.id)
            logger.info(f'Bot removed from channel: {chat.title} (ID: {chat_id})')
            
    except Exception as e:
        logger.error(f'Error in handle_my_chat_member: {e}')


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
    
    # Creation date
    creation_date = config.get('creation_date')
    if creation_date:
        try:
            created_dt = datetime.fromisoformat(creation_date)
            creation_str = created_dt.strftime('%Y-%m-%d %H:%M:%S')
            days_ago = (datetime.now(timezone.utc) - created_dt).days
            creation_text = f'{creation_str}, ({days_ago}д тому)'
        except Exception:
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
📅 Дата створення каналу:
    {creation_text}
👤 Кількість юзерів у каналі: {user_count}
👨‍💻 Автор телеграм каналу:
      Ім'я: {author_name}
      Username: @{author_username}
      Telegram ID: {author_id}

🤖 Версія бота: {BOT_VERSION}'''
    
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
    
    # Show group selection inline keyboard for step 2
    keyboard = build_group_keyboard()
    await query.message.reply_text(
        f'✅ Регіон змінено на: *{region_name}*\n\n'
        'Крок 2 з 3: Оберіть номер групи:',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


async def handle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle group selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    # Extract group from callback data (format: group_3.1)
    group = query.data.replace('group_', '')
    
    update_chat_config(chat_id, {'group': group})
    
    # Show format selection inline keyboard for step 3
    keyboard = build_format_keyboard()
    await query.message.reply_text(
        f'✅ Групу змінено на: *{group}*\n\n'
        'Крок 3 з 3: Оберіть формат графіків:',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


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
    """Handle Settings menu - now redirects to main menu with all settings buttons"""
    chat_id = str(update.effective_chat.id)
    
    # Build reply keyboard with dynamic pause/resume button and all settings
    reply_keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
    
    # Get pause status for the message
    pause_status = '⏸️ Призупинено' if is_channel_paused(chat_id) else '▶️ Активний'
    
    # Message explaining the new interface
    settings_text = f'''⚙️ Налаштування бота

Статус каналу: {pause_status}

Використовуйте кнопки нижче для керування налаштуваннями:

🌐 IP - змінити IP-адресу моніторингу
🗺 Регіон і Група - налаштувати регіон, групу та формат графіків
🔔 Сповіщення - увімкнути/вимкнути сповіщення
⏱ Інтервали - налаштувати інтервали перевірки
✏️ Заголовок / Опис каналу - змінити назву та опис
⚒️ Техпідтримка - контакти підтримки
🗑️ Видалити бота - видалити всі налаштування'''
    
    await update.message.reply_text(
        settings_text,
        reply_markup=reply_keyboard
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
    
    elif action == 'settings_format':
        keyboard = build_format_keyboard()
        await query.message.reply_text(
            '📊 Оберіть формат графіків:',
            reply_markup=keyboard
        )
    
    elif action == 'settings_region':
        keyboard = build_region_keyboard()
        await query.message.reply_text(
            '🗺 Оберіть регіон:',
            reply_markup=keyboard
        )
    
    elif action == 'settings_group':
        keyboard = build_group_keyboard()
        await query.message.reply_text(
            '🔢 Оберіть номер групи:',
            reply_markup=keyboard
        )
    
    elif action == 'settings_notifications':
        current = config.get('notifications_enabled', True)
        keyboard = build_notification_keyboard()
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
            f'З питаннями звертайтесь: {SUPPORT_USERNAME}\n'
            f'Email: {SUPPORT_EMAIL}'
        )
    
    elif action == 'settings_delete':
        keyboard = build_delete_confirmation_keyboard()
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
    
    format_display = {
        'format_image': '🖼 Зображення',
        'format_text': '📝 Текст',
        'format_both': '🖼📝 Обидва'
    }
    
    new_format = format_map.get(query.data)
    if new_format:
        update_chat_config(chat_id, {'format_preference': new_format})
        # Refresh keyboard after changes
        keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
        await query.message.reply_text(
            f'✅ Формат змінено на: {format_display.get(query.data, new_format)}\n\n'
            'Налаштування регіону, групи та формату збережено.',
            reply_markup=keyboard
        )


async def handle_notification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle notification callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    
    if query.data == 'notif_on':
        update_chat_config(chat_id, {'notifications_enabled': True})
        message = '✅ Сповіщення увімкнено'
    elif query.data == 'notif_off':
        update_chat_config(chat_id, {'notifications_enabled': False})
        message = '❌ Сповіщення вимкнено'
    
    # Refresh keyboard after changes
    keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
    await query.message.reply_text(message, reply_markup=keyboard)



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
        
        # Refresh keyboard after deletion
        keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
        await query.message.reply_text(
            '✅ Бот видалено з каналу. Всі налаштування скинуто.\n\n'
            'Для повторного використання введіть /start',
            reply_markup=keyboard
        )
    elif query.data == 'delete_cancel':
        # Refresh keyboard after cancellation
        keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
        await query.message.reply_text('❌ Скасовано', reply_markup=keyboard)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for settings"""
    # Rate limit check
    if await rate_limit_middleware(update, context):
        return
    
    chat_id = str(update.effective_chat.id)
    text = update.message.text
    
    # Check for cancel button first
    if text == '❌ Скасувати':
        await cancel(update, context)
        return
    
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
        elif text == '🔴 Тимчасово зупинити канал':
            await toggle_channel_pause(update, chat_id, pause=True)
        elif text == '✅ Відновити роботу каналу':
            await toggle_channel_pause(update, chat_id, pause=False)
        elif text == '🌐 IP':
            # Start IP configuration flow
            await update.message.reply_text(
                '🌐 Налаштування IP-адреси\n\n'
                'Введіть IP-адресу або DDNS:\n\n'
                'Приклад: 93.127.118.86 або myhost.ddns.net'
            )
            context.user_data['awaiting'] = 'ip'
        elif text == '🗺 Регіон і Група':
            # Start region/group/format configuration flow
            keyboard = build_region_keyboard()
            await update.message.reply_text(
                '🗺 Налаштування регіону, групи та формату графіків\n\n'
                'Крок 1 з 3: Оберіть регіон:',
                reply_markup=keyboard
            )
        elif text == '🔔 Сповіщення':
            config = get_chat_config(chat_id)
            current = config.get('notifications_enabled', True)
            keyboard = build_notification_keyboard()
            await update.message.reply_text(
                f'🔔 Сповіщення зараз: {"✅ Увімкнено" if current else "❌ Вимкнено"}\n\n'
                'Оберіть стан:',
                reply_markup=keyboard
            )
        elif text == '⏱ Інтервали':
            user_id = update.effective_user.id if update.effective_user else 0
            is_admin = user_id == ADMIN_USER_ID
            
            if not is_admin:
                await update.message.reply_text('❌ Доступ заборонено. Тільки для адміністраторів.')
            else:
                config = get_chat_config(chat_id)
                light_interval = config.get('light_check_interval', DEFAULT_INTERVAL)
                graph_interval = config.get('graph_check_interval', GRAPHENKO_UPDATE_INTERVAL)
                
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton('⏱ Інтервал світла', callback_data='settings_light_interval')],
                    [InlineKeyboardButton('⏱ Інтервал графік', callback_data='settings_graph_interval')]
                ])
                await update.message.reply_text(
                    f'⏱ Поточні інтервали:\n\n'
                    f'Світло: {light_interval}с\n'
                    f'Графіки: {graph_interval}с\n\n'
                    'Оберіть інтервал для зміни:',
                    reply_markup=keyboard
                )
        elif text == '✏️ Заголовок / Опис каналу':
            # Start title/description flow
            await update.message.reply_text(
                '✏️ Налаштування заголовку та опису каналу\n\n'
                'Введіть новий заголовок каналу:'
            )
            context.user_data['awaiting'] = 'title'
        elif text == '➕ Додати канал':
            # Show instructions for adding the bot to a channel
            instructions = (
                '➕ *Як додати бота до каналу*\n\n'
                '*Крок 1:* Додайте бота до каналу як адміністратора\n'
                '• Відкрийте налаштування каналу\n'
                '• Перейдіть до "Адміністратори"\n'
                '• Натисніть "Додати адміністратора"\n'
                '• Знайдіть цього бота і додайте його\n'
                '• Увімкніть право "Може змінювати інформацію про канал"\n\n'
                '*Крок 2:* Відправте команду /start у каналі\n'
                '• Це необхідно, щоб бот зберіг chat_id каналу\n\n'
                '*Крок 3:* Використовуйте меню для налаштувань\n'
                '• Налаштуйте моніторинг світла через меню "💡 Моніторинг"\n'
                '• Налаштуйте графіки через меню "📈 Графіки"\n'
                '• Змініть заголовок/опис через меню "✏️ Заголовок / Опис каналу"\n\n'
                '✅ Після додавання бот буде автоматично оновлювати інформацію в каналі!'
            )
            await update.message.reply_text(instructions, parse_mode=ParseMode.MARKDOWN)
        elif text == '⚒️ Техпідтримка':
            await update.message.reply_text(
                '⚒️ Техпідтримка\n\n'
                f'З питаннями звертайтесь: {SUPPORT_USERNAME}\n'
                f'Email: {SUPPORT_EMAIL}'
            )
        elif text == '🗑️ Видалити бота':
            keyboard = build_delete_confirmation_keyboard()
            await update.message.reply_text(
                '⚠️ Ви впевнені, що хочете видалити бота з каналу?\n\n'
                'Всі налаштування будуть втрачені!',
                reply_markup=keyboard
            )
        return
    
    # Process input based on what we're awaiting
    if awaiting == 'ip':
        ip_value = text.strip()
        if not is_valid_ip_or_hostname(ip_value):
            await update.message.reply_text('❌ Невірний формат IP-адреси або DDNS. Спробуйте ще раз.')
            return
        update_chat_config(chat_id, {'monitor_host': ip_value})
        # Refresh keyboard after changes
        keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
        await update.message.reply_text(f'✅ IP-адресу змінено на: {ip_value}', reply_markup=keyboard)
        context.user_data['awaiting'] = None
        return
    elif awaiting == 'region':
        update_chat_config(chat_id, {'region': text.strip().lower()})
        await update.message.reply_text(f'✅ Регіон змінено на: {text.strip()}')
    elif awaiting == 'group':
        update_chat_config(chat_id, {'group': text.strip()})
        await update.message.reply_text(f'✅ Групу змінено на: {text.strip()}')
    elif awaiting == 'title':
        update_chat_config(chat_id, {'channel_title': text.strip()})
        # Try to update channel title via Telegram API only if this is a channel
        if update.effective_chat.type == 'channel':
            try:
                await context.bot.set_chat_title(chat_id=chat_id, title=text.strip())
                await update.message.reply_text(f'✅ Заголовок каналу змінено\n\nТепер введіть новий опис каналу:')
            except Exception as e:
                await update.message.reply_text(f'✅ Заголовок збережено, але не вдалося змінити в Telegram: {e}\n\nТепер введіть новий опис каналу:')
        else:
            await update.message.reply_text(f'✅ Заголовок збережено\n\n⚠️ Ця команда працює тільки в каналах. Додайте бота до каналу через "➕ Додати канал"\n\nТепер введіть новий опис каналу:')
        context.user_data['awaiting'] = 'description'
        return
    elif awaiting == 'description':
        update_chat_config(chat_id, {'channel_description': text.strip()})
        # Try to update channel description via Telegram API only if this is a channel
        if update.effective_chat.type == 'channel':
            try:
                await context.bot.set_chat_description(chat_id=chat_id, description=text.strip())
                await update.message.reply_text(f'✅ Опис каналу змінено')
            except Exception as e:
                await update.message.reply_text(f'✅ Опис збережено, але не вдалося змінити в Telegram: {e}')
        else:
            await update.message.reply_text(f'✅ Опис збережено\n\n⚠️ Ця команда працює тільки в каналах. Додайте бота до каналу через "➕ Додати канал"')
        # Refresh keyboard after changes
        keyboard = ReplyKeyboardMarkup(build_settings_keyboard(chat_id), resize_keyboard=True)
        await update.message.reply_text('Налаштування збережено.', reply_markup=keyboard)
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
            logger.info(f'Status notification sent to {chat_id}: {new_status}')
        except Exception as e:
            logger.error(f'ERROR sending notification to {chat_id}: {e}')
    
    def run(self):
        """Main monitoring loop"""
        logger.info('Monitor thread started')
        
        while self.running:
            try:
                config = load_config()
                
                for chat_id, settings in config.items():
                    if not settings.get('monitor_enabled') or settings.get('light_paused'):
                        continue
                    
                    host = settings.get('monitor_host', DEFAULT_HOST)
                    port = settings.get('monitor_port', DEFAULT_PORT)
                    interval = settings.get('light_check_interval', DEFAULT_INTERVAL)
                    
                    # Check status with retry logic
                    is_online = check_tcp_connection_with_retry(host, port)
                    new_status = 'online' if is_online else 'offline'
                    
                    current_time = get_kyiv_time()
                    logger.debug(f'[{current_time}] Monitor {chat_id}: {host}:{port} -> {new_status}')
                    
                    # Detect state change
                    previous_status = settings.get('monitor_last_status')
                    last_change = settings.get('monitor_last_change', int(time.time() * MILLISECONDS_PER_SECOND))
                    
                    if previous_status and previous_status != new_status:
                        # Status changed!
                        logger.info(f'Status changed for {chat_id}: {previous_status} -> {new_status}')
                        
                        # Check debounce settings
                        debounce_enabled = settings.get('debounce_enabled', True)
                        debounce_seconds = settings.get('debounce_seconds', DEBOUNCE_SECONDS)
                        time_since_last_change = (int(time.time() * MILLISECONDS_PER_SECOND) - last_change) / MILLISECONDS_PER_SECOND
                        
                        if debounce_enabled and time_since_last_change < debounce_seconds:
                            logger.info(f'Debounce: skipping notification for {chat_id}, last change was {time_since_last_change:.0f}s ago')
                            # Update status without notification
                            settings['monitor_last_status'] = new_status
                            settings['monitor_last_change'] = int(time.time() * MILLISECONDS_PER_SECOND)
                            config[chat_id] = settings
                            save_config(config)
                            continue
                        
                        # Send notification using the application's event loop
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                self.send_status_notification(chat_id, new_status, last_change),
                                self.event_loop
                            )
                            # Wait for completion with timeout to catch errors
                            future.result(timeout=10)
                        except Exception as e:
                            logger.error(f'ERROR in notification: {e}')
                        
                        # Update state
                        settings['monitor_last_status'] = new_status
                        settings['monitor_last_change'] = int(time.time() * MILLISECONDS_PER_SECOND)
                        config[chat_id] = settings
                        save_config(config)
                    elif not previous_status:
                        # First check - initialize without notification
                        logger.info(f'Initializing monitor state for {chat_id}: {new_status}')
                        settings['monitor_last_status'] = new_status
                        settings['monitor_last_change'] = int(time.time() * MILLISECONDS_PER_SECOND)
                        config[chat_id] = settings
                        save_config(config)
                
                # Sleep for the shortest interval among all monitored chats
                time.sleep(DEFAULT_INTERVAL)
            
            except Exception as e:
                logger.error(f'ERROR in monitor thread: {e}')
                time.sleep(DEFAULT_INTERVAL)
        
        logger.info('Monitor thread stopped')


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
                logger.debug(f'Skipping private chat {chat_id} for graph updates')
                return
        except (ValueError, TypeError):
            # If chat_id is not numeric (e.g., test data), skip validation
            logger.warning(f'Non-numeric chat_id {chat_id}, proceeding with update')
        
        region = settings.get('region', 'kyiv')
        group = settings.get('group', '3.1')
        format_pref = settings.get('format_preference', 'image')
        group_formatted = convert_group_to_url_format(group)
        
        # Log region for diagnostics
        logger.debug(f'Using region: {region} for chat {chat_id}')
        
        image_url = f'{OUTAGE_IMAGES_BASE}{region}/gpv-{group_formatted}-emergency.png'
        
        # Fetch image and compute hash to check if it changed
        try:
            response = requests.get(image_url, timeout=30, verify=True)
            if response.status_code != 200:
                logger.warning(f'Failed to fetch image for {chat_id}: HTTP {response.status_code}')
                return
            
            new_hash = hashlib.sha256(response.content).hexdigest()
        except Exception as e:
            logger.error(f'Error fetching image for {chat_id}: {e}')
            return
        
        # Compare with previous hash
        last_hash = settings.get('last_graph_hash')
        if new_hash == last_hash:
            # Graph hasn't changed - skip update
            logger.debug(f'Graph unchanged for {chat_id}, skipping update')
            return
        
        # Graph changed - publish update
        logger.info(f'Graph changed for {chat_id}, publishing update')
        
        # Update hash in config
        update_chat_config(chat_id, {'last_graph_hash': new_hash})
        
        try:
            # Отримати текстовий розклад
            schedule_text = format_schedule_text(region, group)
            
            if format_pref in ['image', 'both']:
                # Використовувати schedule_text як caption або fallback
                caption = schedule_text if schedule_text else f'💡Оновлено графік для черги {group}'
                
                # Send new photo (not edit) with cache buster
                cb = int(time.time() * MILLISECONDS_PER_SECOND)
                photo_url = f'{image_url}?cb={cb}'
                
                await self.application.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url,
                    caption=caption
                )
            
            if format_pref in ['text', 'both']:
                # Send text schedule (plain text, no markdown)
                text_schedule = schedule_text if schedule_text else 'Не вдалося завантажити розклад'
                
                await self.application.bot.send_message(chat_id=chat_id, text=text_schedule)
        
        except Exception as e:
            logger.error(f'ERROR sending graph update to {chat_id}: {e}')
    
    def run(self):
        """Main Graphenko update loop"""
        logger.info('Graphenko thread started')
        
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
                    
                    logger.debug(f'Sleeping for {min_interval} seconds until next graph check')
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
                        logger.error(f'ERROR in graph update: {e}')
                    
                    time.sleep(1)  # Rate limiting
            
            except Exception as e:
                logger.error(f'ERROR in Graphenko thread: {e}')
        
        logger.info('Graphenko thread stopped')


# ============================================================================
# HealthCheck HTTP Server
# ============================================================================

from http.server import HTTPServer, BaseHTTPRequestHandler


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks"""
    
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            health_data = {
                'status': 'ok',
                'version': BOT_VERSION,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            self.wfile.write(json.dumps(health_data).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass


class HealthCheckServer(threading.Thread):
    """Background thread for health check HTTP server"""
    
    def __init__(self, port: int = HEALTHCHECK_PORT):
        super().__init__(daemon=True)
        self.port = port
        self.server = None
    
    def run(self):
        try:
            self.server = HTTPServer(('0.0.0.0', self.port), HealthCheckHandler)
            logger.info(f'Health check server started on port {self.port}')
            self.server.serve_forever()
        except Exception as e:
            logger.error(f'Health check server error: {e}')
    
    def stop(self):
        if self.server:
            self.server.shutdown()


# ============================================================================
# Main
# ============================================================================

def main():
    """Main bot function"""
    logger.info('Starting DTEK Bot with interactive UX...')
    logger.info(f'Bot token: {BOT_TOKEN[:10]}...')
    logger.info(f'Config file: {CONFIG_FILE}')
    
    # Start health check server
    health_server = HealthCheckServer()
    health_server.start()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('cancel', cancel))
    application.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(handle_settings_callback, pattern='^settings_'))
    application.add_handler(CallbackQueryHandler(handle_format_callback, pattern='^format_'))
    application.add_handler(CallbackQueryHandler(handle_notification_callback, pattern='^notif_'))
    application.add_handler(CallbackQueryHandler(handle_delete_callback, pattern='^delete_'))
    application.add_handler(CallbackQueryHandler(handle_graph_type_callback, pattern='^graph_type_'))
    application.add_handler(CallbackQueryHandler(handle_region_callback, pattern='^region_'))
    application.add_handler(CallbackQueryHandler(handle_group_callback, pattern='^group_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    # Use post_init to start background tasks with the correct event loop
    async def post_init(application: Application):
        """Start background tasks after application is initialized"""
        loop = asyncio.get_running_loop()
        
        # Start background threads with the correct event loop
        monitor_thread = MonitorThread(application, loop)
        monitor_thread.start()
        
        graphenko_thread = GraphenkoThread(application, loop)
        graphenko_thread.start()
        
        # Store references for cleanup
        application.bot_data['monitor_thread'] = monitor_thread
        application.bot_data['graphenko_thread'] = graphenko_thread
        
        logger.info('Background threads started')
    
    async def post_shutdown(application: Application):
        """Clean up background tasks"""
        monitor_thread = application.bot_data.get('monitor_thread')
        graphenko_thread = application.bot_data.get('graphenko_thread')
        
        if monitor_thread:
            monitor_thread.stop()
        if graphenko_thread:
            graphenko_thread.stop()
        
        logger.info('Background threads stopped')
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    # Run bot
    logger.info('Bot started successfully!')
    application.run_polling(allowed_updates=['message', 'callback_query', 'my_chat_member'])


if __name__ == '__main__':
    main()
