# Docker Hub 不可达

2026-09-14。`docker compose up -d` 拉 grafana / victoriametrics 超时。node-exporter（quay.io）成功、grafana（docker.io）失败，Hub 单独被限。第三方源报 `denied: You may not login yet`。

## 修复

`docker save`、scp、`docker load`；09-24 改用前缀：

```bash
docker pull docker.m.daocloud.io/library/nginx:1.24-alpine
docker tag  docker.m.daocloud.io/library/nginx:1.24-alpine nginx:1.24-alpine
```

Registry 受限，产物不入库（[09-16 tar](2026-09-16-image-tar-in-git.md)、[baseline](../baseline.md)）。
