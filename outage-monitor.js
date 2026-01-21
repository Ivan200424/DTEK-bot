const fetch = require('node-fetch');
const fs = require('fs').promises;
const path = require('path');

// Configuration
const OUTAGE_REPO_URL = 'https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/';

async function fetchOutageData(region) {
  try {
    const url = `${OUTAGE_REPO_URL}${region}.json`;
    console.log(`Fetching outage data from: ${url}`);
    
    const response = await fetch(url);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching outage data:', error);
    return null;
  }
}

function parseOutageSchedule(data, group) {
  if (!data || !data.groups) {
    console.log('No groups data available');
    return null;
  }
  
  // Safely check if the group exists to prevent prototype pollution
  if (!Object.prototype.hasOwnProperty.call(data.groups, group)) {
    console.log(`Group ${group} not found`);
    return null;
  }
  
  const groupData = data.groups[group];
  
  return {
    region: data.region || 'Unknown',
    group: group,
    schedule: groupData,
    lastUpdate: data.lastUpdate || new Date().toISOString()
  };
}

function formatOutageSchedule(scheduleData) {
  if (!scheduleData) {
    return 'Немає даних про графік відключень';
  }
  
  let message = `📅 <b>Графік відключень</b>\n\n`;
  message += `📍 Регіон: ${scheduleData.region}\n`;
  message += `🔢 Група: ${scheduleData.group}\n`;
  message += `🕐 Оновлено: ${new Date(scheduleData.lastUpdate).toLocaleString('uk-UA')}\n\n`;
  
  if (scheduleData.schedule && Array.isArray(scheduleData.schedule)) {
    message += `<b>Заплановані відключення:</b>\n`;
    
    for (const slot of scheduleData.schedule) {
      message += `• ${slot.time || slot}\n`;
    }
  } else {
    message += `Немає запланованих відключень або дані недоступні`;
  }
  
  return message;
}

async function checkForScheduleUpdates(config) {
  try {
    // Fetch current outage data
    const data = await fetchOutageData(config.region);
    
    if (!data) {
      console.log('Failed to fetch outage data');
      return null;
    }
    
    // Parse schedule for the specific group
    const scheduleData = parseOutageSchedule(data, config.group);
    
    if (!scheduleData) {
      console.log('Failed to parse schedule data');
      return null;
    }
    
    // Check if there's a previous schedule saved
    let previousSchedule = null;
    try {
      const prevData = await fs.readFile('outage-schedule.json', 'utf8');
      previousSchedule = JSON.parse(prevData);
    } catch (error) {
      // No previous schedule exists
      console.log('No previous schedule found');
    }
    
    // Check if schedule has changed
    let hasChanged = false;
    if (!previousSchedule || 
        previousSchedule.lastUpdate !== scheduleData.lastUpdate ||
        JSON.stringify(previousSchedule.schedule) !== JSON.stringify(scheduleData.schedule)) {
      hasChanged = true;
    }
    
    // Save current schedule
    await fs.writeFile('outage-schedule.json', JSON.stringify(scheduleData, null, 2));
    
    return {
      scheduleData,
      hasChanged,
      message: formatOutageSchedule(scheduleData)
    };
  } catch (error) {
    console.error('Error checking schedule updates:', error);
    return null;
  }
}

async function getOutageSchedule(config) {
  try {
    const data = await fetchOutageData(config.region);
    
    if (!data) {
      return 'Не вдалося отримати дані про графік відключень';
    }
    
    const scheduleData = parseOutageSchedule(data, config.group);
    return formatOutageSchedule(scheduleData);
  } catch (error) {
    console.error('Error getting outage schedule:', error);
    return 'Помилка при отриманні графіку відключень';
  }
}

module.exports = {
  fetchOutageData,
  parseOutageSchedule,
  formatOutageSchedule,
  checkForScheduleUpdates,
  getOutageSchedule
};
