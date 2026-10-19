# 2026-10-19 · 健康检查在规范化 HTTPS 入口上返回 404

## 背景

准备进入 Week 5-6（SLO 与告警治理）。SLO 的第一步是**外部拨测**：
从外部周期性请求站点的健康检查端点，把结果变成可用性指标。

ADR 0003 当初把 blackbox-exporter 暂缓，理由之一是「从 ECS 拨自己的公网 IP 存在回环 NAT 不确定性，
得先做受控实验」。2026-10-19 把实验做了：

```
服务器 → https://www.zhourui2000.online/   301   0.090s
本机   → 同一个 URL                       301   0.468s
```

**回环 NAT 是通的** —— 拨测方案的前提成立。

## 现象

顺手把每个入口的 `/healthz` 都打了一遍，结果不一致：

| 入口 | 状态 |
|---|---|
| `http://zhourui2000.online/healthz` | **200** ✅ |
| `http://www.zhourui2000.online/healthz` | **200** ✅ |
| `https://zhourui2000.online/healthz` | **404** ❌ |
| `https://www.zhourui2000.online/healthz` | 301 → `https://zhourui2000.online/healthz` → **404** |
| `https://zhourui2000.online/` | 200 ✅ |

## 根因

`nginx/conf.d/default.conf` 里三个 server 块的 location 集合**不一致**：

| server 块 | 有 `/healthz` 吗 | 有 acme 吗 | `location /` 干什么 |
|---|---|---|---|
| `:80`（裸域 + www） | ✅ `location = /healthz` | ✅ | `return 301` 到 https 裸域 |
| `:443` www | ❌（server 级 `return 301`） | ❌ | — |
| `:443` 裸域 | **❌** | ❌ | `try_files $uri $uri/ =404` |

所以：

1. `http://…/healthz` 命中的是 `:80` 那个精确匹配 → 200。
2. `https://…/healthz` 进入 443 裸域块，`try_files` 找 `html/healthz` 文件 → 不存在 → **404**。

**`:80` 有、`:443` 没有** —— 而这个端点当初是为了让容器 healthcheck 用的
（`wget http://127.0.0.1/healthz`），一直只在 `:80` 上验，所以从没暴露。

## 为什么之前一直"看着是好的"

所有历史验证都是**单点验证**：

- `docker exec web wget http://127.0.0.1/healthz` → 200
- `curl http://127.0.0.1/healthz` → 200
- `curl -k https://127.0.0.1/healthz` → **301**（无 SNI，落到默认块）——当时解释为"正常"

**没有一次是`用真实域名走 https 打的。** 而用户和外部拨测走的恰恰是那条路。

> 这是「判据覆盖不全」的又一实例：**判据没错，但它只覆盖了一个入口。**
> 单点通过会被读成"服务健康"，而真正的访问路径是坏的。

## 修复

在 `:443` 裸域 server 块里补一个精确匹配，放在 `location /` 之前：

```nginx
location = /healthz {
    access_log off;
    return 200 "ok\n";
}

location / {
    try_files $uri $uri/ =404;
}
```

**为什么不动 `:443` 的 www 块**：它的 `return 301` 写在 **server 级**，
nginx 的 server-rewrite 阶段在 location 选择**之前**执行 ——
在那里加 `location = /healthz` 不会生效。而 www→裸域的归一本身是正确行为，
所以只保证"规范化之后的那个入口"健康即可；拨测应直接打裸域（不产生跳转）。

**为什么不顺手把 `:80` 的 301 也改了**：`:80` 的 `/healthz` 必须保留 200（容器 healthcheck 依赖它），
而它的 `return 301` 写在 `location /` 里（location 级），所以精确匹配能覆盖它 —— 现状是对的。

## 验证

新增 `scripts/check-endpoints.py`：**7 个入口 × 两个判据**（第一跳状态 + 跟随重定向后的终态）。

**修复前**（补丁之前实测）：

```
  http 裸域 /healthz    200  200   —      ✅
  http www  /healthz    200  200   —      ✅
  https 裸域 /healthz   404  200   —      ❌
  https www /healthz    301  301   404(期望200) ❌
  …（其余 3 个 ✅）
→ ❌ 2/7 个入口不符合预期
```

**修复后**（预期）：7/7 ✅。

另一步关键验证：**用 nginx 官方镜像先跑 `nginx -t`**（挂临时自签证书），
确认语法通过再 reload —— 因为 `nginx -s reload` 在语法错误时**会保留旧配置继续跑**，
不验证就会得到"reload 成功但没生效"的假象。

## 教训

### ① 一个服务有几个入口，就有几套判据

同一份配置里，`:80` 和 `:443`、裸域和 www，**location 集合可以完全不同**。
单点验证通过只说明"那个入口通"，不说明"服务健康"。

**矩阵化验证**才是有意义的判据 —— 这也是新工具存在的理由：
把入口清单写进代码，任何人任何时候跑一次就知道有没有缺口。

### ② `server` 级 `return` 会先于 `location` 执行

想在"整块 301 的 server"里开一个例外，靠 `location` 是做不到的
（server-rewrite 阶段在 location 选择之前）。要么把 `return` 移进 `location /`，
要么接受这一层就是纯跳转。

### ③ 为了通过某个工具而生的端点，不一定是给用户/拨测用的

`/healthz` 最初是给容器 healthcheck 用的（只需 `:80` 本机可达）。
一旦要拿它当**外部可用性信号**，判据就变了：必须走**外部真实访问路径**。
**端点的用途变了，验证方式也要跟着变。**

## 遗留

- 本记录只覆盖"健康检查端点"。**证书有效性、TLS 版本、跳转链长度**没有纳入矩阵 ——
  这些属于可用性之外的维度，留给 Week 5-6 的 SLO/SLI 设计一并考虑。
- `https://www…/healthz` 仍是 301（不是 200）。这是**有意的**：www 是纯跳转层。
  但拨测若选它，就必须"跟随重定向"，否则会误判为不可用 ——
  这个选择要写进 SLI 定义，而不是靠人记住。
