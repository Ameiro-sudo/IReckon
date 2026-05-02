"""
工具零件：多功能计算器
功能：提供 50+ 种数学运算，通过操作名称和参数列表调用。
"""

import math
import statistics
import cmath
import random
from typing import Union, List, Any

# 使用 lambda 构建操作映射，涵盖广泛的计算功能
OPERATIONS = {
    # ── 基本算术 ──
    "add": lambda *args: sum(args),
    "sub": lambda *args: args[0] - sum(args[1:]) if len(args) >= 2 else args[0],
    "mul": lambda *args: math.prod(args),
    "div": lambda a, b: a / b if b != 0 else float('inf'),
    "floordiv": lambda a, b: a // b,
    "mod": lambda a, b: a % b,
    "pow": lambda a, b: a ** b,

    # ── 一元数学函数 ──
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

    # ── 三角函数 (弧度) ──
    "sin": lambda x: math.sin(x),
    "cos": lambda x: math.cos(x),
    "tan": lambda x: math.tan(x),
    "asin": lambda x: math.asin(x),
    "acos": lambda x: math.acos(x),
    "atan": lambda x: math.atan(x),
    "atan2": lambda y, x: math.atan2(y, x),

    # ── 角度与弧度转换 ──
    "degrees": lambda rad: math.degrees(rad),
    "radians": lambda deg: math.radians(deg),

    # ── 双曲函数 ──
    "sinh": lambda x: math.sinh(x),
    "cosh": lambda x: math.cosh(x),
    "tanh": lambda x: math.tanh(x),
    "asinh": lambda x: math.asinh(x),
    "acosh": lambda x: math.acosh(x),
    "atanh": lambda x: math.atanh(x),

    # ── 指数与对数 ──
    "exp": lambda x: math.exp(x),
    "expm1": lambda x: math.expm1(x),
    "log": lambda x, base=math.e: math.log(x, base),
    "log10": lambda x: math.log10(x),
    "log2": lambda x: math.log2(x),
    "log1p": lambda x: math.log1p(x),

    # ── 组合数学 ──
    "comb": lambda n, k: math.comb(n, k),
    "perm": lambda n, k: math.perm(n, k),
    "gcd": lambda a, b: math.gcd(a, b),
    "lcm": lambda a, b: math.lcm(a, b),
    "gcd_list": lambda *args: math.gcd(*args),
    "lcm_list": lambda *args: math.lcm(*args),

    # ── 统计函数 ──
    "mean": lambda *args: statistics.mean(args),
    "median": lambda *args: statistics.median(args),
    "median_low": lambda *args: statistics.median_low(args),
    "median_high": lambda *args: statistics.median_high(args),
    "mode": lambda *args: statistics.mode(args),
    "stdev": lambda *args: statistics.stdev(args) if len(args) >= 2 else None,
    "variance": lambda *args: statistics.variance(args) if len(args) >= 2 else None,

    # ── 求和/乘积 ──
    "sum": lambda *args: sum(args),
    "prod": lambda *args: math.prod(args),

    # ── 距离与向量 ──
    "hypot": lambda *args: math.hypot(*args),          # 二维或三维
    "dist": lambda p, q: math.dist(p, q),

    # ── 误差函数等 ──
    "erf": lambda x: math.erf(x),
    "erfc": lambda x: math.erfc(x),
    "gamma": lambda x: math.gamma(x),
    "lgamma": lambda x: math.lgamma(x),

    # ── 常量输出 (忽略参数) ──
    "pi": lambda *_: math.pi,
    "e": lambda *_: math.e,
    "tau": lambda *_: math.tau,
    "inf": lambda *_: float('inf'),
    "nan": lambda *_: float('nan'),

    # ── 随机数 ──
    "random": lambda a=0, b=1: random.uniform(a, b),
    "randint": lambda a, b: random.randint(a, b),
    "choice": lambda *args: random.choice(args),

    # ── 复数运算 ──
    "complex": lambda r, i: complex(r, i),   # 参数名 r, i 防止与内建函数混淆
    "real": lambda c: c.real if isinstance(c, complex) else float(c),
    "imag": lambda c: c.imag if isinstance(c, complex) else 0.0,
    "conjugate": lambda c: c.conjugate() if isinstance(c, complex) else c,
    "abs_complex": lambda c: abs(c),
    "phase": lambda c: cmath.phase(c),
    "polar": lambda c: cmath.polar(c),
    "rect": lambda r, phi: cmath.rect(r, phi),
}


def multi_calculator(operation: str, *args) -> Any:
    """
    执行指定的数学运算。

    Args:
        operation: 操作名称（见 OPERATIONS 键）
        *args: 运算所需的参数，数量及顺序与对应操作一致

    Returns:
        计算结果（数字或常量），若操作不存在则返回包含错误信息的字符串。
    """
    if operation not in OPERATIONS:
        return f"不支持的操作: {operation}. 支持的操作: {', '.join(sorted(OPERATIONS.keys()))}"

    try:
        return OPERATIONS[operation](*args)
    except Exception as e:
        return f"运算出错: {e}"


# 如果作为独立脚本运行，提供简单测试
if __name__ == "__main__":
    print("多功能计算器测试：")
    print("add(1,2,3):", multi_calculator("add", 1, 2, 3))
    print("sqrt(16):", multi_calculator("sqrt", 16))
    print("sin(pi/2):", multi_calculator("sin", math.pi / 2))
    print("comb(5,2):", multi_calculator("comb", 5, 2))
    print("mean(1,2,3,4):", multi_calculator("mean", 1, 2, 3, 4))
    print("complex(3,4) abs:", multi_calculator("abs_complex", complex(3, 4)))
    print("random():", multi_calculator("random"))