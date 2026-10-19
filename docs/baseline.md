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

- **宿主必须是 cgroup v2**（判据：`stat -fc %T /sys/fs/cgroup` = `cgroup2fs`）。
  ⚠️ **Kubernetes v1.35+ 的 kubelet 在 cgroup v1 主机上直接退出**（不是降级、不是警告），
  k3s v1.37.1 同样强制。这条**比内存更硬**：内存不够可以换轻量发行版，
  cgroup 版本不对，什么发行版都起不来（2026-10-15 实测：安装脚本 `exit=0`、`k3s --version` 正常，
  但服务每 14 秒自杀一次，无限循环）。
  开关在 `/boot/grub2/grubenv` 的 `kernelopts` 变量（BLS 条目只写 `options $kernelopts $tuned_params`），
  用 `grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"` 修改，
  并同步写 `/etc/default/grub` 防将来 `grub2-mkconfig` 重新生成时丢参数。
  详见 [incidents/2026-10-15-cgroup-v1-blocks-kubelet.md](incidents/2026-10-15-cgroup-v1-blocks-kubelet.md)。

- **内存 / 组件成本以 cgroup 实测为准，`requests` / `limits` 之和不是成本**。
  在 k8s 里尤其如此：组件的**大头往往在控制面**（apiserver 的 watch cache），不在它自己的 Pod 里。
  2026-10-17 实测 ArgoCD：4 个 Pod 合计约 **83 MiB**，但 `available` 掉了约 **135 MB**、
  swap 涨了约 **114 MB** —— **真实成本 ≈ Pod 占用的 3 倍**。
  估算任何 k8s 组件一律按这个口径，详见 [`capacity.md`](capacity.md)。

- **一个服务有几个对外入口，就有几套判据；健康检查必须矩阵化验证**。
  同一份 nginx 配置里，`:80` 与 `:443`、裸域与 www 的 location 集合**可以完全不同**。
  2026-10-19 实测：`http://…/healthz` = 200，但规范化后的
  `https://zhourui2000.online/healthz` = **404**（443 裸域块缺该 location）。
  **单点通过会被读成"服务健康"，而真正的访问路径是坏的。**
  判据用 `scripts/check-endpoints.py`（7 个入口 × 第一跳 + 跟随终态），
  见 [incidents/2026-10-19-healthz-missing-on-canonical-https.md](incidents/2026-10-19-healthz-missing-on-canonical-https.md)。

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

- **cgroup 版本 = v2**（2026-10-15 用 `systemd.unified_cgroup_hierarchy=1` + 重启切换）。
  宿主内核 `5.10.134-19.8.al8`（Alibaba Cloud Linux 3，**出厂默认 cgroup v1**）、systemd 239。
  ⚠️ **v2 下没有 `memory.swappiness` 这个 cgroup 文件**（v2 改用 `memory.swap.max`）——
  这意味着 systemd 服务不再被强制 `swappiness=60` 覆盖全局的 `vm.swappiness=10`，
  「保留 swap 并监测」的取舍终于和配置意图一致（cgroup v1 下该意图对**所有** systemd 服务无效）。
  ⚠️ **v2 下 docker 的 `mem_limit` 只限内存**，swap 由独立的 `memory.swap.max` 管（默认不限）——
  容器更容易用 swap：OOM 风险下降，换页延迟代价上升。
  ⚠️ 5.10 内核的 tmpfs **不支持 `noswap` 选项**，kubelet 启动时打
  `error mounting tmpfs with the noswap option. Assuming not supported` 后继续 ——
  意味着 **kubelet 无法为 Pod 保证"不使用 swap"**。

- **`helm` 不会自动继承 k3s 的 kubeconfig**。k3s 写在 `/etc/rancher/k3s/k3s.yaml`
  （`mode 600`，即 `write-kubeconfig-mode: "0600"` 的结果），`~/.kube/config` **不存在**。
  `k3s kubectl` 自带配置所以能连；`helm` 走标准发现流程，**找不到就退回 `localhost:8080`**，
  报出极具误导性的 `Kubernetes cluster unreachable: dial tcp [::1]:8080`。
  → 脚本里显式 `export KUBECONFIG=/etc/rancher/k3s/k3s.yaml`；
  **不在服务器上建 `~/.kube/config` 软链**（手工产物 = 漂移），
  要开箱可用须把软链声明进 `ansible/roles/k3s/`（`file: state=link`）。
- **外部 registry 依赖必须有兜底端点，且顺序即优先级**。`registries.yaml` 的 `endpoint`
  是从上到下尝试的列表；只写一个 mirror，等于把整个集群的拉镜像能力绑在单一服务的可用性上。
  2026-10-17：daocloud 的 docker.io 端点间歇 502 → `redis` 拉不到 → helm `--wait` 超时 12 分钟。
  现为 `dockerproxy.net` 优先 + daocloud 兜底，见
  [incidents/2026-10-17-registry-mirror-502.md](incidents/2026-10-17-registry-mirror-502.md)。
  **改完必须 `systemctl restart k3s`** —— `registries.yaml` 只在启动时渲染成
  `certs.d/<registry>/hosts.toml`，判据要落在渲染产物上，不是源文件。

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
镜像合计 866 MB → 磁盘 **27%**。
⚠️ **原记「loki-data 605.5 KB / 48 min ≈ 18 MB/日」已作废**：那个窗口含 Alloy 首启回灌 12h
journal 积压，是**启动期突发**而非稳态。37 小时实测约 **1.94 MB/日**，详见 `capacity.md`。

---

## 六、k3s 与集群组件实测（2026-10-17 · 稳定运行 36 小时后）

| 指标 | 实测 |
|---|---|
| 版本 / 拓扑 | **k3s v1.37.1+k3s1**，单节点（`ROLES=control-plane`） |
| 控制面 `MemoryCurrent` | **575.4 / 577.6 MiB**（两次采样） |
| Pod 侧 `kubepods.slice` | **44.8 / 51.0 MiB** |
| **合计** | **≈ 620–630 MiB** |
| 系统 Pod | 3 个（`coredns` Running、`local-path-provisioner` Running、`helm-install-gateway-api-crd` Completed） |
| CRD | **14 个全部 `Established=True`**（含 k3s v1.37 新增的 gateway-api 11 个） |
| 磁盘 | `/var/lib/rancher` **727 MB**；`/` **30%** |
| 启动后水位 | available **594–597 MB**、swap 已用 **203.5 MB** |

⚠️ **口径提醒**：`systemctl show k3s -p MemoryCurrent` **不含 Pod** ——
kubelet 把 Pod 放在**与 `k3s.service` 同级**的 `/kubepods.slice`，只读 `MemoryCurrent` 会少算约 50 MiB。

**750 MB 估算至此退役**：实测比它低约 16–17%，方向没错但偏保守。
详见 [`capacity.md`](capacity.md)。

### ArgoCD（GitOps）实测（2026-10-19 · 落地两天后）

部署形态：k3s 内、命名空间 `argocd`、Helm chart `argo-cd` 10.10.5（ArgoCD v3.5.5）、
关 dex / notifications、`applicationSet.replicas: 0`、ClusterIP + 两层端口转发（不开 NodePort）。

| 判据 | 实测 |
|---|---|
| helm release | `REVISION 2 / deployed` |
| 常驻 Pod | 4 个，全 `1/1 Running`（`applicationset-controller` 为 `0/0`，设计如此） |
| Application `hello` | **Synced / Healthy**，revision 与仓库 HEAD 一致（`0abc9d2`） |
| **self-heal** | 删 Pod → 新 Pod 在 **≤36 秒**内重建（ReplicaSet hash 不变、suffix 变化） |
| **drift 纠正** | `scale --replicas=3` → 数秒内 `OutOfSync` → 自动 scale 回 1，事件可见 `Scaled down replica set from 3 to 1` |
| `kubepods.slice` | `max=0`、`oom_kill=0`（两天） |
| `argocd-server` 重启 2 次 | **liveness 探测超时 → SIGTERM → 优雅退出（exit 0）**，非 OOM、非崩溃 |

**成本**（详见 [`capacity.md`](capacity.md)）：

- Pod 合计约 **83 MiB**，但 `available` 掉约 **135 MB**、swap 涨约 **114 MB**
  → **真实成本 ≈ Pod 占用的 3 倍**（差额在 apiserver 的 watch cache）
- `application-controller` 是唯一持续长大的：27.7 → 80.6 → **126.2 MiB**（占 limit 49%）
- 两天稳态 `available` **338 MB**、swap **550 MB**（414 → 550，是唯一持续恶化的指标）

**结论：A 方案成立，但已到边界 —— 再加 k8s 侧组件前必须先升配 4G。**

## 七、待补基线

- 手工部署一次耗时（停服 → 替换 → 启动 → 验证，掐表）
- **blackbox-exporter（外部可用性拨测）**：暂缓至 Week 5-6（SLO 阶段）。
  理由与被否方案见 [ADR 0003](adr/0003-blackbox-exporter-deferred.md) ——
  **引入时必须与消费它的告警规则同批提交**，否则当天就是新的死变量。
- 可观测栈**满负载**峰值内存（10-09 复测为空载数据，不足以定配额）
- ~~GitOps 部署耗时（第 4 周）~~ → **已完成**：ArgoCD 首次安装到 4 Pod 就绪约 34 分钟
  （其中 **12 分钟是镜像拉取超时白等**，见事故记录）；首次同步 **12 秒**。详见 [`capacity.md`](capacity.md)。
- 各类故障 MTTR、RTO/RPO（第 7 周）

## 八、故障索引

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
| 10-15 | k3s 装完却无限重启 | 宿主 cgroup v1，而 k8s v1.35+ 的 kubelet 直接拒绝在 v1 上启动 | [→](incidents/2026-10-15-cgroup-v1-blocks-kubelet.md) |
| 10-15 | k3s 起来了但集群 0 Pod | 一个 CRD 停在 `Installing` —— 崩溃循环期间被写入的中间态 | [→](incidents/2026-10-15-crd-stuck-installing.md) |
| 10-17 | ArgoCD 装上但 `redis` 一直 ImagePullBackOff | 镜像源的 docker.io 端点**间歇 502**；`/v2/` 探活正常**也不代表**能下 blob | [→](incidents/2026-10-17-registry-mirror-502.md) |
| 10-19 | 健康检查在规范化 HTTPS 入口上 404 | 只验了 http 入口；www→裸域的 301 之后那个 server 块缺 `location = /healthz` | [→](incidents/2026-10-19-healthz-missing-on-canonical-https.md) |
