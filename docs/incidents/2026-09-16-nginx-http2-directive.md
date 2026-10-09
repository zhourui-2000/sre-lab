# nginx http2 指令版本不兼容

- **日期**：2026-09-16
- **影响**：web 容器崩溃循环，`nginx: [emerg] unknown directive "http2"`
- **一句话结论**：用了 `http2 on;`（需 nginx 1.25.1+），而镜像实际为旧版

## 修复

- 改用兼容写法 `listen 443 ssl http2;`
- **根因中的根因**：使用了 `nginx:alpine` 浮动标签，**版本不可控**
- 措施：锁定为 `nginx:1.24-alpine`，杜绝同类问题

## 教训

**浮动标签 = 版本不可控。** 生产镜像一律固定版本标签（见 [baseline 不变量](../baseline.md)）。
