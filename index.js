const TelegramBot = require('node-telegram-bot-api');
const ping = require('ping');
const fs = require('fs').promises;
const fetch = require('node-fetch');
const path = require('path');
const { checkForScheduleUpdates } = require('./outage-monitor');

// Load environment variables from .env file if it exists
try {
  require('dotenv').config();
} catch (error) {
  // dotenv not available, using environment variables
}

// Load configuration
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

async function saveHistory() {
  try {
    await fs.writeFile('light-history.json', JSON.stringify(history, null, 2));
    console.log('History saved successfully');
  } catch (error) {
    console.error('Error saving history:', error);
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

async function checkPing() {
  try {
    // Validate IP address format to prevent command injection
    const ipRegex = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    
    if (!ipRegex.test(config.ip)) {
      console.error('Invalid IP address format:', config.ip);
      return false;
    }
    
    const res = await ping.promise.probe(config.ip, {
      timeout: config.ping_timeout || 5,
      extra: ['-c', '1']
    });
    return res.alive;
  } catch (error) {
    console.error('Ping error:', error);
    return false;
  }
}

async function sendTelegramMessage(message) {
  if (!process.env.TELEGRAM_BOT_TOKEN) {
    console.log('No TELEGRAM_BOT_TOKEN set, would send:', message);
    return;
  }
  
  try {
    const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN);
    await bot.sendMessage(config.chat_id, message, { parse_mode: 'HTML' });
    console.log('Message sent to Telegram');
  } catch (error) {
    console.error('Error sending message:', error);
  }
}

async function checkLightStatus() {
  const isOnline = await checkPing();
  const newStatus = isOnline ? 'ON' : 'OFF';
  const currentTime = new Date().toISOString();
  
  console.log(`Ping result: ${isOnline ? 'Success' : 'Failed'} - Status: ${newStatus}`);
  
  // Check if status changed
  if (history.current_status !== 'UNKNOWN' && history.current_status !== newStatus) {
    const lastChangeTime = history.last_change ? new Date(history.last_change) : new Date();
    const duration = new Date(currentTime) - lastChangeTime;
    
    let message;
    if (newStatus === 'OFF') {
      message = `🔴 Світло зникло\n🕐 О ${formatTime(currentTime)}\n⏱ Було світла ${formatDuration(duration)}`;
    } else {
      message = `🟢 Світло з'явилось\n🕐 О ${formatTime(currentTime)}\n⏱ Його не було ${formatDuration(duration)}`;
    }
    
    console.log('Status changed:', history.current_status, '->', newStatus);
    console.log('Notification:', message);
    
    // Send notification
    await sendTelegramMessage(message);
    
    // Add to history
    history.history.push({
      time: currentTime,
      event: newStatus,
      duration: duration,
      duration_formatted: formatDuration(duration)
    });
    
    // Keep only last 100 records
    if (history.history.length > 100) {
      history.history = history.history.slice(-100);
    }
  }
  
  // Update current status
  if (history.current_status !== newStatus) {
    history.current_status = newStatus;
    history.last_change = currentTime;
    await saveHistory();
  }
}

async function exportHistoryToCSV() {
  const csvLines = ['Time,Event,Duration (ms),Duration Formatted'];
  
  for (const entry of history.history) {
    // Properly escape CSV values
    const escapeCSV = (value) => {
      if (value === null || value === undefined) return '';
      const stringValue = String(value);
      // If value contains comma, quote, or newline, wrap in quotes and escape quotes
      if (stringValue.includes(',') || stringValue.includes('"') || stringValue.includes('\n')) {
        return `"${stringValue.replace(/"/g, '""')}"`;
      }
      return stringValue;
    };
    
    csvLines.push(
      `${escapeCSV(entry.time)},${escapeCSV(entry.event)},${escapeCSV(entry.duration)},${escapeCSV(entry.duration_formatted)}`
    );
  }
  
  const csvContent = csvLines.join('\n');
  await fs.writeFile('light-history.csv', csvContent);
  console.log('History exported to CSV');
  return csvContent;
}

async function getLightHistory(limit = 10) {
  const recentHistory = history.history.slice(-limit).reverse();
  
  if (recentHistory.length === 0) {
    return 'Історія порожня';
  }
  
  let message = '📊 Історія змін статусу світла:\n\n';
  
  for (const entry of recentHistory) {
    const icon = entry.event === 'ON' ? '🟢' : '🔴';
    const eventText = entry.event === 'ON' ? 'Світло з\'явилось' : 'Світло зникло';
    message += `${icon} ${eventText}\n`;
    message += `🕐 ${formatTime(entry.time)}\n`;
    message += `⏱ Тривалість: ${entry.duration_formatted}\n\n`;
  }
  
  message += `Поточний статус: ${history.current_status === 'ON' ? '🟢 Є світло' : '🔴 Немає світла'}`;
  
  return message;
}

// Main execution
async function main() {
  console.log('DTEK Power Monitoring Bot starting...');
  
  await loadConfig();
  await loadHistory();
  
  // Check status once
  await checkLightStatus();
  
  // Check for outage schedule updates
  console.log('Checking for outage schedule updates...');
  const scheduleUpdate = await checkForScheduleUpdates(config);
  
  if (scheduleUpdate && scheduleUpdate.hasChanged) {
    console.log('Outage schedule has changed!');
    const message = `📅 <b>Оновлено графік відключень</b>\n\n${scheduleUpdate.message}`;
    await sendTelegramMessage(message);
  }
  
  console.log('Bot execution completed');
}

// Run the bot
main().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});

// Export functions for potential future use
module.exports = {
  checkLightStatus,
  getLightHistory,
  exportHistoryToCSV
};
