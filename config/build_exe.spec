# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

project_root = os.path.dirname(os.path.abspath(SPECPATH))

# Collect all data files and submodules from app
app_datas, app_binaries, app_hiddenimports = collect_all('app')

# Additional hidden imports
extra_hiddenimports = [
    'uvicorn',
    'uvicorn.protocols',
    'uvicorn.server',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'fastapi',
    'streamlit',
    'loguru',
    'watchdog',
    'litellm',
    'langchain',
    'langgraph',
    'chromadb',
    'httpx',
    'websockets',
    'jinja2',
    ' cryptography',
    'aiosqlite',
    'pydantic',
    'yaml',
]

# Check if ui directory exists
ui_datas = []
if os.path.exists(os.path.join(project_root, 'ui')):
    ui_datas = [('ui', 'ui')]
    extra_hiddenimports.extend(['ui.components', 'ui.utils'])

# Frontend dist files
frontend_datas = []
frontend_dist_path = os.path.join(project_root, 'frontend', 'dist')
if os.path.exists(frontend_dist_path):
    frontend_datas = [(frontend_dist_path, 'frontend/dist')]

# Config directory
config_datas = []
config_path = os.path.join(project_root, 'config')
if os.path.exists(config_path):
    config_datas = [('config', 'config')]

all_datas = app_datas + ui_datas + frontend_datas + config_datas

a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=app_binaries,
    datas=all_datas,
    hiddenimports=app_hiddenimports + extra_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='IReckon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)