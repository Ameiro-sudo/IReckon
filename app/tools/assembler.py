"""
确定性工具组装器
支持顺序执行、条件分支、循环三种基本组合，使用 Python 代码生成
"""

import json
from typing import Dict, Any, List, Optional
from loguru import logger


class ToolAssembler:
    @staticmethod
    def assemble_sequence(parts: List[Dict[str, Any]]) -> str:
        code_lines = ["import json", ""]
        for i, part in enumerate(parts):
            func_name = f"part_{i}"
            code_lines.append(f"# 零件{i}: {part['name']}")
            code_lines.append(f"{func_name}_output = None")
            code_lines.append(part['code'])
            code_lines.append("")
        code_lines.append("def assembled_tool(input_data):")
        code_lines.append("    data = input_data")
        for i, part in enumerate(parts):
            func_name = f"part_{i}"
            code_lines.append(f"    data = {func_name}(data)")
        code_lines.append("    return data")
        return "\n".join(code_lines)

    @staticmethod
    def assemble_condition(condition_part: Dict[str, Any],
                           true_part: Dict[str, Any],
                           false_part: Dict[str, Any]) -> str:
        code_lines = ["import json", ""]
        code_lines.append(f"# 条件零件: {condition_part['name']}")
        code_lines.append(condition_part['code'])
        code_lines.append("")
        code_lines.append(f"# True分支: {true_part['name']}")
        code_lines.append(true_part['code'])
        code_lines.append("")
        code_lines.append(f"# False分支: {false_part['name']}")
        code_lines.append(false_part['code'])
        code_lines.append("")
        code_lines.append("def assembled_tool(input_data):")
        code_lines.append(f"    if condition(input_data):")
        code_lines.append(f"        return true_branch(input_data)")
        code_lines.append(f"    else:")
        code_lines.append(f"        return false_branch(input_data)")
        return "\n".join(code_lines)

    @staticmethod
    def assemble_loop(loop_body: Dict[str, Any], max_iter: int = 100) -> str:
        code_lines = ["import json", ""]
        code_lines.append(f"# 循环体零件: {loop_body['name']}")
        code_lines.append(loop_body['code'])
        code_lines.append("")
        code_lines.append("def assembled_tool(input_data, max_iter=100):")
        code_lines.append("    data = input_data")
        code_lines.append("    for _ in range(max_iter):")
        code_lines.append("        data = loop_body(data)")
        code_lines.append("        if data is None or data.get('stop'):")
        code_lines.append("            break")
        code_lines.append("    return data")
        return "\n".join(code_lines)