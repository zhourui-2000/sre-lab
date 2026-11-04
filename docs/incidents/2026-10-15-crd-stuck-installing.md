# 2026-10-15 · k3s 起不来（第二次）：一个 CRD 卡在 Installing，集群 0 Pod

2026-10-15。cgroup v1 修好重启后 `cgroup2fs` 生效（[cgroup v1](2026-10-15-cgroup-v1-blocks-kubelet.md)），8 个 docker 容器恢复、站点正常；做 K3 验收时集群一个 Pod 都没有，k3s 仍在崩溃循环（每约 72 秒一轮）。

## 现象

```text
kubectl get pods -A -o wide → No resources found（退出码 0）
level=fatal msg="failed to start controllers: failed to create new server context:
  failed waiting on CRD 'addons.k3s.cattle.io': timed out waiting for the condition"
```

`get nodes` 显示 `Ready`，`get ns` 4 个系统命名空间。「0 Pod」是结果：coredns / local-path-provisioner 由 addon 控制器下发，后者在 `startControllers` 前随 fatal 死掉。

## 根因

```text
kubectl get crd -o jsonpath='{range .items[*]}{.metadata.name}{"="}
  {.status.conditions[?(@.type=="Established")].status}{"\n"}{end}'
```

| CRD | Established | resourceVersion | creationTimestamp |
|---|---|---|---|
| `addons.k3s.cattle.io` | `False`（reason=`Installing`） | 719 | `10:57:00Z` |
| `etcdsnapshotfiles.k3s.cattle.io` | `True`（`InitialNamesAccepted`） | — | `10:57:00Z` |
| `helmcharts.helm.cattle.io` | `True` | — | `10:57:39Z` |
| `helmchartconfigs.helm.cattle.io` | `True` | — | `10:57:39Z` |

只有这一个卡死，同秒创建的 `etcdsnapshotfiles` 正常：

- `lastTransitionTime` 等于 `creationTimestamp`，`resourceVersion` 仍 719，同期集群 1900+。
- spec 与好的 CRD 一致：同 `controller-gen.kubebuilder.io/version: v0.21.0`、同 schema、`conversion.strategy: None`。
- 从未 serve：`kubectl get addons` 报 `the server doesn't have a resource type "addons"`，`api-resources` 只有另外三个，每轮等它 60 秒。

旁证：`/var/lib/rancher/k3s/server/manifests/` 不存在（应 6 个 yaml）、`/var/lib/rancher/k3s/agent/images/` 不存在、containerd `k8s.io` 命名空间 0 镜像 0 容器。

写入时每 14 秒被杀一次（`creationTimestamp` = 18:57，`cgroup v1` 崩溃循环期），停在「已创建、安装未完成」，`kubectl get crd` 可见。此前也有半成品：安装脚本 `set -e` 中止，81 MB 二进制在、unit 不在，`k3s --version` 仍正常。

## 修复

```text
# 阶段 A（采用）：只删那一个 CRD
kubectl delete crd addons.k3s.cattle.io

# 阶段 B（A 失败才做）：重置整个数据存储
rm -rf /var/lib/rancher/k3s/server/db
```

A 成功、B 未使用：病灶只那一个对象。

## 判据

删除后 13 秒重建：

```text
addons.k3s.cattle.io  Namespaced  v1(storage)  CREATED AT 2026-10-15T12:55:44Z
  NamesAccepted=True(NoConflicts)   Established=True(InitialNamesAccepted)
```

判据不是 CRD 变绿，而是 Pod：

| 判据 | 修复前 | 修复后 |
|---|---|---|
| k3s 服务 | activating / 无限重启 | active · NRestarts=1 · SubState=running |
| Pod 数 | 0 | 3（local-path-provisioner、coredns `Running`，helm-install `Completed`） |
| `api-resources` 的 addons | 不存在 | `addons  k3s.cattle.io/v1  true` |
| `server/manifests/` | 不存在 | 6 个 manifest |
| containerd `k8s.io` ns | 不存在 · 0 镜像 | 存在 · 6 镜像 / 4 容器 |
| CRD 总数 | 1 个卡死 | 14 个全部 `Established=True` |
| 站点 | 301 / 200 | 301 / 200；80/443 仍 `docker-proxy` |

36 小时后：`NRestarts` 仍 1、14 个 CRD 全绿、3 个 Pod Running、`Ready · control-plane`（AGE 36h）；`PRAGMA integrity_check = ok`、kine 2085 行。

## 另两处

删 CRD 后第一周期报错变为 `failed to get CRD 'addons.k3s.cattle.io' for status checking: … "not found"`：阶段变了，不是变严重。

手册 K3 只预设「cgroup 没修好」一种失败（回查 grubenv），实测撞上第二个 fatal。失败处置要覆盖三类：同一原因未解决、修好但暴露下一层、判据本身失效。

## 遗留

establishing 控制器为何不处理该对象，**确切机制未确定**（apiserver 日志无 error）；先删后建有效、数据存储完好，按操作性结论处理。再遇对象卡中间态，先查是否在进程被反复杀死期间写入。见 [methodology ⑰](../methodology.md)、[capacity.md](../capacity.md)。
