import json
from pathlib import Path
from loguru import logger
from .library import search, add_part


def _load_manifest(path: Path):
    """加载并校验 manifest：必须含非空 name；py_files 非空且存在。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            manifest = json.load(f, strict=False)
    except Exception as e:
        logger.warning(f"manifest 解析失败: {path}: {e}")
        return None
    if not isinstance(manifest, dict) or not manifest.get("name"):
        logger.warning(f"manifest 缺少非空 name: {path}")
        return None
    if not isinstance(manifest.get("name"), str) or len(manifest["name"]) > 64:
        logger.warning(f"manifest name 不合法: {path}")
        return None
    manifest.setdefault("version", "1.0.0")
    return manifest


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

        manifest = _load_manifest(manifest_path)
        if manifest is None:
            continue

        py_files = list(tool_dir.glob("*.py"))
        if not py_files:
            logger.warning(f"工具目录 {tool_dir.name} 无 .py 文件，跳过")
            continue

        code_file = py_files[0]
        with open(code_file, "r", encoding="utf-8") as f:
            code = f.read()

        existing_parts = await search(query=manifest["name"])
        if existing_parts:
            logger.debug(f"工具 '{manifest['name']}' 已注册，跳过")
            continue

        await add_part(
            name=manifest["name"],
            description=manifest.get("description", ""),
            language=manifest.get("language", "python"),
            code=code,
            input_schema=manifest.get("input_schema", {}),
            output_schema=manifest.get("output_schema", {}),
            tags=manifest.get("tags", []),
            created_by=manifest.get("created_by", "builtin"),
        )
        registered_count += 1

    logger.info(f"内置工具注册完成，共注册 {registered_count} 个新工具")
