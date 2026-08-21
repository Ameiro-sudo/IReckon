"""配置管理 API：读取、原子更新配置，主题查询。"""

import os
import re
import tempfile
from typing import Any, Dict

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import config_manager

router = APIRouter(prefix="/api", tags=["config"])

# 允许通过 API 更新的配置白名单（ui.* 限两级且段名受限，见 _is_allowed_update_key）
_UPDATE_WHITELIST = {
    "server.open_browser",
    "server.frontend_dev_url",
    "system.log_level",
    "server.log_level",
}

_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _is_allowed_update_key(key: str) -> bool:
    if key in _UPDATE_WHITELIST:
        return True
    # ui.* 仅允许两级（ui.<segment>），防止深层嵌套注入任意配置结构
    parts = key.split(".")
    return (
        len(parts) == 2
        and parts[0] == "ui"
        and all(_KEY_SEGMENT.match(p) for p in parts)
    )


class ConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]


@router.get("/config")
async def get_config():
    # 掩码 api_key 后再返回，避免明文泄露
    return config_manager.get_redacted()


@router.post("/config/update")
async def update_config(req: ConfigUpdateRequest):
    if not req.updates:
        raise HTTPException(422, "updates 不能为空")
    # 白名单校验：只允许更新 UI 与少量安全配置项，防止任意 key 写入造成 RCE 链
    for key in req.updates:
        if not _is_allowed_update_key(key):
            raise HTTPException(403, f"不允许更新配置项: {key}")
    config_path = config_manager.config_path
    with open(config_path, "r", encoding="utf-8") as f:
        current = yaml.safe_load(f) or {}
    for key, value in req.updates.items():
        keys = key.split(".")
        d = current
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
    # 原子写入：先写临时文件再替换，避免写一半损坏配置
    fd, tmp = tempfile.mkstemp(dir=str(config_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(current, f, allow_unicode=True, default_flow_style=False)
        os.replace(tmp, config_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    config_manager.reload()
    return {"status": "ok"}


@router.get("/themes")
async def list_themes():
    from app.engine.style import style_engine

    style_engine._ensure_themes()
    return {
        name: {"name": t.get("name", name)} for name, t in style_engine._themes.items()
    }
