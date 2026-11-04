# ADR 0003：暂不部署 blackbox-exporter，先清除死变量

- **日期**：2026-10-14
- **状态**：已采纳（2026-10-19 解除暂缓，见 [ADR 0005](0005-blackbox-on-docker-compose.md)）
- **相关**：[methodology ⑧](../methodology.md)

## 背景

`observability/.env` 有 `BB_VER=v0.29.0`，`docker-compose.yml` 无 service 引用。

危害是误导：容易以为 blackbox-exporter 已纳入管理。10-09 故障里 `AM_VER` 同样躺了很久，而 alertmanager 根本没定义（[2026-10-09](../incidents/2026-10-09-alert-chain-silent.md)）。

## 决策

删除 `BB_VER`，本轮不部署 blackbox-exporter：

| 理由 | 事实 |
|---|---|
| 没有消费方 | 4 条规则全基于 `up{job="node"}`，无规则依赖 blackbox |
| 时机未到 | 用武之地在 Week 5-6（SLO 与告警治理），应与消费方同批引入 |
| hairpin NAT 不确定 | 从 ECS 拨自己公网 IP 未必可达，需受控实验 |

## 被否方案

| 方案 | 理由 |
|---|---|
| 直接部署，保留 `BB_VER` | 无规则消费；未验证 hairpin NAT |
| 保留 `BB_VER`，文档写未部署 | 死变量仍在，仍误导 |
| `BB_VER` 换成 `# TODO` | `.env` 不是待办清单 |

## 后果

- `.env` 每项都被引用（`VM_VER` / `NE_VER` / `AM_VER`），「变量数 == 被引用数」即可判一致。
- 引入时机记在 [baseline](../baseline.md) 的「六、待补基线」。
- 将来部署必须与消费它的告警规则同批提交，并先验证公网拨测路径。
