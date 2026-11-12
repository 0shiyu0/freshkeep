# legacy/ · 早期纯静态版归档

这里的文件是项目**第一版**的实现：无框架、无构建步骤，数据存在浏览器 `localStorage`
（键名 `freshkeep.v1`），单文件应用外壳 + `js/store.js` 数据层 + `js/app.js` 界面层。

## 为什么不删

它对两件事仍有参考价值：

1. **交互参考**：清单上 `−1` 一键扣减、底部弹层、Toast 撤销这些交互最早在这里验证过，
   当前 Vue 版本保留了同样的操作路径。
2. **历史对照**：从 localStorage 单机版迁移到「FastAPI + PostgreSQL + 三容器」时，
   字段命名与统计口径的演进可以在这里追溯。

## 重要说明

- **不参与任何构建与部署**。`frontend/Dockerfile` 只从 `frontend/` 构建，
  nginx 只托管 `frontend/dist`，本目录不会被任何流程读取。
- **不要再基于这里开发**。当前实现的入口是 `frontend/src/main.ts` 与 `backend/app/main.py`。
- 若要本地打开 `index.html` 预览，注意它读取的是**浏览器本地数据**，与 NAS 上的数据库无关，
  不要误以为两边数据同步。
