[app]

title = IReckon
package.name = ireckon
package.domain = org.ireckon

version = 0.1.0

requirements = python3,kivy,pyyaml,loguru,litellm,langgraph,chromadb,httpx,fastapi,uvicorn,websockets,pydantic,python-multipart,aiosqlite,cryptography,jinja2,python-dateutil,psutil,aiofiles,watchdog

orientation = landscape

fullscreen = 1

android.api = 31
android.min_api = 21
android.accept_sdk_license = True

android.permissions = INTERNET,ACCESS_NETWORK_STATE

# Entry point
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,yaml,yml,css,js,html,svg

osx.python_version = 3.11
osx.kivy_version = 2.3.0

[buildozer]

log_level = 2

warn_on_root = 1
