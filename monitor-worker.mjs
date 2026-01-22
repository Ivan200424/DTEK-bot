import './src/config/env.mjs';
import { MAP_FILE } from './src/config/constants.mjs';
import { loadMessageMapFromFile, saveMessageMapToFile } from './src/storage/messageMapIO.mjs';
import { checkHostStatus, formatDuration } from './src/utils/monitor.mjs';
import { getNextPlannedOutage, formatOutageWindow } from './src/utils/outage.mjs';
import { sendTextMessage } from './src/telegram/api.mjs';

// Constants
const MONITOR_DURATION_MS = 15 * 60 * 1000; // 15 minutes
const TARGET_CHAT_ID = '-1003523279109';
const DEFAULT_HOST = '93.127.118.86';
const DEFAULT_PORT = 443;
const DEFAULT_INTERVAL_SEC = 30;

/**
 * Get Kyiv time in HH:MM format
 */
function getKyivTime() {
  const now = new Date();
  const kyivTime = new Date(now.toLocaleString('en-US', { timeZone: 'Europe/Kyiv' }));
  const hours = String(kyivTime.getHours()).padStart(2, '0');
  const minutes = String(kyivTime.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

/**
 * Send status change notification
 */
async function sendStatusNotification(chatId, newStatus, lastChangeTime) {
  const currentTime = getKyivTime();
  const duration = Date.now() - lastChangeTime;
  const formattedDuration = formatDuration(duration);
  
  let message;
  
  if (newStatus === 'online') {
    // Power is back ON
    message = `🟢 ${currentTime} Світло з'явилося\n🕓 Його не було ${formattedDuration}`;
    
    // Try to get next planned outage
    const nextOutage = await getNextPlannedOutage();
    if (nextOutage) {
      const windowStr = formatOutageWindow(nextOutage);
      message += `\n🗓 Наступне планове: ${windowStr}`;
    }
  } else {
    // Power is OFF
    message = `🔴 ${currentTime} Світло зникло\n🕓 Воно було ${formattedDuration}`;
    
    // Try to get next planned outage (when we expect it back)
    const nextOutage = await getNextPlannedOutage();
    if (nextOutage) {
      message += `\n🗓 Очікуємо за графіком о ${nextOutage.start}`;
    }
  }
  
  await sendTextMessage(chatId, message);
  console.log(`Status notification sent to ${chatId}: ${newStatus}`);
}

/**
 * Monitor loop - runs for ~15 minutes
 */
async function monitorLoop() {
  const startTime = Date.now();
  const endTime = startTime + MONITOR_DURATION_MS;
  
  console.log(`Starting monitor loop for ${MONITOR_DURATION_MS / 1000}s (until ${new Date(endTime).toISOString()})`);
  
  while (Date.now() < endTime) {
    // Load current state
    const { map } = loadMessageMapFromFile(MAP_FILE);
    const chatConfig = map[TARGET_CHAT_ID];
    
    if (!chatConfig) {
      console.log(`Chat ${TARGET_CHAT_ID} not found in map, skipping monitoring`);
      break;
    }
    
    // Check if monitoring is enabled for this chat
    if (chatConfig.monitor_enabled !== true) {
      console.log(`Monitoring disabled for ${TARGET_CHAT_ID}, exiting loop`);
      break;
    }
    
    // Get monitor config with defaults
    const host = chatConfig.monitor_host || DEFAULT_HOST;
    const port = chatConfig.monitor_port !== undefined ? chatConfig.monitor_port : DEFAULT_PORT;
    const intervalSec = chatConfig.monitor_interval_sec || DEFAULT_INTERVAL_SEC;
    
    // Check status
    const isOnline = await checkHostStatus(host, port);
    const newStatus = isOnline ? 'online' : 'offline';
    
    console.log(`[${getKyivTime()}] Host ${host}:${port} status: ${newStatus}`);
    
    // Detect state change
    const previousStatus = chatConfig.monitor_last_status;
    const lastChange = chatConfig.monitor_last_change || Date.now();
    
    if (previousStatus && previousStatus !== newStatus) {
      // Status changed!
      console.log(`Status changed from ${previousStatus} to ${newStatus}`);
      await sendStatusNotification(TARGET_CHAT_ID, newStatus, lastChange);
      
      // Update state
      chatConfig.monitor_last_status = newStatus;
      chatConfig.monitor_last_change = Date.now();
      map[TARGET_CHAT_ID] = chatConfig;
      saveMessageMapToFile(MAP_FILE, map);
    } else if (!previousStatus) {
      // First check - initialize state without notification
      console.log(`Initializing monitor state: ${newStatus}`);
      chatConfig.monitor_last_status = newStatus;
      chatConfig.monitor_last_change = Date.now();
      map[TARGET_CHAT_ID] = chatConfig;
      saveMessageMapToFile(MAP_FILE, map);
    }
    
    // Wait for next check
    const remainingTime = endTime - Date.now();
    const sleepTime = Math.min(intervalSec * 1000, remainingTime);
    
    if (sleepTime > 0) {
      await new Promise(resolve => setTimeout(resolve, sleepTime));
    }
  }
  
  console.log('Monitor loop finished');
}

// Run the monitor loop
(async () => {
  try {
    await monitorLoop();
  } catch (error) {
    console.error('Monitor loop error:', error);
    process.exit(1);
  }
})();
