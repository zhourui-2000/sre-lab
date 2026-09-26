# 基线数据（2026-09-12）

所有"优化降幅"的分母。测量于第一周加固完成之后、可观测栈部署之前。

## 系统资源

| 指标 | 测量命令 | 基线值 |
|---|---|---|
| 内存总量 / 已用 / 可用 | `free -m` | 1870 / 471 / **1399 MB** |
| Swap 总量 / 已用 | `swapon --show` | 2047 / 59.6 MB |
| 磁盘水位 | `df -h /` | 7.1G / 40G = **19%** |
| journald 占用 | `journalctl --disk-usage` | **32.0M**（限额 500M 已生效） |
| 镜像拉取耗时 | `time docker pull nginx:alpine` | 2.2s（加速器生效） |

## 安全

| 指标 | 基线值 |
|---|---|
| fail2ban 累计失败认证 | **5858 次** |
| 累计自动封禁 IP | **52 个** |
| 成功入侵次数 | 0（密钥认证，密码登录已关闭） |

## 容量判断（重要修正）

**磁盘不是瓶颈（19%），内存才是。** 简历故事应聚焦内存容量治理，
"磁盘水位下降"这条不成立，不要硬写。

可观测栈预计占用 576MB，部署后剩余约 823MB；
k3s 需 700–900MB。**处于边界，需实测后决策**（见 docs/capacity.md）。

## 待补基线

- 手工部署一次耗时（停服→替换→启动→验证，掐表）
- 可观测栈实测内存（Day 6 后）
- GitOps 部署耗时（第 4 周）
- 各类故障 MTTR、RTO/RPO（第 7 周）

## 故障记录：控制端到 GitHub 推送间歇性失败（2026-09-12 记录，09-24 修正归因）

- 现象：`git push` 无限挂起、**无任何输出**；`curl` 曾报 `Failed to connect ... after 7 ms`；
  间歇性发生，且同一网络下浏览器访问 GitHub 正常
- 修复尝试与各自结果：

  | 措施 | 结果 |
  |---|---|
  | `wsl --shutdown` 重建网络栈 | 当时看似恢复 |
  | `ip link set eth0 mtu 1400` | 当时看似恢复；09-24 复发时改 MTU **完全无效** |
  | `ssh -o IPQoS=none` | 无效 |
  | 改走 SSH 443（`ssh.github.com:443`） | 有效，已固化进 `~/.ssh/config` |
  | **切换到手机热点** | **稳定推送** |

- **修正后的结论**：根因是**公司网络到 GitHub 的链路不稳定**。
  同一网络下"本机 → 阿里云服务器"始终稳定，说明问题出在"到 GitHub"这一段，而不是本地网络栈。
  09-12 曾归因于"WSL 虚拟网卡故障"——那是**把相关性当成了因果**（当时"改完立刻成功"更可能是链路自己恢复了）
- 处理：推送前切手机热点；或使用**服务器中转链路**（见下节）
- 仍未定论：最初 `7 ms` 秒失败的成因——按特征更像 hosts 劫持或代理端口未监听，而非链路超时
- 保留结论：控制端与被管机分离后，控制端可用性成为单点；需有备用推送路径

## 故障记录：Docker Hub 不可达（2026-09-14）

- 现象：`docker compose up -d` 拉取 grafana / victoriametrics 超时
- 诊断：node-exporter（quay.io）成功、grafana（docker.io）失败 → 网络整体正常，Docker Hub 单独被限
- 试错：第三方公共镜像源返回 `denied: You may not login yet`，不可依赖
- 处理：本机 `docker save` → scp → 服务器 `docker load`
- 结论：外部 Registry 属不可控依赖，需建立自有镜像链路；镜像归档属构建产物，不进版本控制

## 故障记录：firewalld 阻断容器间采集链路（2026-09-16）

- 现象：VM 与 node-exporter 均正常运行，但 `up` 指标恒为 0
- 诊断：容器同属 observability_default，排除网络配置；停 firewalld 后 `up` 立即变 1 → 定位为防火墙拦截容器间转发
- 修复：`firewall-cmd --permanent --zone=trusted --add-source=172.16.0.0/12`
- 结论：安全加固会改变系统行为边界，加固后必须回归验证业务与监控链路

## 事故记录：Docker 镜像 tar 包误入 Git（2026-09-16）

- 现象：`git push` 被拒，`File grafana.tar is 126.58 MB; exceeds 100.00 MB`
- 根因：`git add .` 将镜像归档一并暂存；后续删除文件仅新增删除 commit，历史中大对象仍存在
- 修复：`git filter-repo --invert-paths` 重写历史；`.gitignore` 补充 `*.tar`
- 教训：构建产物不进版本控制；`git add .` 前先 `git status` 确认暂存内容

## 可观测栈部署后实测（2026-09-16）

| 容器 | 配额 | 实际占用 | 利用率 |
|---|---|---|---|
| node-exporter | 64MB | 19.4MB | 30% |
| grafana | 256MB | 116.5MB | 46% |
| victoriametrics | 256MB | 94.4MB | 37% |
| web (nginx) | 128MB | 2.96MB | 2.3% |

**可观测栈合计约 230MB，远低于预估的 576MB。**

部署后系统状态：
- 可用内存 1143MB（注意看 available 而非 free）
- 磁盘 19%

### 结论

1. **k3s 可行**：1143 - 750 = 393MB 余量，但需关闭内置 traefik/servicelb/metrics-server
2. **配额可收紧**：所有容器实际用量远低于配额，web 仅 2.96MB
3. **需持续观察**：当前为空载数据，VM 内存随数据量增长，一周后复测峰值再定最终配额

## 故障记录：nginx http2 指令版本不兼容（2026-09-16）

- 现象：容器崩溃循环，`nginx: [emerg] unknown directive "http2"`
- 根因：`http2 on;` 为 nginx 1.25.1+ 语法，镜像实际为旧版
- 修复：改用 `listen 443 ssl http2;`（兼容写法）
- 根因中的根因：使用了 `nginx:alpine` 浮动标签，版本不可控
- 措施：锁定为 `nginx:1.24-alpine`，杜绝同类问题

## 实测更新（2026-09-16）

原估算"可观测栈 576MB"偏保守，**实测仅 230MB**。
text

可用内存  1143MB

减 k3s    -750MB（关闭内置组件后）

──────────────────

剩余余量   393MB  ✅ 健康

纯文本
**决策：第 3 周可以上 k3s**，安装时禁用 traefik / servicelb / metrics-server。

### 配额优化空间

| 容器 | 现配额 | 实测 | 建议调整至 |
|---|---|---|---|
| web | 128m | 2.96MB | 64m |
| victoriametrics | 256m | 94MB | 200m |
| grafana | 256m | 116MB | 200m |
| node-exporter | 64m | 19MB | 保持 |

可释放约 180MB。**但等运行一周取得真实峰值后再执行**，避免空载数据误导。

## 环境前提：SELinux 为 Disabled（2026-09-17）

- 现状：阿里云镜像预设 SELinux=Disabled，`semanage` 已安装
- 影响：sshd 监听 2222 无需 SELinux 端口标签即可工作
- 风险：若重建于默认 Enforcing 的环境（官方 ISO 安装的标准发行版），
        sshd 绑定 2222 会 bind 失败导致无法远程登录
- 现状决策：暂不启用 SELinux（学习环境，已有四层防护：安全组+密钥+非标准端口+fail2ban）
- 若未来启用：需 `semanage port -a -t ssh_port_t -p tcp 2222`

## 故障记录：sshd 加固改动未生效（2026-09-22）

- 现象：playbook 报 X11Forwarding changed，但 `sshd -T` 显示仍为 yes
- 诊断：lineinfile 语义为「替换最后一条匹配行」（源码 index[0]=lineno，
  仅 firstmatch:yes 才 break）；原 regexp `^#?\s*KEY\s+` 命中文件内
  #Match 示例块的缩进行（第140行），而激活行在第104行 → 改动落在无效位置
- 叠加因素：sshd 对多数指令取「首个有效值」，104 行在前，故 140 行的新值永不生效
- 修复：regexp 收紧为 `^#?KEY[ \t]+`（# 后不允许空白，锚定行首）
- 验证：sshd -T 九项生效值 + 连续两次运行 changed=3 → changed=0
- 教训：lineinfile 只能保证「改了文件」，不等于「改了生效值」，必须用
  sshd -T / nginx -T 这类配置自检命令做验收

## 故障记录：服务器配置未生效——git pull 静默失败（2026-09-24）

- 现象：本机已推送「锁定 nginx 镜像版本」等提交，服务器执行
  `docker compose up -d --force-recreate web` 后，`docker ps` 仍显示旧镜像 `nginx:alpine`
- 第一层误判：以为 compose 没改或重建命令无效 —— 实际是**服务器上的仓库根本没更新**
- 诊断路径：
  - `git log --oneline -1` → 服务器 HEAD 仍停在 8 个提交之前（`265f687`）
  - `git status --short` → 存在两处本地改动（`nginx/conf.d/default.conf`、`nginx/html/index.html`）
  - 结论：被改动的文件在远端本次提交中也要变更 → git 拒绝 pull
- 叠加因素：daemon.json 的原镜像加速器已失效，docker 回退直连 `registry-1.docker.io`
  后超时 → 即使 compose 更新，目标镜像也拉不下来
- 修复：
  1. 备份 → `git stash push <两个文件>` → `git pull`（通过）
  2. 复核 stash：`default.conf` 的改动与仓库既有提交同内容（重复修改，可丢弃）
  3. 镜像改走前缀：`docker pull docker.m.daocloud.io/library/nginx:1.24-alpine`
     → `docker tag` 回 `nginx:1.24-alpine`（免去 save/scp/load）
  4. 清理 `.bak` 残留与旧镜像
- 根因：**「服务器只 pull、不改文件」的约定被破坏**。一旦服务器上有本地改动，
  pull 就失败，而这条报错混在长输出里极易被当成噪音划过，最终表现为
  「我明明改了配置却没生效」
- 教训：
  - 服务器上出现 `M` 状态文件即是红灯，必须先处理再谈部署
  - 「改了配置」与「配置生效」之间必须有一次校验：`git log -1` + `docker inspect` 实际镜像
  - 手工 pull 流程没有失败中断机制 → 这是第 4 周引入 GitOps 的直接动机

## 附：镜像获取途径实测（2026-09-24）

| 途径 | 结果 |
|---|---|
| 直连 `registry-1.docker.io` | ❌ 超时（`Client.Timeout exceeded`） |
| 阿里云专属加速器（原 daemon.json 配置） | ❌ 实际已失效：docker 回退直连后超时 |
| `docker.m.daocloud.io/` 前缀 | ✅ 服务器实测拉取成功 |

- 处置：`registry-mirrors` 调整为 daocloud 优先，阿里云条目保留作后备
- 注意：`registry-mirrors` **只对 docker.io 生效**；quay.io / ghcr.io 等仍需前缀方式
  （`quay.m.daocloud.io` / `ghcr.m.daocloud.io`），此前拉取 node-exporter 即属此类

## 故障记录：web 容器 healthcheck 恒为 unhealthy（2026-09-24）

- 现象：`docker ps` 显示 `web ... (unhealthy)`，已持续多日；业务访问正常
- 第一层误判：以为是 HTTP 全量 301 导致 healthcheck 失败 —— **假设未经验证**
- 实测推翻（关键动作：先跑一条命令，而不是先下结论）：
  - `docker exec web wget -qO /dev/null http://127.0.0.1/` → EXIT=0
  - `docker exec web wget -qO /dev/null http://localhost/` → EXIT=1（Connection refused）
  - `getent hosts localhost` → `::1`；容器 /etc/hosts 中 localhost 同时指向 127.0.0.1 与 ::1
  - `netstat -tlnp` → nginx 仅监听 0.0.0.0:80 / 0.0.0.0:443，无 IPv6 监听
- 根因：healthcheck 使用 `localhost`，容器内解析优先返回 IPv6 `::1`，
  而 nginx `listen 80` 只绑定 IPv4 → 连接被拒；busybox wget 不会回退重试 IPv4
- 修复：
  1. healthcheck 改用 `http://127.0.0.1/healthz`（显式 IPv4）
  2. 新增 `location = /healthz { access_log off; return 200 "ok\n"; }`，
     使健康检查不再依赖 301 跳转 → 公网 → 发夹回环 → 证书这条脆弱链路
- 验证：`nginx -t` 通过；`wget -qO- http://127.0.0.1/healthz` 返回 ok；
  一个检查周期后状态变为 healthy；站点 200 / HTTP 301 跳转逻辑保持
- 教训：
  - **`localhost` 不等于 `127.0.0.1`**：多栈解析下可能先走 IPv6，健康检查、探针、
    inter-container 调用一律写显式地址或用服务名
  - 健康检查必须"自包含"：只验证本进程可用性，不引入 DNS、外网、证书等外部依赖

### 验证证据（三重，可复现）

**① 状态与自检**
```text
docker inspect web --format '{{.State.Health.Status}}'  → healthy
FailingStreak                                            → 0
最近三次检查（18:50:49 / 18:51:19 / 18:52:50）           → exit=0
docker exec web wget -qO- http://127.0.0.1/healthz       → ok
```

**② 日志噪音：跨周期增量对照（验证 `access_log off`）**

| 时点 | access.log 总行数 | `/healthz` 出现次数 |
|---|---|---|
| 基线 | 14006 | 6 |
| 等待 70 秒（跨 2 个检查周期）后 | 14006（**+0**） | 6（**+0**） |

等待期间健康检查确实执行（时间戳由 18:50:49 推进至 18:52:50，全部 exit=0），
但访问日志零增长 → `access_log off` 生效。

**③ 对照组：证明"日志功能本身正常"**

```text
GET /                     → 200   ← 日志 +1
GET /nonexistent-404-test → 404   ← 日志 +1
```
日志共 **+2 行** → 不是"日志整体坏了"，而是 `/healthz` 这一个 location 被精确关闭。

**④ 历史记录反证（修复前后对照）**

| 时间（CST） | 状态码 |
|---|---|
| 09-19 10:26 | 404 |
| 09-24 12:30 | 301 |
| 09-24 16:44 | 301 + 404 |
| 09-24 17:47 | 301 + 404 |

6 条全部早于容器重建时刻 **18:25:17**，且**没有一条 200** —— 从反面证明修复前端点确实不可用。

### 修复过程中暴露的两个同源问题（值得单独记）

1. **只 `git pull` 未重建容器** → nginx 只在启动/收到 reload 时读配置，文件改了不等于生效 →
   `/healthz` 仍 404。更坑的是：`nginx -T` 会显示新配置（它只是"读磁盘解析并打印"），
   **不能用来判断运行态**；判断运行态要看业务行为、容器 `StartedAt`、master 进程启动时间。
2. **compose 的 `test` 数组元素未加引号** → YAML 把 `3` 解析为整数 →
   `validating ...: services.web.healthcheck.test.4 must be a string` → `up -d` 直接退出、
   容器未重建，表现为"改完了但一切照旧"。**改完 compose 先跑 `docker compose config` 预检**
   （本机即可、10 秒、不启动容器）就能提前抓住。

---

## 方法论沉淀（六条，可直接用于面试）

> 每条都来自真实故障，且都能配一个具体的"现象 → 诊断 → 根因 → 修复 → 复盘"故事。

### ① 文件内容 ≠ 实际生效值
- 来源：`sshd_config` 里写了 `X11Forwarding no`，`sshd -T` 仍显示 yes（lineinfile 替换了最后一条匹配行）
- 延伸：`nginx -T` 显示新配置 ≠ 运行中的 master 已加载它（它只是"读磁盘解析并打印"）
- 做法：验收一律打**生效值**——`sshd -T` / `nginx -t` / 业务请求的真实响应，而不是看文件内容

### ② `--check` 不是幂等测试
- 来源：`--check` 不写任何文件，跑几次结果都一样，无法暴露"第二次是否收敛"
- 做法：实跑（`changed=N`）→ 再跑（期望 `changed=0`）。
  本项目 base / security / web 三个角色均以此方式验收

### ③ 验证"关闭类"改动必须配对照组
- 来源：验证 `access_log off` 时，只看到"日志零增长"不足以定论——也可能是日志整体坏了
- 做法：**同时**发起正常请求（`/` 返回 200、`/nonexistent-404-test` 返回 404）确认日志仍在写，
  再做跨周期增量对比；单次快照无法证明**周期性**行为

### ④ 相关性 ≠ 因果

- 来源：09-12 改完 MTU 后推送立刻成功，被记为"修复有效"；09-24 复发时同样的改动**完全无效**，
  而切换到手机热点立刻稳定
- 教训：在不稳定/共享的接入网络里，"改完就好了"完全可能是链路自身恢复了。
  **归因必须靠重复验证或对照**——同一网络换目标主机对照，或同一目标换网络对照
- 附带结论：**没有实测收益的配置不要持久化**，否则会留下无法解释的"迷信配置"

### ⑤ 修复要考虑路径依赖（多路径择优）

- 来源：同一目标存在多条可达路径，稳定性差异巨大：

  | 路径 | 稳定性 |
  |---|---|
  | 本机 → GitHub | 不稳定（间歇性挂起、无输出） |
  | 本机 → 阿里云服务器 | 稳定 |
  | 阿里云服务器 → GitHub | 稳定 |

- 做法：**绕开不稳定段**——用服务器做同步中转，把"本机 → GitHub"拆成两段稳定链路（见下节）
- 意义：这既是可用性方案，也与第 4 周 GitOps 同构——让服务器主动同步，而不是依赖开发机网络

### ⑥ 幂等 ≠ 正确（`changed=0` 只证明收敛，不证明状态正确）

- 来源：2026-09-26，Ansible 侧一份过期的 `default.conf` 覆盖了服务器上已修好的配置，
  容器转为 unhealthy；**修复前的第二次运行 playbook 报 `changed=0`，但系统是坏的**
- 机制：`changed=0` 是相对于 **IaC 里声明的期望状态** 收敛的。当期望状态本身是错的副本时，
  幂等检查会毫发无伤地把这个错误状态一直维持下去
- 推论：
  - **幂等只保证"不再漂移"，不保证"漂向的地方是对的"**
  - **多真源 = 迟早互相覆盖**：同一份配置只允许存在一个源头
  - IaC 的"期望状态"必须与真源一致，而不是与"另一份副本"一致
- 做法：幂等验收之外**必须再加一次业务层验收**（`docker inspect` 的 Health、
  真实 HTTP 响应、业务请求返回码）；两者都过才算完成

### 贯穿六条的元规则

> **每次改完先问一句"我怎么知道它生效了"，然后找一个能证明的观测点。**

> **幂等能保证系统稳定，不能保证系统正确——收敛性验收与正确性验收，缺一不可。**

三天内出现三次同一模式——服务器 `git pull` 静默失败、nginx 未重载、compose 校验失败——
三次都不是"配置写错了"，而是**缺了一次生效性验证**。这也是第 4 周引入 GitOps（ArgoCD）
的直接动机：把"我推了代码"到"集群状态已同步"之间的确认，交给系统而不是人。

---

## 网络约束与中转推送方案（2026-09-24）

### 约束

- **公司网络到 GitHub 的链路间歇性不可用**：`git push` 挂起且无输出；SSH 连通性采样 3/3 失败
- 同一网络下的其他路径稳定：

  | 路径 | 状态 |
  |---|---|
  | 本机 → 阿里云服务器（SSH 2222） | ✅ 稳定 |
  | 阿里云服务器 → GitHub | ✅ 稳定（`git ls-remote` / `git push` 均正常） |

- 附带：Docker Hub（docker.io）直连超时，需走镜像前缀（见《镜像获取途径实测》）

### 方案：以自有服务器做同步中转

```text
本机(WSL) --push--> 阿里云裸仓库 relay --post-receive--> /opt/sre-lab 工作副本 --push--> GitHub
    稳定链路段 ①                        服务器内部                   稳定链路段 ②
```

落地（一次性）：

```bash
# 服务器：建裸仓库作为中转站
git init --bare ~/sre-lab-relay.git

# 本机：登记 remote
git remote add relay lab-node:~/sre-lab-relay.git
```

日常（一条命令）：

```bash
git push relay main
```

钩子 `~/sre-lab-relay.git/hooks/post-receive` 收到推送后自动执行：

```sh
unset GIT_DIR GIT_WORK_TREE
cd /opt/sre-lab
git fetch /root/sre-lab-relay.git main
git merge --ff-only FETCH_HEAD
git push origin main
```

日志：`/var/log/sre-relay.log`

### 踩过的坑（都值得记住）

1. **钩子内必须先 `unset GIT_DIR`**：钩子运行时 `GIT_DIR` 指向裸仓库，
   清理前操作别的仓库会让 git 继续作用于裸仓库
2. **不要用 `git fetch <url> main:main` 更新"已被检出的分支"**：
   git 会拒绝——`fatal: refusing to fetch into branch 'refs/heads/main' checked out at ...`
   → 正确写法是 `git pull --ff-only <url> main`（先抓到 `FETCH_HEAD` 再合并），或抓进临时分支再 merge
3. **钩子是 `post-receive`，失败不会拒绝推送**：relay 已收到提交，但 GitHub / 工作副本可能没同步
   → 推完必须校验：`tail -3 /var/log/sre-relay.log` + `git log --oneline -1`
4. **工作副本有本地改动时 `merge --ff-only` 会失败**：这是有意的安全设计，
   把"服务器不该改文件"的违规暴露出来，而不是静默覆盖

### 为什么不选其他方案

| 方案 | 未采用的原因 |
|---|---|
| 直连 + 自动重试 | 链路整段不可用时重试无效，只是把失败延后 |
| 仅在手机热点下推送 | 可行，但需要随时开热点，不便于日常迭代 |
| 引入 VPN / 第三方代理 | 增加不可控外部依赖，在受限网络中未必可用 |
| 改用 HTTPS + Token 替代 SSH | 没有解决链路本身的不稳定，只换了协议 |

---

## 故障总结：重建控制端引发的连锁故障（2026-09-26）

### 背景

控制端（WSL2）在 2026-09 进水事故中报废后重建。**服务器本体 24 天未动**（`uptime` 24 天），
但新建的控制端带来了与原环境**不同的版本组合**，一天之内连环暴露出 5 个问题。

值得记的是：这 5 个问题**没有一个属于"配置写错了"**——
全部是"环境漂移"或"缺少生效性验证"，与本文档既有的元规则完全同构。

### 时间线

| 时刻 | 事件 | 结果 |
|---|---|---|
| 14:39 | WSL 侧重新 clone 仓库 | ✅ HEAD = `bde67c2`，工作区干净 |
| 15:1x | `ansible lab -m ping` | ❌ `No start of json char found` |
| 15:5x | 目标解释器改为 `python3.11` | ✅ ping 通过 |
| 16:0x | 首次实跑 playbook | ❌ firewalld 模块缺 Python 绑定 |
| 16:2x | firewalld 任务改为命令行调用 | ✅ `changed=1` → `changed=0`，幂等成立 |
| 16:3x | 再次实跑 playbook | ❌ web 容器转 unhealthy，`/healthz` 消失 |
| 16:4x | `git commit` | ❌ `Author identity unknown`，提交被拒 |

### 故障 1：目标机 Python 版本不兼容

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
- **反向验证**：**这类问题无法用 playbook 内的前置断言拦住**——`assert` 本身也是模块，
  同样依赖目标机 Python，而 Python 恰恰是坏掉的那一环。**验证手段必须先于被验证对象可用**
- **教训**：**不要用 `alternatives` 改系统默认 python3**。ALinux3 的 yum/dnf 依赖 3.6，
  改系统默认会连带搞坏包管理；只调整"Ansible 用哪个解释器"

### 故障 2：OS 集成库只绑定在系统 Python 上

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
  但 `--check` 本就不是幂等测试（见方法论 ②），真验收仍是"实跑两次 changed=0"

### 故障 3：IaC 期望状态本身是错的（双真源覆盖）

- **现象**：实跑 playbook 后 `web` 容器转 **unhealthy**；`/healthz` 在容器运行态配置与宿主机配置里**都已消失**；
  业务首页仍返回 **200** —— **静默降级**
- **证据**：
  - `docker inspect web` → `Health=unhealthy`
  - `docker exec web grep healthz /etc/nginx/conf.d/default.conf` → 无匹配
  - 服务器 `git status` → `M nginx/conf.d/default.conf`，`git diff --stat` → **-5 行**
- **根因链**：web 角色把 `ansible/roles/web/files/default.conf`（09-16 版，无 `/healthz`）
  `copy` 覆盖到 `/opt/sre-lab/nginx/conf.d/default.conf`（容器挂载的那份），
  盖掉了 09-24 修好的版本 → handler `reload nginx` 生效 → 健康检查 404
- **最值得记住的一点**：修复前的第二次运行报 `changed=0`，**但系统是坏的**（见方法论 ⑥）
- **修复**：先合并双真源（Ansible 侧对齐线上那份）并提交推送，
  再跑 playbook 把正确配置写回；服务器上的 `M` 由 IaC 自己消除，
  而不是手工 `git checkout` 抹平——这样"修好"这件事本身也走了 IaC 路径
- **教训**：**多真源 = 迟早互相覆盖**。同一份配置只允许存在一个源头

### 故障 4：控制端未配 git 身份，提交被拒

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

### 故障 5：relay 裸仓库 HEAD 指向不存在的分支

- **现象**：`git -C /root/sre-lab-relay.git log` 返回 exit 128
- **根因**：`git init --bare` 时默认分支为 `master`，HEAD 指向 `refs/heads/master`；
  而实际推送的分支是 `main` → 该 ref 不存在
- **影响**：post-receive 钩子使用**显式** `main`，故推送链路不受影响；
  但 `clone` / `log` 等走 HEAD 的操作会报错
- **修复**：`git -C <裸仓库> symbolic-ref HEAD refs/heads/main`
- **教训**：**"暂时无害"的配置缺陷最容易累积成事故**——它今天不咬人，不代表明天不咬

### 本次沉淀

1. 新增方法论 **⑥ 幂等 ≠ 正确**，已并入上方"方法论沉淀"章节
2. 一次控制端重建暴露 5 个不同类型的根因，**没有一个属于"配置写错了"**
3. 故障 3 是由容器 healthcheck 捕获的（09-24 修复的成果），**但无人被告知** ——
   直接印证第 2 周主线：**有观测能力 ≠ 有通知能力，告警必须上线**
4. 复发防线已前移：目标解释器模板、firewalld 调用方式、git 身份、relay HEAD
   四项均已修正，下次重建不会再逐条重踩
