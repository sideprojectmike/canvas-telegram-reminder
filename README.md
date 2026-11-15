# Canvas → Telegram homework reminder

A free bot that texts you every morning with everything due this week, color-coded by urgency, then checks in at 6:30 PM and keeps pinging every 30 minutes until you reply. It runs on GitHub Actions, so there's no server and your computer can be off. Python standard library only.

**Morning (9:06 AM)**
- Today's weather emoji and the high and low (Open-Meteo, free, no key)
- 🔥 Due today, then the rest of the week grouped by day
- 🟢 due within 2 days · 🟡 within 4 · 🟠 within 7 · 📝 exams
- Your classes for the day

**Evening (6:30 PM)**
- What's still due tonight and what's due tomorrow
- Reply anything in Telegram to stop the 👀 ⏰ 🚨 📣 reminders. They also stop at 11:30 PM.

## Setup (about 10 minutes)
1. **Telegram bot:** message @BotFather (the verified one), send `/newbot`, and copy the token. Send your new bot any message.
2. **Chat ID:** open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`.
3. **Canvas feed:** in Canvas, go to Calendar → **Calendar Feed** and copy the link.
4. **Fork this repo**, then go to Settings → Secrets and variables → Actions:

| Secrets | |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from step 1 |
| `TELEGRAM_CHAT_ID` | from step 2 |
| `CANVAS_ICS_URL` | from step 3 |

| Variables (optional) | |
|---|---|
| `TIMEZONE` | e.g. `America/Chicago` (default `America/New_York`) |
| `WEATHER_LAT`, `WEATHER_LON` | your city, for the weather emoji |
| `COURSE_SITE_URL`, `COURSE_SITE_NAME` | a course website that lists "Homework 3 (due 3/6)" style rows |

5. Edit `SCHEDULE` and `COURSE_TAGS` at the top of `briefing.py` to match your classes.
6. If you're not on US Eastern time, change the cron times in `.github/workflows/` (they're in UTC).
7. Go to **Actions → Morning briefing → Run workflow** to test it.

## Notes
- Your token, chat ID and Canvas link stay in GitHub secrets, never in the code. The Canvas feed link works like a password, so don't share it.
- GitHub can start scheduled runs 5–30 minutes late.
- Only Canvas and the optional course site are checked. Gradescope, Piazza and Ed have no feeds.
- Run `python test_briefing.py` for the self-check, or `python briefing.py --dry-run` (with the env vars set) to print instead of sending.
