
---

## 实测修正（2026-09-12）

原假设"磁盘最易被打满"**不成立**：实测磁盘仅 19%，journald 限额后仅占 32M。
**真实瓶颈是内存**：总量 1870MB，加固后可用 1399MB。

## k3s 决策规则（Day 6 后执行）

部署完可观测栈后重测 `free -m` 的 available：

| 可用内存 | 决策 |
|---|---|
| ≥ 800MB | 上 k3s，关闭内置 traefik / servicelb / metrics-server |
| 600–800MB | 上 k3s，同时 Grafana 降至 192m、VM retention 压至 15 天 |
| < 600MB | **放弃 k3s，全线 Docker Compose** |

第三种情况需在文档中记录判断依据——"实测后论证不可行"本身即是有效工程决策。
