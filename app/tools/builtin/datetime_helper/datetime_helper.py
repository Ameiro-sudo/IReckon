"""
宸ュ叿闆朵欢锛氭棩鏈熸椂闂村姪鎵?鎻愪緵鏃ユ湡宸绠椼€佹牸寮忓寲銆佹椂鍖鸿浆鎹€乁nix鏃堕棿鎴崇瓑鎿嶄綔銆?"""

from datetime import datetime, timezone, timedelta
from dateutil import parser, relativedelta
import time
from zoneinfo import ZoneInfo
from typing import Any, Callable, Dict


def datetime_helper(operation: str, *args, **kwargs):
    ops: Dict[str, Callable[..., Any]] = {
        # 褰撳墠鏃堕棿
        "now": lambda tz=None: datetime.now(tz).isoformat(),
        "timestamp": lambda: int(time.time()),
        # 瑙ｆ瀽
        "parse": lambda dt_str: parser.parse(dt_str).isoformat(),
        # 鏍煎紡鍖栵紙杈撳嚭鎸囧畾鏍煎紡锛?        "strftime": lambda dt_str, fmt: parser.parse(dt_str).strftime(fmt),
        # 鏃ユ湡宸?        "days_between": lambda d1, d2: abs((parser.parse(d1) - parser.parse(d2)).days),
        "seconds_between": lambda d1, d2: abs(
            (parser.parse(d1) - parser.parse(d2)).total_seconds()
        ),
        # 鍔犲噺鏃堕棿
        "add_days": lambda dt_str, days: (
            parser.parse(dt_str) + timedelta(days=days)
        ).isoformat(),
        "add_months": lambda dt_str, months: (
            parser.parse(dt_str) + relativedelta
        ).isoformat(),
        "add_years": lambda dt_str, years: (
            parser.parse(dt_str) + relativedelta
        ).isoformat(),
        # 鏃跺尯杞崲
        "to_utc": lambda dt_str: (
            parser.parse(dt_str).astimezone(timezone.utc).isoformat()
        ),
        "to_timezone": lambda dt_str, tz_name: (
            parser.parse(dt_str).astimezone(ZoneInfo(tz_name)).isoformat()
            if tz_name
            else None
        ),
        # 鏄熸湡鐩稿叧
        "weekday": lambda dt_str: parser.parse(dt_str).strftime("%A"),
        "week_number": lambda dt_str: parser.parse(dt_str).isocalendar()[1],
        # 鏃堕棿鎴宠浆鏃ユ湡
        "from_timestamp": lambda ts: datetime.fromtimestamp(ts).isoformat(),
    }
    if operation not in ops:
        return f"涓嶆敮鎸佺殑鎿嶄綔: {operation}"
    try:
        return ops[operation](*args, **kwargs)
    except Exception as e:
        return f"杩愮畻鍑洪敊: {e}"
