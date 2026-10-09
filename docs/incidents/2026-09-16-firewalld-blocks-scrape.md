# firewalld 阻断容器间采集链路

- **日期**：2026-09-16
- **影响**：VM 与 node-exporter 均正常运行，但 `up` 指标**恒为 0**（监控静默失效）
- **一句话结论**：firewalld 拦截了容器间的转发

## 现象与诊断

- 两个容器同属 `observability_default` 网络，排除网络配置问题
- **对照组定位**：停 firewalld 后 `up` 立即变 1 → 定位为防火墙拦截容器间转发

## 修复

```bash
firewall-cmd --permanent --zone=trusted --add-source=172.16.0.0/12
```

## 教训

**安全加固会改变系统行为边界**——加固后必须回归验证业务与监控链路。

这条与 09-26 的双真源事故同构：**改动之后必须有生效性验收**，
（见 [methodology ①②⑥](../methodology.md)）。
