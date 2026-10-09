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
                                 └─► vmalert:8880 ──► alertmanager:9093
```

## 目录说明

```text
ansible/       主机配置即代码（base：swap/sysctl/journald/docker；security：sshd/fail2ban/firewalld）
nginx/         业务站点（容器化，配置与静态资源）
observability/ 可观测栈（VictoriaMetrics / Grafana / 告警规则）
docs/          容量预算、基线数据、演练记录、故障复盘
```

## 一键复现

```bash
cd ansible
ansible lab -m ping              # 测试连通
ansible-playbook site.yml        # 应用主机配置
```

幂等验证：连续执行两次，第二次 `changed=0`。

> 真实 inventory 含服务器地址，不进版本控制：`~/.sre-lab-secrets/hosts.ini`。

## 文档结构

- `baseline.md` —— 当前已知良好状态与不变量（唯一真源快照）
- `methodology.md` —— 经验规则 ①–⑩
- `runbook.md` —— 症状速查
- `incidents/` —— 每起故障一份
- `adr/` —— 设计决策## 进度

## 项目进度
- [x] Week 1  系统基线、安全加固、配置即代码
- [ ] Week 2  可观测栈（指标 / 日志 / 告警）
- [ ] Week 3-4  k3s + GitOps 交付链路
- [ ] Week 5-6  SLO 与告警治理
- [ ] Week 7  韧性演练与灾备验证
- [ ] Week 8  材料化
