# SRE Lab

单台 2核2G / 40G 云服务器上的 SRE 实践环境：
配置即代码（Ansible）+ 容器化交付 + 可观测性 + 告警治理 + 灾备演练。

## 这机器要做什么

把「运维」从手工操作变成可复现的代码：安全基线、配置即代码、
可观测与告警闭环、以及「删掉整机也能重建」的灾备验证。

## 环境

- 云主机：Alibaba Cloud Linux 3.2104（2核2G / 40G）
- 控制端：WSL2 Ubuntu 22.04.1 + Ansible（`ansible-core 2.17.14`，Python 3.10.6）
  > ⚠️ 版本会漂移：**ansible-core ≥2.18 要求控制端 Python ≥3.11**，Ubuntu 22.04 自带的 3.10 装不了。
  > 重建控制端后须重新确认版本，并**先做权限收敛** —— 跨文件系统拷贝会留下 `0777`，
  > Ansible 会因此**静默忽略** `ansible.cfg`
  > （见 [incidents/2026-10-14](docs/incidents/2026-10-14-migration-perms-ansible-cfg.md)）。
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
  journald + docker logs ──► Alloy ──► Loki:3100 ──► Grafana:3000
```

## 目录说明

```text
ansible/       主机配置即代码（base：swap/sysctl/journald/docker；security：sshd/fail2ban/firewalld）
nginx/         业务站点（容器化，配置与静态资源）
observability/ 可观测栈（VictoriaMetrics / Grafana / vmalert / alertmanager / 告警规则）
               └─ grafana/  数据源与面板**代码化**（provisioning，容器重建后自动恢复）
docs/          基线、方法论、runbook、故障复盘、ADR
scripts/       运维核对工具（只读）；check-fw-drift.py 检查服务器是否偏离 IaC 声明
```

## 一键复现

```bash
# 控制端若为新迁移 / 重建的，先做权限收敛与配置读取确认（见 docs/runbook.md）
find /root/sre-lab -perm -o+w | wc -l   # 期望 0；非 0 则 chmod -R go-w /root/sre-lab
ansible --version | grep 'config file'  # 必须指向本仓库的 ansible.cfg，否则配置根本没被加载

cd ansible
ansible lab -m ping              # 测试连通
ansible-playbook site.yml        # 应用主机配置
 > 例外：observability/alertmanager.yml 含 SMTP 授权码，不入库；
 > 新环境需 cp alertmanager.yml.example alertmanager.yml 后填入授权码。
 > 文件权限必须是 644（容器以 nobody 运行，写 600 会 crash loop —— 见 docs/adr/0002）。
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
   - [x] 日志 —— **Loki 3.7.8 + Alloy v1.20.1**，两类来源（journald / docker）端到端验证通过
        （采集端因 promtail EOL 改用 Alloy，见 ADR 0004；磁盘稳态 ~126 MB / 7 天）
- [ ] Week 3-4  k3s + GitOps 交付链路
- [ ] Week 5-6  SLO 与告警治理
- [ ] Week 7  韧性演练与灾备验证
- [ ] Week 8  材料化
