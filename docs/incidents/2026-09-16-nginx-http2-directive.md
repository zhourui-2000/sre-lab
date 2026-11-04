# nginx http2 指令版本不兼容

2026-09-16。web 容器崩溃循环：`nginx: [emerg] unknown directive "http2"`。`http2 on;` 需 nginx 1.25.1+，`nginx:alpine` 浮动标签给的是旧版。

## 修复

改用 `listen 443 ssl http2;`，镜像锁定 `nginx:1.24-alpine`。见 [baseline](../baseline.md)。
