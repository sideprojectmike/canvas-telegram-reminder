"""Homework reminder bot: morning briefing + 6:30pm check-in that nags until you reply.
Reads a Canvas calendar feed, an optional course website and Open-Meteo weather (all free),
sends via Telegram. Standard library only.

Env vars (GitHub secrets): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CANVAS_ICS_URL.
Optional: TIMEZONE, WEATHER_LAT + WEATHER_LON, COURSE_SITE_URL + COURSE_SITE_NAME.
  python briefing.py             morning briefing
  python briefing.py --evening   evening check-in / nag
  add --dry-run to print instead of sending
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TIMEZONE") or "America/New_York")  # GitHub passes "" for unset vars
DAYS_AHEAD = 7
CHECKIN_START, CHECKIN_END = (18, 30), (23, 30)  # local time window for evening nags

# EDIT ME: your weekly class schedule (Mon=0 ... Sun=6). Shown in the morning message.
SCHEDULE = {
    0: [" 9a  CS 101 · Room 100", " 2p  MATH 200 · Room 210"],
    2: [" 9a  CS 101 · Room 100", " 2p  MATH 200 · Room 210"],
    4: [" 9a  CS 101 · Room 100"],
}
# EDIT ME: Canvas course names -> short tags (substring match). Unmatched names are shown as-is.
COURSE_TAGS = {"CS 101": "CS 101", "MATH 200": "Math 200"}
EXAM_RE = re.compile(r"\b(exam|midterm|final|quiz)\b", re.I)

# WMO weather codes (Open-Meteo) -> (emoji, words)
WEATHER = [((0,), "☀️", "clear"), ((1,), "🌤️", "mostly sunny"), ((2,), "⛅", "partly cloudy"),
           ((3,), "☁️", "cloudy"), ((45, 48), "🌫️", "foggy"), ((51, 53, 55, 56, 57), "🌦️", "drizzle"),
           ((61, 63, 65, 66, 67, 80, 81, 82), "🌧️", "rain"), ((71, 73, 75, 77, 85, 86), "🌨️", "snow"),
           ((95, 96, 99), "⛈️", "thunderstorms")]


def http(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "morning-briefing"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def resolve(month, day, today):
    """Month/day with no year -> nearest sensible date (handles Dec->Jan rollover)."""
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    if d < today - timedelta(days=60):
        d = d.replace(year=today.year + 1)
    return d


def short_time(dt):
    return dt.strftime("%-I:%M%p").replace(":00", "").lower()


# ---------- sources ----------

def parse_ics(text):
    """Canvas feed -> [(date, time, title)] for assignments, plus exam-like calendar events."""
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold continuation lines
    events = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        uid = re.search(r"^UID:(.*)$", block, re.M)
        summ = re.search(r"^SUMMARY[^:]*:(.*)$", block, re.M)
        start = re.search(r"^DTSTART[^:]*:(\d{8})(T(\d{6})(Z?))?", block, re.M)
        if not (uid and summ and start):
            continue
        title = summ.group(1).replace("\\,", ",").replace("\\;", ";").strip()
        title = re.sub(r"\s*\((Fall|Spring|Summer) \d{4}\)", "", title)
        is_assignment = "assignment" in uid.group(1)
        if not is_assignment and not EXAM_RE.search(title):
            continue
        if start.group(2):
            dt = datetime.strptime(start.group(1) + start.group(3), "%Y%m%d%H%M%S")
            dt = dt.replace(tzinfo=ZoneInfo("UTC") if start.group(4) else TZ).astimezone(TZ)
            events.append((dt.date(), short_time(dt), title))
        else:
            # Canvas exports assignments due at 11:59pm as all-day events
            d = datetime.strptime(start.group(1), "%Y%m%d").date()
            events.append((d, "11:59pm" if is_assignment else None, title))
    return events


SITE_RE = re.compile(r"\b(Homework|Lab|Project)\s+(\d+)\b[^()]{0,80}\(([^)]*due[^)]*)\)", re.I)
SITE_DUE_RE = re.compile(r"(checkpoint)?[^,]*?\bdue\s+(\d{1,2})/(\d{1,2})", re.I)


def course_site_items(html, today, course="Course"):
    """For course websites whose schedule rows look like 'Homework 9 Linear Regression (due 11/18)'
    or 'Project 2 (Checkpoint due 11/13, Entire project due 11/20)'. Assumes a 10am deadline,
    so each item is shown the day before."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    out = {}
    for kind, num, inner in SITE_RE.findall(text):
        for ckpt, mo, dy in SITE_DUE_RE.findall(inner):
            label = f"{kind.title()} {num}" + (" checkpoint" if ckpt else "") + f" [{course}]"
            d = resolve(int(mo), int(dy), today)
            if d:  # due 10am, so remind the day before
                out[label] = (d - timedelta(days=1), f"due {d.strftime('%a')} 10am", label)
    return list(out.values())


def weather_today():
    """Open-Meteo (free, no key) -> (emoji, words, hi, lo), or None if no location is set."""
    if not os.environ.get("WEATHER_LAT"):
        return None
    q = urllib.parse.urlencode({
        "latitude": os.environ["WEATHER_LAT"], "longitude": os.environ["WEATHER_LON"], "forecast_days": 1,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit", "timezone": str(TZ)})
    d = json.loads(http("https://api.open-meteo.com/v1/forecast?" + q))["daily"]
    code = d["weather_code"][0]
    emoji, words = next(((e, w) for codes, e, w in WEATHER if code in codes), ("🌡️", ""))
    return emoji, words, round(d["temperature_2m_max"][0]), round(d["temperature_2m_min"][0])


def gather(today):
    """All due items + warnings. Each source fails on its own so one broken site never kills it."""
    due, notes = [], []
    try:
        due += parse_ics(http(os.environ["CANVAS_ICS_URL"]))
    except Exception as e:
        notes.append(f"Canvas feed failed ({type(e).__name__}). Check Canvas.")
    site, name = os.environ.get("COURSE_SITE_URL"), os.environ.get("COURSE_SITE_NAME") or "Course"
    if site:
        try:
            items = course_site_items(http(site), today, name)
            due += items
            if not items:
                notes.append(f"{name} site had no due dates (new semester URL?).")
        except Exception as e:
            notes.append(f"{name} site unreachable ({type(e).__name__}).")
    return due, notes


# ---------- formatting ----------

def minutes(t):
    """'2pm' -> 840, '11:59pm' -> 1439; 'due Wed 10am' -> 600; unknown times sort last."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?([ap])", (t or "").replace(".", ""))
    if not m:
        return 9999
    return (int(m.group(1)) % 12 + (12 if m.group(3) == "p" else 0)) * 60 + int(m.group(2) or 0)


def split_course(text):
    """'Homework 3: Foo [CS 101-LEC-001]' -> ('CS 101', 'Homework 3: Foo')."""
    m = re.match(r"(.*?)\s*\[(.*)\]\s*$", text)  # course names can nest: [BIO 15 [F 2026]]
    if not m:
        return "", text
    tag = next((v for k, v in COURSE_TAGS.items() if k in m.group(2)), m.group(2))
    return tag, m.group(1)


def esc(s):  # Telegram HTML mode needs these escaped
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tier(days):
    return "🟢" if days <= 2 else "🟡" if days <= 4 else "🟠"


def pretty_time(t):
    return (t or "time TBD").replace("am", " am").replace("pm", " pm")


def window(today, due, days=DAYS_AHEAD):
    """Sorted, de-duplicated items due from today through today+days."""
    end = today + timedelta(days=days)
    seen, items = set(), []
    for d, t, text in sorted(due, key=lambda x: (x[0], minutes(x[1]))):
        key = (d, re.sub(r"\W+", "", text.lower())[:40])
        if today <= d <= end and key not in seen:
            seen.add(key)
            items.append((d, t, text))
    return items


def item_lines(today, d, t, text):
    course, title = split_course(text)
    icon = "📝" if EXAM_RE.search(title) else tier((d - today).days)
    head = f"<b>{esc(course)}</b>  " if course else ""
    return [f"{icon} {head}{esc(title)}", f"      <i>{esc(pretty_time(t))}</i>"]


def day_label(today, d):
    n = (d - today).days
    when = "tomorrow" if n == 1 else f"in {n} days"
    return f"<b>{d.strftime('%a %b %-d')}</b>  ·  <i>{when}</i>"


RULE = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
HEAVY = "━━━━━━━━━━━━━━"


def header(emoji, title):
    """Telegram has no heading sizes, so: emoji + bold underlined caps + heavy rule."""
    return f"{emoji} <b><u>{esc(title.upper())}</u></b>\n{HEAVY}"


def build_message(today, due, notes=(), weather=None):
    """Morning briefing in Telegram HTML."""
    items = window(today, due)
    today_items = [i for i in items if i[0] == today]
    later = [i for i in items if i[0] > today]

    emoji, words, hi, lo = weather or ("☀️", "", None, None)
    lines = [header(emoji, today.strftime("%A · %B %-d"))]
    if hi is not None:
        lines.append(f"<i>{words} · {hi}° / {lo}°</i>")
    summary = f"{len(today_items)} due today" if today_items else "nothing due today"
    lines += [f"<i>{summary} · {len(items)} this week</i>", ""]

    if today_items:
        lines.append("🔥 <b>DUE TODAY</b>")
        for i in today_items:
            lines += item_lines(today, *i)
    else:
        lines.append("✨ <b>Nothing due today</b>")

    if later:
        lines += ["", "🗓️ <b>THIS WEEK</b>"]
        for day in sorted({d for d, _, _ in later}):
            lines += ["", day_label(today, day)]
            for i in later:
                if i[0] == day:
                    lines += item_lines(today, *i)

    if today.weekday() in SCHEDULE:
        lines += [RULE, "🏫 <b>CLASSES</b>",
                  "<blockquote>" + "\n".join(esc(c) for c in SCHEDULE[today.weekday()]) + "</blockquote>"]
    else:
        lines += [RULE]
    if notes:
        lines += [""] + [f"⚠️ <i>{esc(n)}</i>" for n in notes]
    return "\n".join(lines)[:4000]


def build_checkin(today, due, nag=0):
    """Evening check-in. nag=0 is the first message; later ones get shorter and pushier."""
    tonight = [i for i in window(today, due, 0) if minutes(i[1]) >= 18 * 60]
    tomorrow = [i for i in window(today, due, 1) if i[0] == today + timedelta(days=1)]
    if nag:
        ping = ["👀", "⏰", "🚨", "📣"][min(nag, 4) - 1]
        lines = [header(ping, f"Check-in reminder #{nag}"), ""]
    else:
        lines = [header("🌙", "Evening check-in · " + today.strftime("%a %b %-d")),
                 "<i>How's the work going?</i>", ""]
    if tonight:
        lines.append("⏳ <b>STILL DUE TONIGHT</b>")
        for i in tonight:
            lines += item_lines(today, *i)
    if tomorrow:
        if tonight:
            lines.append("")
        lines.append("🌅 <b>DUE TOMORROW</b>")
        for i in tomorrow:
            lines += item_lines(today, *i)
    if not (tonight or tomorrow):
        lines.append("✨ Nothing due tonight or tomorrow")
    lines += [RULE, "💬 <b>Reply anything</b> (like <i>done</i>) to check in.",
              "<i>I'll ping you every 30 min until you do.</i>" if not nag else "<i>Pings stop once you reply.</i>"]
    return "\n".join(lines)


# ---------- telegram ----------

def tg(method, **params):
    return json.loads(http(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}", params))


def send(text):
    if "--dry-run" in sys.argv:
        print(text)
    else:
        tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=text, parse_mode="HTML")


def last_reply_time():
    """Newest message you sent the bot (Telegram keeps ~24h of these), or None."""
    chat = int(os.environ["TELEGRAM_CHAT_ID"])
    times = [u["message"]["date"] for u in tg("getUpdates").get("result", [])
             if u.get("message", {}).get("chat", {}).get("id") == chat]
    return datetime.fromtimestamp(max(times), TZ) if times else None


# ---------- entry points ----------

def scheduled():
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def is_9am_cron(cron, now):
    """Two UTC crons cover standard/daylight time; send only from the one that is 9am local.
    Uses the cron that fired, not the clock, because GitHub often starts runs late."""
    utc_hour = int(cron.split()[1])
    offset = int(now.utcoffset().total_seconds() // 3600)  # e.g. -5 EST, -4 EDT
    return (9 - offset) % 24 == utc_hour


def morning(now):
    if scheduled() and not is_9am_cron(os.environ.get("SCHEDULE_CRON", "6 14 * * *"), now):
        return
    today = now.date()
    due, notes = gather(today)
    try:
        weather = weather_today()
    except Exception:
        weather = None
    send(build_message(today, due, notes, weather))


def evening(now):
    start = now.replace(hour=CHECKIN_START[0], minute=CHECKIN_START[1], second=0, microsecond=0)
    end = now.replace(hour=CHECKIN_END[0], minute=CHECKIN_END[1])
    if scheduled() and not (start - timedelta(minutes=10) <= now <= end):
        return
    replied = last_reply_time()
    if scheduled() and replied and replied >= start:
        if now - replied < timedelta(minutes=31):  # acknowledge once, on the first run after the reply
            send("✅ <b>Checked in.</b> Nice work. See you in the morning 🌙")
        return
    # first run (18:30, even if GitHub starts it ~20 min late) is the check-in; each later run is a nag
    late = (now - start).total_seconds() / 60
    nag = 0 if not scheduled() or late < 20 else int((late - 20) // 30) + 1
    due, _ = gather(now.date())
    send(build_checkin(now.date(), due, nag))


def main():
    if not os.environ.get("TELEGRAM_BOT_TOKEN") and "--dry-run" not in sys.argv:
        return print("Not configured yet: add the TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and CANVAS_ICS_URL secrets.")
    now = datetime.now(TZ)
    evening(now) if "--evening" in sys.argv else morning(now)


if __name__ == "__main__":
    main()
