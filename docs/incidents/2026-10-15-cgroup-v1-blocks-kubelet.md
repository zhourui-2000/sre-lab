# 2026-10-15 · k3s 装完却起不来：kubelet 拒绝 cgroup v1

Week 3-4，`182.92.122.36` 落地 k3s（`ansible/roles/k3s/` 入 IaC，K2.1 记指纹，K2.2 固定版本）。K2.2 首次失败：`setup_selinux()` 依赖 `container-selinux >= 3:2.191.0-1`，源里没有，`set -e` 中止；加 `INSTALL_K3S_SKIP_SELINUX_RPM=true`（SELinux `Disabled`）后 `exit=0`。

## 现象

```text
systemctl is-enabled k3s → enabled
systemctl is-active k3s → activating
systemctl show k3s -p NRestarts → 141（仍在涨）
k3s kubectl get nodes → connection refused（127.0.0.1:6443 无监听）
/usr/local/bin/k3s --version → k3s version v1.37.1+k3s1 ✅
```

二进制、unit、`--version`、`is-enabled` 正常，但启动 8 秒后退出、每约 14 秒重试；18:37:44 至 19:09:53，共 32 分 9 秒内 `Starting Lightweight Kubernetes` 141 次、`Failed with result` 140 次。

## 根因

```text
Error: failed to validate kubelet configuration, error:
  kubelet is configured to not run on a host using cgroup v1.
  cgroup v1 support is unsupported and will be removed in a future release
→ k3s.service: Failed with result 'exit-code'.
```

Kubernetes v1.35 起 kubelet 在 cgroup v1 主机上直接退出，v1.37 继续；k3s v1.37.1 内含 k8s v1.37。宿主 Alibaba Cloud Linux 3（RHEL8 系）、内核 `5.10.134-19.8.al8`、systemd 239，默认 v1。三条命令：

| 判据 | 实测 | 含义 |
|---|---|---|
| `stat -fc %T /sys/fs/cgroup` | `tmpfs` | v1（v2 是 `cgroup2fs`） |
| `ls /sys/fs/cgroup/cgroup.controllers` | 不存在 | v2 才有；v1 只有 `cpu` / `memory` 等目录 |
| `grep cgroup /proc/cmdline` | 无 `systemd.unified_cgroup_hierarchy` | 默认即 v1 |

## 修复

| 方案 | 取舍 | 结论 |
|---|---|---|
| `kubelet-arg: ["fail-cgroupv1=false"]` | 不重启 | 未采用，官方称「桥，不是修复」 |
| 切 cgroup v2 + 重启 | 站点停机 1–3 分钟 | 采用 |

```bash
# grubby 写 BLS 的 kernelopts
grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"

# 同时写 /etc/default/grub
sed -i 's/^GRUB_CMDLINE_LINUX="\(.*\)"$/GRUB_CMDLINE_LINUX="\1 systemd.unified_cgroup_hierarchy=1"/' /etc/default/grub

# 重启
systemctl reboot
```

BLS 条目写 `options $kernelopts $tuned_params`，`$kernelopts` 在 `/boot/grub2/grubenv`，`grubby` 改的就是它；只改 `/etc/default/grub` 不跑 `grub2-mkconfig` 对启动无效，只跑 grubby 则升级可能丢。

## 判据

重启于 `2026-10-15 20:19:28`，6 周 1 天来首次重启：

| 判据 | 实测 |
|---|---|
| `stat -fc %T /sys/fs/cgroup` | `cgroup2fs` |
| `/proc/cmdline` | 含 `systemd.unified_cgroup_hierarchy=1` |
| `/sys/fs/cgroup/cgroup.controllers` | `cpuset cpu io memory hugetlb pids ioasids rdma` |
| `/proc/1/cgroup` | `0::/init.scope`；v1 的 `/sys/fs/cgroup/memory`、`/cpu` 已消失 |

持久层一致：5 个 IaC 文件 md5 全同、防火墙两表不变、`vm.swappiness` 仍 10、8 个容器 `unless-stopped` 自动恢复、站点 301/200 不变；swap 从 234.7 MB 归零。

6443 带对照组验收：

| 对象 | 结果 |
|---|---|
| 2222（SSH） | ✅ 可达（对照） |
| 443（web） | HTTP 301 ✅（对照） |
| 6443（apiserver） | ✅ 不可达（curl 000，待验） |

`ss -lntp` 显示 6443 由 `k3s-server` 在 `*:6443` 监听，是防火墙挡的。

## 另两处

崩溃循环是消耗：稳态约 1 MB/日，这次 32 分钟把 journald 从 24 MB 顶到 72 MB。

`NRestarts` 不可预测（同族见 [间接证据当事实](2026-10-14-indirect-evidence-as-fact.md)）：`stop` + `disable` 后读取，一次 `0`（前 84）、一次 `18`，`Result` 也出现过 `success` 与 `exit-code`。改用 `journalctl -u k3s | grep -c '<特征行>'`，实测 141/20。装完验 `is-active` 稳在 `active`，而非 `is-enabled` / `--version` / `which k3s`。

## 遗留

3 节点 kubeadm 同样受约束，VM 的 guest 也要 cgroup v2。切 v2 后 `memory.swappiness` 消失（改用 `memory.swap.max`），systemd 不再强制 `swappiness=60`。`-t tmpfs -o noswap` 在 5.10 挂载失败（kubelet 打 `Assuming not supported`），Pod 的 swap 无保证。见 [methodology ⑰](../methodology.md)、[baseline](../baseline.md)、[capacity.md](../capacity.md)。
