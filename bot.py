#!/usr/bin/env python3
"""
DTEK Bot - Standalone Telegram Bot for Power Monitoring and Graphenko Updates
Combines power monitoring (TCP checks) and Graphenko functionality (image updates)
"""

import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

try:
    import requests
except ImportError:
    print('ERROR: requests library not found. Install with: pip install requests')
    sys.exit(1)

# Configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
DEFAULT_CHAT_ID = os.getenv('CHAT_ID', '-1003523279109')
CONFIG_FILE = 'graphenko-chats.json'

# Constants
DEFAULT_HOST = '93.127.118.86'
DEFAULT_PORT = 443
DEFAULT_INTERVAL = 30
OUTAGE_IMAGES_BASE = 'https://raw.githubusercontent.com/Baskerville42/outage-data-ua/refs/heads/main/images/'
DEFAULT_CAPTION = '⚡️ Графік стабілізаційних вімкнень. Це повідомлення оновлюється щогодини автоматично.'

if not BOT_TOKEN:
    print('ERROR: BOT_TOKEN environment variable is required')
    sys.exit(1)

API_BASE = f'https://api.telegram.org/bot{BOT_TOKEN}'


# ============================================================================
# Telegram API Functions
# ============================================================================

def telegram_request(method: str, data: Dict = None) -> Dict:
    """Make a request to Telegram API"""
    url = f'{API_BASE}/{method}'
    try:
        if data:
            response = requests.post(url, json=data, timeout=30)
        else:
            response = requests.get(url, timeout=30)
        
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f'ERROR: Telegram API request failed for {method}: {e}')
        return {'ok': False, 'error': str(e)}
    except Exception as e:
        print(f'ERROR: Unexpected error in {method}: {e}')
        return {'ok': False, 'error': str(e)}


def send_message(chat_id: str, text: str, **kwargs) -> Dict:
    """Send a text message to a chat"""
    data = {'chat_id': chat_id, 'text': text, **kwargs}
    return telegram_request('sendMessage', data)


def delete_message(chat_id: str, message_id: int) -> Dict:
    """Delete a message"""
    data = {'chat_id': chat_id, 'message_id': message_id}
    result = telegram_request('deleteMessage', data)
    if not result.get('ok'):
        # Message already deleted is OK
        if result.get('error_code') == 400 and 'not found' in result.get('description', '').lower():
            return {'ok': True, 'reason': 'already-deleted'}
    return result


def send_photo(chat_id: str, photo_url: str, caption: str = '', **kwargs) -> Dict:
    """Send a photo message"""
    data = {'chat_id': chat_id, 'photo': photo_url, 'caption': caption, **kwargs}
    return telegram_request('sendPhoto', data)


def edit_message_media(chat_id: str, message_id: int, photo_url: str, caption: str = '') -> Dict:
    """Edit media in an existing message"""
    data = {
        'chat_id': chat_id,
        'message_id': message_id,
        'media': {
            'type': 'photo',
            'media': photo_url,
            'caption': caption
        }
    }
    return telegram_request('editMessageMedia', data)


def pin_message(chat_id: str, message_id: int) -> Dict:
    """Pin a message in a chat"""
    data = {'chat_id': chat_id, 'message_id': message_id, 'disable_notification': True}
    return telegram_request('pinChatMessage', data)


def get_updates(offset: Optional[int] = None, timeout: int = 30) -> Dict:
    """Get updates from Telegram (long polling)"""
    data = {
        'timeout': timeout,
        'allowed_updates': ['my_chat_member', 'message', 'channel_post']
    }
    if offset is not None:
        data['offset'] = offset
    return telegram_request('getUpdates', data)


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


# ============================================================================
# Monitoring Functions
# ============================================================================

def check_tcp_connection(host: str, port: int, timeout: int = 5) -> bool:
    """Check if TCP connection to host:port succeeds"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        print(f'ERROR: TCP check failed for {host}:{port}: {e}')
        return False


def get_kyiv_time() -> str:
    """Get current time in Kyiv timezone (HH:MM format)"""
    # UTC+2 (standard) or UTC+3 (DST) - simplified to UTC+2 for now
    now = datetime.now(timezone.utc)
    # Note: This is a simplified version. For production, use pytz or zoneinfo
    kyiv_offset = 2  # hours
    kyiv_time = datetime.fromtimestamp(now.timestamp() + kyiv_offset * 3600)
    return kyiv_time.strftime('%H:%M')


def format_duration(milliseconds: int) -> str:
    """Format duration in Ukrainian"""
    seconds = milliseconds // 1000
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    
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
        remaining_hours = hours % 24
        if remaining_hours > 0:
            return f'{days} {plural_days(days)} {remaining_hours} {plural_hours(remaining_hours)}'
        return f'{days} {plural_days(days)}'
    
    if hours > 0:
        remaining_minutes = minutes % 60
        if remaining_minutes > 0:
            return f'{hours} {plural_hours(hours)} {remaining_minutes} {plural_minutes(remaining_minutes)}'
        return f'{hours} {plural_hours(hours)}'
    
    if minutes > 0:
        return f'{minutes} {plural_minutes(minutes)}'
    
    return f'{seconds} секунд'


def send_status_notification(chat_id: str, new_status: str, last_change_time: int):
    """Send power status change notification"""
    current_time = get_kyiv_time()
    duration = int(time.time() * 1000) - last_change_time
    formatted_duration = format_duration(duration)
    
    if new_status == 'online':
        message = f'🟢 {current_time} Світло з\'явилося\n🕓 Його не було {formatted_duration}'
    else:
        message = f'🔴 {current_time} Світло зникло\n🕓 Воно було {formatted_duration}'
    
    send_message(chat_id, message)
    print(f'Status notification sent to {chat_id}: {new_status}')


# ============================================================================
# Monitoring Thread
# ============================================================================

class MonitorThread(threading.Thread):
    """Background thread for power monitoring"""
    
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True
    
    def stop(self):
        self.running = False
    
    def run(self):
        """Main monitoring loop"""
        print('Monitor thread started')
        
        while self.running:
            try:
                config = load_config()
                
                for chat_id, settings in config.items():
                    if not settings.get('monitor_enabled'):
                        continue
                    
                    host = settings.get('monitor_host', DEFAULT_HOST)
                    port = settings.get('monitor_port', DEFAULT_PORT)
                    interval = settings.get('monitor_interval_sec', DEFAULT_INTERVAL)
                    
                    # Check status
                    is_online = check_tcp_connection(host, port)
                    new_status = 'online' if is_online else 'offline'
                    
                    current_time = get_kyiv_time()
                    print(f'[{current_time}] Monitor {chat_id}: {host}:{port} -> {new_status}')
                    
                    # Detect state change
                    previous_status = settings.get('monitor_last_status')
                    last_change = settings.get('monitor_last_change', int(time.time() * 1000))
                    
                    if previous_status and previous_status != new_status:
                        # Status changed!
                        print(f'Status changed for {chat_id}: {previous_status} -> {new_status}')
                        send_status_notification(chat_id, new_status, last_change)
                        
                        # Update state
                        settings['monitor_last_status'] = new_status
                        settings['monitor_last_change'] = int(time.time() * 1000)
                        config[chat_id] = settings
                        save_config(config)
                    elif not previous_status:
                        # First check - initialize without notification
                        print(f'Initializing monitor state for {chat_id}: {new_status}')
                        settings['monitor_last_status'] = new_status
                        settings['monitor_last_change'] = int(time.time() * 1000)
                        config[chat_id] = settings
                        save_config(config)
                
                # Sleep for the shortest interval among all monitored chats
                time.sleep(DEFAULT_INTERVAL)
            
            except Exception as e:
                print(f'ERROR in monitor thread: {e}')
                time.sleep(DEFAULT_INTERVAL)
        
        print('Monitor thread stopped')


# ============================================================================
# Command Handlers
# ============================================================================

def handle_monitor_on(chat_id: str, message_id: int):
    """Handle /monitor_on command"""
    config = load_config()
    if chat_id not in config:
        config[chat_id] = {}
    
    config[chat_id]['monitor_enabled'] = True
    config[chat_id]['monitor_host'] = config[chat_id].get('monitor_host', DEFAULT_HOST)
    config[chat_id]['monitor_port'] = config[chat_id].get('monitor_port', DEFAULT_PORT)
    config[chat_id]['monitor_interval_sec'] = config[chat_id].get('monitor_interval_sec', DEFAULT_INTERVAL)
    
    save_config(config)
    
    host = config[chat_id]['monitor_host']
    port = config[chat_id]['monitor_port']
    interval = config[chat_id]['monitor_interval_sec']
    
    send_message(chat_id, f'✅ Моніторинг увімкнено\nЦіль: {host}:{port}\nІнтервал: {interval}с')
    delete_message(chat_id, message_id)


def handle_monitor_off(chat_id: str, message_id: int):
    """Handle /monitor_off command"""
    config = load_config()
    if chat_id not in config:
        config[chat_id] = {}
    
    config[chat_id]['monitor_enabled'] = False
    save_config(config)
    
    send_message(chat_id, '✅ Моніторинг вимкнено')
    delete_message(chat_id, message_id)


def handle_monitor_status(chat_id: str, message_id: int):
    """Handle /monitor_status command"""
    config = load_config()
    settings = config.get(chat_id, {})
    
    if not settings.get('monitor_enabled'):
        send_message(chat_id, '⚪️ Моніторинг вимкнено')
    else:
        status = settings.get('monitor_last_status', 'невідомий')
        status_emoji = '🟢' if status == 'online' else '🔴' if status == 'offline' else '⚪️'
        host = settings.get('monitor_host', DEFAULT_HOST)
        port = settings.get('monitor_port', DEFAULT_PORT)
        
        message = f'{status_emoji} Моніторинг увімкнено\nСтатус: {status}\nЦіль: {host}:{port}'
        
        last_change = settings.get('monitor_last_change')
        if last_change:
            duration = int(time.time() * 1000) - last_change
            message += f'\nОстання зміна: {format_duration(duration)} тому'
        
        send_message(chat_id, message)
    
    delete_message(chat_id, message_id)


def handle_graphenko_image(chat_id: str, message_id: int, image_url: str):
    """Handle /graphenko_image command"""
    # Validate URL
    if not image_url.startswith(OUTAGE_IMAGES_BASE) or not image_url.lower().endswith('.png'):
        send_message(chat_id, 
            f'❌ Невірний URL. Використовуйте PNG з базою:\n{OUTAGE_IMAGES_BASE}\n'
            f'приклад: /graphenko_image {OUTAGE_IMAGES_BASE}kyiv/gpv-3-2-emergency.png')
        return
    
    # Save config
    config = load_config()
    if chat_id not in config:
        config[chat_id] = {}
    
    config[chat_id]['image_url'] = image_url
    save_config(config)
    
    send_message(chat_id, '✅ Зображення збережено. Розсилка увімкнена.')
    delete_message(chat_id, message_id)


def handle_graphenko_caption(chat_id: str, message_id: int, caption_text: str):
    """Handle /graphenko_caption command"""
    config = load_config()
    if chat_id not in config:
        config[chat_id] = {}
    
    if caption_text.strip().lower() == '-default':
        # Reset to default
        if 'caption' in config[chat_id]:
            del config[chat_id]['caption']
        save_config(config)
        send_message(chat_id, '✅ Підпис скинуто до стандартного. Буде застосовано під час наступного оновлення.')
    elif not caption_text.strip():
        send_message(chat_id, '❌ Порожній підпис. Спробуйте так: /graphenko_caption Мій власний підпис')
        return
    else:
        config[chat_id]['caption'] = caption_text.strip()
        save_config(config)
        send_message(chat_id, '✅ Підпис збережено. Буде застосовано під час наступного оновлення.')
    
    delete_message(chat_id, message_id)


def process_update(update: Dict):
    """Process a single update from Telegram"""
    # Handle chat member updates (bot added/removed)
    if 'my_chat_member' in update:
        mcm = update['my_chat_member']
        chat = mcm.get('chat', {})
        chat_id = str(chat.get('id', ''))
        status = mcm.get('new_chat_member', {}).get('status', '')
        
        if status in ['left', 'kicked', 'restricted']:
            # Bot removed from chat
            config = load_config()
            if chat_id in config:
                del config[chat_id]
                save_config(config)
                print(f'Bot removed from chat {chat_id}, config deleted')
        elif status in ['administrator', 'creator', 'member']:
            # Bot added to chat
            config = load_config()
            if chat_id not in config:
                config[chat_id] = {}
                save_config(config)
                print(f'Bot added to chat {chat_id}, config created')
        return
    
    # Handle messages (commands)
    message = update.get('message') or update.get('channel_post')
    if not message:
        return
    
    chat = message.get('chat', {})
    chat_id = str(chat.get('id', ''))
    text = message.get('text', '') or message.get('caption', '')
    message_id = message.get('message_id', 0)
    
    if not text or not chat_id:
        return
    
    # Parse commands
    text = text.strip()
    
    # /monitor_on
    if text.startswith('/monitor_on'):
        handle_monitor_on(chat_id, message_id)
        return
    
    # /monitor_off
    if text.startswith('/monitor_off'):
        handle_monitor_off(chat_id, message_id)
        return
    
    # /monitor_status
    if text.startswith('/monitor_status'):
        handle_monitor_status(chat_id, message_id)
        return
    
    # /graphenko_image <url>
    if text.startswith('/graphenko_image'):
        parts = text.split(None, 1)
        if len(parts) == 2:
            handle_graphenko_image(chat_id, message_id, parts[1])
        return
    
    # /graphenko_caption <text>
    if text.startswith('/graphenko_caption'):
        parts = text.split(None, 1)
        if len(parts) == 2:
            handle_graphenko_caption(chat_id, message_id, parts[1])
        else:
            handle_graphenko_caption(chat_id, message_id, '')
        return


# ============================================================================
# Graphenko Update Thread
# ============================================================================

class GraphenkoThread(threading.Thread):
    """Background thread for periodic Graphenko image updates"""
    
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True
    
    def stop(self):
        self.running = False
    
    def run(self):
        """Main Graphenko update loop - runs every 5 minutes"""
        print('Graphenko thread started')
        
        while self.running:
            try:
                time.sleep(300)  # 5 minutes
                
                config = load_config()
                for chat_id, settings in config.items():
                    image_url = settings.get('image_url')
                    if not image_url:
                        continue
                    
                    caption = settings.get('caption', DEFAULT_CAPTION)
                    
                    # Add timestamp
                    now = datetime.now(timezone.utc)
                    kyiv_time = datetime.fromtimestamp(now.timestamp() + 2 * 3600)
                    timestamp = kyiv_time.strftime('%Y-%m-%d %H:%M')
                    full_caption = f'{caption}\nОновлено: {timestamp}'
                    
                    # Add cache buster
                    cb = int(time.time() * 1000)
                    photo_url = f'{image_url}?cb={cb}'
                    
                    # Check if we have an existing message
                    message_id = settings.get('message_id')
                    
                    if message_id:
                        # Edit existing message
                        result = edit_message_media(chat_id, message_id, photo_url, full_caption)
                        if result.get('ok'):
                            print(f'Updated image for {chat_id}')
                            pin_message(chat_id, message_id)
                        else:
                            # Message might be deleted, send new one
                            result = send_photo(chat_id, photo_url, full_caption)
                            if result.get('ok'):
                                new_message_id = result.get('result', {}).get('message_id')
                                settings['message_id'] = new_message_id
                                config[chat_id] = settings
                                save_config(config)
                                pin_message(chat_id, new_message_id)
                    else:
                        # Send new message
                        result = send_photo(chat_id, photo_url, full_caption)
                        if result.get('ok'):
                            new_message_id = result.get('result', {}).get('message_id')
                            settings['message_id'] = new_message_id
                            config[chat_id] = settings
                            save_config(config)
                            pin_message(chat_id, new_message_id)
                    
                    time.sleep(1)  # Rate limiting
            
            except Exception as e:
                print(f'ERROR in Graphenko thread: {e}')
        
        print('Graphenko thread stopped')


# ============================================================================
# Main Bot Loop
# ============================================================================

def main():
    """Main bot loop with long polling"""
    print('Starting DTEK Bot...')
    print(f'Bot token: {BOT_TOKEN[:10]}...')
    print(f'Config file: {CONFIG_FILE}')
    
    # Start background threads
    monitor_thread = MonitorThread()
    monitor_thread.start()
    
    graphenko_thread = GraphenkoThread()
    graphenko_thread.start()
    
    # Long polling
    offset = None
    
    try:
        while True:
            try:
                result = get_updates(offset, timeout=30)
                
                if not result.get('ok'):
                    print(f'ERROR: Failed to get updates: {result}')
                    time.sleep(5)
                    continue
                
                updates = result.get('result', [])
                
                for update in updates:
                    update_id = update.get('update_id')
                    if update_id:
                        offset = update_id + 1
                    
                    try:
                        process_update(update)
                    except Exception as e:
                        print(f'ERROR processing update: {e}')
                
                if not updates:
                    # No updates, just continue polling
                    pass
            
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f'ERROR in main loop: {e}')
                time.sleep(5)
    
    except KeyboardInterrupt:
        print('\nStopping bot...')
        monitor_thread.stop()
        graphenko_thread.stop()
        print('Bot stopped')


if __name__ == '__main__':
    main()
