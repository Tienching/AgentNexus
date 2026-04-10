# -*- coding: utf-8 -*-
"""Natural language to cron expression parser.

Converts natural language descriptions into cron expressions.

Examples:
    "每天早上9点" -> "0 9 * * *"
    "每周一早上10点" -> "0 10 * * 1"
    "每小时" -> "0 * * * *"
    "每15分钟" -> "*/15 * * * *"
    "每天午夜" -> "0 0 * * *"
    "每周末下午3点" -> "0 15 * * 0,6"
    "每月1号凌晨2点" -> "0 2 1 * *"
    "每个工作日上午9点半" -> "30 9 * * 1-5"

Usage:
    from src.nanobot.cron.nlp_parser import parse_natural_language

    result = parse_natural_language("每天早上9点")
    if result:
        print(f"Cron: {result.expression}")
        print(f"Description: {result.description}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Day of week mapping
DAY_MAP = {
    "monday": 1, "mon": 1, "星期一": 1, "周一": 1,
    "tuesday": 2, "tue": 2, "星期二": 2, "周二": 2,
    "wednesday": 3, "wed": 3, "星期三": 3, "周三": 3,
    "thursday": 4, "thu": 4, "星期四": 4, "周四": 4,
    "friday": 5, "fri": 5, "星期五": 5, "周五": 5,
    "saturday": 6, "sat": 6, "星期六": 6, "周六": 6,
    "sunday": 0, "sun": 0, "星期日": 0, "周日": 0,
}

# Month mapping
MONTH_MAP = {
    "january": 1, "jan": 1, "一月": 1,
    "february": 2, "feb": 2, "二月": 2,
    "march": 3, "mar": 3, "三月": 3,
    "april": 4, "apr": 4, "四月": 4,
    "may": 5, "五月": 5,
    "june": 6, "jun": 6, "六月": 6,
    "july": 7, "jul": 7, "七月": 7,
    "august": 8, "aug": 8, "八月": 8,
    "september": 9, "sep": 9, "九月": 9,
    "october": 10, "oct": 10, "十月": 10,
    "november": 11, "nov": 11, "十一月": 11,
    "december": 12, "dec": 12, "十二月": 12,
}


@dataclass
class ParsedCron:
    """Result of parsing a natural language cron expression."""
    expression: str
    description: str
    minute: str = "*"
    hour: str = "*"
    day_of_month: str = "*"
    month: str = "*"
    day_of_week: str = "*"


def parse_natural_language(text: str) -> Optional[ParsedCron]:
    """Parse natural language text into a cron expression.

    Args:
        text: Natural language cron description

    Returns:
        ParsedCron object if parsing succeeded, None otherwise

    Supported patterns:
        - "每X分钟" / "every X minutes" - minute intervals
        - "每小时" / "every hour" - hourly
        - "每天X点" / "daily at X" - daily at specific hour
        - "每天早上X点" / "every morning at X" - daily morning
        - "每天下午X点" / "every afternoon at X" - daily afternoon
        - "每周X" / "every week on X" - weekly on specific day
        - "每月X号" / "monthly on day X" - monthly on specific day
        - "工作日" / "weekdays" - Monday-Friday
        - "周末" / "weekends" - Saturday and Sunday
    """
    if not text:
        return None

    text = text.strip().lower()

    # Interval patterns (every X minutes/hours)
    interval_match = re.match(
        r"(?:每|every)\s*(\d+)\s*(?:分钟|min(?:ute)?s?|hours?|小时)",
        text
    )
    if interval_match:
        value = int(interval_match.group(1))
        if "分钟" in text or "min" in text.lower():
            if value < 1 or value > 59:
                return None
            return ParsedCron(
                expression=f"*/{value} * * * *",
                description=text,
                minute=f"*/{value}",
            )
        else:  # hours
            if value < 1 or value > 23:
                return None
            return ParsedCron(
                expression=f"0 */{value} * * *",
                description=text,
                minute="0",
                hour=f"*/{value}",
            )

    # Hourly patterns
    if "每小时" in text or text == "every hour":
        return ParsedCron(
            expression="0 * * * *",
            description=text,
            minute="0",
        )

    # Every X minutes (without "every" keyword)
    simple_interval = re.match(r"(\d+)\s*(?:分钟|min)", text)
    if simple_interval:
        value = int(simple_interval.group(1))
        if 1 <= value <= 59:
            return ParsedCron(
                expression=f"*/{value} * * * *",
                description=text,
                minute=f"*/{value}",
            )

    # Weekdays / workdays
    if "工作日" in text or "weekdays" in text:
        return ParsedCron(
            expression="0 9 * * 1-5",
            description=text,
            minute="0",
            hour="9",
            day_of_week="1-5",
        )

    # Weekends
    if "周末" in text:
        return ParsedCron(
            expression="0 9 * * 0,6",
            description=text,
            minute="0",
            hour="9",
            day_of_week="0,6",
        )

    # Daily at specific time "每天X点" / "daily at X" - must check before general period patterns
    daily_pattern = re.compile(
        r"(?:每|every)\s*(?:天|日|day)\s*(?:at|在)?\s*(\d{1,2})(?::(\d{2}))?(?:\s*[点分:])?"
    )
    daily_match = daily_pattern.search(text)
    if daily_match:
        hour = int(daily_match.group(1))
        minute = int(daily_match.group(2) or "0")
        if hour > 23 or minute > 59:
            return None
        cron_minute = str(minute).rjust(2, "0")
        return ParsedCron(
            expression=f"{cron_minute} {hour} * * *",
            description=text,
            minute=cron_minute,
            hour=str(hour),
        )

    # Every morning/afternoon/evening with specific time "每天早上9点" / "every morning at 9"
    time_pattern = re.compile(
        r"(?:每|every)\s*(?:天|日|day)?\s*(?:在|at)?\s*"
        r"(早上|上午|下午|晚上|早晨|evening|afternoon|morning|noon)\s*"
        r"(\d{1,2})(?::(\d{2}))?(?:\s*[点分:])?"
    )
    time_match = time_pattern.search(text)
    if time_match:
        period = time_match.group(1)
        hour = int(time_match.group(2))
        minute = int(time_match.group(3) or "0")

        if hour > 23 or minute > 59:
            return None

        # Convert hour for afternoon/evening periods
        # "下午3点" means 3 PM = 15:00, "晚上8点" means 8 PM = 20:00
        if period in ("下午", "afternoon") and hour < 12:
            hour += 12
        if period in ("晚上", "evening") and hour < 12:
            hour += 12
        # "早上" and "上午" are morning hours, no conversion needed

        # Validate hour is within period bounds after conversion
        if period in ("早上", "早晨", "morning") and (hour < 5 or hour > 11):
            return None
        if period in ("上午",) and (hour < 8 or hour > 12):
            return None
        if period in ("下午", "afternoon") and (hour < 12 or hour > 23):
            return None
        if period in ("晚上", "evening") and (hour < 12 or hour > 23):
            return None

        cron_minute = str(minute).rjust(2, "0")
        return ParsedCron(
            expression=f"{cron_minute} {hour} * * *",
            description=text,
            minute=cron_minute,
            hour=str(hour),
        )

    # Midnight / noon
    if "午夜" in text or "midnight" in text:
        return ParsedCron(
            expression="0 0 * * *",
            description=text,
            minute="0",
            hour="0",
        )

    if "中午" in text or "noon" in text:
        return ParsedCron(
            expression="0 12 * * *",
            description=text,
            minute="0",
            hour="12",
        )

    # Weekly patterns "每周一" / "每周一早上10点" / "every week on Monday"
    # Handle Chinese day names (no space before day name)
    weekly_pattern = re.compile(
        r"(?:每周|每星期|every\s*week\s*(?:on)?)"
        r"([一二三四五六日](?:[期星]?日|[曜日])?|[一二三四五六天]|"
        r"(?:monday?|tue(?:s|sday)?|wednesday?|thu(?:r(?:s|sday)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?))"
        r"(?:\s*(?:早上|上午|下午|晚上|早晨|[0-9]{1,2}(?::[0-9]{2})?[点分:])?)?"
    )
    weekly_match = weekly_pattern.search(text)
    if weekly_match:
        day_str = weekly_match.group(1).lower() if len(weekly_match.group(1)) > 1 else weekly_match.group(1)
        # Map Chinese day names
        day_map_cn = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0,
            "天": 0,
        }
        # Check if it's a Chinese character day
        if day_str and day_str[0] in "一二三四五六日天":
            day_num = day_map_cn.get(day_str[0], 0)
        else:
            day_num = DAY_MAP.get(day_str, 0)

        # Extract time if present - search after the day name
        hour = 9
        minute = 0
        remaining_text = text[weekly_match.end():]
        time_in_remaining = re.search(r"(\d{1,2})(?::(\d{2}))?", remaining_text)
        if time_in_remaining:
            hour = int(time_in_remaining.group(1))
            minute = int(time_in_remaining.group(2) or "0")

        # Convert afternoon/evening hours - check original text
        if "下午" in text or "afternoon" in text.lower():
            if hour < 12:
                hour += 12
        if "晚上" in text or "evening" in text.lower():
            if hour < 12:
                hour += 12

        cron_minute = str(minute).rjust(2, "0")
        return ParsedCron(
            expression=f"{cron_minute} {hour} * * {day_num}",
            description=text,
            minute=cron_minute,
            hour=str(hour),
            day_of_week=str(day_num),
        )

    # Monthly patterns "每月X号" / "monthly on day X"
    monthly_pattern = re.compile(
        r"(?:每月|每月|monthly|every\s*month)\s*"
        r"(?:on\s*)?(?:第\s*)?(\d{1,2})(?:\s*号)?"
    )
    monthly_match = monthly_pattern.search(text)
    if monthly_match:
        day = int(monthly_match.group(1))
        if day < 1 or day > 31:
            return None

        # Extract time if present
        hour = 9
        minute = 0
        time_match = re.search(r"(\d{1,2})(?::(\d{2}))?", text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or "0")

        cron_minute = str(minute).rjust(2, "0")
        return ParsedCron(
            expression=f"{cron_minute} {hour} {day} * *",
            description=text,
            minute=cron_minute,
            hour=str(hour),
            day_of_month=str(day),
        )

    # Simple time "X点Y分" or "X:Y"
    simple_time = re.match(r"(\d{1,2})(?::(\d{2}))?(?:\s*[点分:])", text)
    if simple_time:
        hour = int(simple_time.group(1))
        minute = int(simple_time.group(2) or "0")
        if hour > 23 or minute > 59:
            return None
        cron_minute = str(minute).rjust(2, "0")
        return ParsedCron(
            expression=f"{cron_minute} {hour} * * *",
            description=text,
            minute=cron_minute,
            hour=str(hour),
        )

    return None


def describe_cron(expression: str) -> str:
    """Convert a cron expression back to human-readable text.

    Args:
        expression: Standard 5-field cron expression

    Returns:
        Human-readable description
    """
    parts = expression.split()
    if len(parts) != 5:
        return "Invalid cron expression"

    minute, hour, day_of_month, month, day_of_week = parts

    desc_parts = []

    # Time
    if minute == "*" and hour == "*":
        desc_parts.append("Every minute")
    elif minute.startswith("*/"):
        desc_parts.append(f"Every {minute[2:]} minutes")
    elif hour == "*":
        desc_parts.append(f"At minute {minute} of every hour")
    elif minute == "0" and hour != "*":
        desc_parts.append(f"At {hour}:00")
    else:
        desc_parts.append(f"At {hour}:{minute.rjust(2, '0')}")

    # Day of week
    if day_of_week != "*":
        day_names = {
            "0": "Sunday", "1": "Monday", "2": "Tuesday",
            "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday",
            "0,6": "weekends", "1-5": "weekdays"
        }
        dow_name = day_names.get(day_of_week, f"day {day_of_week}")
        desc_parts.append(f"on {dow_name}")

    # Day of month
    if day_of_month != "*":
        desc_parts.append(f"on day {day_of_month} of the month")

    # Month
    if month != "*":
        month_names = {
            "1": "January", "2": "February", "3": "March",
            "4": "April", "5": "May", "6": "June",
            "7": "July", "8": "August", "9": "September",
            "10": "October", "11": "November", "12": "December",
        }
        desc_parts.append(f"in {month_names.get(month, month)}")

    return " ".join(desc_parts) if desc_parts else "Invalid expression"
