# 告警链路静默失效：ALERTS 恒空 + alertmanager 不存在

- **日期**：2026-10-09
- **影响**：**告警看起来在工作，实际没人会收到**（silent alarm）
- **一句话结论**：两个独立缺陷叠加——vmalert 缺 `--remoteWrite.url`，且 compose 里根本没定义 alertmanager

## 第一阶段：链路本身是断的

### 现象

三点验证时发现视图互相矛盾（**同一时刻**）：

| 视图 | 接口 | 结果 |
|---|---|---|
| 引擎态 | vmalert `/api/v1/alerts` | **firing** ✅ |
| 落库态 | VM `query=ALERTS` | **`[]` 恒空** ❌ |
| 送达态 | alertmanager `/api/v2/alerts` | 端口无响应 ❌ |

### 诊断

**缺陷 1：缺 remote write**

```text
docker inspect vmalert --format '{{.Config.Cmd}}'
→ [--datasource.url=... --rule=... --notifier.url=... --httpListenAddr=:8880]
                                            ↑ 没有 --remoteWrite.url
```

连查 3 次（间隔 5s，共 15s）ALERTS 全空 → 排除"秒级延迟"，确认 **vmalert 从不往 VM 写 ALERTS**。

**缺陷 2：alertmanager 服务不存在**

```text
docker ps -a → 只有 vmalert / victoriametrics / node-exporter / grafana / web
```

`.env` 里躺着 `AM_VER` / `BB_VER`，但**没有任何 service 引用它们**（死变量）。
vmalert 日志留下铁证（**每 30s 一条**）：

```text
notifier failure: failed to send alerts to "http://alertmanager:9093/api/v2/alerts":
dial tcp4: lookup alertmanager on 127.0.0.11:53: no such host
```

**错误一直在刷，只是没人看** —— 典型的 who-watches-the-watcher 问题。

### 根因

1. vmalert 启动参数缺 `--remoteWrite.url` → ALERTS 只活在引擎内存里，不落库
2. compose 未定义 alertmanager → notifier 每周期 DNS 失败，且失败**不产生任何外部可见信号**

### 修复

1. `observability/docker-compose.yml` 的 vmalert.command 补一行 `- '--remoteWrite.url=http://victoriametrics:8428'`
2. 新增 `observability/alertmanager.yml`（route + default receiver）+ compose 新增 alertmanager service

commit `ea144de` / `06e025f`。

### 验证（三点对齐）

| 视图 | 结果 |
|---|---|
| vmalert `/api/v1/alerts` | `pending` → 跨 `for:1m` 转 firing |
| VM `ALERTS` | `alertstate: pending`，`value: 1`，`seriesFetched: 1` |
| alertmanager `/api/v2/alerts` | 收到 NodeDown，`status.state: active`，`receivers:[default]` |

---

## 第二阶段：接通通知渠道

（同日，连踩 4 个坑）

第一阶段只做到「告警送到 alertmanager」。**送到 alertmanager ≠ 有人被通知**。
本轮目标是把最后一环打通：**邮件通知**（选它的理由：SMTP 是标准协议、alertmanager 原生支持、零额外容器；
钉钉/企微/飞书机器人要求各自的 `msgtype` 载荷，直接填 webhook URL 会被**静默丢弃**，需额外 bridge）。

> ⚠️ 若将来改用 webhook 类渠道，注意：**容器内的 `127.0.0.1` 指容器自身，不是宿主机**。
> 要打到宿主上的服务需用服务名、`host.docker.internal` 或宿主内网 IP。

### 坑 1：`docker compose up -d` 是 no-op，容器根本没重建

- **现象**：改成 SMTP 配置后 `up -d`，注入测试告警返回 **HTTP 200**，但**邮箱毫无动静**
- **诊断**：容器内文件与宿主机文件**不一致** —— 容器里还是旧的 `webhook_configs`；日志
  `integration=webhook[0] ... dial tcp 127.0.0.1:9099: connect: connection refused`；
  容器 `StartedAt` 远早于文件修改时间
- **根因**：compose 只比较**服务定义**，不比较**挂载文件内容** → 判定"无需变更"；
  且 `cp` 覆盖文件会**换 inode**，旧容器的 bind-mount 仍指向旧 inode
- **修复**：`docker compose up -d --force-recreate alertmanager`
- **沉淀**：[methodology ⑪](../methodology.md)

### 坑 2：`smtp_from` 拼错一个字符

```yaml
smtp_from:          '961684345@qq.com'   # 9 6 1...
smtp_auth_username: '981684345@qq.com'   # 9 8 1...
```

- QQ 邮箱**强制要求 From 等于认证账号**，不一致会被拒（`553 Mail from must equal authorized user`）
- 这个坑极隐蔽 —— 两个字符串长得几乎一样

### 坑 3：`alertmanager-data` 属主错误（附带故障）

```text
每 15 分钟：ERROR open /alertmanager/nflog.*: permission denied
           ERROR open /alertmanager/silences.*: permission denied
```

容器以 `nobody(65534)` 运行，而宿主目录是 `root:root` → 写不进去。
**后果：silence 与通知日志无法持久化**（设的维护窗口重启就丢）。
修复：`chown -R 65534:65534 alertmanager-data`。

### 坑 4（最贵）：为保护密钥 `chmod 600`，把容器锁死

- **现象**：`--force-recreate` 后容器 **crash loop**（ExitCode=1，RestartCount=10）
- **日志**：`error loading configuration file: open /etc/alertmanager/alertmanager.yml: permission denied`
- **根因**：镜像以 **`nobody`** 运行，而文件被 `chmod 600` 成 root 私有 → 读不到。
  **"更严的权限"没有更安全，只是让消费方读不到。**
- **修复**：从「`chown nobody` + 600」改为 **「目录 700 保护 + 文件 644 可读」**，
  并把密钥文件移到仓库外的 `/root/.sre-lab-secrets/`
- **收获**：这次崩溃逼出了一个更好的设计 —— 见 [ADR 0002](../adr/0002-secret-file-permissions.md)

### 判据纠错（重要）

验证"容器能否读到配置"时，**不能用宿主机的 nobody 视角**：

```sh
sudo -u nobody cat /root/.sre-lab-secrets/alertmanager.yml   # ❌ 假阴性
```

`/root` 是 750，nobody 连目录都进不去 —— 报 `Permission denied` 但**容器其实读得好好的**
（bind mount 由 dockerd 以 root 解析，容器内不涉及宿主目录穿越）。正确的判据是**容器视角**：

```sh
docker exec alertmanager cat /etc/alertmanager/alertmanager.yml >/dev/null && echo "✅ 容器可读"
```

### 最终验证

| 检查 | 结果 |
|---|---|
| 注入测试告警（alertmanager API） | HTTP 200 |
| 邮件到达 | ✅ `[FIRING] ChannelTest` |
| 迁移后复测 | ✅ 渠道无副作用 |
| 免疫性受控实验（`chown root:root` 后） | ✅ 容器仍可读 |

**四环闭环达成：检测（vmalert）→ 落库（VM）→ 送达（alertmanager）→ 通知到人（邮件）。**

## 教训

- 见 [methodology ⑦](../methodology.md)：告警三视图 ≠ 一个真源，必须三点同验
- 见 [methodology ⑧](../methodology.md)：`.env` 里没有被任何 service 引用的变量就是死变量，会误导人以为功能已存在
- 见 [methodology ⑪](../methodology.md)：改了挂载的配置 ≠ 容器生效
- 见 [methodology ⑫](../methodology.md)：收紧权限前先确认消费方不是 root
- **"有观测能力 ≠ 有通知能力"** —— 09-26 就写过这条，这次在告警链路上再次应验

## 遗留

- 告警规则 4 条中仅 `NodeDown` 经端到端验证；其余 3 条尚未触发过（待验证）
- `BB_VER`（blackbox-exporter）仍是死变量，服务未加
- 集中日志（Loki + promtail）未做；Grafana 已装 `grafana-lokiexplore-app` 插件，属计划中
- Grafana 数据源 / 面板未代码化（只在 `grafana.db` 里），容器重建即丢
