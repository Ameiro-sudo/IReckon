"""
确定性工具组装器
支持顺序执行、条件分支、循环三种基本组合，使用 Python 代码生成。
生成的代码通过 AST 解析零件中的顶层函数定义，确保引用名真实存在（可编译）。
"""

import ast
from typing import Dict, Any, List, Optional


def _extract_entry_function(code: str) -> Optional[str]:
    """提取代码中第一个顶层 def 的函数名；解析失败返回 None。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return None


class ToolAssembler:
    @staticmethod
    def assemble_sequence(parts: List[Dict[str, Any]]) -> str:
        code_lines = ["import json", ""]
        calls: List[str] = []
        for i, part in enumerate(parts):
            func_name = _extract_entry_function(part["code"])
            code_lines.append(f"# 零件{i}: {part.get('name', 'unnamed')}")
            code_lines.append(part["code"])
            code_lines.append("")
            if func_name:
                calls.append(func_name)
            else:
                raise ValueError(f"零件 {part.get('name')} 无法解析出顶层函数定义")
        if not calls:
            raise ValueError("缺少可调用的零件函数")
        code_lines.append("def assembled_tool(input_data):")
        code_lines.append("    data = input_data")
        for fn in calls:
            code_lines.append(f"    data = {fn}(data)")
        code_lines.append("    return data")
        return "\n".join(code_lines)

    @staticmethod
    def assemble_condition(
        condition_part: Dict[str, Any],
        true_part: Dict[str, Any],
        false_part: Dict[str, Any],
    ) -> str:
        code_lines = ["import json", ""]
        cond_fn = _extract_entry_function(condition_part["code"])
        true_fn = _extract_entry_function(true_part["code"])
        false_fn = _extract_entry_function(false_part["code"])
        if not (cond_fn and true_fn and false_fn):
            raise ValueError("条件/分支零件必须各自含一个顶层函数")
        code_lines.append(f"# 条件零件: {condition_part.get('name')}")
        code_lines.append(condition_part["code"])
        code_lines.append("")
        code_lines.append(f"# True分支: {true_part.get('name')}")
        code_lines.append(true_part["code"])
        code_lines.append("")
        code_lines.append(f"# False分支: {false_part.get('name')}")
        code_lines.append(false_part["code"])
        code_lines.append("")
        code_lines.append("def assembled_tool(input_data):")
        code_lines.append(f"    if {cond_fn}(input_data):")
        code_lines.append(f"        return {true_fn}(input_data)")
        code_lines.append("    else:")
        code_lines.append(f"        return {false_fn}(input_data)")
        return "\n".join(code_lines)

    @staticmethod
    def assemble_loop(loop_body: Dict[str, Any], max_iter: int = 100) -> str:
        code_lines = ["import json", ""]
        body_fn = _extract_entry_function(loop_body["code"])
        if not body_fn:
            raise ValueError("循环体零件必须含一个顶层函数")
        code_lines.append(f"# 循环体零件: {loop_body.get('name')}")
        code_lines.append(loop_body["code"])
        code_lines.append("")
        code_lines.append("def assembled_tool(input_data, max_iter=100):")
        code_lines.append("    data = input_data")
        code_lines.append("    for _ in range(max_iter):")
        code_lines.append(f"        data = {body_fn}(data)")
        code_lines.append("        if data is None or (isinstance(data, dict) and data.get('stop')):")
        code_lines.append("            break")
        code_lines.append("    return data")
        return "\n".join(code_lines)