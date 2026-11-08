# 开发计划

> 阶段划分与任务清单。完成情况见 `PROJECT_STATUS.md`，进度变化记入 `CHANGELOG.md`。
> 人日为「单人 + AI 辅助」口径的估算，不含需求变更与设计返工。

---

## 总览

| 阶段 | 内容 | 估时 | 状态 |
| --- | --- | --- | --- |
| 阶段 0 | 项目准备：文档、规则、骨架、数据库评审 | 2 | ✅ 完成 |
| 阶段 1 | 项目初始化：三容器可运行、前后端骨架、日志与错误处理 | 2 | ✅ 完成 |
| M0 | 骨架收尾：CIDR/幂等中间件、静态托管验证、CI | 1.5 | 🔄 进行中（迁移与统一响应已验证） |
| M1 | 认证：配对码 → 设备令牌（Cookie + Bearer 双通道） | 1.5 | ⬜ |
| M2 | 档案域：分类 / 单位 / 位置 / 食材 / 条码 / 文件 | 3.5 | ⬜ |
| M3 | 批次域：入库建批次、批次查询、状态流转 | 4 | ⬜ |
| M4 | **消耗域**：FEFO、成本分摊、尾差、双计量、营养快照 | 5 | ⬜ |
| M5 | 库存域：`v_inventory`、流水、详情聚合、对账任务 | 2.5 | ⬜ |
| M6 | 首页与营养：dashboard、营养目标、日汇总 | 3 | ⬜ |
| M7 | 备份导出：pg_dump 定时、文件备份、CSV/JSON 导出 | 1 | ⬜ |
| M8 | 前端 5 页：配对 / 首页 / 库存 / 记录 / 设置 | 6 | ⬜ |
| M9 | 原生 App：Capacitor 集成、原生配置、双端出包 | 4 | ⬜ |
| M10 | 联调验收：9 条用例转绿、时区边界、部署手册 | 2.5 | ⬜ |
| | **P0 合计** | **36** | |

P1（临期提醒 + 盘点 + 报损 + 撤销 + 统计页 + 导出 + 扫码 + App 本地通知）≈ 12 人日。
P2（AI 识别 + 采购清单 + 菜谱 + 对账告警 + TLS）≈ 14 人日。

---

## 阶段 0 · 项目准备（已完成）

| # | 任务 | 交付物 | 完成判据 |
| --- | --- | --- | --- |
| 0.1 | 整理项目文档 | `PRD.md` `ARCHITECTURE.md` | 产品范围、业务规则、验收标准、架构与 API 无歧义 |
| 0.2 | 建立项目规则 | `AGENTS.md` | 技术栈、分层、数值精度、禁止事项可执行 |
| 0.3 | 确定技术栈 | `ARCHITECTURE.md` §2 + `requirements.txt` / `package.json` | 版本可获取且钉死 |
| 0.4 | 确定目录结构 | `backend/` `frontend/` `database/` `deploy/` `docs/` | 每层职责清晰，空目录有占位 |
| 0.5 | 初始化 Git | 仓库 + 首次提交 | 有 `.gitignore`，密钥与数据未入库 |
| 0.6 | 数据库设计评审 | `database/001_init.sql` `docs/database.md` `docs/er-diagram.md` | 25 表有用途、外键合理、对账视图为 0 |

---


## 阶段 1 · 项目初始化（已完成）

目标：能跑起来、能连上库、能看见日志。不做业务页面。

| # | 任务 | 交付物 | 完成判据 | 状态 |
| --- | --- | --- | --- | --- |
| 1.1 | Vue3 + TS + Vite 初始化 | `frontend/`、`vite.config.ts`、`tsconfig.json`、`src/main.ts` | `npm run build` 通过（vue-tsc 无错） | ✅ |
| 1.2 | FastAPI + SQLAlchemy + Pydantic 初始化 | `backend/app/{main,core,db,api}` | `/api/v1/ping` 可访问，OpenAPI 可打开 | ✅ |
| 1.3 | PostgreSQL 配置与连接池 | `db/session.py`、`/api/v1/system/db` | 返回 connected/tables/migration/pool | ✅ |
| 1.4 | Alembic 迁移 | `backend/migrations/`（`alembic.ini` 指向它） | 干净库 `upgrade head` → 25 表 + `0001_init` | ✅ |
| 1.5 | Docker 三容器 | `docker-compose.yml`、`backend/Dockerfile`、`frontend/Dockerfile` + `nginx.conf` | 三容器 healthy，依赖链 db→api→web | ✅ |
| 1.6 | 基础布局 | `layouts/AppLayout.vue`、`styles/main.css` | 桌面有侧边栏、移动有底部导航、顶部栏常驻 | ✅ |
| 1.7 | Axios 与统一错误处理 | `api/http.ts`、`api/index.ts`、`utils/notify.ts` | 统一 `{success,data}` 解析、错误弹提示、401 统一出口 | ✅ |
| 1.8 | 前后端日志与异常记录 | `core/logging.py`、`utils/logger.ts`、`POST /system/client-logs` | 访问日志 JSON 落 `storage/logs/api.log`；前端错误可上报 | ✅ |

**验收实测（2026-11-09）**：三容器 healthy；`GET /` 200 且资源与 SPA 回退正常；
`/api/v1/system/db` 返回 connected=true / tables=25 / migration=0001_init；
重启 db+api 后探针数据仍在；干净库跑 `alembic upgrade head` 成功。

---

## M0 · 骨架收尾

| # | 任务 | 完成判据 |
| --- | --- | --- |
| 0.1 | `docker compose up -d` 在 NAS 上跑通 | `/health` 返回 `{"status":"ok","db":true}` |
| 0.2 | Alembic 迁移在真库执行 | `alembic current` → `0001_init (head)`；25 表存在 |
| 0.3 | `ALLOW_CIDR` 中间件 | 非白名单 IP 返回 403；白名单放行 |
| 0.4 | 统一响应与错误处理 | 参数错误返回 `VALIDATION_ERROR` 且含 `request_id` |
| 0.5 | 静态托管 | `npm run build` 后 `/` 返回 SPA，`/api/v1/*` 不被兜住 |
| 0.6 | 幂等中间件 | 同 `Idempotency-Key` 同 body 返回原响应 |
| 0.7 | CI 基础 | push 触发 `pytest` + `npm run build` 通过 |

**验收**：本地/ NAS 上 `curl` 六个接口返回预期 JSON；`pytest` 全绿。

---

## M1 · 认证

配对码生成（CLI）→ `/auth/pair` → 设备令牌 → Cookie/Bearer 双通道 → 设备列表与吊销 → 登录限流。

**完成判据**：浏览器输入配对码后可访问受保护接口；App 用 Bearer 可访问；吊销后 1 秒内失效；
重复使用同一配对码返回 401。

---

## M2 · 档案域

分类（两级，同级不重名）→ 单位（dimension 隔离）→ 储存位置 → 食材（含拼音索引）→ 条码 → 文件上传。

**完成判据**：能建档、能按中文/拼音/首字母搜到；改营养档案生成新版本且旧版本 `is_current=false`；
条码重复绑定被拒。

---

## M3 · 批次域

入库（同一事务写 `purchase` 流水 + 分配）→ 批次列表/详情 → 临期与过期查询 → 状态流转。

**完成判据**：`batches.remaining_*` 与分配聚合一致（`v_batch_reconcile` 差异为 0）；
批次元数据可改但数量不可直接改（必须走盘点）。

---

## M4 · 消耗域（风险最高）

FEFO 分配 → 成本分摊 + 尾差 → 双计量联动 → 事务边界 → 营养快照 → 批量消耗 → 撤销。

**完成判据**：PRD 9 条验收用例中消耗相关 6 条全绿（成本 10.80 / 剩余 42.20 / FEFO / 库存不足 / 幂等 / 回滚）；
并发压测无负库存；撤销后余额与流水均回到原值。

> 做法：先把 9 条用例写成**失败测试**，再实现到全绿。

---

## M5 · 库存域

`v_inventory` 查询与筛选 → 流水分页 → 食材详情聚合 → 盘点 / 报损 → 对账任务。

**完成判据**：库存页数据与批次聚合逐条一致；盘点后差额落在 `adjustment` 流水；对账任务在人为制造差异后能发现并修正。

---

## M6 · 首页与营养

dashboard 五组接口 → 营养定义/目标 → 日汇总（区分"无记录"与"0 摄入"）。

**完成判据**：首页四个数字与手工核对一致；营养卡片标注"按库存消耗量估算"。

---

## M7 · 备份导出

定时 `pg_dump` + 文件 tar + 保留策略 → 导出 CSV/JSON。

**完成判据**：`./deploy/backup.sh` 产物可被 `restore.sh` 恢复；导出文件 Excel 打开不乱码。

---

## M8 · 前端 5 页

配对页 → 首页 → 库存（含批次详情）→ 记录 → 设置（设备/分类/单位/目标/备份）。

**完成判据**：手机浏览器全流程可用；三态（加载/空/错误）齐全；401 自动跳配对页。

---

## M9 · 原生 App

Capacitor 8 集成 → 原生配置（ATS/cleartext/androidScheme）→ 安全存储令牌 → 地址与配对 → APK / IPA 出包。

**完成判据**：APK 装到 Android 真机可配对可记账；未签名 IPA 用长期证书重签后装到 iOS 可运行。

---

## M10 · 联调验收

9 条用例端到端跑绿 → 时区与边界 → 部署手册 → 备份恢复演练。

**完成判据**：`PROJECT_STATUS.md` 的"已知问题"清空或全部有处置说明。

---

## P1 待排期

临期提醒（含 App 本地通知排程）· 盘点批量 · 报损 · 撤销入口 UI · 统计页图表 · 导出中心 · 条码扫描 · 开封后保质期。

## P2 待排期

AI 图片/营养表识别（结果仅作草稿）· 采购清单（含菜谱缺口合并）· 菜谱管理 · 对账告警 · 自签 TLS（可选）。
