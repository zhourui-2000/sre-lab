# SRE Lab

单台 2核2G / 40G 云服务器上的 SRE 实践环境：
配置即代码（Ansible）+ 容器化交付 + 可观测性 + 告警治理 + 灾备演练。

## 这机器要做什么

把「运维」从手工操作变成可复现的代码：安全基线、配置即代码、
可观测与告警闭环、以及「删掉整机也能重建」的灾备验证。

## 环境

- 云主机：Alibaba Cloud Linux 3.2104（2核2G / 40G）
- 控制端：WSL2 Ubuntu + Ansible
- 容器运行时：Docker（overlay2 + 日志轮转）

## 架构

```text
Internet
   │  80 / 443
   ▼
[web: nginx 1.24]──┬─ 静态站点（dtb / story）
                   └─ Let's Encrypt（自动续期 cron）
   ▲
   │ 127.0.0.1:2222（密钥认证 + fail2ban + firewalld）
控制端 WSL ── Ansible ──► 主机配置
                  └─ relay 中转 ──► GitHub

可观测栈（全部收口 127.0.0.1）
  node-exporter:9100 ──► VictoriaMetrics:8428 ──► Grafana:3000
                                 └─► vmalert:8880 ──► alertmanager:9093 ──► 邮件
```

## 目录说明

```text
ansible/       主机配置即代码（base：swap/sysctl/journald/docker；security：sshd/fail2ban/firewalld）
nginx/         业务站点（容器化，配置与静态资源）
observability/ 可观测栈（VictoriaMetrics / Grafana / vmalert / alertmanager / 告警规则）
docs/          基线、方法论、runbook、故障复盘、ADR
```

## 一键复现

```bash
cd ansible
ansible lab -m ping              # 测试连通
ansible-playbook site.yml        # 应用主机配置
 > 例外：observability/alertmanager.yml 含 SMTP 授权码，不入库；
 > 新环境需 cp alertmanager.yml.example alertmanager.yml 后填入授权码（600 权限）。
```

幂等验证：连续执行两次，第二次 `changed=0`。

## 密钥与敏感文件（不入库）

| 文件 | 位置 | 权限 | 说明 |
|---|---|---|---|
| Ansible inventory（含服务器地址） | 控制端 `~/.sre-lab-secrets/hosts.ini` | — | 仓库只留 `hosts.example.ini` |
| alertmanager 配置（含 SMTP 授权码） | **服务器** `/root/.sre-lab-secrets/alertmanager.yml` | 目录 `700` / 文件 **`644`** | 仓库只留 `observability/alertmanager.yml.example` |

> **为什么 alertmanager 配置是 `644` 而不是 `600`？**
> 容器以 `nobody` 运行，`600 + root:root` 会让它读不到配置而 crash loop。
> 保护来自**目录不可穿越**（`/root` 750 + 密钥目录 700），可读性来自 644。决策全文见
> [`docs/adr/0002-secret-file-permissions.md`](docs/adr/0002-secret-file-permissions.md)。
>
> ⚠️ **新环境部署时**：`cp observability/alertmanager.yml.example /root/.sre-lab-secrets/alertmanager.yml`
> → 填入授权码 → `chmod 644` → `docker compose up -d --force-recreate alertmanager`。

## 文档结构

- [`docs/baseline.md`](docs/baseline.md) —— 当前已知良好状态与不变量
- [`docs/methodology.md`](docs/methodology.md) —— 经验规则（编号持续增加）
- [`docs/runbook.md`](docs/runbook.md) —— 症状 → 定位命令 → 修复
- [`docs/incidents/`](docs/incidents/) —— 每起故障一份
- [`docs/adr/`](docs/adr/) —— 设计决策记录

## 项目进度

- [x] Week 1  系统基线、安全加固、配置即代码
- [x] Week 2  可观测栈
   - [x] 指标 —— node-exporter → VictoriaMetrics → Grafana
   - [x] 告警 —— 4 条规则端到端验证（检测 / 落库 / 送达 / 通知四环）+ 邮件通知
   - [ ] 日志 —— 集中日志（Loki）未做；当前仅 journald 500M 限额 + docker 日志轮转- [ ] Week 3-4  k3s + GitOps 交付链路
- [ ] Week 5-6  SLO 与告警治理
- [ ] Week 7  韧性演练与灾备验证
- [ ] Week 8  材料化
