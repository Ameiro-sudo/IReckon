# 备忘录

## 推送代码
```bash
git add .
git commit -m "改了什么"
git push
```

## 打 tag 触发云端构建
```bash
git tag v0.1.0 && git push origin v0.1.0
```

## 本地构建 EXE
```powershell
cd frontend && npm run build && cd ..
python scripts/build_exe.py
```
输出在 `dist/IReckon/`

## 手动触发 GitHub Actions 构建 APK
1. https://github.com/ninasukiwww-png/IReckon/actions
2. Build Android APK → Run workflow → 等几分钟
3. 构建完成后下载 APK
