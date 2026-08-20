"""文件上传 API：临时保存需求描述附件，供创建任务时引用。"""

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger


from app.core.config import get

router = APIRouter(prefix="/api", tags=["uploads"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_FILES = 20
# 上传文件扩展名白名单
_ALLOWED_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".html",
    ".css",
    ".sh",
    ".toml",
    ".ini",
    ".cfg",
    ".sql",
    ".csv",
    ".log",
    ".ipynb",
}


@router.post("/uploads")
async def upload_files(files: List[UploadFile] = File(...)):
    """批量上传参考文件，返回 upload_id 供创建任务时引用。"""
    if not files:
        return {"status": "error", "error": "未选择文件"}
    if len(files) > MAX_FILES:
        return {"status": "error", "error": f"最多上传 {MAX_FILES} 个文件"}
    upload_id = f"up-{uuid.uuid4().hex[:12]}"
    data_dir = Path(get("system.data_dir", "./data"))
    uploads_root = (data_dir / "uploads").resolve()
    dest = (uploads_root / upload_id).resolve()
    try:
        # 防目录穿越：dest 必须位于 data_dir/uploads 之下
        dest.relative_to(uploads_root)
    except ValueError:
        raise HTTPException(400, "非法上传路径")
    dest.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        name = Path(f.filename or "file").name
        if not name or name in (".", ".."):
            continue
        if Path(name).suffix.lower() not in _ALLOWED_EXTENSIONS:
            logger.warning(f"文件 {name} 扩展名不在白名单，跳过")
            continue
        # 只读 MAX_FILE_SIZE+1 字节：超限即跳过，防止未限流大文件耗尽内存
        content = await f.read(MAX_FILE_SIZE + 1)
        if len(content) > MAX_FILE_SIZE:
            logger.warning(f"文件 {name} 超过大小限制，跳过")
            continue
        (dest / name).write_bytes(content)
        saved.append(
            {"name": name, "size": len(content), "path": f"uploads/{upload_id}/{name}"}
        )

    if not saved:
        return {"status": "error", "error": "没有有效文件"}
    return {"status": "ok", "upload_id": upload_id, "files": saved}
