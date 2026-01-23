#!/usr/bin/env python3
“””
Скрипт для моніторингу та статистики оновлень графіків ДТЕК
Можна запустити локально для отримання інформації про роботу бота
“””

import asyncio
import json
import hashlib
import aiohttp
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logging.basicConfig(
level=logging.INFO,
format=’%(asctime)s - %(levelname)s - %(message)s’
)
logger = logging.getLogger(**name**)

class GraphenkoMonitor:
“”“Клас для моніторингу стану графіків”””

```
def __init__(self, config_file: str = 'graphenko-chats.json'):
    self.config_file = config_file
    self.config = self._load_config()
    self.session: Optional[aiohttp.ClientSession] = None
    self.image_hashes: Dict[str, str] = {}
    self.stats = {
        'total_checks': 0,
        'successful_downloads': 0,
        'failed_downloads': 0,
        'updates_detected': 0,
        'errors': []
    }

def _load_config(self) -> Dict[str, Any]:
    """Завантажити конфігурацію"""
    try:
        if Path(self.config_file).exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Помилка при завантаженні конфігурації: {e}")
    return {'chats': {}}

async def init_session(self):
    """Ініціалізувати HTTP сесію"""
    if self.session is None:
        self.session = aiohttp.ClientSession()

async def close_session(self):
    """Закрити HTTP сесію"""
    if self.session:
        await self.session.close()

async def fetch_image(self, url: str, timeout: int = 30) -> Optional[bytes]:
    """Завантажити зображення з URL"""
    await self.init_session()
    
    try:
        async with self.session.get(
            url, 
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status == 200:
                self.stats['successful_downloads'] += 1
                return await resp.read()
            else:
                logger.warning(f"HTTP {resp.status} для {url}")
                self.stats['failed_downloads'] += 1
    except asyncio.TimeoutError:
        logger.error(f"Timeout при завантаженні {url}")
        self.stats['failed_downloads'] += 1
    except Exception as e:
        logger.error(f"Помилка при завантаженні {url}: {e}")
        self.stats['failed_downloads'] += 1
    
    return None

def calculate_hash(self, data: bytes) -> str:
    """Розрахувати SHA256 хеш"""
    return hashlib.sha256(data).hexdigest()

async def check_all_graphs(self) -> Dict[str, Any]:
    """Перевірити всі графіки на оновлення"""
    results = {
        'timestamp': datetime.now().isoformat(),
        'total_chats': len(self.config['chats']),
        'updates': [],
        'no_changes': [],
        'errors': []
    }
    
    for chat_id, chat_data in self.config['chats'].items():
        image_url = chat_data.get('image_url')
        if not image_url:
            continue
        
        self.stats['total_checks'] += 1
        
        try:
            logger.info(f"Перевіряю {chat_id}...")
            image_data = await self.fetch_image(image_url)
            
            if not image_data:
                results['errors'].append({
                    'chat_id': chat_id,
                    'error': 'Не вдалося завантажити зображення'
                })
                continue
            
            current_hash = self.calculate_hash(image_data)
            prev_hash = self.image_hashes.get(chat_id)
            
            if prev_hash is None:
                # Перший запуск
                self.image_hashes[chat_id] = current_hash
                results['no_changes'].append({
                    'chat_id': chat_id,
                    'status': 'initialized'
                })
            elif prev_hash != current_hash:
                # Графік оновлено!
                logger.warning(f"🔴 ОНОВЛЕННЯ ВИЯВЛЕНО для {chat_id}!")
                self.image_hashes[chat_id] = current_hash
                self.stats['updates_detected'] += 1
                results['updates'].append({
                    'chat_id': chat_id,
                    'url': image_url,
                    'timestamp': datetime.now().isoformat(),
                    'image_size': len(image_data),
                    'hash': current_hash[:16] + '...'
                })
            else:
                results['no_changes'].append({
                    'chat_id': chat_id,
                    'hash': current_hash[:16] + '...'
                })
        
        except Exception as e:
            logger.error(f"Помилка при перевірці {chat_id}: {e}")
            results['errors'].append({
                'chat_id': chat_id,
                'error': str(e)
            })
            self.stats['errors'].append({
                'chat_id': chat_id,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
    
    return results

def print_results(self, results: Dict[str, Any]):
    """Вивести результати в консоль"""
    print("\n" + "="*60)
    print(f"📊 Результати перевірки графіків")
    print(f"⏰ {results['timestamp']}")
    print("="*60)
    
    print(f"\n📈 Статистика:")
    print(f"  • Всього каналів: {results['total_chats']}")
    print(f"  • Перевірено: {self.stats['total_checks']}")
    print(f"  • Оновлено: {len(results['updates'])} 🔴")
    print(f"  • Без змін: {len(results['no_changes'])} ✅")
    print(f"  • Помилок: {len(results['errors'])} ⚠️")
    
    if results['updates']:
        print(f"\n🔴 ОНОВЛЕНІ ГРАФІКИ:")
        for update in results['updates']:
            print(f"  • {update['chat_id']}")
            print(f"    URL: {update['url'][:50]}...")
            print(f"    Розмір: {update['image_size'] // 1024} KB")
            print(f"    Хеш: {update['hash']}")
            print()
    
    if results['errors']:
        print(f"\n⚠️ ПОМИЛКИ:")
        for error in results['errors']:
            print(f"  • {error['chat_id']}: {error['error']}")
    
    print(f"\n📊 ЗАГАЛЬНА СТАТИСТИКА:")
    print(f"  • Успішних завантажень: {self.stats['successful_downloads']}")
    print(f"  • Помилок завантаження: {self.stats['failed_downloads']}")
    print(f"  • Всього виявлено оновлень: {self.stats['updates_detected']}")
    print("="*60 + "\n")

async def continuous_monitor(self, interval: int = 300):
    """Безперервний моніторинг з інтервалом"""
    logger.info(f"Запускаю безперервний моніторинг (інтервал: {interval}с)")
    
    try:
        iteration = 0
        while True:
            iteration += 1
            logger.info(f"\n--- Ітерація #{iteration} ---")
            results = await self.check_all_graphs()
            self.print_results(results)
            
            logger.info(f"Очікування {interval} секунд до наступної перевірки...")
            await asyncio.sleep(interval)
    
    except KeyboardInterrupt:
        logger.info("\n⏹️  Моніторинг припинено")
    finally:
        await self.close_session()
```

async def main():
“”“Головна функція”””
import sys

```
monitor = GraphenkoMonitor()

# Перевірити, чи існує конфігурація
if not monitor.config['chats']:
    print("\n⚠️  Конфігурація порожня!")
    print("Переконайтесь, що:")
    print("  1. Файл 'graphenko-chats.json' існує")
    print("  2. Додали канали через /start -> 📊 Додати канал")
    return

print("\n🔍 ДТЕК Graphenko Monitor v3.0")
print("="*60)
print(f"Знайдено каналів: {len(monitor.config['chats'])}")

# Вибір режиму
if len(sys.argv) > 1 and sys.argv[1] == '--continuous':
    # Безперервний моніторинг
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    await monitor.continuous_monitor(interval)
else:
    # Одна перевірка
    print("\nВиконую одну перевірку...\n")
    results = await monitor.check_all_graphs()
    monitor.print_results(results)
```

if **name** == ‘**main**’:
asyncio.run(main())