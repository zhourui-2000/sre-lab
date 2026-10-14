# 基线（Baseline）

> 用途：记录**当前已知良好状态**与**不可违反的前提**。只随实测变化而更新，不记录过程。
> 故障过程见 [`incidents/`](incidents/)，经验规则见 [`methodology.md`](methodology.md)，设计决策见 [`adr/`](adr/)。

## 一、系统资源

测量于 2026-09-12（第一周加固完成后、可观测栈部署前）。

| 指标 | 基线值 | 测量命令 |
|---|---|---|
| 内存 总/已用/可用 | 1870 / 471 / **1399 MB** | `free -m` |
| Swap 总/已用 | 2047 / 59.6 MB | `swapon --show` |
| 磁盘水位 | 7.1G / 40G = **19%** | `df -h /` |
| journald 占用 | **32.0 MB**（限额 500M 已生效） | `journalctl --disk-usage` |
| 镜像拉取耗时 | 2.2s（加速器生效） | `time docker pull nginx:alpine` |

**容量结论：磁盘不是瓶颈（19%），内存才是。**
简历故事应聚焦内存容量治理 —— **"磁盘水位下降"这条不成立，不要硬写**（详见第五节与 `capacity.md`）。

## 二、安全

| 指标 | 基线值 |
|---|---|
| fail2ban 累计失败认证 | 5858 次 |
| 累计自动封禁 IP | 52 个 |
| 成功入侵次数 | 0（密钥认证，密码登录已关闭） |
| SSH 端口 | 2222（非 22） |

防护层次：云安全组 + 密钥认证 + 非标准端口 + fail2ban，共**四层**。

## 三、不变量（绝不违反）

- **部署路径 `/opt/sre-lab`**（旧文档中的 `/root/sre-lab` 已作废）。
- **服务器只 pull，不改文件**。出现 `M` 状态文件即是红灯，必须先处理再谈部署。
- **Ansible 目标解释器固定 `/usr/bin/python3.11`**；**永不改系统默认 python3**（ALinux3 的 yum/dnf 依赖 3.6）。
- **端口一律绑 `127.0.0.1`**，不暴露 `0.0.0.0`。
- **同一份配置只允许一个真源**（多真源 = 迟早互相覆盖）。
- **镜像固定版本标签**，禁用浮动标签（`:latest` / `:alpine`）。
- **构建产物不进版本控制**（`*.tar` 等）。
- **密钥配置放 `/root/.sre-lab-secrets/`**：目录 `700` + 文件 **`644`**。
  ⚠️ **绝不 `chmod 600`** —— 容器以 `nobody` 运行会读不到而 crash loop。
  保护来自**目录不可穿越**，可读性来自 644。见 [ADR 0002](adr/0002-secret-file-permissions.md)。
- **改了被挂载的配置文件，必须 `docker compose up -d --force-recreate <svc>`**。
  普通 `up -d` 只比较服务定义、不比较挂载内容，**是 no-op**（见 [methodology ⑪](methodology.md)）。
- **控制端仓库不得有 group/other 可写位**（`find /root/sre-lab -perm -o+w` 应为 0）。
  跨文件系统拷贝不保留权限、会回落 `0777`，而 Ansible 会因此**静默忽略** `ansible.cfg` ——
  不报错、只降级（见 [methodology ⑭](methodology.md)）。
- **Grafana 数据源与面板必须 provisioned**（代码在 `observability/grafana/`）。
  不接受"只存在 `grafana.db` 里"的状态 —— 删容器即丢，且无法 code review。
  迁移时 `name` / `uid` 必须沿用原值，否则既有面板的 `ds_prometheus` 变量解析不到数据源。
- **站点备份脚本与定时任务必须在 IaC 内**（`ansible/roles/web/`）。
  `/usr/local/bin/site-backup.sh` 与 `/etc/cron.d/site-backup` 此前游离在 Ansible 之外，
  **重建机器即丢**。
- **日志链路 = Loki（存储）+ Alloy（采集）**，两者版本由 `observability/.env` 固定。
  ⚠️ **不得回退到 promtail** —— 它已于 2026-03-02 EOL（见 [ADR 0004](adr/0004-promtail-eol-alloy.md)）。
- **容器内监听地址与宿主侧绑定是两回事**：需要被宿主访问的服务，**容器内必须绑 `0.0.0.0`**，
  收口靠宿主侧写 `127.0.0.1::`。
  ⚠️ 容器内绑 `127.0.0.1` 会让端口映射失效（2026-10-14 实测：Alloy 因此 `/metrics` 返回 **HTTP 000**）。
- **Loki 数据目录属主必须是 10001**（镜像以 uid 10001 运行）。
  `./loki-data` 若由 Docker 自动创建会成为 root 属主，**Loki 起不来**。固定动作见 runbook。
  ⚠️ Loki 3.6+ 镜像**不含 shell**，排障判据是 `curl 127.0.0.1:3100/ready` 与 `docker logs loki`，
  不是 `docker exec loki sh`。
- **防火墙持久配置必须等于 IaC 声明**（真源 = `ansible/roles/security/tasks/main.yml` 的 loop）。
  核对命令：`python3 scripts/check-fw-drift.py`。
  ⚠️ 该角色是**增量式**的（只 `--add-*`，**从不删除**）—— 服务器上手加的规则 playbook 既不会撤销、
  也不会报错，漂移会静默存活到重建那天（2026-10-14 实测：`trusted` 区多出 `192.168.0.0/16`，
  来自 09-16 的手工命令，游离 28 天未被发现）。
- **k3s 的 Pod / Service 网段 `10.42.0.0/16` / `10.43.0.0/16` 必须在 trusted 区，且由 IaC 管理**。
  ⚠️ **`6443/tcp` 刻意不对外开放**：单节点没有外部节点需要访问 apiserver，
  k3s 官方文档的 `--add-port=6443/tcp` 是给多节点集群的，照抄等于在公网开一个 API 端点。
  收口靠 firewalld + 云安全组，并实测外部不可达。
- **文件权限也是配置的一部分，且以「索引里记录的模式」为准**。
  `core.fileMode` 必须为 `true`（跨文件系统迁移会让 git 自动关掉它）；
  否则 `chmod +x` 不会入索引，**重建出来的机器上脚本不可执行**。
  验收用 `git clone` 实测磁盘权限（见 [methodology ⑯](methodology.md)）。
- **判断远端状态必须用实时查询**（`git ls-remote`，带重试），
  **不得使用 `origin/main` 等本地缓存引用**；验证命令**不得吞 stderr**（`2>/dev/null`）——
  那会让失败伪装成结论（2026-10-14 一天内三次踩到，见 [methodology ⑯](methodology.md)）。

## 四、环境前提

- **控制端工具链**：`ansible-core 2.17.14` + Python 3.10.6（Ubuntu 22.04.1 的可用最高线）。
  ⚠️ 原控制端为 `ansible-core 2.20.1` / Python 3.14；**ansible-core ≥2.18 要求控制端 Python ≥3.11**，
  在 3.10 上装不了。控制端重建后**必须重新确认**，不能照抄旧记录。
- **SELinux = Disabled**（阿里云镜像预设，`semanage` 已装）。sshd 监听 2222 无需端口标签。
  ⚠️ 若重建于默认 Enforcing 的环境（官方 ISO 安装的标准发行版），sshd 绑定 2222 会 bind 失败导致无法远程登录；
  需 `semanage port -a -t ssh_port_t -p tcp 2222`。
  现状决策：暂不启用 SELinux（学习环境，已有四层防护）。
- **镜像获取**：`registry-mirrors` **只对 docker.io 生效**；直连 `registry-1.docker.io` 超时。
  daocloud 前缀实测可用：`docker.m.daocloud.io/`（quay.io / ghcr.io 需 `quay.m.daocloud.io` / `ghcr.m.daocloud.io`）。
- **网络**：公司网络 → GitHub 链路间歇不可用；本机 → 服务器、服务器 → GitHub 均稳定。
  推送走服务器中转，见 [`adr/0001-server-relay-push.md`](adr/0001-server-relay-push.md)。
- **出网端口**：阿里云封 **25**，`smtp.qq.com:465` / `:587` 均**可达**（发告警邮件已验证）。

## 五、可观测栈实测

部署于 2026-09-16；配额收紧决策见 `capacity.md`。

| 容器 | 配额 | 实测占用 | 利用率 |
|---|---|---|---|
| node-exporter | 64MB | 19.4MB | 30% |
| grafana | 256MB | 116.5MB | 46% |
| victoriametrics | 256MB | 94.4MB | 37% |
| web (nginx) | 128MB | 2.96MB | 2.3% |

**可观测栈合计约 230MB**，远低于预估的 576MB。部署后：可用内存 1143MB（看 available 而非 free）、磁盘 19%。

**2026-10-09 复测**（已加入 vmalert + alertmanager，容器数 4 → 6）：

| 指标 | 09-16 | 10-09 |
|---|---|---|
| 可用内存 | 1143 MB | **1212 MB** |
| 磁盘水位 | 19% | **25%**（9.2G / 40G，镜像与数据增长） |

**k3s 决策**：以 10-09 为准，1212 − 750 ≈ 462MB 余量 → 仍可行，但安装时须禁用内置
traefik / servicelb / metrics-server。（当前仍接近空载，上 k3s 前需再做一次峰值复测。）

**2026-10-14 复测（Phase D 收口）**：可用内存 **1161 MB**、磁盘 **25%**（9.2G / 40G，可用 29G）、
容器 6 个合计约 **250 MiB**。**Loki + promtail 按 160 MB 预算 → 1161 − 160 ≈ 1000 MB**，
上 k3s 后余量约 **250 MB**（比 10-09 测算的 462 MB 紧）。
实测数据与 Loki 可行性论证见 [`capacity.md`](capacity.md)。

**2026-10-14 日志层实测**（Loki 3.7.8 + Alloy v1.20.1，采集端因 promtail EOL 而改用 Alloy）：
8 个容器实测合计 **440 MiB**，其中日志层 **218.5 MiB**（loki 143.5 + alloy 75.0）；
**available 1161 → 1020 MB**。**k3s 判据：1020 − 750 ≈ 270 MB 余量 → 可以上 k3s。**
⚠️ 结构性隐患：8 个容器 `mem_limit` 之和 **1216 MB > available 1020 MB**（见 [`capacity.md`](capacity.md)）。
镜像合计 866 MB → 磁盘 **27%**；loki-data 实测 605.5 KB / 48 min ≈ 18 MB/日。

## 六、待补基线

- 手工部署一次耗时（停服 → 替换 → 启动 → 验证，掐表）
- **blackbox-exporter（外部可用性拨测）**：暂缓至 Week 5-6（SLO 阶段）。
  理由与被否方案见 [ADR 0003](adr/0003-blackbox-exporter-deferred.md) ——
  **引入时必须与消费它的告警规则同批提交**，否则当天就是新的死变量。
- 可观测栈**满负载**峰值内存（10-09 复测为空载数据，不足以定配额）
- GitOps 部署耗时（第 4 周）
- 各类故障 MTTR、RTO/RPO（第 7 周）

## 七、故障索引

| 日期 | 事件 | 根因一句话 | 详情 |
|---|---|---|---|
| 09-12 | GitHub 推送间歇失败 | 公司网络到 GitHub 链路不稳（曾误归因 WSL 网卡） | [→](incidents/2026-09-12-github-push-flaky.md) |
| 09-14 | Docker Hub 不可达 | docker.io 被限，quay.io 正常 | [→](incidents/2026-09-14-dockerhub-unreachable.md) |
| 09-16 | 采集链路 `up` 恒为 0 | firewalld 拦截容器间转发 | [→](incidents/2026-09-16-firewalld-blocks-scrape.md) |
| 09-16 | `git push` 被拒：超大文件 | 镜像 tar 误入 Git | [→](incidents/2026-09-16-image-tar-in-git.md) |
| 09-16 | nginx 崩溃循环 | `http2 on;` 需 1.25+，镜像为旧版 | [→](incidents/2026-09-16-nginx-http2-directive.md) |
| 09-22 | sshd 加固改动不生效 | lineinfile 命中注释块的缩进行 | [→](incidents/2026-09-22-sshd-lineinfile.md) |
| 09-24 | 改了配置却不生效 | git pull 静默失败（服务器有本地改动） | [→](incidents/2026-09-24-git-pull-silent-fail.md) |
| 09-24 | healthcheck 恒 unhealthy | `localhost` 解析到 IPv6，nginx 只听 IPv4 | [→](incidents/2026-09-24-web-healthcheck-ipv6.md) |
| 09-26 | 控制端重建连锁故障 | 环境漂移 + 缺生效性验证（5 个根因） | [→](incidents/2026-09-26-control-node-rebuild.md) |
| 10-09 | ALERTS 恒空、告警静默 | 缺 `--remoteWrite.url` + alertmanager 未定义 | [→](incidents/2026-10-09-alert-chain-silent.md) |
| 10-09 | 通知渠道再三踩坑 | `up -d` no-op / `smtp_from` 拼错 / 属主 / `chmod 600` | [→](incidents/2026-10-09-alert-chain-silent.md#第二阶段接通通知渠道) |
| 10-14 | 控制端迁移后 Ansible 静默失效 | 权限回落 `0777`，Ansible 拒读全局可写目录下的配置 | [→](incidents/2026-10-14-migration-perms-ansible-cfg.md) |
| 10-14 | 防火墙持久配置漂移 28 天 | 增量式 IaC 只加不删；回填 IaC 时凭记忆漏了一条 | [→](incidents/2026-10-14-firewall-drift-incremental-iac.md) |
| 10-14 | 可执行位未进版本控制 / GitHub 状态被误判 | 缓存与索引被当成事实；核验命令吞掉了 stderr | [→](incidents/2026-10-14-indirect-evidence-as-fact.md) |
