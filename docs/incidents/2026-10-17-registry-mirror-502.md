# 2026-10-17 · 镜像源间歇 502 导致 ArgoCD 装不上

## 背景

Week 4 引入 ArgoCD（GitOps）。按 A 方案精简部署：k3s 内、命名空间 `argocd`、
关 dex / notifications、`applicationSet.replicas: 0`、ClusterIP + 两层端口转发。

安装方式：Helm chart `argo-cd` 10.10.5（appVersion v3.5.5），sha256 钉死。

## 现象

`helm upgrade --install --wait --timeout 12m` 跑满 12 分钟超时，release 变 `failed`：

```
STATUS: failed
REVISION: 1
DESCRIPTION: Release "argocd" failed: context deadline exceeded
```

4 个常驻工作负载里 **3 个 Running，只有 `argocd-redis` 一直 `ImagePullBackOff`**：

```
Warning  Failed  pod/argocd-redis-85c9fff869-4w559
  Failed to pull image "docker.io/library/redis:8.6.4-alpine":
  failed to copy: httpReadSeeker: failed open: unexpected status from GET request to
  https://docker.m.daocloud.io/v2/library/redis/blobs/sha256:064995e374e6... — 502 Bad Gateway
```

## 诊断

### 一、先排除"是不是网络/配置问题"

| 镜像 | 走的 mirror | 结果 |
|---|---|---|
| `quay.io/argoproj/argocd:v3.5.5`（222 MB） | `quay.m.daocloud.io` | **一次拉成** |
| `docker.io/library/redis:8.6.4-alpine` | `docker.m.daocloud.io` | **3 个 layer blob 全部 502** |

同一时段、同一台机器、同一份 `registries.yaml` —— 一个通一个不通。
**所以不是网络、不是 DNS、不是配置拼错，是 daocloud 的 docker.io 端点单独出问题。**

### 二、`/v2/` 连测 5 次

```
第 1 次: 502      第 4 次: 502
第 2 次: 401      第 5 次: 401
第 3 次: 401
```

**间歇性 502**（5 次里 2 次）。containerd 恰好在那几次失败的请求里取 blob，
于是退避重试 12 分钟（21 次）都没成功。

### 三、换哪个 mirror？—— 探活接口给出的是错误答案

只看 `GET /v2/` 的返回码会得出完全错误的结论，因为：

- `401` 是**正常的匿名响应**（"请先取 token"），不是故障；
- `502` 也可能只影响探活路径，不影响 blob 交付。

所以走**完整的 token 流程**（`/v2/` → `WWW-Authenticate` → 取 token → manifest → 真下一层 blob）：

| mirror | `/v2/` | manifest | blob（真下载） |
|---|---|---|---|
| `docker.m.daocloud.io` | 502 / 401 抖动 | 401（需 token） | ❌ **502** |
| `docker.1ms.run` | 401 | 200 ✅ | ❌ 读超时 |
| `hub.rat.dev` | 302 | 200 ✅ | ❌ 读超时 |
| **`dockerproxy.net`** | **502** | 200 ✅ | ✅ **7/7 层，32.9 MB** |

`dockerproxy.net` 逐层实测：

```
1/7  e6f31ffc  3.67 MB   5.5s   ✅
2/7  27462c3a  0.00 MB   1.1s   ✅
3/7  064995e3  0.19 MB   5.1s   ✅
4/7  7fd2b918 29.02 MB  15.0s   ✅   ← 最大层，≈1.9 MB/s
5/7  74788a58  0.00 MB   1.0s   ✅
6/7  4f4fb700  0.00 MB   1.2s   ✅
7/7  c0241ea5  0.00 MB   0.9s   ✅
```

> **两个方向都被探活骗了**：`dockerproxy.net` 的 `/v2/` 是 502 却功能完好；
> `daocloud` 的 `/v2/` 常回 401 却拉不动 blob。
> **探活只证明"端点活着"，不证明"你的用途可行"。**

## 根因

**在 `registries.yaml` 里给 `docker.io` 只配了一个 mirror，等于把整个集群的拉镜像能力
绑在单一服务的可用性上。** 那个服务一旦抖动，拉取就失败 —— 而我们此前没有任何兜底。

这不是"配置写错了"，而是**依赖的可靠性没有被当成配置来对待**。

## 修复

`ansible/roles/k3s/files/registries.yaml`：`docker.io` 的 `endpoint` 改为两条，顺序即优先级：

```yaml
mirrors:
  docker.io:
    endpoint:
      - "https://dockerproxy.net"        # 实测可完整交付，放第一位
      - "https://docker.m.daocloud.io"   # 保留兜底（它通常更快）
```

**没有改 `values.yaml` 里的镜像地址**（如 `dockerproxy.net/library/redis:8.6.4-alpine`）——
那会把代理域名焊进清单，换源即失效。**镜像源的事在镜像源那一层解决，而那一层本来就在 IaC 里。**

## 验证

| 判据 | 结果 |
|---|---|
| playbook | `changed=1`（只有 registries.yaml 那一个任务变） |
| **`certs.d/docker.io/hosts.toml`** | **2 个 host**，`dockerproxy.net` 在前 —— 判据必须落在这里，不是源文件 |
| helm release | `REVISION 2 / deployed`（rev1 变 `superseded`） |
| Pod | 4 个常驻全 `1/1 Running` |
| 站点 | `/healthz` 200、`/` 301 —— 重启 k3s 未影响业务 |

## 教训

### ① 依赖的可用性要当成配置来管

单点 mirror = 单点故障。**判据是"被依赖方抖动时还能不能干活"，不是"当前它能不能通"。**

而在网络不稳的环境里，**sha256 钉死才是敢用镜像/代理的前提**：
判据是"校验和一致"，不是"域名可信"。反过来说，如果只能靠信任域名才敢用，
就永远不敢走代理，也就会一直被 8 KB/s 卡住。

### ② 探活 ≠ 用途

`/v2/` 是 registry 的探活接口，blob 才是业务路径。二者的结论可以完全相反。
**要有一步"真下一层"的验证**（就像验证 `ansible.cfg` 要跑 playbook，
验证 `registries.yaml` 要看 `hosts.toml` 而不看源文件）。

### ③ 一个"看着像装到一半失败"的错误，其实是前置条件没满足

`helm --wait` 等到最后才报错，而 chart 下载、sha256、渲染预检全都过了 ——
看起来像"装到一半炸了"。实际是**镜像拉不到**。
→ 已在 `scripts/install-argocd.sh` 里补了安装**前**的集群连通性预检，
把"连不上"挡在下载和渲染之前。

### ④ 顺带发现的同类问题：helm 不会继承 k3s 的 kubeconfig

`k3s kubectl` 自带配置所以一直能连；`helm` 走标准发现流程，找不到就退回 `localhost:8080`，
报 `Kubernetes cluster unreachable: dial tcp [::1]:8080`。
**"我用 kubectl 试过是好的"证明不了 helm 也能连** —— 两个工具找配置的路径不同。
已把 `export KUBECONFIG=/etc/rancher/k3s/k3s.yaml` 写进安装脚本（见 `baseline.md` 环境前提）。

## 遗留

- `quay.io` / `ghcr.io` 目前只有单一 mirror，**同类风险仍存在**。等真正踩到再补，
  避免在没依据的情况下加配置。
- daocloud 恢复后是否把顺序调回去：应该是一次**带实测数据**的提交，不是为了"好看"。
- `dockerproxy.net` 不保证长期可用 —— 因为它不被信任所依赖，而是靠 sha256 校验，
  所以换掉它只需改一行，不构成风险。
