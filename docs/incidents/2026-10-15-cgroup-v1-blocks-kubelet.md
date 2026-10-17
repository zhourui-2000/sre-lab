# 2026-10-15 · k3s 装完却起不来：kubelet 拒绝 cgroup v1

> 关联：[methodology ⑰](../methodology.md) · [baseline 四、环境前提](../baseline.md) · [capacity.md](../capacity.md)
> 这是一次**版本/宿主兼容性**事故：安装全程 `exit=0`，但服务 8 秒后自杀并无限循环。

## 背景

Week 3-4 第一步：在 `182.92.122.36` 上落地 k3s。
当日完成 `ansible/roles/k3s/`（配置先行入 IaC）、K2.1（记安装脚本指纹）、K2.2（固定版本安装）。

K2.2 第一次尝试半途失败，根因是安装脚本的 `setup_selinux()` 依赖 `container-selinux >= 3:2.191.0-1`
而本机源里没有 → `set -e` 中止。加 `INSTALL_K3S_SKIP_SELINUX_RPM=true`（本机 SELinux 本就 `Disabled`）后安装全程通过。

## 现象

```
systemctl is-enabled k3s   → enabled          # 看起来一切正常
systemctl is-active  k3s   → activating       # 不是 active
systemctl show k3s -p NRestarts → 141         # 且一直在涨
k3s kubectl get nodes      → connection refused（127.0.0.1:6443 无监听）
/usr/local/bin/k3s --version → k3s version v1.37.1+k3s1 ✅
```

**所有"装好了"的信号全绿**：二进制到位、systemd unit 生成、`--version` 正常、`is-enabled` 正常。
但服务在启动 8 秒后退出，然后每约 14 秒重试一次。

实测时间窗：**18:37:44 → 19:09:53（32 分 9 秒）**，其中
`Starting Lightweight Kubernetes` **141 次**、`Failed with result` **140 次**。

## 诊断

```
Error: failed to validate kubelet configuration, error:
  kubelet is configured to not run on a host using cgroup v1.
  cgroup v1 support is unsupported and will be removed in a future release
→ k3s.service: Failed with result 'exit-code'.
```

判据（**这是本节真正的价值：判 cgroup 版本只需三条命令**）：

| 判据 | 实测 | 含义 |
|---|---|---|
| `stat -fc %T /sys/fs/cgroup` | **`tmpfs`** | cgroup v1（v2 是 `cgroup2fs`） |
| `ls /sys/fs/cgroup/cgroup.controllers` | **不存在** | v2 才有；v1 只有 `cpu` / `memory` 等控制器目录 |
| `grep cgroup /proc/cmdline` | 无 `systemd.unified_cgroup_hierarchy` | 用默认值 = v1 |

宿主：Alibaba Cloud Linux 3（RHEL8 系）、内核 `5.10.134-19.8.al8`、systemd 239、**默认 cgroup v1**。

## 根因

**Kubernetes v1.35 起，kubelet 在 cgroup v1 主机上直接退出**（不是降级、不是警告），v1.37 继续强制。
k3s v1.37.1 内含 k8s v1.37，因此同样强制。

这不是本项目任何文档覆盖过的前提，也不在任何安装检查里 ——
**它比内存更硬**：内存不够可以换 k3s，cgroup 版本不对，任何发行版都起不来。

> 此前关于"2C2G 装不下上游控制面，所以选 k3s"的容量论证只考虑了内存。
> 这条前提说明：**容量账算得再细，也挡不住一条隐式的宿主前提。**

## 修复

两条路，选择了根治而不是逃生阀：

| 方案 | 取舍 | 结论 |
|---|---|---|
| `kubelet-arg: ["fail-cgroupv1=false"]` | 不重启、不下线 | **未采用**：官方措辞是「桥，不是修复」，上游正在移除 |
| **切 cgroup v2 + 重启** | 站点停机 1–3 分钟 | **采用** |

```
# 1. 主操作：grubby 写 BLS 引用的 kernelopts 变量（新内核自动继承）
grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"

# 2. 加固：同时写 /etc/default/grub，防将来 grub2-mkconfig 重新生成时丢参数
sed -i 's/^GRUB_CMDLINE_LINUX="\(.*\)"$/GRUB_CMDLINE_LINUX="\1 systemd.unified_cgroup_hierarchy=1"/' /etc/default/grub

# 3. 重启（cgroup 版本是内核启动参数决定的，没有别的办法）
systemctl reboot
```

⚠️ **参数不在引导条目文本里**：BLS 条目写的是 `options $kernelopts $tuned_params`，
`$kernelopts` 的值存放在 `/boot/grub2/grubenv`，`grubby` 改的就是它。
**只改 `/etc/default/grub` 而不跑 `grub2-mkconfig` 对当前启动无效**；只跑 grubby 则内核升级后可能丢。两处都写才是"配置持久"。

## 验证

重启于 `2026-10-15 20:19:28`（该机 **6 周 1 天以来第一次重启**）。四面证据：

| 判据 | 实测 |
|---|---|
| `stat -fc %T /sys/fs/cgroup` | **`cgroup2fs`** |
| `/proc/cmdline` | 含 `systemd.unified_cgroup_hierarchy=1` |
| `/sys/fs/cgroup/cgroup.controllers` | `cpuset cpu io memory hugetlb pids ioasids rdma`（**memory 在**） |
| `/proc/1/cgroup` | `0::/init.scope`；v1 的 `/sys/fs/cgroup/memory`、`/cpu` 已消失 |

**重启后持久层逐项一致**（"可无缝重建"的直接检验）：
5 个 IaC 管理文件的 md5 全同、防火墙两张表不变、`vm.swappiness` 仍为 10、8 个容器全部
`unless-stopped` 自动恢复、站点 301/200 不变。**swap 从 234.7 MB 归零**（重启的自然结果）。

**6443 外部可达性同时完成验收**（带对照组，从本机侧实测）：

| 对象 | 结果 | 作用 |
|---|---|---|
| 2222（SSH） | ✅ 可达 | 对照组：公网到本机路径通 |
| 443（web） | HTTP 301 ✅ | 对照组：服务正常 |
| **6443（apiserver）** | **✅ 不可达（curl 000）** | 待验对象 |

且 `ss -lntp` 显示 6443 确实由 `k3s-server` 在 `*:6443` 监听 ——
**证明是防火墙按规则挡的，不是服务没起**。这与 baseline 里「6443 刻意不对外开放」的不变量一致。

## 教训

### ⑰ 「装上了」不等于「能跑」——版本/宿主兼容性是隐式前提

危害形状：安装脚本 `exit=0`、二进制到位、systemd unit 生成、`--version` 正常 ——
**所有"装好了"的信号全绿**，但服务 8 秒后自杀。

判据：**装完必须验证"它活着"，并且验证"它持续活着"** ——
看的是 `NRestarts` 是否停在 1、`is-active` 是否稳定在 `active`，
**不是** `is-enabled` / `--version` / `which k3s`。

### 崩溃循环本身是资源消耗

稳态日志摄入约 1 MB/日 量级，而这次崩溃循环把 journald 从 **24 MB 顶到 72 MB** ——
32 分钟写出约 48 MB，**相当于稳态约 250 天的量**。
外加 141 次进程启停的 CPU 开销。

→ **让一个失败的服务"安静地失败"，比让它刷屏安全得多。** 处置顺序必须是「先止血、再诊断」。

### 想留"故障有多大"的证据，不能在止血之后读

`NRestarts` 这个计数器**行为不可预测**：同样"`stop` + `disable` 后读取"的操作，
一次返回 `0`（`stop` 前是 84），另一次返回 `18`。服务停止后 `Result` 也出现过
`success` 与 `exit-code` 两种，无法用某个属性稳定预测它是否归零。

→ 正确做法是**换一个不会被修复动作影响的判据**：`journalctl -u k3s | grep -c '<特征行>'`。
两次实测（141 次 / 20 次）都与日志时间窗对得上，稳定可复现。

### 观测窗口必须匹配被测对象的粒度

同一天还踩了两次相关的问题（详见 [间接证据当事实](2026-10-14-indirect-evidence-as-fact.md)）：
**短窗既可能高估（赶上启动突发）也可能低估（赶上静默期）**。
判断"速率"类量必须跨足够长的窗口，或换用连续的计数器。

## 遗留

- 本机 3 节点 kubeadm 实验**同样受这条前提约束**，起 VM 时必须确认 guest 也是 cgroup v2。
- 切到 v2 后，`memory.swappiness` 这个 cgroup 文件消失（v2 用 `memory.swap.max`），
  systemd 服务不再被强制 `swappiness=60` 覆盖全局的 10 —— 属附带收益，已记入 baseline。
- `-t tmpfs -o noswap` 在 5.10 内核上挂载失败（kubelet 打 `Assuming not supported` 后继续），
  意味着 **kubelet 无法为 Pod 保证"不使用 swap"** —— 与「保留 swap 并监测」的取舍一致，需持续观察。
