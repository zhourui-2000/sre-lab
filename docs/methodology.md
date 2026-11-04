# 方法论

每条来自一次真实故障。故事在 [`incidents/`](incidents/)，本文只留规则。用法：动手前扫一眼，收尾前对一遍。

两条元规则：**改完先问「我怎么知道它生效了」，再找一个能证明的观测点**；**幂等保证稳定，不保证正确，收敛性验收与正确性验收缺一不可**。

---

## ① 文件内容 ≠ 实际生效值

- `sshd_config` 写 `X11Forwarding no`，`sshd -T` 仍是 `yes`（lineinfile 命中最后一条匹配行）。
- `nginx -T` 打印新配置 ≠ 运行中的 master 已加载（它只读盘解析并打印）。
- 判据：打生效值，如 `sshd -T` / `nginx -t` / 真实 HTTP 响应。

## ② `--check` 不是幂等测试

- `--check` 不落盘，跑几次结果都一样，暴露不了"第二次是否收敛"。
- 判据：实跑 `changed=N`，再跑 `changed=0`（base / security / web 均按此）。

## ③ 验证「关闭类」改动必须配对照组

- 验 `access_log off` 时，日志零增长也可能是日志整体坏了。
- 判据：同时发 `/`（200）与 `/nonexistent-404-test`（404），确认日志仍在写，再做跨周期增量对比。单次快照证明不了周期性。

## ④ 相关性 ≠ 因果

- 09-12 改完 MTU 后推送成功，记为"修复有效"；09-24 复发时同样改动完全无效，切手机热点立刻稳定。
- 判据：重复验证或对照（同一网络换目标 / 同一目标换网络）。
- 没有实测收益的配置不要持久化，否则留下无法解释的迷信配置。

## ⑤ 修复要考虑路径依赖

| 路径 | 稳定性 |
|---|---|
| 本机 → GitHub | 不稳定（间歇挂起、无输出） |
| 本机 → 服务器 / 服务器 → GitHub | 稳定 |

做法：用服务器做中转，把「本机到 GitHub」拆成两段稳定链路。

## ⑥ 幂等 ≠ 正确

- 09-26：IaC 里一份过期的 `default.conf` 覆盖了服务器上已修好的配置，容器 unhealthy；而**修复前的第二次跑 playbook 报 `changed=0`**。
- `changed=0` 只说明与 IaC 声明的期望状态一致。期望状态本身是错副本时，幂等会把错误状态稳定维持下去。多真源 = 迟早互相覆盖。
- 判据：幂等验收之外加一次业务层验收（`docker inspect` 的 Health、真实响应码）。

## ⑦ 告警三视图 ≠ 一个真源

- 10-09：vmalert `/api/v1/alerts` 已 firing，VM `ALERTS` 恒空、alertmanager 根本不存在。
- 三条独立链路：引擎态（vmalert 内存）/ 落库态（`--remoteWrite.url`）/ 送达态（`--notifier.url`）。
- 判据：三点同验；`docker inspect vmalert --format '{{.Config.Cmd}}'` 里必须同时出现 `--datasource.url`、`--notifier.url`、`--remoteWrite.url`。

## ⑧ 部署路径 / 流程无约束 = 隐性真源泄漏

- 10-09：文档写 `/root/sre-lab`，实际在 `/opt/sre-lab`；observability 不在 `site.yml` 内，靠手工 `git pull` 维系。
- 判据：路径与部署方式写进 README 并被 IaC 或脚本强制。

## ⑨ 判据必须能区分失败原因

- 反例：`docker compose config >/dev/null && echo OK || echo 语法错` 在没装 docker 的机器上跑，把"命令不存在"报成"语法错"（假阴性）。
- 判据：先做环境检查，`command -v docker >/dev/null || { echo "环境缺 docker"; exit 2; }`
- `A && echo OK || echo FAIL` 是坏模式，会把多种失败混成一种结论。

## ⑩ 验证手段必须先于被验证对象可用

- 09-26：想用 playbook 的 `assert` 拦住"目标机 Python 损坏"，但 `assert` 本身也依赖目标机 Python，而 Python 正是坏的那一环。
- 判据：设计校验前先确认校验手段自己能跑。

## ⑪ 改了被挂载的配置 ≠ 容器生效

- 实例①：10-09 alertmanager receiver 从 webhook 换 SMTP 后 `docker compose up -d`，容器没重建（日志仍是 `integration=webhook[0]`），加 `--force-recreate` 才生效。
- 实例②（次日复现）：10-10 把阈值压低、`for` 改 `0s`，`git pull` + `up -d vmalert` 后文件是新值，vmalert 加载的仍是旧值，告警一封没收到。
- 三层机制：
  - compose：`up -d` 只比服务定义（image / command / ports），不比挂载文件内容；
  - Docker：`cp` 或编辑器覆盖会换 inode，旧容器 bind-mount 仍指旧 inode，`restart` 无用；
  - 热重载：inotify 盯 inode，而 `git pull` / `cp` / 编辑器写入是 rename 替换，监视对象消失，因此不会触发。不要把"它有热重载"当兜底。
- 判据：改挂载配置一律 `docker compose up -d --force-recreate <svc>`，验收打组件自报的生效值。

| 组件 | 生效值 |
|---|---|
| vmalert | `curl -s 127.0.0.1:8880/api/v1/rules` 看 `query` 与 `duration` |
| nginx | `nginx -t` |
| sshd | `sshd -T` |
| 任意容器 | `docker exec <svc> cat <容器内路径>` |

两天内三次复现（09-24 nginx 未 reload、10-09 alertmanager、10-10 vmalert），不是偶发，是默认会发生。

## ⑫ 收紧权限前，先确认「谁要读它」

- 10-09：给 alertmanager 配置 `chmod 600` 后容器 crash loop（镜像以 `nobody` 运行，`error loading configuration file: ... permission denied`）。`600 + root:root` 对非 root 消费进程等于文件不存在。
- 判据：`docker inspect <c> --format '{{.Config.User}}'` 查消费方身份；用 `docker exec <c> cat <路径>` 取消费方视角，而不是宿主 `sudo -u nobody cat`（会被目录权限挡住，产生假阴性）。
- 更严的权限未必更安全：真正的边界是文件不入库 + 目录不可穿越 + 容器不持宿主能力。见 [ADR 0002](adr/0002-secret-file-permissions.md)。

## ⑬ 回滚 / 还原必须以「显式标识」为目标

- 10-10：手册写 `git revert --no-edit HEAD`，但目标提交 `68180cc` 之后叠了文档提交 `79a203e`，于是 `HEAD` / `HEAD~1` / `HEAD^` 是相对引用，此时指向的已不是原来那条，revert 还原的是文档，临时阈值一动不动。
- 危险在于静默：命令报错会打断你，错位只会让你以为成功了，而该撤的配置留在生产里。
- 步骤：`git log --oneline -N` 取 SHA；`git show --stat <SHA>` 复核文件；`git revert --no-edit <SHA>`；验生效值。
- 推论：撤销 / 回退类操作，目标必须能被独立指认（SHA、时间戳、明确路径）。

## ⑭ 迁移 / 拷贝不保留权限语义

- 10-14：控制端迁移后 `ansible lab -m ping` 不报错也不生效。三条 WARNING：`ignoring it as an ansible.cfg source` / `No inventory was parsed` / `Could not match supplied host pattern, ignoring: lab`。
- 机制：文件经 `/mnt/c`（DrvFs）进 WSL，无 `tar -p` 式保留，整树落成 `0777`（实测 135 目录 + 150 文件）。Ansible 从全局可写目录加载 `ansible.cfg` 等于把 `roles_path` 交给任何能写该目录的人，所以宁可不读。这是正确设计。
- 最危险的是没有报错：`exit=0`、`--syntax-check` 照样通过（不依赖 inventory）、`ansible-playbook` 以 `skipping: no hosts matched` 结束。
- 判据：`find <dir> -perm -o+w | wc -l` 应为 0，否则 `chmod -R go-w`；验收打 `ansible --version` 的 `config file` 指向、`ping` 的 pong、实跑 `changed=N`。
- 附带：`ansible-core` ≥2.18 要求控制端 Python ≥3.11，重建后必须重新确认版本。

## ⑮ 增量式 IaC 不会纠正漂移，只会忽略它

- 10-14：`trusted` 区多出一条 IaC 之外的 `192.168.0.0/16`，09-16 手工所加，游离 28 天。
- 机制：firewalld 任务先 `--query-*` 再 `--add-*`，从不删除、从不重置。方向决定命运：

| 服务器上的动作 | playbook 反应 | 症状 |
|---|---|---|
| 加一条新规则 | 不撤销 | `changed=0`、无警告 → 失败只在重建那天暴露 |
| 删 IaC 里已有的条目 | 下次跑加回来 | "我改的东西自己变回来了" |

- 判据：需要"没有多余项"时必须单独写。本例用出厂态 `/usr/lib/firewalld/zones/*.xml` 与当前态 `/etc/firewalld/zones/*.xml` 的差集，减去 IaC 声明 = 无主改动，无需白名单。
- 手工改动回填 IaC 必须做差集核对（手改 N 条、回填 N−1 条是常态）。验证 IaC 能重建的唯一办法是先删后建；先手工加再补进 IaC 只会得到 `changed=0`。
- 风险取决于有无消费方：那条规则 conntrack 实测 0 条流量，丢了不出事；k3s 的网段规则丢了就是功能事故。

## ⑯ 判据的数据来源本身也可能是假的

10-14 一天内三次，全在验证环节：

1. `core.fileMode=false`：磁盘权限 `755` 是对的，索引里记的是 `644`，而被重建的是索引，所以新机器上脚本不可执行；
2. `origin/main` 只是本地缓存，`git fetch` 失败不报错只留旧值，被读成"GitHub 落后"（同类假信号累计 3 次）；
3. `2>/dev/null` 把"fetch 失败"吞掉，过期缓存当事实。

判据：对每个验证值问一句：这是事实，还是事实的代理？

| 我看到的 | 它其实是 | 事实是 |
|---|---|---|
| 磁盘文件权限 | 本地状态 | 索引里记录的模式；用 `git clone` 实测 |
| `origin/main` | 缓存 | `git ls-remote` 实时结果 / 钩子日志里 push 被接受那行 |
| 退出码 | 代理 | 它的 stderr，绝不吞 stderr |
| 校验器 `exit=0` | 代理 | 它对已知错误输入也会失败这一事实 |

校验器本身也要验：拿已知错误输入喂它。实测 `alloy fmt` 对写坏的配置也返回 `0`，真正的校验器是 `alloy validate`。

## ⑰ 稳态、瞬态、累计量不能混用一把尺子

| 想回答 | 该用 | 不能用 |
|---|---|---|
| 现在有没有危险 | 两时点差分（`memory.current`） | 单次快照 |
| 故障规模多大 | 不回退的计数器（journald 行数、启动次数） | 会被修复动作重置的指标 |
| 历史最高到过多少 | `memory.peak`（5.19+） | 5.10 上没有这个文件 |

- k3s 控制面：崩溃循环中 `329.5 MiB`，稳定后 `558 MiB`，差 70%。崩溃中的数字是"第 N 次启动到校验失败那一刻"的瞬时值。
- `alloy` 的 `memory.events.max=783`：单看像被限流，跨周期 `Δ=0`，是启动回灌的一次性事件（旁证：`loki_write_dropped_entries_total` 五种 reason 全 0）。
- ArgoCD `available`：354（拉镜像）、459（空转）、354（有负载）。"装完测一次"既不是峰值也不是稳态。

判据：报数字前先问：这次测的是稳态、瞬态，还是累计量？

## ⑱ 探活接口通过，不代表用途可行

`GET /v2/` 是 registry 的探活接口，拉镜像是 blob 路径，两者会给出相反结论：

| mirror | `/v2/` | 能不能下 blob |
|---|---|---|
| `docker.m.daocloud.io` | 401（正常） | ❌ 502 |
| `dockerproxy.net` | 502 | ✅ 7/7 层，32.9 MB |

同族：`systemctl is-active`=active 但无限重启；`/healthz` 200 但业务全 500；`helm list` 默认隐藏 failed（要 `--all`）；`--syntax-check` 通过但 inventory 没加载。

判据：真的走一遍业务路径（下一层 blob / 调业务接口 / 跑 playbook），而不是打一个"我还活着"的接口。

## ⑲ 口径是判据的一部分

| 判据 | 口径 | 结论 | 换口径后 |
|---|---|---|---|
| 样本 23 < 60 → 采集有洞 | 理想满窗值 | ❌ 故障 | 同期 `up` 30 → 没有洞 |
| 探针 20 / up 60 → 有洞 | 15 分钟窗口 | ❌ 故障 | 1 分钟窗口 4/4 → 没有洞 |
| 容器 316 MB > available → 112% | `memory.current`（含可回收缓存） | ⚠️ 危险 | `anon` 238 MB → 正常 |
| `grep` 还能搜到 → 没改干净 | 全文匹配 | ❌ 没改完 | 命中的在 docstring 里 → 已改完 |

四类口径：基准、时间窗、统计范围、匹配范围。

判据：写判据前先答三句：统计哪段时间？包含哪些东西？匹配到哪一行？答不上来就还没写好，而它照样会返回一个看起来很确定的数。四次里两次太严两次太松，根因同一个：口径没写下来。

## ⑳ 验证的输出被截断时，验证本身失效

- 改变量名 `iac_files` 为 `iac_map`，改了定义与使用处，漏了统计输出那行。崩溃在第 192 行，而命令是 `... 2>&1 | sed -n '1,40p'`，失败落在被裁掉的那段。
- `ast.parse` 只查语法，`NameError` 是运行时错误。
- 判据三条：退出码 `echo "退出码=$?"`；`grep -q Traceback` 不命中；关键计数行存在（如 `grep -q "合计：✅ 15"`）。
- `| head` / `| tail -N` / `| sed -n '1,Np'` / `2>&1 | grep 关键词` 都能裁掉异常。为了看得清爽而缩小观察范围，而失败没有义务出现在你选的范围内。

## ㉑ 交互式命令不能放进可复制块

手册 1.1 曾把这三行放同一块（还带复制按钮）：

```bash
read -rsp '备份口令: ' SRE_BACKUP_PASS; echo
export SRE_BACKUP_PASS
bash scripts/backup-state.sh /root/backup
```

整块粘贴时 `read` 把后两行当口令吃掉（实测 496 字符 / 564 字节）；`read -s` 不回显，用户以为没粘上又敲一遍，两次口令不同，于是必然 `bad decrypt`，报错指不到真原因。

判据：`read -s` 类提示必须独占一个代码块；输入完立刻回显一个可验证量（长度、字节数，或"已用该口令成功解开"）。

## ㉒ 报错指向的位置，不一定是出错的位置

| 报错 | 看起来像 | 实际是 |
|---|---|---|
| `rsync: connection unexpectedly closed (0 bytes received so far) [Receiver] (code 12)` | 网络中断 | 目标端没装 `rsync` |
| `docker compose down` → `no configuration file provided: not found` | compose 文件损坏 | cwd 不在 `nginx/` |
| `restore-state.sh: line 20: 1: 用法: ...` | 脚本有 bug | `$A` 是空的 |
| `bad decrypt` | 文件损坏 | 口令输错（粘贴吃进 496 字符） |

手段按成本从低到高：看退出码与 stderr 全文；查被指向的那个对象（`command -v rsync`、`pwd`、`echo "[$A]"`、`printf '%s' "$PASS" | wc -c`）；用已知正确输入跑一遍（`testpass123`）；分层排除（先 `sha256` 证文件没坏再怀疑口令）。

## ㉓ 「数对得上」不是证据，「身份对得上」才是

- 10-22 用备份恢复 k3s 后 `namespace 6 / pods 8 / deployments 7 / secrets 9` 与恢复前一致；但干净的 k3s 加两次 `kubectl apply` 也能造出一样多的对象。
- 能分辨的是 `creationTimestamp`（存在 db 里，重建造不出来）：四个时间戳全为原值（10-15 / 10-17 / 10-19）。
- 规则：选一个「假成功路径下不成立」的量。自检问法：假如这次操作完全没生效，还有别的路能让这个数变成对的？

| 量 | 假成功下也成立？ | 强度 |
|---|---|---|
| 对象数量 | 是（重新 apply） | 弱 |
| 对象创建时间 | 否 | 强 |
| 文件大小 | 是（内容不同也可能同大小） | 弱 |
| 文件哈希 | 几乎不可能巧合 | 强 |
| 端口在监听 | 是（换个程序也行） | 弱 |

---

## 附录：同族索引

原文每条的「同族 / 区别」段落合并于此。

| 族 | 条目 | 共同形态 |
|---|---|---|
| A 代理指标 | ①⑨⑫⑬⑯ | 打到的不是事实本身；代理会过期、漏记、被裁 |
| B 不报错的失败 | ⑥⑭⑮ | 工具按设计静默降级或忽略，且都返回成功 |
| C 观察范围 | ⑳㉑㉒ | 输出被自己裁掉、被交互设计关闭、被报错指向别处 |
| D 判据选择性 | ⑱⑲㉓ | 问错了问题、口径没声明、量本身区分不了真假 |
| E 时序 | ③⑰ | 采样时点决定结论 |
| F 幂等与真源 | ②④⑤⑥⑧⑮ | 收敛不等于正确，因果需对照，路径需择优，真源只能有一个 |

**历史脉络**：三天内三次同一模式（`git pull` 静默失败、nginx 未重载、compose 校验失败），都不是配置写错，而是缺一次生效性验证。这是第 4 周引入 ArgoCD 的直接动机：把"我推了代码"到"集群已同步"之间的确认交给系统。
