# SRE Lab

单台 2核2G / 40G 云服务器上的 SRE 实践：Ansible 配置即代码 + 容器化交付 + 可观测 + 告警治理 + 灾备演练。

## 关键数字

| 项 | 值 |
|---|---|
| 主机 / 控制端 | Alibaba Cloud Linux 3.2104（2C/2G/40G）· WSL2 Ubuntu 22.04 + ansible-core 2.17.14 |
| 幂等 | 二次执行 `changed=0`（base / security / web） |
| 日志量 | 1.94 MB/日（37 小时实测），7 天稳态 ≈ 14 MB |
| k3s | v1.37.1 单节点，控制面 ≈620–630 MiB，冒烟零残留 |
| GitOps | ArgoCD v3.5.5，`self-heal` ≤36 s，drift 秒级纠正，真实成本 ≈ Pod 的 3 倍 |
| SLO | 99.5% / 30 天，预算 216 min（864 次探针）；烧钱率 14.4× / 6× / 1× |
| RTO | 影子 8 s / 完整 134 s（手工 98 s + 内容 36 s）/ 含排障 14 min；L4 从零拉起 339 s（含重拉 313 MB 镜像） |
| MTTR | 首次实测 n=1：MTTD **128 s** / MTTR **69 s**（2026-11-04 受控中断 197 s）；均值待 3 次样本 |

## 架构

```text
Internet ──80/443──► nginx 1.24（容器）── 静态站点 dtb / story
                                        └─ Let's Encrypt 自动续期 cron
控制端 WSL ── Ansible ──► 主机配置（base / security / web）
           └─ relay 中转 ──► GitHub

可观测（全部收口 127.0.0.1）
  node-exporter:9100 ─► VictoriaMetrics:8428 ─┬► Grafana:3000
  journald + docker logs ─► Alloy ─► Loki:3100 ┘
  VictoriaMetrics ─► vmalert:8880 ─► alertmanager:9093 ─► 邮件
  blackbox:9115 ─► VictoriaMetrics（外部拨测 = SLI）

k3s v1.37.1 单节点（cgroup v2，API 6443 不对公网开放）
  └─ ArgoCD v3.5.5（ClusterIP + port-forward）── sync ──► apps/hello
```

## 目录

| 路径 | 内容 |
|---|---|
| `ansible/` | `base`（swap / sysctl / journald / docker）、`security`（sshd / fail2ban / firewalld）、`web` |
| `nginx/` | 站点容器（配置 + 静态资源） |
| `observability/` | VM / Grafana / vmalert / alertmanager / blackbox / 规则；`grafana/` 走 provisioning |
| `k8s/` | `apps/hello`、`smoke-test/`、`argocd/` |
| `scripts/` | 只读核对：`check-fw-drift.py`、`check-mem-budget.py`、`slo-report.py`、`check-recoverability.py`、`check-endpoints.py` |
| `docs/` | 基线、方法论、runbook、复盘、ADR |

## 复现

```bash
find /root/sre-lab -perm -o+w | wc -l      # 期望 0；非 0 则 chmod -R go-w /root/sre-lab
ansible --version | grep 'config file'    # 必须指向本仓库 ansible.cfg
git config core.fileMode                  # 期望 true；false 则 chmod +x 不入索引

cd ansible && ansible lab -m ping && ansible-playbook site.yml
```

幂等：连跑两次，第二次 `changed=0`。

敏感文件不入库：`~/.sre-lab-secrets/hosts.ini`（控制端）、`/root/.sre-lab-secrets/alertmanager.yml`（服务器，目录 700 / 文件 644）。alertmanager 必须 644，因为容器以 `nobody` 运行，600 会 crash loop，见 [ADR 0002](docs/adr/0002-secret-file-permissions.md)。新环境先 `cp observability/alertmanager.yml.example` 过去，填授权码后 `docker compose up -d --force-recreate alertmanager`。

## 文档

| 文件 | 用途 |
|---|---|
| [baseline.md](docs/baseline.md) | 已知良好状态、不变量、待补基线（状态数字的唯一真源） |
| [methodology.md](docs/methodology.md) | 23 条判据规则 |
| [runbook.md](docs/runbook.md) | 症状 → 定位命令 → 修复 |
| [slo.md](docs/slo.md) | SLI / SLO / 烧钱率 / 未证事项 |
| [dr.md](docs/dr.md) | 备份恢复、L1–L4 演练 |
| [capacity.md](docs/capacity.md) | 内存与磁盘预算、实测口径 |
| [incidents/](docs/incidents/) · [adr/](docs/adr/) | 故障复盘（17 篇）· 设计决策（5 篇） |

## 已知缺口

- SLI 只覆盖 `/healthz`，不含 `/`、`/dtb/` 等真实页面路径与传输耗时。
- 内容层（`dtb/ story/ quiz/`，49 MB）不在 Git，唯一副本是 WSL 手工副本。
- 无 CI；`host_key_checking = False`；k3s 未开 `secrets-encryption`；K8s 层无告警。
