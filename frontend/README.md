# IReckon Frontend

Vue 3 前端 — 冰海控制台设计系统（SnowBlock 配色 · v6）

---

## 安装依赖

```bash
cd frontend
npm install
```

---

## 开发模式

```bash
npm run dev
```

然后访问 http://localhost:3000

---

## 构建

```bash
npm run build
```

构建产物输出到 `dist/`，由 FastAPI 生产模式直接托管（端口 8000）。

---

## 设计系统

- **SnowBlock 配色正本**（v1.0，与三站 tokens.css 同源）——亮色 = 纸雪车间（纸雪底 `#f2efe9` · 雾蓝主色 `#5b9bb5`），暗色 = 深海夜班（深海底 `#0b2b3b` · 冰青主色 `#8fd8ef`）
- **功能色原值上屏**（暗色主题）——Online `#1fdf64` / Offline `#f25e5e` / Warning `#f0b34b` / Info Blue `#5ea3f2`
- **品牌点缀令牌** —— 芯暖 `--sb-core-warm`（晶核/点睛，勿大面积）、内光 `--sb-inner-frost`、磁贴渐变 `--sb-tile-gradient`，见 `src/assets/main.css` 头部
- **一套类名通吃双主题** —— Tailwind v4 `@theme inline` 映射语义令牌，明暗只翻转原始变量
- **签名元素「信号轨」** —— 导航激活 / 任务选中共用同一条 3px 主色左轨
- **响应式布局** —— 桌面 / 平板 / 移动端自适应

## 功能

- 聊天界面 - 多层消息（公共广场 / 会议层）、实时 WebSocket、任务看板
- 任务管理 - 创建（含参考文件上传）、取消、恢复、删除任务
- 仪表盘 - KPI 卡片、任务状态分布、Token 用量、系统状态
- 交付产物 - 任务文件浏览 + 语法高亮预览 + ZIP 下载
- AI 实例管理 - 添加、编辑、删除、测试 AI 端点
- 系统日志 - 全页实时日志流（WebSocket 推送 + 级别筛选）
- 自我进化 - AI 自分析并推送改进分支
- 设置 - 版本更新管理与配置查看
- 深色/浅色主题切换

---

Enjoy using IReckon!
