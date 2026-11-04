# ADR 0005：blackbox-exporter 放 docker compose，不进 k3s

- **日期**：2026-10-19
- **状态**：已采纳
- **相关**：[ADR 0003](0003-blackbox-exporter-deferred.md)、[`docs/slo.md`](../slo.md)、[methodology ⑧](../methodology.md)

## 背景

ADR 0003 的三条推迟理由（无消费方、hairpin NAT 不确定、不塞进收口）现在都变了：

| 前提 | 现状 |
|---|---|
| 消费方 | SLI 即外部拨测成功率，与 `observability/slo-rules.yml` 同批提交 |
| hairpin NAT | 实测通：拨自己域名 301 / 0.090s，与外部一致 |
| 探针落点 | `/healthz` 已在规范化入口可用（`ae85985`） |

## 决策

在 `observability/docker-compose.yml` 中作为一个服务，与 VM / vmalert / Loki 同级，不进 k3s。

| 细节 | 取值 | 理由 |
|---|---|---|
| 模块命名 | `http_2xx` / `http_2xx_follow` | 不同入口结果不同，按期望分组复用 |
| 证书校验 | `insecure_skip_verify: true` + 独立证书告警 | 混进 `probe_success` 会互相掩盖 |
| SLI 目标 | 只有 `https://裸域/healthz` | 多目标混算无法归因 |

## 候选方案

| 方案 | 优点 | 否决理由 |
|---|---|---|
| **docker compose（采纳）** | 同网络运维；约 20 MB，`mem_limit` 一行；与 k3s 故障域分离 | 无 |
| k3s Deployment（`k8s/`） | 演示 k8s | 2G 机已到边界：ArgoCD 后 available 338 MB、swap 550 MB，3 倍；探针在被测平台里难归因 |
| 外部探针（GitHub Actions） | 真正端到端 | 需结果回传通道，本轮不做，记在 `baseline.md` |

## 后果

- `.env` 重现 `BB_VER=v0.29.0`，非死变量（compose 有引用）。判据：变量数 == 引用数 == 7。

- 新服务一律 `ports: 127.0.0.1:*`。

- 偏差写进 `slo.md`：服务内部可用性 SLI，不许说成「外网 100% 可用」。

- `mem_limit: 48m`（空载约 20 MB，2× 余量）；实测 `scripts/check-mem-budget.py` 采 cgroup `memory.current`。

- k3s 侧要探针则新起实例，不搬它。
