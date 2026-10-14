# 重建控制端引发的连锁故障

- **日期**：2026-09-26
- **影响**：一天之内连环暴露 **5 个**不同类型的问题
- **一句话结论**：**5 个问题没有一个属于「配置写错了」**——全部是环境漂移或缺生效性验证

## 背景

控制端（WSL2）在 2026-09 进水事故中报废后重建。**服务器本体 24 天未动**（`uptime` 24 天），
但新建的控制端带来了与原环境**不同的版本组合**，一天之内连环暴露 5 个问题。

## 时间线

| 时刻 | 事件 | 结果 |
|---|---|---|
| 14:39 | WSL 侧重新 clone 仓库 | ✅ HEAD = `bde67c2`，工作区干净 |
| 15:1x | `ansible lab -m ping` | ❌ `No start of json char found` |
| 15:5x | 目标解释器改为 `python3.11` | ✅ ping 通过 |
| 16:0x | 首次实跑 playbook | ❌ firewalld 模块缺 Python 绑定 |
| 16:2x | firewalld 任务改为命令行调用 | ✅ `changed=1` → `changed=0`，幂等成立 |
| 16:3x | 再次实跑 playbook | ❌ web 容器转 unhealthy，`/healthz` 消失 |
| 16:4x | `git commit` | ❌ `Author identity unknown`，提交被拒 |

## 故障 1：目标机 Python 版本不兼容

- **现象**：`ansible lab -m ping` 失败，报
  `Module result deserialization failed: No start of json char found`；
  真正的线索藏在 `module_stderr` 里：`SyntaxError: future feature annotations is not defined`
- **诊断**：`future feature annotations` 是 Python 3.7+ 才引入的语法；
  `readlink -f /usr/bin/python3` → `/usr/bin/python3.6`；控制端为 `ansible-core 2.20.1`
- **根因**：Alibaba Cloud Linux 3 默认 `python3` 是 **3.6.8**，不满足新版 ansible-core 对目标机的最低要求。
  **服务器没变，变的是控制端版本**——属"重建控制端引入的版本漂移"
- **修复**：inventory 的 `ansible_python_interpreter` 指向 `/usr/bin/python3.11`
  （系统已装，无需额外安装）；并把 `ansible/inventory/hosts.example.ini` 模板同步更正，
  否则下一次重建会原样复现
- **反向验证**：这类问题**无法用 playbook 内的前置断言拦住**——`assert` 本身也是模块，
  同样依赖目标机 Python，而 Python 恰恰是坏掉的那一环（见 [methodology ⑩](../methodology.md)）
- **教训**：**不要用 `alternatives` 改系统默认 python3**。ALinux3 的 yum/dnf 依赖 3.6，
  改系统默认会连带搞坏包管理；只调整"Ansible 用哪个解释器"

## 故障 2：OS 集成库只绑定在系统 Python 上

- **现象**：`Failed to import the required Python library (firewall) on ...'s Python /usr/bin/python3.11`
- **诊断矩阵（实测）**：

  | 库 | python3.6 | python3.11 | 仓库有 3.11 版包 |
  |---|---|---|---|
  | `firewall` | ✅ | ❌ | 无 |
  | `dbus` | ✅ | ❌ | 无 |
  | `dnf` | ✅ | ❌ | 无 |
  | `selinux` | ✅ | ❌ | 无 |

- **根因**：**RHEL 系发行版把 OS 集成库只安装给系统 Python**。
  一旦让 Ansible 用第三方 Python 当目标解释器，就是在与发行版的打包约定对抗。
  且"补依赖"是死路：仓库里没有对应包，`dbus`/`dnf`/`selinux` 还是 C 扩展，无法跨版本复制
- **修复**：把 4 个 `ansible.builtin.firewalld` 任务改为 `command: firewall-cmd`，
  配合 `--permanent --zone=<zone> --query-<kind>=<value>` 只读预检
  （`rc=0` 已放行 / `rc=1` 缺失）+ `when: item.rc != 0` 条件执行 —— **幂等性完整保留**
- **验证**：先人为移除一条永久规则（只动 permanent、不 `--reload`，运行态零影响），
  实跑 `changed=1`（补回）→ 再跑 `changed=0`（真收敛）
- **已知代价**：`command` 不支持 check mode，`--check` 时这几条显示 skipped。
  但 `--check` 本就不是幂等测试（见 [methodology ②](../methodology.md)），真验收仍是"实跑两次 changed=0"

## 故障 3：IaC 期望状态本身是错的（双真源覆盖）

- **现象**：实跑 playbook 后 `web` 容器转 **unhealthy**；`/healthz` 在容器运行态配置与宿主机配置里**都已消失**；
  业务首页仍返回 **200** —— **静默降级**
- **证据**：
  - `docker inspect web` → `Health=unhealthy`
  - `docker exec web grep healthz /etc/nginx/conf.d/default.conf` → 无匹配
  - 服务器 `git status` → `M nginx/conf.d/default.conf`，`git diff --stat` → **-5 行**
- **根因链**：web 角色把 `ansible/roles/web/files/default.conf`（09-16 版，无 `/healthz`）
  `copy` 覆盖到 `/opt/sre-lab/nginx/conf.d/default.conf`（容器挂载的那份），
  盖掉了 09-24 修好的版本 → handler `reload nginx` 生效 → 健康检查 404
- **最值得记住的一点**：修复前的第二次运行报 `changed=0`，**但系统是坏的**（见 [methodology ⑥](../methodology.md)）
- **修复**：先合并双真源（Ansible 侧对齐线上那份）并提交推送，
  再跑 playbook 把正确配置写回；服务器上的 `M` 由 IaC 自己消除，
  而不是手工 `git checkout` 抹平——这样"修好"这件事本身也走了 IaC 路径
- **教训**：**多真源 = 迟早互相覆盖**。同一份配置只允许存在一个源头

## 故障 4：控制端未配 git 身份，提交被拒

- **现象**：`git commit` 后 HEAD 未变化，没有产生新提交
- **诊断**：`git var GIT_AUTHOR_IDENT` →
  `Author identity unknown` / `fatal: unable to auto-detect email address (got 'Admin@...')`
  （乱码来自 Windows 计算机名经 9p 传递时的 GBK→Latin-1 误解码）
- **根因**：新建 WSL 没有 `~/.gitconfig`，仓库级也未设 user；git 2.55 不再自动推断身份
- **修复**：从历史提交反查身份（`git log --format='%an <%ae>' | sort -u`，
  全 37 个提交为**单一身份** `zhourui-2000 <2465224280@qq.com>`）写入全局配置，
  并设 `init.defaultBranch main`
- **注意**：**邮箱必须与历史一致**——GitHub 按邮箱归属提交，填错则该提交不计入账号贡献
- **教训**：**又一次"报错在，但没被读到"**。当日同类模式第 3 次复现
  （前两次：服务器 `git pull` 静默失败、nginx 未 reload）

## 故障 5：relay 裸仓库 HEAD 指向不存在的分支

- **现象**：`git -C /root/sre-lab-relay.git log` 返回 exit 128
- **根因**：`git init --bare` 时默认分支为 `master`，HEAD 指向 `refs/heads/master`；
  而实际推送的分支是 `main` → 该 ref 不存在
- **影响**：post-receive 钩子使用**显式** `main`，故推送链路不受影响；
  但 `clone` / `log` 等走 HEAD 的操作会报错
- **修复**：`git -C <裸仓库> symbolic-ref HEAD refs/heads/main`
- **教训**：**"暂时无害"的配置缺陷最容易累积成事故**——它今天不咬人，不代表明天不咬

## 本次沉淀

1. 新增方法论 [⑥ 幂等 ≠ 正确](../methodology.md) 与 [⑩ 验证手段必须先于被验证对象可用](../methodology.md)
2. 一次控制端重建暴露 5 个不同类型的根因，**没有一个属于"配置写错了"**
3. 故障 3 是由容器 healthcheck 捕获的（09-24 修复的成果），**但无人被告知** ——
   直接印证第 2 周主线：**有观测能力 ≠ 有通知能力，告警必须上线**
4. 复发防线已前移：目标解释器模板、firewalld 调用方式、git 身份、relay HEAD
   四项均已修正，下次重建不会再逐条重踩
