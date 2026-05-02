"""
工具零件：日期时间助手
提供日期差计算、格式化、时区转换、Unix时间戳等操作。
"""

from datetime import datetime, timezone, timedelta
from dateutil import parser, relativedelta
import time
from zoneinfo import ZoneInfo

def datetime_helper(operation: str, *args, **kwargs):
    ops = {
        # 当前时间
        "now": lambda tz=None: datetime.now(tz).isoformat(),
        "timestamp": lambda: int(time.time()),
        # 解析
        "parse": lambda dt_str: parser.parse(dt_str).isoformat(),
        # 格式化（输出指定格式）
        "strftime": lambda dt_str, fmt: parser.parse(dt_str).strftime(fmt),
        # 日期差
        "days_between": lambda d1, d2: abs((parser.parse(d1) - parser.parse(d2)).days),
        "seconds_between": lambda d1, d2: abs((parser.parse(d1) - parser.parse(d2)).total_seconds()),
        # 加减时间
        "add_days": lambda dt_str, days: (parser.parse(dt_str) + timedelta(days=days)).isoformat(),
        "add_months": lambda dt_str, months: (parser.parse(dt_str) + relativedelta(months=months)).isoformat(),
        "add_years": lambda dt_str, years: (parser.parse(dt_str) + relativedelta(years=years)).isoformat(),
        # 时区转换
        "to_utc": lambda dt_str: parser.parse(dt_str).astimezone(timezone.utc).isoformat(),
        "to_timezone": lambda dt_str, tz_name: parser.parse(dt_str).astimezone(ZoneInfo(tz_name)).isoformat() if tz_name else None,
        # 星期相关
        "weekday": lambda dt_str: parser.parse(dt_str).strftime("%A"),
        "week_number": lambda dt_str: parser.parse(dt_str).isocalendar()[1],
        # 时间戳转日期
        "from_timestamp": lambda ts: datetime.fromtimestamp(ts).isoformat(),
    }
    if operation not in ops:
        return f"不支持的操作: {operation}"
    try:
        return ops[operation](*args, **kwargs)
    except Exception as e:
        return f"运算出错: {e}"