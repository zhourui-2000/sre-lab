# k8s/smoke-test · 集群冒烟测试

**作用**：验证 k3s 集群三条最基础的链路真的通 —— 网络（DNS / 出网）、镜像（加速器）、存储（动态供给）。
它同时是 **Week 4 GitOps 的目录范式预演**：清单进仓库、`apply -f` 应用、`delete` 按同一份清单回收。

## 为什么用清单而不是命令行

原来的打算是 `kubectl run ...` + `cat <<EOF | kubectl apply -f -` 一把梭。问题有三个：

1. **命令式创建的 Pod 不在任何仓库里** → 集群里有、Git 里没有，这就是 k8s 层的漂移
   （和 2026-10-14 那条防火墙规则同一类问题）。
2. 它靠最后一行 `kubectl delete pod` 自己擦干净 —— 中途失败（例如 `ImagePullBackOff` 卡住）
   就走不到那行，**对象会留在集群里**。
3. 靠人记得删，不是「可复现」。

`kubectl apply -f k8s/smoke-test/` 就是 ArgoCD 将来要替你做的事。现在先手工做一遍，
等于把判据先立起来。

## 应用

```bash
cd /opt/sre-lab
k3s kubectl apply -f k8s/smoke-test/
```

顺序说明：文件名以数字开头，`apply -f <目录>` 会按**文件名字典序**处理 →
`00-namespace` 先建，后面的对象才有命名空间可落。

## 验证（四组判据）

```bash
# ① 对象状态
k3s kubectl -n smoke-test get pods,pvc,pv

# ② 镜像真的走通了加速器（k3s 内嵌的 4 个镜像不经过网络，不能用来证明这件事）
k3s crictl images | grep busybox

# ③ 网络：DNS + 出网
k3s kubectl exec -n smoke-test nettest -- nslookup kubernetes.default.svc.cluster.local
k3s kubectl exec -n smoke-test nettest -- wget -S -O /dev/null http://docker.m.daocloud.io/v2/ 2>&1 | grep 'HTTP/'

# ④ 存储：容器内读回 + 宿主机侧目录
k3s kubectl exec -n smoke-test storage-writer -- cat /data/proof.txt
sudo ls -l /var/lib/rancher/k3s/storage/
```

判据解释：

| 检查 | 通过的样子 | 为什么它算判据 |
|---|---|---|
| `busybox` 出现在 `crictl images` | 有 `docker.io/library/busybox  1.36` | 直连 docker.io 是 **http 000**，只有 daocloud 镜像站能拉到 → 镜像存在即证明 `registries.yaml` 生效 |
| `nslookup kubernetes.default...` | 返回 `10.43.0.1` | 证明 CoreDNS 在跑、Service 记录能解析 |
| `wget -S` 打出 `HTTP/1.1 401` | **有状态行就算通** | 401 是 daocloud 要求认证的正常响应；关键是「拿到了 HTTP 响应」= 出网通，不是状态码等于 200 |
| `cat /data/proof.txt` | 有带时间戳的内容 | 证明卷真的挂进去且可写 |
| 宿主机 `storage/` 下有 `pvc-...` 目录 | 目录存在且含 `proof.txt` | 证明数据落在磁盘，而非某个看不见的中间层 |

## 清理

```bash
k3s kubectl delete namespace smoke-test
```

用命名空间删除是**级联**的：Pod / PVC / PV 一起回收，不会漏。
（`local-path` 的 `RECLAIMPOLICY` 是 `Delete`，所以 PV 和宿主机目录也会被清掉。）

## 已知的正常现象（别当成故障）

- **PVC 在 Pod 建好之前一直是 `Pending`** —— `volumeBindingMode: WaitForFirstConsumer` 的设计如此。
- **`helm-install-gateway-api-crd` 显示 `Completed`** —— 那是 k3s v1.37 的一次性安装 Job，正常。
- **首次拉 busybox 可能要十几秒** —— 走 daocloud 镜像站，不是本地缓存。
