# 重建控制端引发的连锁故障

2026-09-26。控制端（WSL2）重建，服务器 24 天未动（`uptime` 24 天）。一天暴露 5 个问题，无一属配置错。

## 时间线

| 时刻 | 事件 | 结果 |
|---|---|---|
| 14:39 | 重新 clone 仓库 | ✅ HEAD = `bde67c2`，干净 |
| 15:1x | `ansible lab -m ping` | ❌ `No start of json char found` |
| 15:5x | 目标解释器改为 `python3.11` | ✅ ping 通过 |
| 16:0x | 首次实跑 playbook | ❌ firewalld 模块缺 Python 绑定 |
| 16:2x | firewalld 任务改为命令行调用 | ✅ `changed=1` → `changed=0` |
| 16:3x | 再次实跑 playbook | ❌ web 转 unhealthy，`/healthz` 消失 |
| 16:4x | `git commit` | ❌ `Author identity unknown` |

## 1. 目标机 Python 版本不兼容

`ansible lab -m ping` 报 `Module result deserialization failed: No start of json char found`；`module_stderr` 里的 `SyntaxError: future feature annotations is not defined` 才是线索（`future feature annotations` 需 Python 3.7+）。`readlink -f /usr/bin/python3` 指向 `/usr/bin/python3.6`，控制端 `ansible-core 2.20.1`。

根因：Alibaba Cloud Linux 3 默认 `python3` 是 3.6.8，变的是控制端。修复：`ansible_python_interpreter` 指向 `/usr/bin/python3.11`（已装），同步 `ansible/inventory/hosts.example.ini`。

`assert` 也依赖目标机 Python，拦不住这类问题（[methodology ⑩](../methodology.md)）；不要用 `alternatives` 改系统默认 python3。

## 2. OS 集成库只绑定系统 Python

报 `Failed to import the required Python library (firewall) on ...'s Python /usr/bin/python3.11`。RHEL 系只把 OS 集成库装给系统 Python。

| 库 | python3.6 | python3.11 | 仓库有 3.11 版包 |
|---|---|---|---|
| `firewall` | ✅ | ❌ | 无 |
| `dbus` | ✅ | ❌ | 无 |
| `dnf` | ✅ | ❌ | 无 |
| `selinux` | ✅ | ❌ | 无 |

修复：4 个 `ansible.builtin.firewalld` 任务改 `command: firewall-cmd`，以 `--permanent --zone=<zone> --query-<kind>=<value>` 预检（`rc=0` 已放行 / `rc=1` 缺失）+ `when: item.rc != 0`。验证：移除一条永久规则（只动 permanent、不 `--reload`），实跑 `changed=1` 再 `changed=0`；`command` 不支持 check mode（`--check` 时 skipped）。

## 3. IaC 期望状态本身是错的

实跑后 `web` 转 unhealthy，`/healthz` 在容器与宿主机配置里都已消失，首页仍 200。证据：`docker inspect web` 为 `Health=unhealthy`、`docker exec web grep healthz /etc/nginx/conf.d/default.conf` 无匹配、`git status` 为 `M nginx/conf.d/default.conf`、`git diff --stat` 为 -5 行。

根因：web 角色把 `ansible/roles/web/files/default.conf`（09-16 版，无 `/healthz`）`copy` 覆盖 `/opt/sre-lab/nginx/conf.d/default.conf`，盖掉 09-24 的版本，`reload nginx` 后健康检查 404。

第二次运行报 `changed=0` 但系统是坏的（[methodology ⑥](../methodology.md)）。修复：合并双真源、提交推送，再跑 playbook 写回，`M` 由 IaC 消除，不 `git checkout`。

## 4. 控制端未配 git 身份

`git commit` 后 HEAD 未变化。`git var GIT_AUTHOR_IDENT` 报 `Author identity unknown` / `fatal: unable to auto-detect email address (got 'Admin@...')`（9p 传递的 GBK 与 Latin-1 误解码）。新建 WSL 无 `~/.gitconfig`，git 2.55 不再推断身份。

修复：`git log --format='%an <%ae>' | sort -u` 反查，全 37 个提交同一身份 `zhourui-2000 <2465224280@qq.com>`，写入全局配置并设 `init.defaultBranch main`。邮箱须与历史一致，否则不算贡献。

## 5. relay 裸仓库 HEAD 指向不存在的分支

`git -C /root/sre-lab-relay.git log` 返回 exit 128：`git init --bare` 默认 `master`，HEAD 指向 `refs/heads/master`，实际分支是 `main`。post-receive 钩子用显式 `main`，推送不受影响，`clone` / `log` 出错。修复：`git -C <裸仓库> symbolic-ref HEAD refs/heads/main`。

## 沉淀

故障 3 由 healthcheck 捕获但无人被告知；`git pull` 静默失败、nginx 未 `reload nginx` 当日第三次同类复现。
