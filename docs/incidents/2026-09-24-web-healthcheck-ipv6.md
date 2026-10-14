# web 容器 healthcheck 恒为 unhealthy

- **日期**：2026-09-24
- **影响**：`docker ps` 显示 `web ... (unhealthy)` 已持续多日；业务访问正常（**静默降级**）
- **一句话结论**：healthcheck 用 `localhost`，容器内解析优先 IPv6 `::1`，而 nginx 只听 IPv4

## 第一层误判

以为是 HTTP 全量 301 导致 healthcheck 失败 —— **假设未经验证**。

## 实测推翻

（关键动作：先跑命令，而不是先下结论）

```text
docker exec web wget -qO /dev/null http://127.0.0.1/   → EXIT=0
docker exec web wget -qO /dev/null http://localhost/   → EXIT=1（Connection refused）
getent hosts localhost                                  → ::1
netstat -tlnp                                           → nginx 仅监听 0.0.0.0:80 / 0.0.0.0:443，无 IPv6 监听
```

## 根因

healthcheck 使用 `localhost`，容器内解析优先返回 IPv6 `::1`，而 nginx `listen 80` 只绑定 IPv4
→ 连接被拒；busybox wget 不会回退重试 IPv4。

## 修复

1. healthcheck 改用 `http://127.0.0.1/healthz`（显式 IPv4）
2. 新增 `location = /healthz { access_log off; return 200 "ok\n"; }`，
   使健康检查不再依赖 301 跳转 → 公网 → 发夹回环 → 证书这条脆弱链路

## 验证（四重，可复现）

**① 状态与自检**

```text
docker inspect web --format '{{.State.Health.Status}}'  → healthy
FailingStreak                                            → 0
最近三次检查（18:50:49 / 18:51:19 / 18:52:50）           → exit=0
docker exec web wget -qO- http://127.0.0.1/healthz       → ok
```

**② 日志噪音：跨周期增量对照（验证 `access_log off`）**

| 时点 | access.log 总行数 | `/healthz` 出现次数 |
|---|---|---|
| 基线 | 14006 | 6 |
| 等待 70 秒（跨 2 个检查周期）后 | 14006（**+0**） | 6（**+0**） |

等待期间健康检查确实执行（时间戳由 18:50:49 推进至 18:52:50，全部 exit=0），但访问日志零增长 → `access_log off` 生效。

**③ 对照组：证明"日志功能本身正常"**

```text
GET /                     → 200   ← 日志 +1
GET /nonexistent-404-test → 404   ← 日志 +1
```

日志共 **+2 行** → 不是"日志整体坏了"，而是 `/healthz` 这一个 location 被精确关闭。

**④ 历史记录反证（修复前后对照）**

| 时间（CST） | 状态码 |
|---|---|
| 09-19 10:26 | 404 |
| 09-24 12:30 | 301 |
| 09-24 16:44 | 301 + 404 |
| 09-24 17:47 | 301 + 404 |

6 条全部早于容器重建时刻 **18:25:17**，且**没有一条 200** —— 从反面证明修复前端点确实不可用。

## 修复过程中暴露的两个同源问题

1. **只 `git pull` 未重建容器** → nginx 只在启动/收到 reload 时读配置，文件改了不等于生效 →
   `/healthz` 仍 404。更坑的是：`nginx -T` 会显示新配置（它只是"读磁盘解析并打印"），
   **不能用来判断运行态**；判断运行态要看业务行为、容器 `StartedAt`、master 进程启动时间。
2. **compose 的 `test` 数组元素未加引号** → YAML 把 `3` 解析为整数 →
   `validating ...: services.web.healthcheck.test.4 must be a string` → `up -d` 直接退出、
   容器未重建，表现为"改完了但一切照旧"。
   **改完 compose 先跑 `docker compose config` 预检**（10 秒、不启动容器）就能提前抓住。

## 教训

- **`localhost` ≠ `127.0.0.1`**：多栈解析下可能先走 IPv6。健康检查、探针、容器间调用一律写显式地址或用服务名
- **健康检查必须"自包含"**：只验证本进程可用性，不引入 DNS、外网、证书等外部依赖
- 见 [methodology ①③](../methodology.md)
