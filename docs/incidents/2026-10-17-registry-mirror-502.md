# 2026-10-17 · 镜像源间歇 502 导致 ArgoCD 装不上

Week 4 引入 ArgoCD：k3s 内 `argocd` 命名空间、关 dex / notifications、`applicationSet.replicas: 0`、ClusterIP + 两层端口转发；chart `argo-cd` 10.10.5（appVersion v3.5.5），sha256 钉死。

## 现象

`helm upgrade --install --wait --timeout 12m` 12 分钟超时，release 变 `failed`（`REVISION: 1`）：

```text
DESCRIPTION: Release "argocd" failed: context deadline exceeded
```

3/4 个负载 Running，`argocd-redis` 一直 `ImagePullBackOff`：

```text
Warning  Failed  pod/argocd-redis-85c9fff869-4w559
  Failed to pull image "docker.io/library/redis:8.6.4-alpine":
  failed to copy: httpReadSeeker: failed open: unexpected status from GET request to
  https://docker.m.daocloud.io/v2/library/redis/blobs/sha256:064995e374e6... — 502 Bad Gateway
```

## 诊断

同一时段、同一机器、同一份 `registries.yaml`：`quay.io/argoproj/argocd:v3.5.5`（222 MB）经 `quay.m.daocloud.io` 拉成，`docker.io/library/redis:8.6.4-alpine` 三个 blob 全 502，不是网络或配置问题。

`/v2/` 连测 5 次：401、401、502、401、502。containerd 恰在失败那几次取 blob，退避 12 分钟（21 次）仍未成功。只看 `GET /v2/` 不够（`401` 正常，`502` 也可能只影响探活），于是走完整 token 流程（`/v2/`、`WWW-Authenticate`、token、manifest、blob）：

| mirror | `/v2/` | manifest | blob（真下载） |
|---|---|---|---|
| `docker.m.daocloud.io` | 502 / 401 抖动 | 401（需 token） | ❌ 502 |
| `docker.1ms.run` | 401 | 200 ✅ | ❌ 读超时 |
| `hub.rat.dev` | 302 | 200 ✅ | ❌ 读超时 |
| `dockerproxy.net` | 502 | 200 ✅ | ✅ 7/7 层，32.9 MB |

逐层实测：

```text
1/7  e6f31ffc  3.67 MB   5.5s   ✅        5/7  74788a58  0.00 MB   1.0s   ✅
2/7  27462c3a  0.00 MB   1.1s   ✅        6/7  4f4fb700  0.00 MB   1.2s   ✅
3/7  064995e3  0.19 MB   5.1s   ✅        7/7  c0241ea5  0.00 MB   0.9s   ✅
4/7  7fd2b918 29.02 MB  15.0s   ✅   ← 最大层，≈1.9 MB/s
```

## 根因

`registries.yaml` 给 `docker.io` 只配一个 mirror，等于把集群拉镜像绑在单一服务。

## 修复

`ansible/roles/k3s/files/registries.yaml` 的 `docker.io` `endpoint` 改两条，顺序即优先级：

```yaml
mirrors:
  docker.io:
    endpoint:
      - "https://dockerproxy.net"        # 实测可完整交付，放第一位
      - "https://docker.m.daocloud.io"   # 保留兜底（通常更快）
```

没有改 `values.yaml` 的镜像地址（如 `dockerproxy.net/library/redis:8.6.4-alpine`），代理域名不该焊进清单。

## 判据

| 判据 | 结果 |
|---|---|
| playbook | `changed=1` |
| `certs.d/docker.io/hosts.toml` | 2 个 host，`dockerproxy.net` 在前；判据看生成的 `hosts.toml` |
| helm release | `REVISION 2 / deployed`（rev1 `superseded`） |
| Pod / 站点 | 4 个常驻全 `1/1 Running`；`/healthz` 200、`/` 301 |

## 另两处

`helm --wait` 到最后才报错，实际是镜像拉不到，已在 `scripts/install-argocd.sh` 补安装前连通性预检。`k3s kubectl` 能连，但 `helm` 不继承 kubeconfig，退回 `localhost:8080` 报 `Kubernetes cluster unreachable: dial tcp [::1]:8080`（同 `ansible.cfg`）；`export KUBECONFIG=/etc/rancher/k3s/k3s.yaml` 已写进（见 `baseline.md`）。

## 遗留

`quay.io` / `ghcr.io` 仍是单一 mirror。`dockerproxy.net` 换掉只需改一行：靠 sha256 校验而非信任域名，否则一直被 8 KB/s 卡住（[methodology ⑱](../methodology.md)）。
