# ADR 0004：日志采集端选用 Grafana Alloy（因 promtail 已 EOL）

- **日期**：2026-10-14
- **状态**：已采纳
- **相关**：[ADR 0003](0003-blackbox-exporter-deferred.md)（同日，另一个「先核实再决定」的例子）

## 背景

按主流教程的写法，Loki 的日志采集端默认配 **promtail**。动手前核实了一下它的维护状态，
结论是**不能用**：

| 事实 | 日期 |
|---|---|
| promtail 进入 LTS（随 Loki 3.4） | 2025-02-13 |
| **promtail 到达 EOL** —— 商业支持终止，不再有任何安全补丁或缺陷修复 | **2026-03-02** |
| promtail 从 Loki 仓库中**移除** | Loki **3.7.3** |
| Grafana Agent（Static / Flow / Operator）EOL | 2025-11-01 |

> `lambda-promtail`（AWS Lambda 版）被明确排除在该 EOL 公告之外，本决策不涉及。

这意味着一个**读遍宿主机所有日志文件、且长期持有到后端网络连接**的进程，
已经 7 个月没有上游安全路径。这类组件的危险之处恰恰在于它**不报错**：
运行表现与 EOL 前毫无差别，所以它会安静地躺在待办里，直到某天以事故的形式被发现。

## 决策

**日志采集端使用 Grafana Alloy**（Grafana 的 OpenTelemetry Collector 发行版），
版本由 `.env` 的 `ALLOY_VER` 固定（与其余镜像一样，禁用浮动标签）。

理由：

1. **它是官方唯一继任者。** Grafana Agent 与 promtail 两条线统一收敛到 Alloy ——
   这不是「另一个可选方案」，而是**唯一还有上游支持的方向**。
2. **与既有栈同源。** 本项目全栈 Grafana 系（Grafana / Loki / alertmanager），
   引入 Fluent Bit 或 Vector 等于多养一套独立生态。
3. **配置概念可迁移。** Alloy 自带 `alloy convert --source-format=promtail`，
   且 promtail 的 relabel / pipeline 概念在 Alloy 里一一对应（`loki.relabel` /
   `loki.process` / `loki.write`），不是重学一套语法。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 继续用 promtail，固定 `:3.6.7` | 采集端是**特权且持续联网**的进程，放在「无安全补丁」清单上是明确的负债；简历项目更不该如此 |
| Fluent Bit | 内存最优（空载约 20–30 MB）且有成熟 Loki 输出插件；但在 Grafana 全栈项目里引入第二套采集生态，换来的只是内存 |
| Vector | 能力最强（聚合 / 转换 / VRL），对单机 2C2G 明显过配 |
| 先只上 Loki，只用 API 推测试日志 | 能验证后端，但「集中日志」这个能力项不闭环 |

## 后果

- **代价：内存预算翻倍。** 日志层 `mem_limit` 上限从原估的 160 MB 升到 **384 MB**
  （loki 192m + alloy 192m），直接压缩 k3s 的余量。这是本决策**最主要的成本**，
  已在 [`capacity.md`](../capacity.md) 中量化。
  ⚠️ `mem_limit` 是**天花板**不是实际占用，真实值须部署后实测 ——
  在拿到实测值之前**不要把 k3s 的结论定死**。
- **镜像体积 707 MB**（Alloy）+ 159 MB（Loki），磁盘 25% → 27%，不影响「磁盘不是瓶颈」的结论。
- **Loki 3.6+ 的镜像不含 shell**：`docker exec loki sh` 会失败。
  排障判据改用 `curl http://127.0.0.1:3100/ready` 与 `docker logs loki`。
- **方法沉淀**：引入任何**采集 / 代理类**组件前，先查它的维护状态。
  这类组件「不报错、不告警」，EOL 与否从运行表现上完全看不出来。
