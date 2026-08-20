# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('config', 'config'), ('frontend/dist', 'frontend/dist')]
binaries = []
hiddenimports = ['app.web.api', 'app.web.push', 'app.engine.self_improve', 'app.engine.style', 'app.engine.learner', 'app.engine.registry', 'app.engine.tasks', 'app.engine.room', 'app.engine.machine', 'app.engine.board', 'app.engine.detector', 'app.engine.cost', 'app.agents.base', 'app.agents.executor', 'app.agents.scheduler', 'app.agents.reviewer', 'app.agents.creative', 'app.agents.deliverer', 'app.agents.learner', 'app.agents.tool_manager', 'app.agents.content_filter', 'app.llm.client', 'app.llm.pool', 'app.tools.registry', 'app.tools.library', 'app.tools.assembler', 'app.security.scanner', 'app.security.filter', 'app.security.sandbox', 'app.security.mining', 'app.security.supply', 'app.knowledge.vector', 'app.knowledge.files', 'app.core.updater', 'uvicorn', 'uvicorn.protocols', 'uvicorn.server', 'uvicorn.loops', 'uvicorn.loops.auto', 'multipart', 'watchdog', 'aiosqlite', 'jinja2']
hiddenimports += collect_submodules('chromadb')
tmp_ret = collect_all('app')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='IReckon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='IReckon',
)
