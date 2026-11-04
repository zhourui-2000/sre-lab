# firewalld 阻断容器间采集链路

2026-09-16。VM 与 node-exporter 正常，`up` 恒为 0；两容器同在 `observability_default` 网络，停 firewalld 后 `up` 变 1（对照组）。根因：firewalld 拦截容器间转发。

## 修复

```bash
firewall-cmd --permanent --zone=trusted --add-source=172.16.0.0/12
```

09-26 同构：加固后须验监控链路（见 [methodology ①②⑥](../methodology.md)）。
