"""
工具零件：JSON数据转换器
提供JSON/字典互转、扁平化、嵌套展开、类型转换等。
"""

import json
from collections.abc import MutableMapping

def flatten(d, parent_key='', sep='_'):
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def unflatten(d, sep='_'):
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
    ops = {
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
        return f"不支持的操作: {operation}"
    try:
        return ops[operation](*args, **kwargs)
    except Exception as e:
        return f"运算出错: {e}"