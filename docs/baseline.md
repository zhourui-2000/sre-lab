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

## 故障记录：WSL 控制端网络中断（2026-09-12）

- 现象：`git push` 无限挂起；`curl` 报 `Failed to connect ... after 7 ms`
- 诊断：7ms 即失败说明请求未发出，非超时；Windows 宿主网络正常 → 定位为 WSL 虚拟网卡故障
- 处理：`wsl --shutdown` 重建网络栈
- 结论：控制端与被管机分离后，控制端可用性成为单点；后续需考虑本地仓库定期推送备份

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

