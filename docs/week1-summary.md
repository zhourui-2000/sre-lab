# 第一周总结

## 交付

- 安全基线：密钥认证 + 端口收敛 + fail2ban + firewalld
- 配置即代码：base / security / web 三个角色，幂等性验证通过
- 站点容器化 + 域名 HTTPS（自动续期）
- 可观测栈：VictoriaMetrics + node-exporter + Grafana

## 关键决策

1. **磁盘不是瓶颈**：实测仅 19%，原"日志治理"假设不成立，改聚焦内存容量
2. **k3s 可行**：可观测栈实测仅 230MB（预估 576MB），部署后可用 1143MB
3. **镜像不走 Git**：构建产物归 Registry，代码归 Git

## 故障记录

见 docs/baseline.md，共 5 起，均已定位根因并修复。
