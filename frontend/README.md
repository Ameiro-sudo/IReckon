# IReckon Frontend

Vue 3 前端 — 极简明亮风设计系统（Linear / Notion 质感）

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

- **极简明亮风** — 大留白、克制边框与阴影、12px 圆角、Indigo 强调色
- **浅色优先，深色精修** — 双主题均基于同一套 CSS 变量（`--accent` / `--bg` / `--border` 等）
- **代码块纸感处理** — 深浅主题下代码块保持一致浅色背景，与 github 高亮主题匹配
- **响应式布局** — 桌面 / 平板 / 移动端自适应

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
