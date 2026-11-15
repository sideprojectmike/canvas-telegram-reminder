"""Self-check with made-up data. Run: python test_briefing.py"""
import os
from datetime import date, datetime

os.environ["TIMEZONE"] = "America/New_York"  # expected times below assume this, whatever you configured

from briefing import (TZ, build_checkin, build_message, course_site_items, is_9am_cron, parse_ics,
                      split_course, tier)

today = date(2030, 3, 4)  # a Monday

# Canvas feed: assignments kept, exams kept, other events dropped, all-day assignment = 11:59pm,
# UTC -> local, nested course brackets
ics = """BEGIN:VEVENT
UID:event-assignment-1001
DTSTART:20300304T190000Z
SUMMARY:Lab 4 - Sorting [CS 101-LEC-001]
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-1002
DTSTART;VALUE=DATE;VALUE=DATE:20300304
SUMMARY:Problem Set 6 [MATH 200-LEC-002]
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-1003
DTSTART:20300311T190000Z
SUMMARY:Reading Response 3 [BIO 15 [S 2030]]
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-2001
DTSTART:20300308T150000Z
SUMMARY:Midterm 1 [MATH 200-LEC-002]
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-2002
DTSTART:20300304T180000Z
SUMMARY:Office hours\\, room 2
END:VEVENT"""
feed = parse_ics(ics)
assert (date(2030, 3, 4), "2pm", "Lab 4 - Sorting [CS 101-LEC-001]") in feed, feed
assert (date(2030, 3, 4), "11:59pm", "Problem Set 6 [MATH 200-LEC-002]") in feed, feed
assert (date(2030, 3, 8), "10am", "Midterm 1 [MATH 200-LEC-002]") in feed, feed
assert not any("Office hours" in t for _, _, t in feed), "plain calendar events dropped"
assert split_course("Reading Response 3 [BIO 15 [S 2030]]") == ("BIO 15 [S 2030]", "Reading Response 3")

# optional course website rows; due 10am, so shown the day before
html = """<td><strong>Project 2</strong><a>Project 2 (Checkpoint due 3/1,
Entire project due 3/8)</a></td><td><strong>Homework 9</strong><a>Regression (due 3/6)</a></td>
<td><strong>Lab 9</strong>Lab 9 (due 3/8)</td><td><strong>Lecture 32</strong><a>Inference</a></td>"""
site = course_site_items(html, today, "STAT 20")
assert (date(2030, 3, 5), "due Wed 10am", "Homework 9 [STAT 20]") in site, site
assert (date(2030, 2, 28), "due Fri 10am", "Project 2 checkpoint [STAT 20]") in site, site
assert len(site) == 4, site

assert [tier(n) for n in (0, 2, 3, 4, 5, 7)] == ["🟢", "🟢", "🟡", "🟡", "🟠", "🟠"]

# morning message
m = build_message(today, feed + site, weather=("🌧️", "rain", 58, 49))
assert m.startswith("🌧️ <b><u>MONDAY · MARCH 4</u></b>\n━━━━━━━━━━━━━━\n<i>rain · 58° / 49°</i>"), m
assert "🔥 <b>DUE TODAY</b>" in m and m.index("Lab 4") < m.index("Problem Set 6"), m  # 2pm before 11:59pm
assert "🟢 <b>STAT 20</b>  Homework 9" in m and "tomorrow" in m, m
assert "📝 <b>Math 200</b>  Midterm 1" in m, m
assert "🟠 <b>BIO 15 [S 2030]</b>  Reading Response 3" in m, m  # 7 days out, untagged course
assert "Project 2 checkpoint" not in m, "past items dropped"
assert "<blockquote> 9a  CS 101" in m, m
assert "CLASSES" not in build_message(date(2030, 3, 3), []), "no classes on Sunday"
assert "Nothing due today" in build_message(date(2030, 3, 3), [])
assert "&lt;x&gt;" in build_message(today, [(today, "1pm", "HW <x> [CS 101]")]), "HTML escaped"

# evening check-in and nags
c = build_checkin(today, feed + site)
assert "🌙 <b><u>EVENING CHECK-IN · MON MAR 4</u></b>" in c and "STILL DUE TONIGHT" in c, c
assert "Problem Set 6" in c and "Lab 4" not in c and "DUE TOMORROW" in c and "Homework 9" in c, c
n = build_checkin(today, feed + site, nag=2)
assert n.startswith("⏰ <b><u>CHECK-IN REMINDER #2</u></b>") and "Problem Set 6" in n, n

# DST-proof 9am cron pick (works for whatever TIMEZONE is set; default America/New_York)
off = lambda dt: int(dt.utcoffset().total_seconds() // 3600)
winter, summer = datetime(2030, 1, 7, 9, 30, tzinfo=TZ), datetime(2030, 7, 1, 9, 30, tzinfo=TZ)
assert is_9am_cron(f"6 {(9 - off(winter)) % 24} * * *", winter)
assert not is_9am_cron(f"6 {(10 - off(winter)) % 24} * * *", winter)
assert is_9am_cron(f"6 {(9 - off(summer)) % 24} * * *", summer)
print("tests ok")
