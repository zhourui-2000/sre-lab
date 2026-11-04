# web 容器 healthcheck 恒为 unhealthy

2026-09-24。`docker ps` 显示 `web ... (unhealthy)` 已多日，业务正常；初判 301 未验证。

```text
docker exec web wget -qO /dev/null http://127.0.0.1/  → EXIT=0
docker exec web wget -qO /dev/null http://localhost/  → EXIT=1（Connection refused）
getent hosts localhost                                → ::1
netstat -tlnp                                         → 仅监听 0.0.0.0:80 / 0.0.0.0:443，无 IPv6
```

## 根因

`localhost` 解析优先返回 IPv6 `::1`，nginx `listen 80` 只绑 IPv4，连接被拒；busybox wget 不回退。

## 修复

healthcheck 改 `http://127.0.0.1/healthz`；新增 `location = /healthz { access_log off; return 200 "ok\n"; }`，不再依赖 301、回环、证书。

## 判据

| 检查 | 结果 |
|---|---|
| `docker inspect web --format '{{.State.Health.Status}}'` | healthy |
| `FailingStreak` | 0 |
| `docker exec web wget -qO- http://127.0.0.1/healthz` | ok |

`access_log off` 增量：

| 时点 | access.log 总行数 | `/healthz` 出现次数 |
|---|---|---|
| 基线 | 14006 | 6 |
| 等待 70 秒 | 14006（+0） | 6（+0） |

三次检查 18:50:49/18:51:19/18:52:50 全部 exit=0，日志零增长。对照组 `GET /` 200、`GET /nonexistent-404-test` 404 共 +2 行，仅 `/healthz` 被关。

修复前 6 条早于 18:25:17，无 200：

| 时间 | 码 |
|---|---|
| 09-19 10:26 | 404 |
| 09-24 12:30 | 301 |
| 09-24 16:44 | 301 + 404 |
| 09-24 17:47 | 301 + 404 |

## 另两处

只 `git pull` 未重建容器：nginx 只在启动或 reload 时读配置，`nginx -T` 只解析磁盘；运行态看业务行为、`StartedAt`、master 启动时间。

compose 的 `test` 元素未加引号，YAML 把 `3` 当整数：`validating ...: services.web.healthcheck.test.4 must be a string`，`up -d` 退出；先 `docker compose config`。

`localhost` ≠ `127.0.0.1`；健康检查、探针、容器内调用写显式地址或服务名，不依赖 DNS、外网、证书（[methodology ①③](../methodology.md)）。
