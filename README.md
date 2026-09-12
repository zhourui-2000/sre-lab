# SRE Lab

在单台 2核2G / 40G 云服务器上搭建的 SRE 实验平台：
GitOps 交付 + 可观测性 + 告警治理 + 灾备演练。

## 环境

- 云主机：Alibaba Cloud Linux 3.2104（2核2G / 40G）
- 控制端：WSL2 Ubuntu 24.04 + Ansible
- 容器运行时：Docker（overlay2 + 日志轮转）

## 目录结构
ansible/       主机配置即代码（base：swap/sysctl/journald/docker，security：fail2ban/firewalld）

nginx/         业务站点（容器化）

observability/ 可观测栈

docs/          容量预算、基线数据、演练记录、故障复盘
## 快速开始
bash

cd ansible

ansible lab -m ping              # 测试连通

ansible-playbook site.yml        # 应用配置
配置已完成幂等化验证：连续执行两次，第二次 `changed=0`。

## 进度

- [x] Week 1: 系统基线、安全加固、配置即代码
- [ ] Week 2: 可观测栈（指标 / 日志 / 告警）
- [ ] Week 3-4: k3s + GitOps 交付链路
- [ ] Week 5-6: SLO 与告警治理
- [ ] Week 7: 韧性演练与灾备验证
- [ ] Week 8: 材料化
