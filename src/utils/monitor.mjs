import { exec } from 'node:child_process';
import { promisify } from 'node:util';
import net from 'node:net';

const execAsync = promisify(exec);

/**
 * Validate host parameter to prevent command injection
 * @param {string} host - Host to validate
 * @returns {boolean} true if valid
 */
function isValidHost(host) {
  // Allow IP addresses (IPv4) and simple hostnames
  // IPv4: xxx.xxx.xxx.xxx
  // Hostname: alphanumeric, dots, hyphens only
  const ipv4Regex = /^(\d{1,3}\.){3}\d{1,3}$/;
  const hostnameRegex = /^[a-zA-Z0-9.-]+$/;
  
  if (!host || typeof host !== 'string') return false;
  if (host.length > 253) return false; // Max hostname length
  
  return ipv4Regex.test(host) || hostnameRegex.test(host);
}

/**
 * Try ICMP ping to check if host is reachable
 * @param {string} host - IP or hostname
 * @returns {Promise<boolean>} true if ping succeeds
 */
export async function tryPing(host) {
  if (!isValidHost(host)) {
    console.error(`Invalid host parameter: ${host}`);
    return false;
  }
  
  try {
    // Use ping with timeout of 5 seconds, 1 packet
    const { stdout } = await execAsync(`ping -c 1 -W 5 ${host}`);
    return stdout.includes('1 received') || stdout.includes('1 packets received');
  } catch (err) {
    // Ping failed or command error
    return false;
  }
}

/**
 * Try TCP connect to check if port is open
 * @param {string} host - IP or hostname
 * @param {number} port - Port number (default 443)
 * @returns {Promise<boolean>} true if connection succeeds
 */
export async function tryTcpConnect(host, port = 443) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const timeout = 5000; // 5 seconds

    socket.setTimeout(timeout);
    socket.on('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.on('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.on('error', () => {
      resolve(false);
    });

    socket.connect(port, host);
  });
}

/**
 * Check if target is online using ping and/or TCP connect
 * @param {string} host - IP or hostname
 * @param {number} port - Port number (default 443)
 * @returns {Promise<boolean>} true if either ping or TCP succeeds
 */
export async function checkHostStatus(host, port = 443) {
  // Try ICMP ping first
  const pingResult = await tryPing(host);
  if (pingResult) {
    return true;
  }

  // If ping fails or is blocked, try TCP connect
  const tcpResult = await tryTcpConnect(host, port);
  return tcpResult;
}

/**
 * Format duration in Ukrainian
 * @param {number} milliseconds - Duration in milliseconds
 * @returns {string} Formatted duration like "5 хвилин" or "2 години 15 хвилин"
 */
export function formatDuration(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) {
    const remainingHours = hours % 24;
    if (remainingHours > 0) {
      return `${days} ${pluralDays(days)} ${remainingHours} ${pluralHours(remainingHours)}`;
    }
    return `${days} ${pluralDays(days)}`;
  }

  if (hours > 0) {
    const remainingMinutes = minutes % 60;
    if (remainingMinutes > 0) {
      return `${hours} ${pluralHours(hours)} ${remainingMinutes} ${pluralMinutes(remainingMinutes)}`;
    }
    return `${hours} ${pluralHours(hours)}`;
  }

  if (minutes > 0) {
    return `${minutes} ${pluralMinutes(minutes)}`;
  }

  return `${seconds} ${pluralSeconds(seconds)}`;
}

function pluralDays(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'день';
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'дні';
  return 'днів';
}

function pluralHours(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'година';
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'години';
  return 'годин';
}

function pluralMinutes(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'хвилина';
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'хвилини';
  return 'хвилин';
}

function pluralSeconds(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'секунда';
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'секунди';
  return 'секунд';
}
