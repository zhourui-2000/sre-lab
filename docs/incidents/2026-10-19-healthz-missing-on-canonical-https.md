# 2026-10-19 · 健康检查在规范化 HTTPS 入口上返回 404

Week 5-6 起步做 SLO，第一步是外部拨测。ADR 0003 曾因「回环 NAT 不确定」暂缓 blackbox，10-19 实测：服务器到 `https://www.zhourui2000.online/` 301 / 0.090s，本机同一 URL 301 / 0.468s，回环 NAT 通。

## 现象

| 入口 | 状态 |
|---|---|
| `http://zhourui2000.online/healthz` | 200 ✅ |
| `http://www.zhourui2000.online/healthz` | 200 ✅ |
| `https://zhourui2000.online/healthz` | 404 ❌ |
| `https://www.zhourui2000.online/healthz` | 301/404 |
| `https://zhourui2000.online/` | 200 ✅ |

## 根因

`nginx/conf.d/default.conf` 三个 server 块的 location 集合不一致：

| server 块 | `/healthz` | acme | `location /` |
|---|---|---|---|
| `:80`（裸域 + www） | ✅ `location = /healthz` | ✅ | `return 301` 到 https 裸域 |
| `:443` www | ❌（server 级 `return 301`） | ❌ | — |
| `:443` 裸域 | ❌ | ❌ | `try_files $uri $uri/ =404` |

`http://…/healthz` 命中 `:80` 精确匹配得 200；`https://…/healthz` 落到 443 裸域块，`try_files` 找 `html/healthz` 不存在，404。该端点只为容器 healthcheck 用（`wget http://127.0.0.1/healthz`），一直只在 `:80` 验。

## 修复

在 `:443` 裸域 server 块补精确匹配，放在 `location /` 之前：

```nginx
location = /healthz {
    access_log off;
    return 200 "ok\n";
}

location / {
    try_files $uri $uri/ =404;
}
```

不动 `:443` 的 www 块：`return` 301 在 `server` 级，`server`-rewrite 阶段在 `location` 选择之前执行，加 `location = /healthz` 不生效；www 归一本身正确，拨测直接打裸域。

不动 `:80` 的 301：`:80` 的 `/healthz` 必须保留 200（容器 healthcheck 依赖），其 `return 301` 在 `location /` 里，精确匹配能覆盖。

## 判据

`scripts/check-endpoints.py`：7 个入口 × 两个判据（首跳 + 跟随后的终态）。修复前 2/7 不符合：

```text
http 裸域 /healthz   200  200   —        ✅
http www  /healthz   200  200   —        ✅
https 裸域 /healthz  404  200   —        ❌
https www /healthz   301  301   404(期望200) ❌
…（其余 3 个 ✅）
```

修复后 7/7。reload 前先用 nginx 官方镜像跑 `nginx -t`（挂临时自签证书）：`nginx -s reload` 遇语法错误会保留旧配置继续跑，不验证会得到「reload 成功但没生效」。

## 另两处

历史验证全是单点：`docker exec web wget http://127.0.0.1/healthz` 200、`curl http://127.0.0.1/healthz` 200、`curl -k https://127.0.0.1/healthz` 301（无 SNI，落默认块）都被当成正常，没有一次用真实域名走 https。

`/healthz` 只服务容器 healthcheck（`:80` 本机可达）；当外部可用性信号时，判据必须走外部真实路径。

## 遗留

本记录只覆盖健康检查端点；证书有效性、TLS 版本、跳转链长度未纳入矩阵，留给 SLO/SLI 设计。`https://www…/healthz` 仍是 301（有意，www 是纯跳转层），拨测若选它必须跟随重定向，要写进 SLI 定义。
