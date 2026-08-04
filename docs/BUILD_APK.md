# IReckon APK 构建说明

## 概述

IReckon 是一个 Python 后端 + Vue 前端的应用。APK 构建需要额外环境配置。

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
编辑 `buildozer.spec` 文件，设置正确的requirements。

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

- ✅ EXE 构建完成: `dist/IReckon.exe`
- ⚠️ APK 构建需要 Android SDK 和额外配置

## 环境要求

要构建 APK，需要:
1. Java JDK 17+
2. Android SDK (API 31+)
3. Android NDK
4. ~10GB 磁盘空间