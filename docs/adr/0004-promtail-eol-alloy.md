# ADR 0004：日志采集端选用 Grafana Alloy（因 promtail 已 EOL）

- **日期**：2026-10-14
- **状态**：已采纳
- **相关**：[ADR 0003](0003-blackbox-exporter-deferred.md)（同日）

## 背景

promtail 是教程默认，核实后不可用：

| 事实 | 日期 |
|---|---|
| promtail 进入 LTS（随 Loki 3.4） | 2025-02-13 |
| promtail EOL，商业支持终止，无安全补丁 | 2026-03-02 |
| promtail 从 Loki 仓库移除 | Loki 3.7.3 |
| Grafana Agent（Static / Flow / Operator）EOL | 2025-11-01 |

`lambda-promtail` 不在该 EOL 公告内。promtail 读遍宿主日志、长期连后端，已 7 个月无安全路径；且不报错，表现与 EOL 前无异，会躺成事故。

## 决策

采集端用 Grafana Alloy（OpenTelemetry Collector 发行版），版本由 `.env` 的 `ALLOY_VER` 固定。

| 理由 | 说明 |
|---|---|
| 官方唯一继任者 | Agent 与 promtail 两线收敛到 Alloy |
| 与栈同源 | 全栈 Grafana 系（Grafana / Loki / alertmanager） |
| 配置可迁移 | `alloy convert --source-format=promtail`；relabel / pipeline 对应 `loki.relabel` / `loki.process` / `loki.write` |

## 被否方案

| 方案 | 理由 |
|---|---|
| 继续 promtail，固定 `:3.6.7` | 特权且联网，无补丁即负债 |
| Fluent Bit | 内存优（空载 20–30 MB），但多一套生态 |
| Vector | 能力最强，对 2C2G 过配 |
| 只上 Loki，API 推日志 | 后端可验，「集中日志」不闭环 |

## 后果

- 内存翻倍：日志层 `mem_limit` 从 160 MB 升到 **384 MB**（loki 192m + alloy 192m），压缩 k3s 余量，见 [`capacity.md`](../capacity.md)。`mem_limit` 是天花板，须实测后再定 k3s 结论。

- 镜像 707 MB（Alloy）+ 159 MB（Loki），磁盘 25% 到 27%，不影响「磁盘不是瓶颈」。

- Loki 3.6+ 无 shell，`docker exec loki sh` 失败；改用 `curl http://127.0.0.1:3100/ready` 与 `docker logs loki`。

- 采集 / 代理类组件上线前先查维护状态，EOL 从表现看不出。
