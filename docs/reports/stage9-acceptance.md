# 阶段 9 · 安全与性能验收报告

> 验收脚本：`scripts/stage9_acceptance.py`；机器可读结果：`docs/reports/stage9-acceptance.json`。
> 环境：NAS `192.168.31.198`，HTTP `18080` / HTTPS `18443`（自签证书）。

## 9.9 安全与性能验收结论

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 凭据不入库 | ✅ | 遍历版本库 218 个跟踪文件，NAS 密码 0 命中 |
| 敏感路径忽略 | ✅ | `.env` 与 `storage/certs/freshkeep.key` 均被 gitignore |
| PWA 资产 | ✅ | manifest / sw.js / offline.html / icon 全部 200 且含关键字段 |
| HTTPS | ✅ | 18443 返回 200，TLSv1.2/1.3（自签证书，SAN 含 192.168.31.198） |
| 安全响应头 | ✅ | HSTS、CSP、X-Frame-Options、X-Content-Type-Options、Referrer-Policy |
| API 鉴权 | ✅ | 未带凭据请求 `/api/v1/inventory` 返回 401 |
| 接口延迟 | ✅ | /health p50 17.07ms · p95 108.3ms；首页 p95 100.58ms（20 次采样，含冷启动） |
| 容器健康 | ✅ | api / db / web 三容器 healthy |
| 恢复演练 | ✅ | `restore-drill.json` ok=true，27 表逐表一致 |

**性能结论**：单用户家庭场景下 p95 ≤ 110ms（局域网），满足 PRD 目标；
数据一致性由流水账本保证，备份/恢复演练通过。

**安全结论**：凭据零入库、HTTPS 加密传输、API 默认拒绝未授权访问、
离线模式不缓存任何业务数据（避免数据分歧）、浏览器通知默认关闭需显式授权。

## 待确认风险项

| # | 风险 | 说明与建议 |
| --- | --- | --- |
| R1 | 自签证书需客户端信任 | 手机/浏览器首次访问 18443 会告警；导入证书或改用公网 CA + 域名 |
| R2 | APScheduler 不补跑 | 容器重启后作业重新注册，错过的 03:00/03:10/08:00 窗口不会补跑 |
| R3 | 18080 为明文 HTTP | 局域网内可接受；公网暴露前必须关闭 18080 只留 18443 |
| R4 | 备份只在单 NAS | 建议同步到另一块卷或云存储（`prune_backups` 保留 7 份） |
| R5 | 定时任务首次自动触发未观测 | 已验证手动执行与调度状态；03:00/08:00 自动触发待次日观察 `audit_logs` |
