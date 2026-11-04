# 基线

记录当前**已知良好状态**与**不可违反的前提**。只随实测变化而更新，不记过程。故障见 [`incidents/`](incidents/)，规则见 [`methodology.md`](methodology.md)，决策见 [`adr/`](adr/)。

## 一、系统资源

测量于 2026-09-12（加固完成、可观测栈部署前）。

| 指标 | 基线值 | 命令 |
|---|---|---|
| 内存 总/已用/可用 | 1870 / 471 / **1399 MB** | `free -m` |
| Swap 总/已用 | 2047 / 59.6 MB | `swapon --show` |
| 磁盘水位 | 7.1G / 40G = **19%** | `df -h /` |
| journald 占用 | **32.0 MB**（限额 500M 生效） | `journalctl --disk-usage` |
| 镜像拉取耗时 | 2.2s（加速器生效） | `time docker pull nginx:alpine` |

**容量结论：磁盘不是瓶颈，内存才是。** 简历故事聚焦内存容量治理；"磁盘水位下降"不成立，不要写。

## 二、安全

| 指标 | 值 |
|---|---|
| fail2ban 累计失败认证 | 5858 次 |
| 累计自动封禁 IP | 52 个 |
| 成功入侵 | 0（密钥认证，密码登录已关闭） |
| SSH 端口 | 2222 |

防护四层：云安全组 + 密钥认证 + 非标准端口 + fail2ban。

## 三、不变量

**部署与权限**

- 部署路径 `/opt/sre-lab`（旧文档的 `/root/sre-lab` 已作废）。服务器只 pull，不改文件；出现 `M` 状态即红灯。
- Ansible 目标解释器固定 `/usr/bin/python3.11`，永不改系统默认 `python3`（ALinux3 的 yum/dnf 依赖 3.6）。
- 端口一律绑 `127.0.0.1`，不暴露 `0.0.0.0`。容器内监听与宿主绑定是两回事：需被宿主访问的服务容器内必须绑 `0.0.0.0`，收口靠宿主侧 `127.0.0.1::`。容器内绑 `127.0.0.1` 会让端口映射失效（10-14 实测：Alloy `/metrics` 返回 **HTTP 000**）。
- 同一份配置只允许一个真源。镜像固定版本标签，禁用 `:latest` / `:alpine`。构建产物（`*.tar`）不进版本控制。
- 密钥配置放 `/root/.sre-lab-secrets/`：目录 `700` + 文件 **`644`**。**绝不 `chmod 600`**，容器以 `nobody` 运行会读不到而 crash loop；保护来自目录不可穿越，见 [ADR 0002](adr/0002-secret-file-permissions.md)。
- 文件权限以「索引里记录的模式」为准：`core.fileMode` 必须为 `true`。否则 `chmod +x` 不入索引，重建出的机器上脚本不可执行。验收用 `git clone` 实测。
- 控制端仓库不得有 group/other 可写位：`find /root/sre-lab -perm -o+w` 应为 0。跨文件系统拷贝会回落 `0777`，Ansible 会因此静默忽略 `ansible.cfg`（方法论 ⑭）。
- 防火墙持久配置必须等于 IaC 声明（真源 = `ansible/roles/security/tasks/main.yml` 的 loop），核对用 `python3 scripts/check-fw-drift.py`。该角色是**增量式**的（只 `--add-*`，从不删除），手加规则 playbook 既不撤销也不报错（10-14 实测：`trusted` 区多出 `192.168.0.0/16`，来自 09-16 手工命令，游离 28 天）。
- k3s 的 `10.42.0.0/16` / `10.43.0.0/16` 必须在 trusted 区且由 IaC 管理。**`6443/tcp` 刻意不对外**：单节点没有外部节点需要访问 apiserver，官方文档的 `--add-port=6443/tcp` 是给多节点集群的，照抄等于在公网开一个 API 端点。
- 站点备份脚本与定时任务必须在 IaC 内（`ansible/roles/web/`）。`/usr/local/bin/site-backup.sh` 与 `/etc/cron.d/site-backup` 此前游离在 Ansible 外，重建即丢。
- Grafana 数据源与面板必须 provisioned（代码在 `observability/grafana/`），不接受"只存在 `grafana.db` 里"；迁移时 `name` / `uid` 必须沿用原值，否则既有面板的 `ds_prometheus` 变量解析不到数据源。
- 改了被挂载的配置文件必须 `docker compose up -d --force-recreate <svc>`；普通 `up -d` 只比较服务定义，是 no-op（方法论 ⑪）。

**判据与状态**

- 判断远端状态必须用实时查询（`git ls-remote`，带重试），不得用 `origin/main` 等本地缓存引用；验证命令不得吞 stderr（`2>/dev/null`），那会让失败伪装成结论（10-14 一天内三次，方法论 ⑯）。
- 一个服务有几个对外入口就有几套判据，健康检查必须矩阵化验证。10-19 实测 `http://…/healthz` = 200，而规范化后的 `https://zhourui2000.online/healthz` = **404**（443 裸域块缺该 location）。判据用 `scripts/check-endpoints.py`（7 入口 × 第一跳 + 跟随终态）。
- SLO 的 SLI 只允许一个探针目标，多目标混算则烧钱率无法归因。其他入口另立 `blackbox_follow` job，只做存在性检查，不参与可用性数字。
- 「探针挂了」与「站点挂了」必须分开告警。`avg_over_time` 跳过空洞，探针一挂 SLI 就停在最后一个值；无数据既不是 0% 也不是 100%。兜底靠 `ProbePipelineDown`（`up{job=~"blackbox.*"}==0`）与 `SloNoData`，两条都不依赖 SLI 的分母。

**运行时前提**

- 宿主必须是 cgroup v2（`stat -fc %T /sys/fs/cgroup` = `cgroup2fs`）。**k8s v1.35+ 的 kubelet 在 cgroup v1 上直接退出**，k3s v1.37.1 同样强制。这条比内存更硬：内存不够可换轻量发行版，cgroup 版本不对什么发行版都起不来（10-15 实测：安装脚本 `exit=0`、`k3s --version` 正常，但服务每 14 秒自杀，无限循环）。
  开关在 `/boot/grub2/grubenv` 的 `kernelopts`，用 `grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"` 修改，并同步写 `/etc/default/grub` 防 `grub2-mkconfig` 重生成时丢参数。见 [cgroup 事故](incidents/2026-10-15-cgroup-v1-blocks-kubelet.md)。
- 内存与组件成本以 cgroup 实测为准，`requests`/`limits` 之和不是成本。k8s 里大头常在控制面（apiserver 的 watch cache）。10-17 实测 ArgoCD：4 Pod 合计约 **83 MiB**，但 `available` 掉约 **135 MB**、swap 涨约 **114 MB**，真实成本 ≈ Pod 占用的 **3 倍**。估算任何 k8s 组件一律按此口径。
- 日志链路 = Loki（存储）+ Alloy（采集），版本由 `observability/.env` 固定。不得回退 promtail（2026-03-02 EOL，见 [ADR 0004](adr/0004-promtail-eol-alloy.md)）。
- Loki 数据目录属主必须是 10001。`./loki-data` 若由 Docker 自动创建会成为 root 属主，Loki 起不来。Loki 3.6+ 镜像不含 shell，判据是 `curl 127.0.0.1:3100/ready` 与 `docker logs loki`，不是 `docker exec loki sh`。

## 四、环境前提

| 项 | 值 | 备注 |
|---|---|---|
| 控制端工具链 | `ansible-core 2.17.14` + Python 3.10.6 | Ubuntu 22.04.1 的可用最高线。原为 2.20.1 / Python 3.14；**≥2.18 要求 Python ≥3.11**，3.10 上装不了，重建后必须重新确认 |
| SELinux | Disabled（阿里云镜像预设，`semanage` 已装） | 若重建于 Enforcing 环境，sshd 绑 2222 会 bind 失败导致无法登录，需 `semanage port -a -t ssh_port_t -p tcp 2222` |
| 内核 / systemd | `5.10.134-19.8.al8` / 239 | 出厂默认 cgroup v1，已切 v2 |
| 镜像源 | `registry-mirrors` 只对 docker.io 生效 | daocloud 前缀可用：`docker.m.daocloud.io/`（quay / ghcr 同理）；直连 `registry-1.docker.io` 超时 |
| 网络 | 公司网络 → GitHub 间歇不可用；本机 → 服务器、服务器 → GitHub 稳定 | 推送走服务器中转，见 [ADR 0001](adr/0001-server-relay-push.md) |
| 出网端口 | 阿里云封 25；`smtp.qq.com:465` / `:587` 可达 | 告警邮件已验证 |

**cgroup v2 的三条连带影响**

- v2 下没有 `memory.swappiness`（改用 `memory.swap.max`）。systemd 服务不再被强制 `swappiness=60` 覆盖全局的 `vm.swappiness=10`，「保留 swap 并监测」的取舍才与配置意图一致（v1 下该意图对所有 systemd 服务无效）。
- v2 下 docker 的 `mem_limit` 只限内存，swap 由独立的 `memory.swap.max` 管（默认不限）。容器更容易用 swap：OOM 风险下降，换页延迟代价上升。
- 5.10 内核的 tmpfs 不支持 `noswap`，kubelet 启动时打 `error mounting tmpfs with the noswap option` 后继续，kubelet 无法为 Pod 保证"不使用 swap"。

**其余两条**

- `helm` 不继承 k3s 的 kubeconfig。k3s 写 `/etc/rancher/k3s/k3s.yaml`（`write-kubeconfig-mode: "0600"`），`~/.kube/config` 不存在；`k3s kubectl` 自带配置能连，`helm` 走标准发现流程找不到就退回 `localhost:8080`，报 `Kubernetes cluster unreachable: dial tcp [::1]:8080`。脚本里显式 `export KUBECONFIG=/etc/rancher/k3s/k3s.yaml`；不在服务器上建 `~/.kube/config` 软链（手工产物 = 漂移），要开箱可用须声明进 `ansible/roles/k3s/`。
- 外部 registry 依赖必须有兜底端点，顺序即优先级。`registries.yaml` 的 `endpoint` 从上到下尝试，只写一个 mirror 等于把集群拉镜像能力绑在单一服务上。10-17：daocloud 的 docker.io 端点间歇 502，`redis` 拉不到，helm `--wait` 超时 12 分钟。现为 `dockerproxy.net` 优先 + daocloud 兜底。改完必须 `systemctl restart k3s`（`registries.yaml` 只在启动时渲染成 `certs.d/<registry>/hosts.toml`，判据落在渲染产物上）。

## 五、可观测栈实测

部署于 2026-09-16。

| 容器 | 配额 | 实测占用 | 利用率 |
|---|---|---|---|
| node-exporter | 64MB | 19.4MB | 30% |
| grafana | 256MB | 116.5MB | 46% |
| victoriametrics | 256MB | 94.4MB | 37% |
| web (nginx) | 128MB | 2.96MB | 2.3% |

合计约 **230MB**，远低于预估的 576MB。部署后可用内存 1143MB（看 `available` 不看 `free`）、磁盘 19%。

| 时点 | 可用内存 | 磁盘 | 容器合计 | 备注 |
|---|---|---|---|---|
| 09-16 | 1143 MB | 19% | 4 个 / 230 MB | 基线 |
| 10-09 | **1212 MB** | **25%**（9.2G） | 6 个 / 250 MiB | 加入 vmalert + alertmanager |
| 10-14 | **1161 MB** | 25%（可用 29G） | 8 个 / 440 MiB | 含日志层 218.5 MiB（loki 143.5 + alloy 75.0）；available 1161 → 1020 |

**k3s 判据演进**：10-09 按 1212 − 750 ≈ 462 MB 余量判可行；10-14 按 1020 − 750 ≈ 270 MB 判可行，比前者紧。安装时须禁用内置 traefik / servicelb / metrics-server。上 k3s 前需再做一次峰值复测。

10-14 结构性隐患：8 个容器 `mem_limit` 之和 **1216 MB > available 1020 MB**（见 [`capacity.md`](capacity.md)）。镜像合计 866 MB，磁盘 27%。

原记「loki-data 605.5 KB / 48 min ≈ 18 MB/日」**已作废**：那个窗口含 Alloy 首启回灌 12h journal 积压，是启动期突发。37 小时实测约 **1.94 MB/日**。

## 六、k3s 与集群组件实测

**k3s（2026-10-17，稳定运行 36 小时后）**

| 指标 | 实测 |
|---|---|
| 版本 / 拓扑 | `v1.37.1+k3s1`，单节点（`ROLES=control-plane`） |
| 控制面 `MemoryCurrent` | **575.4 / 577.6 MiB**（两次采样） |
| Pod 侧 `kubepods.slice` | **44.8 / 51.0 MiB** |
| 合计 | **≈ 620–630 MiB** |
| 系统 Pod | 3 个（`coredns` Running、`local-path-provisioner` Running、`helm-install-gateway-api-crd` Completed） |
| CRD | **14 个全部 `Established=True`**（含 v1.37 新增的 gateway-api 11 个） |
| 磁盘 | `/var/lib/rancher` **727 MB**；`/` **30%** |
| 启动后水位 | available **594–597 MB**、swap 已用 **203.5 MB** |

口径提醒：`systemctl show k3s -p MemoryCurrent` 不含 Pod。kubelet 把 Pod 放在与 `k3s.service` 同级的 `/kubepods.slice`，只读 `MemoryCurrent` 会少算约 50 MiB。**750 MB 估算至此退役**：实测低 16–17%，方向没错但偏保守。

**ArgoCD（2026-10-19，落地两天后）**

形态：k3s 内、命名空间 `argocd`、Helm chart `argo-cd` 10.10.5（ArgoCD v3.5.5）、关 dex / notifications、`applicationSet.replicas: 0`、ClusterIP + 两层端口转发（不开 NodePort）。

| 判据 | 实测 |
|---|---|
| helm release | `REVISION 2 / deployed` |
| 常驻 Pod | 4 个全 `1/1 Running`（`applicationset-controller` 为 `0/0`，设计如此） |
| Application `hello` | Synced / Healthy，revision 与仓库 HEAD 一致（`0abc9d2`） |
| self-heal | 删 Pod 后新 Pod **≤36 秒**重建（ReplicaSet hash 不变、suffix 变化） |
| drift 纠正 | `scale --replicas=3` 数秒内 `OutOfSync`，自动 scale 回 1，事件可见 `Scaled down replica set from 3 to 1` |
| `kubepods.slice` | `max=0`、`oom_kill=0`（两天） |
| `argocd-server` 重启 2 次 | liveness 探测超时 → SIGTERM → 优雅退出（exit 0），非 OOM、非崩溃 |

成本：Pod 合计约 83 MiB，`available` 掉约 135 MB、swap 涨约 114 MB，差额在 apiserver 的 watch cache。`application-controller` 是唯一持续长大的：27.7 → 80.6 → **126.2 MiB**（占 limit 49%）。两天稳态 `available` **338 MB**、swap **550 MB**（414 → 550，唯一持续恶化的指标）。

**结论：A 方案成立，但已到边界。再加 k8s 侧组件前必须先升配 4G。**

## 七、待补基线

**已完成**

- 手工部署一次耗时 **已完成**（2026-10-21 影子重建）：L1 站点净值 **8 s**（克隆 4 + 起服验证 4）、L2 指标净值 **9 s**，合计 **17 s**。表面值 45 s 含 28 s `sleep`，不扣会虚报 2.6 倍。口径见 [`dr.md`](dr.md)。
- blackbox-exporter **已完成**（2026-10-19 落地），`v0.29.0` 作为 compose 服务（不进 k3s，见 [ADR 0005](adr/0005-blackbox-on-docker-compose.md)），与消费它的 7 条规则同批提交。探针 15s；SLI 目标 `/healthz` 严格 200；SLO 99.5% / 30 天、预算 216 分钟。
- GitOps 部署耗时 **已完成**：ArgoCD 首装到 4 Pod 就绪约 34 分钟（其中 12 分钟是镜像拉取超时白等），首次同步 12 秒。
- RTO / RPO **已完成**（2026-10-22）。**RTO** 17 s；**RPO** 按可再生性分三层：B 层状态（`state.db` + `tls/token/cred/etc` + `letsencrypt` + `alertmanager` 密钥）**3.1 MB 加密外发**，RPO = 上次备份到现在；A 层 **1.8 G**（containerd 镜像层 + k3s 二进制）可再生产、不备；C 层 **89 M** 压不动（`vmdata` gzip 比率 **0.98**）、明确认输。恢复演练验到 **L4**：空状态起 k3s，用备份覆盖后 `namespace 6 / pods 8 / deployments 7 / secrets 9` 全部回来，且 **`creationTimestamp` 保留原值**（是同一批对象，不是重建的等价对象）。R3 全程 **339 s**，站点不受影响。

**仍空着**

- 可观测栈满负载峰值内存（10-09 复测为空载数据，不足以定配额）。
- 各类故障 **MTTR** 仍未测。容灾侧 RTO/RPO 已闭环，MTTR 是"故障发生后多久修好"，另一个维度。
- 同一份 db 搬到另一台机器（证书绑 hostname/IP）。

10-19 SLO 阶段补充（第 9 个容器 `blackbox-exporter v0.29.0`，`mem_limit` 48 MB）：实测 current **16–17 MB** / anon **10–11 MB**（占 limit 22%），撞限 0、`oom_kill` 0、swap 1 MB。整机 available **338 MB**、swap **435 MB**、9 容器 current 合计 **328 MB**（anon 247 MB）、根分区 **33%**。与 W4 收口（338 / 550）比 swap 反降 115 MB。加探针没有改变「2G 已到边界」的结论。

## 八、故障索引

| 日期 | 事件 | 根因一句话 | 详情 |
|---|---|---|---|
| 09-12 | GitHub 推送间歇失败 | 公司网络到 GitHub 链路不稳（曾误归因 WSL 网卡） | [链接](incidents/2026-09-12-github-push-flaky.md) |
| 09-14 | Docker Hub 不可达 | docker.io 被限，quay.io 正常 | [链接](incidents/2026-09-14-dockerhub-unreachable.md) |
| 09-16 | 采集链路 `up` 恒为 0 | firewalld 拦截容器间转发 | [链接](incidents/2026-09-16-firewalld-blocks-scrape.md) |
| 09-16 | `git push` 被拒：超大文件 | 镜像 tar 误入 Git | [链接](incidents/2026-09-16-image-tar-in-git.md) |
| 09-16 | nginx 崩溃循环 | `http2 on;` 需 1.25+，镜像为旧版 | [链接](incidents/2026-09-16-nginx-http2-directive.md) |
| 09-22 | sshd 加固改动不生效 | lineinfile 命中注释块的缩进行 | [链接](incidents/2026-09-22-sshd-lineinfile.md) |
| 09-24 | 改了配置却不生效 | git pull 静默失败（服务器有本地改动） | [链接](incidents/2026-09-24-git-pull-silent-fail.md) |
| 09-24 | healthcheck 恒 unhealthy | `localhost` 解析到 IPv6，nginx 只听 IPv4 | [链接](incidents/2026-09-24-web-healthcheck-ipv6.md) |
| 09-26 | 控制端重建连锁故障 | 环境漂移 + 缺生效性验证（5 个根因） | [链接](incidents/2026-09-26-control-node-rebuild.md) |
| 10-09 | ALERTS 恒空、告警静默 | 缺 `--remoteWrite.url` + alertmanager 未定义 | [链接](incidents/2026-10-09-alert-chain-silent.md) |
| 10-09 | 通知渠道再三踩坑 | `up -d` no-op / `smtp_from` 拼错 / 属主 / `chmod 600` | [链接](incidents/2026-10-09-alert-chain-silent.md#第二阶段接通通知渠道) |
| 10-14 | 控制端迁移后 Ansible 静默失效 | 权限回落 `0777`，Ansible 拒读全局可写目录下的配置 | [链接](incidents/2026-10-14-migration-perms-ansible-cfg.md) |
| 10-14 | 防火墙持久配置漂移 28 天 | 增量式 IaC 只加不删；回填时凭记忆漏了一条 | [链接](incidents/2026-10-14-firewall-drift-incremental-iac.md) |
| 10-14 | 可执行位未进版本控制 / GitHub 状态被误判 | 缓存与索引被当成事实；核验命令吞掉 stderr | [链接](incidents/2026-10-14-indirect-evidence-as-fact.md) |
| 10-15 | k3s 装完却无限重启 | 宿主 cgroup v1，k8s v1.35+ 的 kubelet 拒绝在 v1 启动 | [链接](incidents/2026-10-15-cgroup-v1-blocks-kubelet.md) |
| 10-15 | k3s 起来了但集群 0 Pod | 一个 CRD 停在 `Installing`，崩溃循环期间写入的中间态 | [链接](incidents/2026-10-15-crd-stuck-installing.md) |
| 10-17 | ArgoCD 装上但 `redis` 一直 ImagePullBackOff | 镜像源 docker.io 端点间歇 502；`/v2/` 探活正常也不代表能下 blob | [链接](incidents/2026-10-17-registry-mirror-502.md) |
| 10-19 | 健康检查在规范化 HTTPS 入口上 404 | 只验了 http 入口；www→裸域 301 之后那个 server 块缺 `location = /healthz` | [链接](incidents/2026-10-19-healthz-missing-on-canonical-https.md) |
