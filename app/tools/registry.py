import json
from pathlib import Path
from loguru import logger
from .library import parts_library


async def register_builtin_tools(builtin_dir: str = "app/tools/builtin"):
    base = Path(builtin_dir)
    if not base.exists():
        logger.warning(f"内置工具目录 {builtin_dir} 不存在，跳过注册")
        return

    registered_count = 0
    for tool_dir in base.iterdir():
        if not tool_dir.is_dir():
            continue
        manifest_path = tool_dir / "manifest.json"
        if not manifest_path.exists():
            logger.warning(f"工具目录 {tool_dir.name} 缺少 manifest.json，跳过")
            continue

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        py_files = list(tool_dir.glob("*.py"))
        if not py_files:
            logger.warning(f"工具目录 {tool_dir.name} 无 .py 文件，跳过")
            continue

        code_file = py_files[0]
        with open(code_file, "r", encoding="utf-8") as f:
            code = f.read()

        existing_parts = await parts_library.search(query=manifest["name"])
        if existing_parts:
            logger.info(f"工具 '{manifest['name']}' 已注册，跳过")
            continue

        await parts_library.add_part(
            name=manifest["name"],
            description=manifest.get("description", ""),
            language=manifest.get("language", "python"),
            code=code,
            input_schema=manifest.get("input_schema", {}),
            output_schema=manifest.get("output_schema", {}),
            tags=manifest.get("tags", []),
            created_by=manifest.get("created_by", "builtin")
        )
        logger.info(f"已注册内置工具: {manifest['name']} (来自 {tool_dir.name})")
        registered_count += 1

    logger.info(f"内置工具注册完成，共注册 {registered_count} 个新工具")
