"""
宸ュ叿闆朵欢锛氬鍔熻兘璁＄畻鍣?鍔熻兘锛氭彁渚?50+ 绉嶆暟瀛﹁繍绠楋紝閫氳繃鎿嶄綔鍚嶇О鍜屽弬鏁板垪琛ㄨ皟鐢ㄣ€?"""

import math
import statistics
import cmath
import random
from typing import Union, List, Any

# 浣跨敤 lambda 鏋勫缓鎿嶄綔鏄犲皠锛屾兜鐩栧箍娉涚殑璁＄畻鍔熻兘
OPERATIONS = {
    # 鈹€鈹€ 鍩烘湰绠楁湳 鈹€鈹€
    "add": lambda *args: sum(args),
    "sub": lambda *args: args[0] - sum(args[1:]) if len(args) >= 2 else args[0],
    "mul": lambda *args: math.prod(args),
    "div": lambda a, b: a / b if b != 0 else float('inf'),
    "floordiv": lambda a, b: a // b,
    "mod": lambda a, b: a % b,
    "pow": lambda a, b: a ** b,

    # 鈹€鈹€ 涓€鍏冩暟瀛﹀嚱鏁?鈹€鈹€
    "abs": lambda x: abs(x),
    "neg": lambda x: -x,
    "round": lambda x, n=0: round(x, n),
    "ceil": lambda x: math.ceil(x),
    "floor": lambda x: math.floor(x),
    "trunc": lambda x: math.trunc(x),
    "sign": lambda x: (1 if x > 0 else -1 if x < 0 else 0),
    "sqrt": lambda x: math.sqrt(x),
    "cbrt": lambda x: x ** (1/3),
    "factorial": lambda n: math.factorial(n) if n >= 0 and n == int(n) else None,

    # 鈹€鈹€ 涓夎鍑芥暟 (寮у害) 鈹€鈹€
    "sin": lambda x: math.sin(x),
    "cos": lambda x: math.cos(x),
    "tan": lambda x: math.tan(x),
    "asin": lambda x: math.asin(x),
    "acos": lambda x: math.acos(x),
    "atan": lambda x: math.atan(x),
    "atan2": lambda y, x: math.atan2(y, x),

    # 鈹€鈹€ 瑙掑害涓庡姬搴﹁浆鎹?鈹€鈹€
    "degrees": lambda rad: math.degrees(rad),
    "radians": lambda deg: math.radians(deg),

    # 鈹€鈹€ 鍙屾洸鍑芥暟 鈹€鈹€
    "sinh": lambda x: math.sinh(x),
    "cosh": lambda x: math.cosh(x),
    "tanh": lambda x: math.tanh(x),
    "asinh": lambda x: math.asinh(x),
    "acosh": lambda x: math.acosh(x),
    "atanh": lambda x: math.atanh(x),

    # 鈹€鈹€ 鎸囨暟涓庡鏁?鈹€鈹€
    "exp": lambda x: math.exp(x),
    "expm1": lambda x: math.expm1(x),
    "log": lambda x, base=math.e: math.log(x, base),
    "log10": lambda x: math.log10(x),
    "log2": lambda x: math.log2(x),
    "log1p": lambda x: math.log1p(x),

    # 鈹€鈹€ 缁勫悎鏁板 鈹€鈹€
    "comb": lambda n, k: math.comb(n, k),
    "perm": lambda n, k: math.perm(n, k),
    "gcd": lambda a, b: math.gcd(a, b),
    "lcm": lambda a, b: math.lcm(a, b),
    "gcd_list": lambda *args: math.gcd(*args),
    "lcm_list": lambda *args: math.lcm(*args),

    # 鈹€鈹€ 缁熻鍑芥暟 鈹€鈹€
    "mean": lambda *args: statistics.mean(args),
    "median": lambda *args: statistics.median(args),
    "median_low": lambda *args: statistics.median_low(args),
    "median_high": lambda *args: statistics.median_high(args),
    "mode": lambda *args: statistics.mode(args),
    "stdev": lambda *args: statistics.stdev(args) if len(args) >= 2 else None,
    "variance": lambda *args: statistics.variance(args) if len(args) >= 2 else None,

    # 鈹€鈹€ 姹傚拰/涔樼Н 鈹€鈹€
    "sum": lambda *args: sum(args),
    "prod": lambda *args: math.prod(args),

    # 鈹€鈹€ 璺濈涓庡悜閲?鈹€鈹€
    "hypot": lambda *args: math.hypot(*args),          # 浜岀淮鎴栦笁缁?    "dist": lambda p, q: math.dist(p, q),

    # 鈹€鈹€ 璇樊鍑芥暟绛?鈹€鈹€
    "erf": lambda x: math.erf(x),
    "erfc": lambda x: math.erfc(x),
    "gamma": lambda x: math.gamma(x),
    "lgamma": lambda x: math.lgamma(x),

    # 鈹€鈹€ 甯搁噺杈撳嚭 (蹇界暐鍙傛暟) 鈹€鈹€
    "pi": lambda *_: math.pi,
    "e": lambda *_: math.e,
    "tau": lambda *_: math.tau,
    "inf": lambda *_: float('inf'),
    "nan": lambda *_: float('nan'),

    # 鈹€鈹€ 闅忔満鏁?鈹€鈹€
    "random": lambda a=0, b=1: random.uniform(a, b),
    "randint": lambda a, b: random.randint(a, b),
    "choice": lambda *args: random.choice(args),

    # 鈹€鈹€ 澶嶆暟杩愮畻 鈹€鈹€
    "complex": lambda r, i: complex(r, i),   # 鍙傛暟鍚?r, i 闃叉涓庡唴寤哄嚱鏁版贩娣?    "real": lambda c: c.real if isinstance(c, complex) else float(c),
    "imag": lambda c: c.imag if isinstance(c, complex) else 0.0,
    "conjugate": lambda c: c.conjugate() if isinstance(c, complex) else c,
    "abs_complex": lambda c: abs(c),
    "phase": lambda c: cmath.phase(c),
    "polar": lambda c: cmath.polar(c),
    "rect": lambda r, phi: cmath.rect(r, phi),
}


def multi_calculator(operation: str, *args) -> Any:
    """
    鎵ц鎸囧畾鐨勬暟瀛﹁繍绠椼€?
    Args:
        operation: 鎿嶄綔鍚嶇О锛堣 OPERATIONS 閿級
        *args: 杩愮畻鎵€闇€鐨勫弬鏁帮紝鏁伴噺鍙婇『搴忎笌瀵瑰簲鎿嶄綔涓€鑷?
    Returns:
        璁＄畻缁撴灉锛堟暟瀛楁垨甯搁噺锛夛紝鑻ユ搷浣滀笉瀛樺湪鍒欒繑鍥炲寘鍚敊璇俊鎭殑瀛楃涓层€?    """
    if operation not in OPERATIONS:
        return f"涓嶆敮鎸佺殑鎿嶄綔: {operation}. 鏀寔鐨勬搷浣? {', '.join(sorted(OPERATIONS.keys()))}"

    try:
        return OPERATIONS[operation](*args)
    except Exception as e:
        return f"杩愮畻鍑洪敊: {e}"


# 如果作为脚本运行，输出简单测试
if __name__ == "__main__":
    print("Multi-calculator self-test:")
    print("add(1,2,3):", multi_calculator("add", 1, 2, 3))
    print("sqrt(16):", multi_calculator("sqrt", 16))
    print("sin(pi/2):", multi_calculator("sin", math.pi / 2))
    print("comb(5,2):", multi_calculator("comb", 5, 2))
    print("mean(1,2,3,4):", multi_calculator("mean", 1, 2, 3, 4))
    print("complex(3,4) abs:", multi_calculator("abs_complex", complex(3, 4)))
    print("random():", multi_calculator("random"))
