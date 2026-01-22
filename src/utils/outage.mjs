/**
 * Fetch and parse planned outage schedule from GitHub
 * Source: https://github.com/Baskerville42/outage-data-ua/blob/main/data/kyiv-region.json
 */

const OUTAGE_DATA_URL = 'https://raw.githubusercontent.com/Baskerville42/outage-data-ua/refs/heads/main/data/kyiv-region.json';
const GROUP_ID = '3.1';

/**
 * Fetch outage data from GitHub
 * @returns {Promise<object|null>} Parsed JSON or null on error
 */
async function fetchOutageData() {
  try {
    const response = await fetch(OUTAGE_DATA_URL);
    if (!response.ok) {
      console.error(`Failed to fetch outage data: ${response.status}`);
      return null;
    }
    return await response.json();
  } catch (err) {
    console.error('Error fetching outage data:', err.message);
    return null;
  }
}

/**
 * Parse time string like "14:00" into hours and minutes
 * @param {string} timeStr - Time in HH:MM format
 * @returns {{hours: number, minutes: number}|null}
 */
function parseTime(timeStr) {
  if (!timeStr || typeof timeStr !== 'string') return null;
  const match = timeStr.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  return {
    hours: parseInt(match[1], 10),
    minutes: parseInt(match[2], 10)
  };
}

/**
 * Get the next planned outage window for the specified group
 * @param {string} groupId - Group ID (e.g., '3.1')
 * @returns {Promise<{start: string, end: string}|null>} Next outage window or null
 */
export async function getNextPlannedOutage(groupId = GROUP_ID) {
  const data = await fetchOutageData();
  if (!data || !data.schedule) return null;

  // Find schedule for the group
  const groupSchedule = data.schedule.find(s => s.group === groupId);
  if (!groupSchedule || !groupSchedule.periods) return null;

  const now = new Date();
  const kyivTime = new Date(now.toLocaleString('en-US', { timeZone: 'Europe/Kyiv' }));
  const currentDay = kyivTime.getDay(); // 0=Sunday, 1=Monday, etc.
  const currentHours = kyivTime.getHours();
  const currentMinutes = kyivTime.getMinutes();

  // Look for the next period starting from today
  for (let dayOffset = 0; dayOffset < 7; dayOffset++) {
    const checkDay = (currentDay + dayOffset) % 7;
    const dayName = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'][checkDay];
    
    const dayPeriods = groupSchedule.periods[dayName];
    if (!dayPeriods || !Array.isArray(dayPeriods)) continue;

    for (const period of dayPeriods) {
      const start = parseTime(period.start);
      const end = parseTime(period.end);
      if (!start || !end) continue;

      // For today (dayOffset === 0), only consider future times
      if (dayOffset === 0) {
        const startMinutes = start.hours * 60 + start.minutes;
        const currentTotalMinutes = currentHours * 60 + currentMinutes;
        if (startMinutes <= currentTotalMinutes) continue;
      }

      // Return first found period
      return {
        start: period.start,
        end: period.end
      };
    }
  }

  return null;
}

/**
 * Format outage window for display
 * @param {{start: string, end: string}} window - Outage window
 * @returns {string} Formatted string like "14:00–16:00"
 */
export function formatOutageWindow(window) {
  if (!window) return null;
  return `${window.start}–${window.end}`;
}
