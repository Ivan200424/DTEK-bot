# Power Monitoring Implementation Summary

## Overview
This implementation adds external power monitoring functionality to the DTEK Telegram bot by monitoring a router's availability via ping/TCP connection checks.

## Architecture

### Components

1. **Monitoring Utilities** (`src/utils/monitor.mjs`)
   - `checkHostStatus()`: Checks if target is online using ICMP ping with TCP fallback
   - `tryPing()`: ICMP ping with command injection protection
   - `tryTcpConnect()`: TCP port check (default 443)
   - `formatDuration()`: Ukrainian duration formatting

2. **Outage Schedule** (`src/utils/outage.mjs`)
   - `getNextPlannedOutage()`: Fetches next planned outage from GitHub repo
   - `formatOutageWindow()`: Formats time window display
   - Source: `github.com/Baskerville42/outage-data-ua` (group 3.1)

3. **Monitor Worker** (`monitor-worker.mjs`)
   - Runs 15-minute monitoring loops
   - Checks every 30 seconds
   - Detects status changes (online ↔ offline)
   - Sends Ukrainian notifications with duration and planned outage info
   - Persists state to graphenko-chats.json

4. **Bot Commands** (in `index.mjs`)
   - `/monitor_on`: Enable monitoring
   - `/monitor_off`: Disable monitoring
   - `/monitor_status`: Check current status

5. **GitHub Actions Workflow** (`.github/workflows/monitor-power.yml`)
   - Runs every 1 minute
   - Each run monitors for ~15 minutes
   - Commits state changes back to repo

### State Storage

Monitor state is stored in `graphenko-chats.json` with these fields:
- `monitor_enabled`: boolean, monitoring on/off
- `monitor_host`: string, target IP/hostname (default: 93.127.118.86)
- `monitor_port`: number, target port (default: 443)
- `monitor_interval_sec`: number, check interval (default: 30)
- `monitor_last_status`: string, "online" or "offline"
- `monitor_last_change`: number, timestamp of last status change

## Notification Messages

### Power OFF (online → offline)
```
🔴 14:30 Світло зникло
🕓 Воно було 2 години 15 хвилин
🗓 Очікуємо за графіком о 16:00
```

### Power ON (offline → online)
```
🟢 14:30 Світло з'явилося
🕓 Його не було 45 хвилин
🗓 Наступне планове: 18:00–20:00
```

## Security Features

1. **Command Injection Protection**: Host parameter validation prevents shell injection
2. **Graceful Error Handling**: Network failures don't crash the monitor
3. **State Persistence**: Atomic file writes prevent data corruption
4. **Input Validation**: All user inputs are validated before use

## Configuration

Target settings (hardcoded as per requirements):
- Chat ID: `-1003523279109`
- Host: `93.127.118.86`
- Port: `443`
- Check interval: `30` seconds
- Monitor duration: `15` minutes per workflow run
- Workflow frequency: Every `1` minute

## Usage

1. User sends `/monitor_on` to enable monitoring
2. Bot acknowledges and starts monitoring on next workflow run
3. Monitor checks host every 30 seconds
4. On status change, bot sends notification to chat
5. State is saved to graphenko-chats.json
6. User can check status with `/monitor_status` or disable with `/monitor_off`

## Testing

All components have been tested:
- ✅ Host validation (prevents command injection)
- ✅ Ping and TCP connectivity checks
- ✅ Duration formatting in Ukrainian
- ✅ Planned outage fetching from GitHub
- ✅ State persistence (load/save)
- ✅ Bot command pattern matching
- ✅ Notification message formatting
- ✅ Timezone handling (Europe/Kyiv)

## Deployment

The monitoring will be active once:
1. PR is merged to main branch
2. User sends `/monitor_on` command in the target chat
3. Next GitHub Actions workflow run starts (within 1 minute)

## Future Improvements

Potential enhancements (not in current scope):
- Multiple chat support (currently hardcoded to one chat)
- Configurable monitoring targets via bot commands
- Statistics and uptime tracking
- SMS/email fallback notifications
- Webhook integration for faster response times
