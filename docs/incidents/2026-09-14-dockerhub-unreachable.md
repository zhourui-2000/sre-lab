# Docker Hub 不可达

- **日期**：2026-09-14
- **影响**：`docker compose up -d` 拉取 grafana / victoriametrics 超时
- **一句话结论**：docker.io 单独被限，quay.io 正常；需建立自有镜像链路

## 现象与诊断

- node-exporter（quay.io）拉取成功、grafana（docker.io）失败
  → 网络整体正常，**Docker Hub 单独被限**
- 试错：第三方公共镜像源返回 `denied: You may not login yet`，**不可依赖**

## 修复

本机 `docker save` → scp → 服务器 `docker load`

## 后续（2026-09-24 更新）

改用镜像前缀更省事，免去 save/scp/load：

```bash
docker pull docker.m.daocloud.io/library/nginx:1.24-alpine
docker tag  docker.m.daocloud.io/library/nginx:1.24-alpine nginx:1.24-alpine
```

详见 [baseline 环境前提](../baseline.md)。

## 教训

- 外部 Registry 属**不可控依赖**，需建立自有镜像链路
- 镜像归档属**构建产物，不进版本控制**（后果然踩坑，见 [09-16 tar 误入 Git](2026-09-16-image-tar-in-git.md)）
