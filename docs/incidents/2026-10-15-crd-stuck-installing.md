# 2026-10-15 · k3s 起不来（第二次）：一个 CRD 卡在 Installing，集群 0 Pod

> 关联：[methodology ⑰](../methodology.md) · [capacity.md](../capacity.md)
> 这是同一天第二个阻塞。cgroup v1 修好之后才暴露出来 —— **"过了第一关"不等于"起来了"**。

## 背景

[cgroup v1 事故](2026-10-15-cgroup-v1-blocks-kubelet.md)修复后重启，`cgroup2fs` 已生效，
`cgroup v1` 报错彻底消失。8 个 docker 容器全部自动恢复，站点正常。

按手册执行 K3 验收时：

```
k3s kubectl get pods -A -o wide
→ No resources found     （退出码 0，不是报错）
```

## 现象

**集群里一个 Pod 都没有**，而 `get nodes` 显示节点 `Ready`、`get ns` 有 4 个系统命名空间。
k3s 仍在崩溃循环（`NRestarts` 持续增长，每约 72 秒一轮），但换了一个 fatal：

```
level=fatal msg="failed to start controllers: failed to create new server context:
  failed waiting on CRD 'addons.k3s.cattle.io': timed out waiting for the condition"
```

**「0 Pod」不是故障本身，而是结果**：k3s 的系统组件（coredns / local-path-provisioner）
由 addon 控制器下发，而该控制器在 `startControllers` 之前就随 fatal 死掉了，
从未有机会运行。

## 诊断

### 第一步：把范围从"整个集群"缩到"单个对象"

```
kubectl get crd -o jsonpath='{range .items[*]}{.metadata.name}{"="}
  {.status.conditions[?(@.type=="Established")].status}{"\n"}{end}'
```

| CRD | Established | resourceVersion | creationTimestamp |
|---|---|---|---|
| **`addons.k3s.cattle.io`** | **`False`（reason=`Installing`）** | **719** | `10:57:00Z` |
| `etcdsnapshotfiles.k3s.cattle.io` | `True`（`InitialNamesAccepted`） | — | `10:57:00Z` |
| `helmcharts.helm.cattle.io` | `True` | — | `10:57:39Z` |
| `helmchartconfigs.helm.cattle.io` | `True` | — | `10:57:39Z` |

**只有这一个卡死**，而且 `etcdsnapshotfiles` 与它**同一秒创建却正常** ——
所以不是"时机不好"，也不是全局性问题。

### 第二步：三条决定性证据

1. **两个条件的 `lastTransitionTime` 都等于 `creationTimestamp`**
   → 该对象**创建之后再没被任何控制器写过**（`resourceVersion` 至今仍是 719，
   而同期集群的 RV 已经走到 1900+）。
2. **它的 spec 与好的那个 CRD 结构完全一致** —— 同 `controller-gen.kubebuilder.io/version: v0.21.0`、
   同 schema 形状、同 `conversion.strategy: None` → **不是 CRD 定义写错，也不是代码 bug**。
3. **该资源从未被 serve**：
   ```
   kubectl get addons    → the server doesn't have a resource type "addons"
   api-resources         → 只有另外三个，没有 addons
   ```
   于是 k3s 每轮启动等它 60 秒 → fatal → 重启 → 再等 60 秒。

### 第三步：旁证 —— bootstrap 从未完成

| 路径 | 状态 | 含义 |
|---|---|---|
| `/var/lib/rancher/k3s/server/manifests/` | **不存在** | k3s 的清单下发目录，正常应有 6 个 yaml |
| `/var/lib/rancher/k3s/agent/images/` | **不存在** | 镜像导入目录 |
| containerd 的 `k8s.io` 命名空间 | **不存在**（0 镜像 / 0 容器） | kubelet 从未真正跑起容器 |

## 根因

**该对象是在 k3s 被每 14 秒杀死一次的环境下被写入的**（`creationTimestamp` = 18:57，
正处于 cgroup v1 崩溃循环期），停在了「已创建、安装未完成」的中间态；
此后 apiextensions 的 establishing 控制器再没有处理过它。

**这是本项目第二次遇到「半成品状态比彻底失败更危险」**：

| 次 | 现场 | 症状 |
|---|---|---|
| 第一次（10-15 早） | k3s 安装脚本 `set -e` 半途中止 | 81 MB 二进制在、systemd unit 不在 → `k3s --version` 正常，极易误判"装好了" |
| **第二次（本次）** | 崩溃循环期间写入的集群状态 | CRD 存在、`kubectl get crd` 能看到，但状态永远停在 Installing |

**关键判断**：故障对象是「被坏环境写出来的半成品」，所以**让它被重新写一遍**就应该好 ——
与本项目已经在用的「先删后建」是同一套路（前一次用于证明 IaC 真能重建防火墙规则）。

## 修复

**两阶段受控实验，先做最小改动**：

```
# 阶段 A（本次采用）：只删那一个 CRD，让 k3s 自己重建
kubectl delete crd addons.k3s.cattle.io

# 阶段 B（A 失败才做）：重置整个数据存储
rm -rf /var/lib/rancher/k3s/server/db
```

**阶段 A 成功，阶段 B 未使用。** 这本身就是一条证据：
**病灶确实只是"那一个对象"，不是整块数据存储。**

> 选择最小改动而不是直接重置，是因为"能只换零件就只换零件"：
> 若直接重置，就永远不知道问题范围有多大。

## 验证

删除后 **13 秒**，k3s 重建了它：

```
addons.k3s.cattle.io  Namespaced  v1(storage)  CREATED AT 2026-10-15T12:55:44Z
  NamesAccepted=True(NoConflicts)   Established=True(InitialNamesAccepted)
```

**判据不是"CRD 变绿"，而是「系统 Pod 出现」** —— 因为那才是"故障真的解除了"的证据：

| 判据 | 修复前 | 修复后 |
|---|---|---|
| k3s 服务 | activating / 无限重启 | **active · NRestarts=1 · SubState=running** |
| Pod 数 | **0** | **3**（local-path-provisioner `Running`、coredns `Running`、helm-install `Completed`） |
| `api-resources` 的 addons | 不存在 | `addons  k3s.cattle.io/v1  true` |
| `server/manifests/` | ❌ 不存在 | ✅ **6 个 manifest** |
| containerd `k8s.io` ns | 不存在 · 0 镜像 | 存在 · **6 镜像 / 4 容器** |
| CRD 总数 | 1 个卡死 | **14 个全部 `Established=True`** |
| 站点 | 301 / 200（未受影响） | 301 / 200；80/443 仍 `docker-proxy` |

**36 小时后复查**：`NRestarts` 仍为 1、14 个 CRD 仍全绿、3 个 Pod 仍 Running、
节点 `Ready · control-plane`（AGE 36h）。**修复是持久的。**

数据存储本身健康：`PRAGMA integrity_check = ok`、kine 2085 行、无残留删除标记。

## 教训

### 判据要指向"消费方是否恢复"，不是"状态字段是否变绿"

CRD 的 `Established=True` 只是必要条件。真正的判据是
**「依赖它的组件是否开始工作」** —— 这里是「系统 Pod 是否出现」。
同族：[methodology ⑫](../methodology.md)（判据从消费方视角取）。

### 报错信息变了，不等于问题变严重

删掉 CRD 后的**第一个**周期，报错从
`timed out waiting for the condition` 变成
`failed to get CRD 'addons.k3s.cattle.io' for status checking: … "not found"`。

这不是变糟，而是**故障阶段变了**：对象从"存在但状态卡死"变成"暂时不存在"，
下一个周期就被重建。**看报错要看它变的是哪一段，而不是看字面严重程度。**

### 一个只覆盖单一失败原因的判据，缺"换个地方失败"这个出口

手册里 K3 的启动步骤原本只预设了"cgroup 没修好"这一种失败（处置是"回查 grubenv"）。
实测遇到的是：**cgroup 那关过了，但撞上完全不同的第二个 fatal**。
失败处置里没有这条分支，等于让读者卡在一个没有出口的位置。

→ 失败处置至少要覆盖三类：**① 同一个原因没解决；② 修好了但暴露出下一层问题；③ 判据本身失效**。

## 遗留

- establishing 控制器为何始终不处理该对象的**确切机制未确定**（apiserver 日志里没有任何
  相关 error）。已知的是"先删后建"有效、且数据存储本身完好 —— 所以按操作性结论处理，不臆测内部实现。
- 若将来再次出现同类"对象卡在中间态"，优先检查：**它是否是某个进程被反复杀死期间写入的**。
