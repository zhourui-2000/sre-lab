# ADR 0005：blackbox-exporter 放 docker compose，不进 k3s

- **日期**：2026-10-19
- **状态**：已采纳
- **相关**：[ADR 0003](0003-blackbox-exporter-deferred.md)（本 ADR 解除它的"暂缓"）、
  [`docs/slo.md`](../slo.md)、[methodology ⑧](../methodology.md)（死变量会让人以为功能已存在）

## 背景

ADR 0003 把 blackbox-exporter 推迟到 Week 5-6，理由有三条：
没有消费方、自拨公网存在 hairpin NAT 不确定性、不该塞进收口轮次。

现在三个前提都变了：

1. **有了消费方**：SLO 阶段要的 SLI 就是"外部拨测成功率"，
   本 ADR 与 `observability/slo-rules.yml` **同批提交**（ADR 0003 明确要求的）。
2. **hairpin NAT 已实测通**：服务器拨自己域名返回 301 / 0.090s，与外部行为一致。
3. **`/healthz` 已在规范化入口上可用**（`ae85985`）—— 探针不会建在一个 404 上。

剩下要决定的是：**它跑在哪。**

## 决策

**作为 `observability/docker-compose.yml` 里的一个服务，与 VM / vmalert / Loki 同级。
不进 k3s。**

同时确定三个实现细节：

| 决策 | 取值 | 理由 |
|---|---|---|
| 模块按期望命名 | `http_2xx` / `http_2xx_follow` | 同一域名不同入口的正确结果不同；按期望分组，规则可复用 |
| 证书校验 | `insecure_skip_verify: true` + 独立证书告警 | 证书与服务是两种故障，混在一个 `probe_success` 里会互相掩盖 |
| 参与 SLI 的目标 | 只有 `https://裸域/healthz` 一个 | 多目标混算 → 烧钱率无法归因，也无法回答"是哪条路径坏了" |

## 候选方案

| 方案 | 优点 | 否决理由 |
|---|---|---|
| **docker compose（采纳）** | 与现有可观测栈同网络、同套运维动作；一个服务 ≈20 MB，`mem_limit` 一行动作；探针与"被测物"（k3s 承载的应用）故障域分离 | — |
| k3s Deployment（`k8s/` 下） | 演示 k8s 部署 | ① **2G 机已到边界**：ArgoCD 落地后 available 338 MB、swap 550 MB（唯一持续恶化项），再加一个被 kubelet 管的组件，真实成本是 Pod 占用的 ≈3 倍；② **测量点会被污染**：探针跑在 k3s 里，它报"失败"时分不清是站点坏了还是 k3s 自己坏了——**用被测平台测量被测平台**，故障归因从第一天起就是糊的 |
| 纯外部探针（GitHub Actions 定时 curl） | 真正的端到端视角 | 需要额外的结果回传通道（推 VM 或站内 API），本轮不做；记在 `baseline.md` 待补基线 |

## 后果

- `.env` 重新出现 `BB_VER=v0.29.0`。**这次它不是死变量** —— compose 里有 service 引用它。
  这正是 ADR 0003 想达到的状态：变量存在的前提是有消费方。
  （判据仍然成立：`.env` 里的变量数 == compose 里被引用的变量数 == 7。）
- 新增服务一律 `ports: 127.0.0.1:*`，符合"端口一律绑回环"的不变量。
- **测量点偏差被写进 `slo.md`**：这是"服务内部可用性"SLI，不是端到端 SLI。
  不许在汇报里把它说成"外网 100% 可用"。
- 内存：`mem_limit: 48m`（Go 程序空载约 20 MB，2× 余量）。
  实测值用 `scripts/check-mem-budget.py` 采，与其它容器同一口径（cgroup `memory.current`）。
- 若将来 k3s 侧也需要探针（例如 Ingress 黑白盒），**新起一个实例**，
  不要把 compose 这个搬进去 —— 两者回答的问题不同。
