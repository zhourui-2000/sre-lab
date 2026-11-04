# 告警链路静默失效：ALERTS 恒空 + alertmanager 不存在

2026-10-09。告警看起来在工作，实际没人会收到。两个独立缺陷叠加：vmalert 缺 `--remoteWrite.url`，compose 未定义 alertmanager。

## 链路

| 视图 | 接口 | 结果 |
|---|---|---|
| 引擎态 | vmalert `/api/v1/alerts` | firing ✅ |
| 落库态 | VM `query=ALERTS` | `[]` 恒空 ❌ |
| 送达态 | alertmanager `/api/v2/alerts` | 端口无响应 ❌ |

```text
docker inspect vmalert --format '{{.Config.Cmd}}'
→ [--datasource.url=... --rule=... --notifier.url=... --httpListenAddr=:8880]
                                            ↑ 没有 --remoteWrite.url
```

连查 3 次（间隔 5s，共 15s）ALERTS 全空，排除秒级延迟。`docker ps -a` 只有 vmalert / victoriametrics / node-exporter / grafana / web，alertmanager 不存在；`.env` 里 `AM_VER` / `BB_VER` 无 service 引用；日志每 30s 一条：

```text
notifier failure: failed to send alerts to "http://alertmanager:9093/api/v2/alerts":
dial tcp4: lookup alertmanager on 127.0.0.11:53: no such host
```

## 修复

`observability/docker-compose.yml` 的 vmalert.command 补 `- '--remoteWrite.url=http://victoriametrics:8428'`；新增 `observability/alertmanager.yml.example`（route+receiver；真配置在服务器 /root/.sre-lab-secrets/，不入库）与 alertmanager service。commit `ea144de` / `06e025f`。

| 视图 | 结果 |
|---|---|
| vmalert `/api/v1/alerts` | `pending` 跨 `for:1m` 转 firing |
| VM `ALERTS` | `alertstate: pending`，`value: 1`，`seriesFetched: 1` |
| alertmanager `/api/v2/alerts` | NodeDown，`status.state: active`，`receivers:[default]` |

## 通知渠道

选邮件：SMTP 标准、原生支持、零额外容器；钉钉/企微/飞书各要 `msgtype` 载荷，直接填 webhook 会静默丢弃。容器内 `127.0.0.1` 指自身，打宿主服务要用 `host.docker.internal` 或宿主内网 IP。

**坑 1** `docker compose up -d` 是 no-op：注入告警 200，邮箱无动静；容器内仍是旧 `webhook_configs`，日志 `integration=webhook[0] ... dial tcp 127.0.0.1:9099: connect: connection refused`，`StartedAt` 早于文件修改，`cp` 覆盖换 inode。修复：`docker compose up -d --force-recreate alertmanager`。

**坑 2** `smtp_from` 与认证账号差一位：

```yaml
smtp_from:          '961684345@qq.com'   # 9 6 1...
smtp_auth_username: '981684345@qq.com'   # 9 8 1...
```

QQ 邮箱要求 From 等于认证账号，否则 `553 Mail from must equal authorized user`。

**坑 3** `alertmanager-data` 属主错误：每 15 分钟 `ERROR open /alertmanager/nflog.*: permission denied`、`silences.*` 同；容器以 `nobody(65534)` 运行而目录 `root:root`，silence 与日志丢失。修复 `chown -R 65534:65534 alertmanager-data`。

**坑 4** `chmod 600` 锁死容器：`--force-recreate` 后 crash loop（ExitCode=1，RestartCount=10），`error loading configuration file: open /etc/alertmanager/alertmanager.yml: permission denied`。从 `chown nobody` + 600 改为目录 700 + 文件 644，密钥移出仓库到 `/root/.sre-lab-secrets/`（[ADR 0002](../adr/0002-secret-file-permissions.md)）。

判据纠错：`sudo -u nobody cat /root/.sre-lab-secrets/alertmanager.yml` 是假阴性（`/root` 750，报 `Permission denied`，但容器读得到）。正确判据 `docker exec alertmanager cat /etc/alertmanager/alertmanager.yml >/dev/null && echo "✅ 容器可读"`。

| 检查 | 结果 |
|---|---|
| 注入测试告警 | HTTP 200 |
| 邮件到达 | ✅ `[FIRING] ChannelTest` |
| 迁移后复测 | ✅ 无副作用 |
| `chown root:root` 受控实验 | ✅ 容器仍可读 |

## 未证

4 条规则中仅 `NodeDown` 经端到端验证，其余 3 条未触发。`BB_VER` 仍是死变量，服务未加。Loki + promtail 未做，Grafana 已装 `grafana-lokiexplore-app` 插件；数据源与面板未代码化（只在 `grafana.db`），容器重建即丢。

09-26 同类：有观测能力 ≠ 有通知能力（[methodology ⑦⑧⑪⑫](../methodology.md)）。
