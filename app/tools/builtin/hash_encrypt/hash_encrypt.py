"""
宸ュ叿闆朵欢锛氬搱甯屼笌鍔犲瘑宸ュ叿
鎻愪緵MD5銆丼HA绯诲垪銆丅ase64缂栬В鐮併€丠MAC绛夈€?"""

import hashlib
import base64
import hmac
import binascii
import os


def hash_encrypt(operation: str, *args, **kwargs):
    ops = {
        "md5": lambda s: hashlib.md5(s.encode()).hexdigest(),
        "sha1": lambda s: hashlib.sha1(s.encode()).hexdigest(),
        "sha256": lambda s: hashlib.sha256(s.encode()).hexdigest(),
        "sha512": lambda s: hashlib.sha512(s.encode()).hexdigest(),
        "base64_encode": lambda s: base64.b64encode(s.encode()).decode(),
        "base64_decode": lambda s: base64.b64decode(s.encode()).decode(),
        "hmac_sha256": lambda key, msg: hmac.new(
            key.encode(), msg.encode(), hashlib.sha256
        ).hexdigest(),
        "crc32": lambda s: binascii.crc32(s.encode()),
        "random_hex": lambda length: binascii.hexlify(os.urandom(length)).decode(),
    }
    if operation not in ops:
        return f"涓嶆敮鎸佺殑鎿嶄綔: {operation}"
    try:
        return ops[operation](*args, **kwargs)
    except Exception as e:
        return f"杩愮畻鍑洪敊: {e}"
