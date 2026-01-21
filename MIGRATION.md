# Migration Guide: v1.0 → v2.0 (Graphenko Architecture)

## Overview

DTEK-bot v2.0 is a complete rewrite from router-ping monitoring to Graphenko-style outage schedule image bot.

## What Changed

### Old Behavior (v1.0)
- Pinged a router to detect power outages
- Stored history in `light-history.json`
- Had interactive commands like `/light_history`, `/status`, `/export`
- Used CommonJS modules
- Exposed token in `light-config.json` ❌

### New Behavior (v2.0)
- Updates pinned PNG images with outage schedules
- Auto-registers channels via Telegram `getUpdates`
- Commands: `/graphenko_image` and `/graphenko_caption`
- ES Modules architecture
- Secure token handling via `.env` or GitHub Secrets ✅

## Migration Steps

### For Repository Owners

#### Step 1: Update GitHub Secrets
1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Delete old secret: `TELEGRAM_BOT_TOKEN` (if exists)
3. Add new secret:
   - Name: `BOT_TOKEN`
   - Value: Your bot token from @BotFather

#### Step 2: Pull New Code
```bash
git pull origin main
```

#### Step 3: Configure Bot for Your Channels
1. Add bot to your channel as admin with these permissions:
   - ✅ Pin messages
   - ✅ Delete messages
   - ✅ Post messages

2. Bot will send welcome message automatically

3. Configure image URL by sending in channel:
```
/graphenko_image https://raw.githubusercontent.com/Baskerville42/outage-data-ua/refs/heads/main/images/kyiv/gpv-3-2-emergency.png
```

4. (Optional) Set custom caption:
```
/graphenko_caption ⚡️ Графік відключень групи 3.2
```

### For Local Development

#### Step 1: Update Environment
```bash
# Remove old .env if exists
rm .env

# Create new .env from example
cp .env.example .env

# Edit .env and add your token
nano .env
```

Your `.env` should contain:
```
BOT_TOKEN=your_telegram_bot_token_here
```

#### Step 2: Install (No Dependencies!)
v2.0 has **zero external dependencies**. Just run:
```bash
node index.mjs
```

## Configuration Differences

### Old: light-config.json
```json
{
  "chat_id": "-1003523279109",
  "ip": "93.127.118.86",
  "region": "kyiv-region",
  "group": "3.1",
  "ping_interval": 60000,
  "ping_timeout": 5,
  "bot_token": "8437419933:AAG..." // ❌ EXPOSED
}
```

### New: graphenko-chats.json
```json
[
  {
    "-1003523279109": {
      "message_id": 123,
      "image_url": "https://raw.githubusercontent.com/.../kyiv/gpv-3-2.png",
      "caption": "⚡️ Custom caption"
    }
  }
]
```

## Breaking Changes

### Commands Removed
- `/start` - No longer needed
- `/light_history` - Router ping history not tracked
- `/status` - No longer monitors router
- `/schedule` - Replaced by automatic image updates
- `/export` - No CSV export
- `/help` - Use README instead

### Commands Added
- `/graphenko_image <url>` - Set image URL for auto-updates
- `/graphenko_caption <text>` - Set custom caption
- `/graphenko_caption -default` - Reset to default caption

### Files Removed
- `bot.js` - Old interactive bot
- `index.js` - Old monitoring script
- `outage-monitor.js` - Old schedule checker
- `light-config.json` - Config with exposed token
- `light-history.json` - Router ping history
- `.github/workflows/monitor.yml` - Old workflow

### Files Added
- `index.mjs` - Main bot (ES Module)
- `src/` directory - Modular architecture
- `graphenko-chats.json` - Channel configuration
- `.github/workflows/run-graphenko-bot.yml` - New workflow

## Troubleshooting

### Bot not updating messages
**Problem:** Workflow runs but nothing happens

**Solution:**
1. Check BOT_TOKEN secret is set correctly
2. Ensure bot is admin in channel
3. Send `/graphenko_image` command to register image URL

### "Network error getMe: Failed to parse URL"
**Problem:** Bot can't connect to Telegram

**Solution:**
- Make sure `BOT_TOKEN` environment variable or `.env` is set
- Token should NOT have any extra spaces or quotes

### Old workflow still running
**Problem:** Both old and new workflows execute

**Solution:**
```bash
# Disable old workflow in GitHub Actions UI
# Or delete it from repository
git rm .github/workflows/monitor.yml
git commit -m "Remove old workflow"
git push
```

### Want to keep old functionality?
**Solution:**
- Create a new branch from v1.0 tag before merging v2.0
- Or fork the v1.0 code to a separate repository
- v2.0 is a complete replacement, not backward compatible

## Data Migration

### If you want to preserve old history
Old `light-history.json` is not compatible with v2.0. To keep it:

```bash
# Before merging v2.0
cp light-history.json light-history.json.backup

# After v2.0
# Keep backup file for reference
# New bot uses different data model
```

## FAQ

**Q: Can I use both v1.0 and v2.0?**
A: No, they are fundamentally different bots. Choose one.

**Q: Will my old commands still work?**
A: No, all commands have changed. See "Commands Added" above.

**Q: Where is my router ping data?**
A: v2.0 doesn't monitor routers. It updates outage schedule images.

**Q: Do I need to install dependencies?**
A: No! v2.0 has zero dependencies.

**Q: What Node.js version do I need?**
A: Node.js 18 or newer (for native fetch and ES Modules)

**Q: How do I add multiple channels?**
A: Add bot to each channel, send `/graphenko_image` in each

**Q: Can I customize update frequency?**
A: Yes, edit `cron` in `.github/workflows/run-graphenko-bot.yml`

## Support

If you have issues with migration:
1. Check this guide thoroughly
2. Review README.md for v2.0 documentation
3. Open an issue on GitHub with:
   - Migration step you're on
   - Error messages (remove sensitive data!)
   - Your environment (OS, Node version)

---

**After migration is complete, you can delete this file.**

Слава Україні! 🇺🇦
