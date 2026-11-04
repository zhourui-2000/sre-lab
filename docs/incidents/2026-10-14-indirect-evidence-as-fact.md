# 判据的数据来源也会骗人：三次「把代理当成了事实」

2026-10-14 一天内三次，全在验证环节；缓存、索引、被裁掉的输出都不是事实，只是代理，而代理会过期、会漏记、会被自己裁掉。

## ① 磁盘权限对了，会被重建的那份没记

新增 `scripts/check-fw-drift.py` 并提交，推送输出 `create mode 100644`，但脚本已 `chmod 0755`，自检也报 ✅。

| 检查 | 值 |
|---|---|
| 磁盘上的权限 | `-rwxr-xr-x` `755` ✅ |
| git 索引里的模式 | `100644` ❌ |
| 控制端 `core.fileMode` | false ← 元凶 |
| 服务器上（对照） | `true` |
| 文件到服务器后 | `-rw-r--r--` `644` ❌ |

`core.fileMode=false` 时 git 忽略权限位，10-13 跨 `/mnt/c` 迁移时自动关掉；与 [10-14 迁移权限事故](2026-10-14-migration-perms-ansible-cfg.md) 是同一件事的两半（那半边是 `0777` 拷贝漂移）。索引 `100644` 到新机器 `git clone` 就是 `644`，`./scripts/check-fw-drift.py` 报 `Permission denied`。

修复：`git config core.fileMode true`，3 个模式不一致文件 `git add` 提交（`methodology/runbook` 755 改 644，工具 644 改 755，另 11 个 `.md`）；索引 `100755` 只剩工具 1 个。

```sh
git clone -q /root/sre-lab /tmp/clone-check
stat -c '%a' /tmp/clone-check/scripts/check-fw-drift.py   # 期望 755
```

`git update-index --chmod=+x` 在 `fileMode=false` 下仍有效（对照验证：索引 `100755`，克隆方 `755`）。

## ② origin/main 落后是缓存

`origin : 828ca36` 旧，local / relay / server 都新。`origin/main` 只是本地缓存，`git fetch` 失败时不报错、只留旧值（实测 `git fetch origin`）：

```text
ssh: Could not resolve hostname ssh.github.com: Temporary failure in name resolution
```

命令自己扔了线索：`git fetch origin --prune 2>/dev/null; git rev-parse origin/main`。硬证据是钩子日志 `To github.com:zhourui-2000/sre-lab.git  <old>..<new>  main -> main` 与 `git ls-remote origin main`（`ls-remote` 实时结果）。假信号已三次：`ahead 22` / `ahead 1` / `origin 落后`。

修复：`git ls-remote origin refs/heads/main`（3–5 次重试）、`tail -8 /var/log/sre-relay.log`；固化为 `check-three-ends.sh`（四方核验 + 重试 + 钩子日志兜底 + 退出码 `0/1`）。

## ③ 验证命令把证据裁掉了

`2>/dev/null` 吞掉 stderr，失败伪装成结论。不重定向，或 `2>&1 | tail -3`，或判退出码。

## 校验器本身也要验

| 现象 | 机制 |
|---|---|
| `alloy fmt` 对写坏的配置也 `exit=0` | 只是格式化器；改用 `alloy validate`（正例 0、两个对照组 1） |
| `inspect.signature(subprocess.run)` 得 `False` | `run` 的额外参数走 `**kwargs`，判据无效；证据是代码真跑通 |

拿已知错误输入喂校验器，确认它会失败。问法：我手上这个值，是事实，还是事实的代理？代理对照表见 [methodology ⑯](../methodology.md)。
