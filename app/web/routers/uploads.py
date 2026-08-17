"""文件上传 API：临时保存需求描述附件，供创建任务时引用。"""

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, UploadFile
from loguru import logger

from app.core.config import config_manager

router = APIRouter(prefix="/api", tags=["uploads"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_FILES = 20


@router.post("/uploads")
async def upload_files(files: List[UploadFile] = File(...)):
    """批量上传参考文件，返回 upload_id 供创建任务时引用。"""
    if not files:
        return {"status": "error", "error": "未选择文件"}
    if len(files) > MAX_FILES:
        return {"status": "error", "error": f"最多上传 {MAX_FILES} 个文件"}
    upload_id = f"up-{uuid.uuid4().hex[:12]}"
    data_dir = Path(config_manager.get("system.data_dir", "./data"))
    dest = data_dir / "uploads" / upload_id
    dest.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        name = Path(f.filename or "file").name
        if not name or name in (".", ".."):
            continue
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            logger.warning(f"文件 {name} 超过大小限制，跳过")
            continue
        (dest / name).write_bytes(content)
        saved.append({"name": name, "size": len(content), "path": f"uploads/{upload_id}/{name}"})

    if not saved:
        return {"status": "error", "error": "没有有效文件"}
    return {"status": "ok", "upload_id": upload_id, "files": saved}
