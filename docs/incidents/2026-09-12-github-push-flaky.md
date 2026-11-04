# GitHub 推送间歇性失败

2026-09-12 记录，09-24 修正归因。`git push` 挂起、无输出；`curl` 报 `Failed to connect ... after 7 ms`。

## 试错

| 措施 | 结果 |
|---|---|
| `wsl --shutdown` 重建网络栈 | 看似恢复 |
| `ip link set eth0 mtu 1400` | 看似恢复；09-24 复发时无效 |
| `ssh -o IPQoS=none` | 无效 |
| SSH 443（`ssh.github.com:443`） | ✅ 有效，固化进 `~/.ssh/config` |
| 热点 | ✅ 稳定 |

## 根因

公司网络到 GitHub 链路不稳定，不是 WSL 虚拟网卡：同网络到阿里云服务器稳定。09-12 的归因是把相关性当因果。

## 修复

切热点或中转（[ADR 0001](../adr/0001-server-relay-push.md)）；控制端需备用路径。

## 未证

`7 ms` 成因未定，更像 hosts 劫持或代理端口未监听，而非链路超时（[methodology ④](../methodology.md)）。
