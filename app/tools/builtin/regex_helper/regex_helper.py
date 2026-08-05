"""
宸ュ叿闆朵欢锛氭鍒欒〃杈惧紡鍔╂墜
鎻愪緵甯歌姝ｅ垯楠岃瘉銆佹彁鍙栥€佹浛鎹€佺敓鎴愮瓑鎿嶄綔銆?"""

import re

PATTERNS = {
    "email": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    "url": r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+",
    "phone": r"^\+?[\d\s-]{7,15}$",
    "ipv4": r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$",
    "date": r"^\d{4}-\d{2}-\d{2}$",
    "time": r"^\d{2}:\d{2}(:\d{2})?$",
    "number": r"^-?\d+(\.\d+)?$",
    "alphanumeric": r"^[a-zA-Z0-9]+$",
}


def regex_helper(operation: str, *args, **kwargs):
    try:
        if operation == "validate":
            pattern_name = args[0]
            text = args[1]
            if pattern_name in PATTERNS:
                return bool(re.match(PATTERNS[pattern_name], text))
            else:
                return f"鏈煡楠岃瘉妯″紡: {pattern_name}"

        elif operation == "match":
            pattern, text = args[0], args[1]
            return re.findall(pattern, text)

        elif operation == "search":
            pattern, text = args[0], args[1]
            m = re.search(pattern, text)
            return m.group(0) if m else None

        elif operation == "replace":
            pattern, repl, text = args[0], args[1], args[2]
            return re.sub(pattern, repl, text)

        elif operation == "split":
            pattern, text = args[0], args[1]
            return re.split(pattern, text)

        elif operation == "escape":
            return re.escape(args[0])

        elif operation == "compile":
            return str(re.compile(args[0]))

        elif operation == "list_patterns":
            return list(PATTERNS.keys())

        else:
            return f"涓嶆敮鎸佺殑鎿嶄綔: {operation}"
    except Exception as e:
        return f"杩愮畻鍑洪敊: {e}"
