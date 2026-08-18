"""
宸ュ叿闆朵欢锛欽SON鏁版嵁杞崲鍣?鎻愪緵JSON/瀛楀吀浜掕浆銆佹墎骞冲寲銆佸祵濂楀睍寮€銆佺被鍨嬭浆鎹㈢瓑銆?"""

import json
from collections.abc import MutableMapping
from typing import Any, Callable, Dict


def flatten(d, parent_key="", sep="_"):
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def unflatten(d, sep="_"):
    result = {}
    for k, v in d.items():
        parts = k.split(sep)
        current = result
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = v
    return result


def json_transformer(operation: str, *args, **kwargs):
    ops: Dict[str, Callable[..., Any]] = {
        "dumps": lambda obj: json.dumps(obj, ensure_ascii=False),
        "loads": lambda s: json.loads(s),
        "pretty": lambda obj: json.dumps(obj, indent=2, ensure_ascii=False),
        "flatten": lambda d: flatten(d),
        "unflatten": lambda d: unflatten(d),
        "to_list": lambda s: json.loads(s) if isinstance(s, str) else list(s),
        "to_dict": lambda s: json.loads(s) if isinstance(s, str) else dict(s),
        "merge": lambda d1, d2: {**d1, **d2},
    }
    if operation not in ops:
        return f"涓嶆敮鎸佺殑鎿嶄綔: {operation}"
    try:
        return ops[operation](*args, **kwargs)
    except Exception as e:
        return f"杩愮畻鍑洪敊: {e}"
