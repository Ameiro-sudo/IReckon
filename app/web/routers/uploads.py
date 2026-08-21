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
# 上传区总配额：认证后仍可脚本化灌盘（每请求 ≤200MB），设总量上限防磁盘耗尽
UPLOADS_QUOTA_BYTES = 500 * 1024 * 1024
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


def _uploads_usage_bytes(root: Path) -> int:
    """统计上传区已用空间；统计失败按 0 处理（不因枚举异常阻断正常上传）。"""
    total = 0
    try:
        for p in root.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


@router.post("/uploads")
async def upload_files(files: List[UploadFile] = File(...)):
    """批量上传参考文件，返回 upload_id 供创建任务时引用。"""
    if not files:
        raise HTTPException(400, "未选择文件")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"最多上传 {MAX_FILES} 个文件")
    upload_id = f"up-{uuid.uuid4().hex[:12]}"
    data_dir = Path(get("system.data_dir", "./data"))
    uploads_root = (data_dir / "uploads").resolve()
    dest = (uploads_root / upload_id).resolve()
    try:
        # 防目录穿越：dest 必须位于 data_dir/uploads 之下
        dest.relative_to(uploads_root)
    except ValueError:
        raise HTTPException(400, "非法上传路径")
    if _uploads_usage_bytes(uploads_root) >= UPLOADS_QUOTA_BYTES:
        raise HTTPException(413, "上传区总配额已满，请先清理旧附件")
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
        target = dest / name
        try:
            target.write_bytes(content)
        except OSError as e:
            # Windows 保留设备名(CON/NUL/COM1…)或磁盘故障：跳过并记录，
            # 不让单个坏文件把整批请求打成 500（此前已写入的文件保留）
            logger.warning(f"文件 {name} 写入失败({e})，跳过")
            continue
        saved.append(
            {"name": name, "size": len(content), "path": f"uploads/{upload_id}/{name}"}
        )

    if not saved:
        # 整批无效时清理空目录，避免孤儿目录堆积
        try:
            dest.rmdir()
        except OSError:
            pass
        raise HTTPException(400, "没有有效文件（扩展名不在白名单或超过大小限制）")
    return {"status": "ok", "upload_id": upload_id, "files": saved}
