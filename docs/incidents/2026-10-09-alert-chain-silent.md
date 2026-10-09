# 告警链路静默失效：ALERTS 恒空 + alertmanager 不存在

- **日期**：2026-10-09
- **影响**：**告警看起来在工作，实际没人会收到**（silent alarm）
- **一句话结论**：两个独立缺陷叠加——vmalert 缺 `--remoteWrite.url`，且 compose 里根本没定义 alertmanager

## 现象

三点验证时发现视图互相矛盾（**同一时刻**）：

| 视图 | 接口 | 结果 |
|---|---|---|
| 引擎态 | vmalert `/api/v1/alerts` | **firing** ✅ |
| 落库态 | VM `query=ALERTS` | **`[]` 恒空** ❌ |
| 送达态 | alertmanager `/api/v2/alerts` | 端口无响应 ❌ |

## 诊断

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

## 根因

1. vmalert 启动参数缺 `--remoteWrite.url` → ALERTS 只活在引擎内存里，不落库
2. compose 未定义 alertmanager → notifier 每周期 DNS 失败，且失败**不产生任何外部可见信号**

## 修复

1. `observability/docker-compose.yml` 的 vmalert.command 补一行：

   ```yaml
   - '--remoteWrite.url=http://victoriametrics:8428'
   ```

2. 新增 `observability/alertmanager.yml`（route + default receiver）+
   compose 新增 alertmanager service（镜像 `${AM_VER}`，端口 `127.0.0.1:9093:9093`，
   挂 `alertmanager-data`）。commit `ea144de` / `06e025f`。

## 验证（三点对齐，全部通过）

| 视图 | 结果 |
|---|---|
| vmalert `/api/v1/alerts` | `pending` → 跨 `for:1m` 转 firing |
| VM `ALERTS` | `alertstate: pending`，`value: 1`，`seriesFetched: 1` |
| alertmanager `/api/v2/alerts` | 收到 NodeDown，`status.state: active`，`receivers:[default]` |

## 教训

- 见 [methodology ⑦](../methodology.md)（告警三视图 ≠ 一个真源）：只看引擎态就会漏掉这条
- 见 [methodology ⑧](../methodology.md)：`.env` 里的变量若无 service 引用，就是死变量，会误导人以为功能已存在
- **"有观测能力 ≠ 有通知能力"** —— 09-26 就写过这条，这次在告警链路上再次应验

## 遗留

- `alertmanager.yml` 的 receiver 是**占位** webhook（`http://127.0.0.1:9099/empty`），未接真实通知渠道。
  ⚠️ 注意：**容器内的 `127.0.0.1` 指容器自身，不是宿主机** → 接渠道时需用服务名或 `host.docker.internal`
- `BB_VER`（blackbox-exporter）仍是死变量，服务未加
