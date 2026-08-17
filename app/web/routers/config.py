"""配置管理 API：读取、原子更新配置，主题查询。"""

import os
import tempfile
from typing import Any, Dict

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import config_manager

router = APIRouter(prefix="/api", tags=["config"])


class ConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]


@router.get("/config")
async def get_config():
    return config_manager.get_all()


@router.post("/config/update")
async def update_config(req: ConfigUpdateRequest):
    if not req.updates:
        raise HTTPException(422, "updates 不能为空")
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

    return {
        name: {"name": t.get("name", name)} for name, t in style_engine._themes.items()
    }
