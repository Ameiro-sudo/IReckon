"""Windows 安全的路径段消毒工具（executor / deliverer 共用）。

处理三类此前遗漏的 Windows 特有风险：
1. 保留设备名（CON/NUL/COM1… 及带扩展名形态）→ 写入会挂起或落到设备流；
2. 尾部点/空格（Win32 归一化会静默丢弃）→ `evil.py.` 与 `evil.py` 碰撞；
3. Unicode 兼容变形（全角字符等）→ NFKC 归一后消除同名混淆。
"""

import re
import unicodedata

# Windows 保留设备名：含 "CON.txt" 这类带扩展名形态（大小写不敏感）
_RESERVED_RE = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE
)


def safe_segment(seg: str) -> str:
    """把单个路径段净化为 Windows 安全文件名；退化到空串时返回空串由调用方裁决。"""
    seg = unicodedata.normalize("NFKC", seg).replace("\x00", "")
    # 冒号统一替换为下划线：顺带堵掉 NTFS ADS 形态（file.txt:$DATA）
    seg = seg.replace(":", "_")
    # Win32 会丢弃尾部点与空格：显式剥除，避免归一化碰撞与设备名残留
    seg = seg.rstrip(" .")
    if _RESERVED_RE.match(seg):
        seg = f"_{seg}"
    return seg
