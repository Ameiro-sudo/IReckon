# IReckon APK 构建说明

## 概述

IReckon 是一个 Python 后端 + Vue 前端的应用。APK 构建需要额外环境配置。

## ⚠️ 现状与可行性评估（2026-08 无人值守验证轮更新）

**当前主分发渠道是 Windows EXE / 安装包**（见 `.github/workflows/build.yml`：
PyInstaller onedir → Inno Setup），本地已复现验证通过。APK 三方案经评估
均属**探索方向而非可用路径**：

| 方案 | 评估 | 阻断点 |
| --- | --- | --- |
| 1. WebView 壳 | 仅能加载静态前端 | IReckon 是重后端应用（FastAPI + LangGraph + SQLite + chromadb），WebView 壳不解决 Python 后端在 Android 上的运行问题 |
| 2. Buildozer/p4a | 不可行 | buildozer 不支持 Windows 宿主（需 WSL/Linux/macOS）；FastAPI/uvicorn/chromadb/litellm 无 p4a recipe |
| 3. Briefcase | 不可行（现阶段） | 同样受限于上述依赖的 Android 交叉编译生态缺失 |

**移动端的现实替代方案**：将 IReckon 部署在 PC 上，手机浏览器远程访问。
服务默认绑定 `127.0.0.1`（fail-closed 鉴权已内置），公网暴露请置于反向代理
之后并显式配置 `security.api_token`。

以下原始方案保留作为未来依赖生态成熟后的参考。

## 构建方案

### 方案 1: 使用 Android Studio WebView (推荐)

最简单的方式是创建一个 Android 应用，使用 WebView 加载已构建的 Vue 前端。

**步骤:**

1. **前置要求**
   - 安装 Android Studio
   - 安装 Java JDK 17+

2. **构建 Vue 前端**
   ```bash
   cd frontend
   npm run build
   ```

3. **创建 Android 项目**
   - 打开 Android Studio
   - 新建项目 -> 选择 "Empty Views Activity"
   - 复制 `frontend/dist` 到 `android/app/src/main/assets/`

4. **配置 WebView**
   在 `MainActivity.kt` 中:
   ```kotlin
   val webView = WebView(this)
   webView.settings.javaScriptEnabled = true
   webView.settings.domStorageEnabled = true
   webView.loadUrl("file:///android_asset/dist/index.html")
   setContentView(webView)
   ```

5. **构建 APK**
   - Build -> Build APK

### 方案 2: 使用 Python-for-Android (Buildozer)

**前置要求:**
- Java JDK 17+
- Android SDK
- Android NDK

**安装:**
```bash
pip install buildozer
```

**配置:**
编辑项目根目录的 `buildozer.spec` 文件，设置正确的requirements。

**构建:**
```bash
buildozer android debug
```

### 方案 3: 使用 BeeWare Briefcase

**步骤:**
```bash
pip install briefcase
briefcase new  # 选择 Android 模板
# 修改代码实现IReckon后端调用
briefcase build android
```

## 当前状态

- [OK] EXE 构建完成: `dist/IReckon.exe`
- APK 构建需要 Android SDK 和额外配置

## 环境要求

要构建 APK，需要:
1. Java JDK 17+
2. Android SDK (API 31+)
3. Android NDK
4. ~10GB 磁盘空间