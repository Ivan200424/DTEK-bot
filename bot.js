const TelegramBot = require('node-telegram-bot-api');
const fs = require('fs').promises;
const path = require('path');
const { getOutageSchedule } = require('./outage-monitor');

// Load environment variables from .env file if it exists
try {
  require('dotenv').config();
} catch (error) {
  // dotenv not available, using environment variables
}

// Load configuration and history
let config;
let history;

async function loadConfig() {
  try {
    const configData = await fs.readFile('light-config.json', 'utf8');
    config = JSON.parse(configData);
    console.log('Configuration loaded:', config);
  } catch (error) {
    console.error('Error loading config:', error);
    process.exit(1);
  }
}

async function loadHistory() {
  try {
    const historyData = await fs.readFile('light-history.json', 'utf8');
    history = JSON.parse(historyData);
    console.log('History loaded. Current status:', history.current_status);
  } catch (error) {
    console.error('Error loading history:', error);
    history = {
      current_status: 'UNKNOWN',
      last_change: null,
      history: []
    };
  }
}

function formatDuration(ms) {
  if (!ms || ms < 0) return 'невідомо';
  
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  
  if (days > 0) {
    const remainingHours = hours % 24;
    const remainingMinutes = minutes % 60;
    return `${days}д ${remainingHours}г ${remainingMinutes}хв`;
  } else if (hours > 0) {
    const remainingMinutes = minutes % 60;
    return `${hours}г ${remainingMinutes}хв`;
  } else if (minutes > 0) {
    const remainingSeconds = seconds % 60;
    return `${minutes}хв ${remainingSeconds}с`;
  } else {
    return `${seconds}с`;
  }
}

function formatTime(date) {
  const d = new Date(date);
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  return `${hours}:${minutes} (${day}.${month})`;
}

async function getLightHistory(limit = 10) {
  const recentHistory = history.history.slice(-limit).reverse();
  
  if (recentHistory.length === 0) {
    return 'Історія порожня';
  }
  
  let message = '📊 <b>Історія змін статусу світла:</b>\n\n';
  
  for (const entry of recentHistory) {
    const icon = entry.event === 'ON' ? '🟢' : '🔴';
    const eventText = entry.event === 'ON' ? 'Світло з\'явилось' : 'Світло зникло';
    message += `${icon} <b>${eventText}</b>\n`;
    message += `🕐 ${formatTime(entry.time)}\n`;
    message += `⏱ Тривалість: ${entry.duration_formatted}\n\n`;
  }
  
  const statusIcon = history.current_status === 'ON' ? '🟢' : '🔴';
  const statusText = history.current_status === 'ON' ? 'Є світло' : 'Немає світла';
  message += `<b>Поточний статус:</b> ${statusIcon} ${statusText}`;
  
  return message;
}

async function exportHistoryToCSV() {
  const csvLines = ['Time,Event,Duration (ms),Duration Formatted'];
  
  for (const entry of history.history) {
    csvLines.push(`${entry.time},${entry.event},${entry.duration},${entry.duration_formatted}`);
  }
  
  const csvContent = csvLines.join('\n');
  await fs.writeFile('light-history.csv', csvContent);
  console.log('History exported to CSV');
  return csvContent;
}

async function runBot() {
  if (!process.env.TELEGRAM_BOT_TOKEN) {
    console.log('TELEGRAM_BOT_TOKEN not set. Bot commands will not work.');
    return;
  }

  await loadConfig();
  await loadHistory();

  const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN, { polling: true });

  // Handle /start command
  bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;
    const welcomeMessage = `
👋 <b>Вітаємо у DTEK Power Monitoring Bot!</b>

Цей бот моніторить наявність електроенергії та надсилає сповіщення про зміни.

<b>Доступні команди:</b>
/light_history - Переглянути історію змін
/status - Поточний статус світла
/schedule - Графік відключень
/export - Експортувати історію в CSV
/help - Показати цю довідку

<b>Налаштування:</b>
IP для моніторингу: <code>${config.ip}</code>
Регіон: ${config.region}
Група: ${config.group}
`;
    
    await bot.sendMessage(chatId, welcomeMessage, { parse_mode: 'HTML' });
  });

  // Handle /help command
  bot.onText(/\/help/, async (msg) => {
    const chatId = msg.chat.id;
    const helpMessage = `
<b>📖 Довідка DTEK Bot</b>

<b>Команди:</b>
/start - Почати роботу з ботом
/light_history - Переглянути останні 10 змін
/status - Поточний статус світла
/schedule - Переглянути графік відключень
/export - Експортувати всю історію в CSV
/help - Показати цю довідку

<b>Як це працює:</b>
Бот автоматично перевіряє доступність роутера кожні 5 хвилин. Коли статус змінюється, ви отримуєте сповіщення з інформацією про час зміни та тривалість попереднього стану.

<b>Сповіщення:</b>
🟢 Світло з'явилось - роутер доступний
🔴 Світло зникло - роутер недоступний
`;
    
    await bot.sendMessage(chatId, helpMessage, { parse_mode: 'HTML' });
  });

  // Handle /light_history command
  bot.onText(/\/light_history/, async (msg) => {
    const chatId = msg.chat.id;
    
    try {
      const historyMessage = await getLightHistory(10);
      await bot.sendMessage(chatId, historyMessage, { parse_mode: 'HTML' });
    } catch (error) {
      console.error('Error getting history:', error);
      await bot.sendMessage(chatId, '❌ Помилка при отриманні історії');
    }
  });

  // Handle /status command
  bot.onText(/\/status/, async (msg) => {
    const chatId = msg.chat.id;
    
    try {
      const statusIcon = history.current_status === 'ON' ? '🟢' : '🔴';
      const statusText = history.current_status === 'ON' ? 'Є світло' : 'Немає світла';
      const lastChange = history.last_change ? formatTime(history.last_change) : 'невідомо';
      
      let statusMessage = `<b>⚡ Поточний статус</b>\n\n`;
      statusMessage += `${statusIcon} <b>${statusText}</b>\n`;
      statusMessage += `🕐 Остання зміна: ${lastChange}\n`;
      
      if (history.last_change) {
        const duration = Date.now() - new Date(history.last_change).getTime();
        statusMessage += `⏱ Тривалість: ${formatDuration(duration)}\n`;
      }
      
      statusMessage += `\n📊 Всього записів в історії: ${history.history.length}`;
      
      await bot.sendMessage(chatId, statusMessage, { parse_mode: 'HTML' });
    } catch (error) {
      console.error('Error getting status:', error);
      await bot.sendMessage(chatId, '❌ Помилка при отриманні статусу');
    }
  });

  // Handle /export command
  bot.onText(/\/export/, async (msg) => {
    const chatId = msg.chat.id;
    
    try {
      if (history.history.length === 0) {
        await bot.sendMessage(chatId, '❌ Історія порожня. Немає даних для експорту.');
        return;
      }
      
      const csvContent = await exportHistoryToCSV();
      
      await bot.sendDocument(chatId, 'light-history.csv', {
        caption: `📊 Експорт історії змін світла\n\nВсього записів: ${history.history.length}`
      });
    } catch (error) {
      console.error('Error exporting history:', error);
      await bot.sendMessage(chatId, '❌ Помилка при експорті історії');
    }
  });

  // Handle /schedule command
  bot.onText(/\/schedule/, async (msg) => {
    const chatId = msg.chat.id;
    
    try {
      await bot.sendMessage(chatId, '⏳ Завантажую графік відключень...');
      
      const scheduleMessage = await getOutageSchedule(config);
      await bot.sendMessage(chatId, scheduleMessage, { parse_mode: 'HTML' });
    } catch (error) {
      console.error('Error getting schedule:', error);
      await bot.sendMessage(chatId, '❌ Помилка при отриманні графіку відключень');
    }
  });

  console.log('Bot is running and listening for commands...');
  
  // Keep the bot running
  process.on('SIGINT', () => {
    console.log('Stopping bot...');
    bot.stopPolling();
    process.exit(0);
  });
}

// Run the bot
if (require.main === module) {
  runBot().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
}

module.exports = {
  runBot,
  getLightHistory,
  exportHistoryToCSV
};
