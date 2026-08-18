#!/usr/bin/env python3
"""Smoke test automation for IReckon.

This script performs basic runtime validation without requiring an active LLM endpoint.
It loads key modules, validates configuration and theme files, connects to SQLite,
and ensures the capability pool initialization path works.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from app.core.config import config_manager
from app.core.database import db
from app.core.logger import setup_logging, logger
from app.engine.style import style_engine
from app.llm.pool import capability_pool


async def run_smoke_tests() -> int:
    setup_logging()
    print("Smoke test: IReckon startup validation")

    print("- Verifying config file...")
    config_path = config_manager.config_path
    if not config_path.exists():
        print(f"FAIL: config file not found: {config_path}")
        return 1

    config = config_manager.get_all()
    required_top_keys = ["server", "ai_pool", "ui"]
    missing = [key for key in required_top_keys if key not in config]
    if missing:
        print(f"WARN: config missing expected keys: {missing}")
    print(f"  Loaded config keys: {sorted(config.keys())}")

    print("- Validating theme files...")
    theme_names = ["catgirl", "programmer"]
    theme_errors = []
    for name in theme_names:
        theme = style_engine.get_theme(name)
        if not isinstance(theme, dict) or not theme.get("name"):
            theme_errors.append(name)
    if theme_errors:
        print(f"FAIL: invalid theme data for {theme_errors}")
        return 1
    print("  Themes loaded successfully")

    print("- Connecting to database...")
    await db.connect()
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
    )
    if not row:
        print("FAIL: expected database table 'tasks' is missing")
        return 1
    print("  Database connected and core tables present")

    print("- Initializing capability pool...")
    await capability_pool.refresh(force=True)
    caps = await capability_pool.get_all()
    print(f"  Capability pool contains {len(caps)} configured instance(s)")

    if len(caps) == 0:
        print("  SKIP: no AI instances configured; endpoint reachability is not tested")

    await db.close()
    print("Smoke test complete.")
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(run_smoke_tests())
    except Exception as exc:
        logger.exception("Smoke test encountered an error")
        print(f"FAIL: exception during smoke test: {exc}")
        exit_code = 1
    raise SystemExit(exit_code)
