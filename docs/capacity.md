# 容量账

所有数字都带测量口径与命令。结论冲突时以最新实测为准，旧推算就地标注「退役」。

## 一、实测修正（2026-09-12）

原假设"磁盘最易打满"不成立：磁盘仅 19%，journald 限额后占 32M。真实瓶颈是内存：总量 1870MB，加固后可用 1399MB。

## 二、k3s 决策规则

部署完可观测栈后重测 `free -m` 的 available：

| 可用内存 | 决策 |
|---|---|
| ≥ 800MB | 上 k3s，关闭内置 traefik / servicelb / metrics-server |
| 600–800MB | 上 k3s，Grafana 降至 192m、VM retention 压至 15 天 |
| < 600MB | 放弃 k3s，全线 Docker Compose |

第三种情况要在文档里记判断依据。"实测后论证不可行"本身是有效工程决策。

## 三、实测更新（2026-09-16）

原估"可观测栈 576MB"偏保守，实测 230MB。

```
可用内存  1143MB
减 k3s    -750MB（关闭内置组件后）
──────────────────
剩余余量   393MB
```

决策：第 3 周可以上 k3s，禁用 traefik / servicelb / metrics-server。

| 容器 | 现配额 | 实测 | 建议调整至 |
|---|---|---|---|
| web | 128m | 2.96MB | 64m |
| victoriametrics | 256m | 94MB | 200m |
| grafana | 256m | 116MB | 200m |
| node-exporter | 64m | 19MB | 保持 |

可释放约 180MB，但等运行一周取得真实峰值后再执行，避免空载数据误导。

## 四、复测（2026-10-14，上 Loki 前的容量评估）

| 指标 | 09-16 | 10-09 | 10-14 |
|---|---|---|---|
| 可用内存 | 1143 MB | 1212 MB | **1161 MB** |
| 磁盘水位 | 19% | 25% | **25%**（9.2G / 40G，可用 29G） |
| journald 落盘 | 32 MB | — | **40 MB**（限额 500M 生效） |
| vmdata | — | — | **38 MB**（`--retentionPeriod=30d`） |
| grafana-data | — | — | **15 MB** |

容器实测（`docker stats --no-stream`，6 个合计约 **250 MiB**）：

| 容器 | 配额 | 实测 | 利用率 |
|---|---|---|---|
| victoriametrics | 256m | 86.1 MiB | 34% |
| grafana | 256m | 76.4 MiB | 30% |
| web | 128m | 34.7 MiB | 27% |
| alertmanager | 64m | 22.0 MiB | 34% |
| node-exporter | 64m | 17.6 MiB | 28% |
| vmalert | 64m | 13.1 MiB | 20% |

### Loki + promtail 可行性

- **磁盘不是问题，且有实测支撑。** 日志产生速率 ≈ **191 KB / 24h**（journald，2493 行），容器 json 日志合计 **1.3 MB**（已轮转）。Loki chunk 是 gzip，按 5–10× 压缩估计年增长几十 MB，29 GB 可用绰绰有余。反过来也成立：「为了省磁盘」不是上 Loki 的理由，真正收益是**可查询**（跨主机聚合、按行检索、与指标关联）。
- **内存是唯一约束。** 同类单机部署 Loki（single binary + filesystem）空载约 **90–120 MB**，promtail 约 **30–40 MB**，合计按 **160 MB** 预算。1161 − 160 ≈ **1000 MB**。
- **对 k3s 的连带影响**：1000 − 750 ≈ **250 MB** 余量，仍可上，但比 10-09 测算的 462 MB 紧。两者先后顺序要显式决策；若都要，给 Loki 显式 `mem_limit`（loki 160m / promtail 64m），让预算可核算。

决策：容量层面放行。Loki 属 Week 2 日志子项、k3s 属 Week 3-4，分开推进。

### 日志层落地：采集端改用 Alloy

promtail 于 **2026-03-02 EOL**（Loki 3.7.3 已移除），改用 Grafana Alloy，理由见 [ADR 0004](adr/0004-promtail-eol-alloy.md)。两项成本与 promtail 方案不同：

| 项 | promtail 方案（原估） | Alloy 方案 |
|---|---|---|
| 采集端镜像 | ~80 MB | **707 MB** |
| 存储端镜像 | — | **159 MB** |
| 日志层 `mem_limit` 上限 | 160 MB | **384 MB**（loki 192m + alloy 192m） |

- 镜像合计约 **866 MB**，磁盘 25% 升到 **27%**（仍 28 GB 可用）。
- 内存预算翻倍压缩 k3s 余量：1161 − 384 ≈ **777 MB**；按 k3s 750 MB 计，最坏情况只剩约 **27 MB**。这是 `mem_limit` 天花板不是实际占用，拿到实测前不把可行性定死。
- 非容量成本：Alloy 需读 `/var/run/docker.sock` 才能拿到容器名与 compose service 元数据，等于把宿主 root 的等效能力交给容器。取舍写在 `observability/alloy-config.alloy` 头部注释。

## 五、日志层实测（2026-10-14，Loki 3.7.8 + Alloy v1.20.1）

| 容器 | 配额 | 实测 | 利用率 |
|---|---|---|---|
| **loki** | 192m | **143.5 MiB** | **74.7%** |
| victoriametrics | 256m | 83.4 MiB | 32.6% |
| grafana | 256m | 77.7 MiB | 30.4% |
| alloy | 192m | 75.0 MiB | 39.1% |
| alertmanager | 64m | 22.6 MiB | 35.3% |
| node-exporter | 64m | 19.1 MiB | 29.9% |
| vmalert | 64m | 12.8 MiB | 20.0% |
| web | 128m | 5.9 MiB | 4.6% |
| **合计** | **1216m** | **440 MiB** | — |

| 指标 | 上线前 | 上线后 | 增量 |
|---|---|---|---|
| available | 1161 MB | **1020 MB** | **−141 MB** |
| 日志层容器合计 | — | **218.5 MiB** | loki 143.5 + alloy 75.0 |
| swap 已用 | — | 137 MB | — |

实测 218.5 MiB 约为 384 MB 上限的一半，再次印证 `mem_limit` 是天花板。

**k3s 决策**：1020 − 750 ≈ 270 MB 余量，落在「≥800 MB」档，可以上（禁用内置 traefik / servicelb / metrics-server）。

**结构性隐患**：8 个容器 `mem_limit` 之和 **1216 MB > available 1020 MB**。多容器同时逼近上限时只能靠 swap（2 GB，已用 137 MB）兜底，swap 不够则 OOM killer 挑一个杀。当前未发生（实测 440 MiB），但它是结构性的。缓解方向未执行：明确谁可牺牲（`oom_score_adj`）、或把总配额压到 ≤1020m、或显式接受 swap 换页延迟并记入 `baseline.md`。**loki 已用 74.7%，第一个要盯。**

**磁盘速率更正**：

| 项 | 实测 |
|---|---|
| 磁盘水位 | 25% → **27%**（镜像 +866 MB） |
| loki-data | **605.5 KB**（运行 48 分钟） |
| alloy-data | 60 KB |
| journald 落盘 | 40 MB → **24 MB** |

605.5 KB ÷ 48.4 min ≈ **18 MB/日**，7 天 retention 稳态约 **126 MB**。

上一版写「年增长几十 MB」差了约两个数量级：当时只按 journald 的 191 KB/24h 推算，漏算容器日志全量采集与 Loki 自身索引 / WAL，实测外推约 **6.6 GB/年**。操作结论不变（7 天 retention 压在 ~126 MB），但数字必须改准，否则会让人以为可以随便放开 retention。该速率含冷启动首次回溯，稳态应更低，建议跑满一天再取样。

标签健康度：journal 来源 11 流（`unit` / `level`）、docker 来源 5 流（`container` / `service`）；`host` 已从容器 ID 纠正为 `zhourui2000`；`drop_stale` 丢弃 **399 行**（`loki_process_dropped_lines_total`）。

## 六、k3s 落地实测（2026-10-17，第一次真实容量复测）

本节替换此前所有「k3s 按 750 MB 估算」的推算。750 MB 是 09-16 沿用下来的估算，从未被实测验证。

### 控制面开销

| 指标 | 实测（10-17 09:25，两次采样间隔 20 秒） |
|---|---|
| `systemctl show k3s -p MemoryCurrent` | **603,316,224 → 605,634,560 字节 = 575.4 / 577.6 MiB** |
| `/sys/fs/cgroup/kubepods.slice/memory.current` | **44.8 / 51.0 MiB**（coredns + local-path-provisioner + pause） |
| k3s 合计 | **≈ 620–630 MiB** |

`MemoryCurrent` 不含 Pod。kubelet 把 Pod 放在与 `k3s.service` 同级（不是子 cgroup）的 `/kubepods.slice`，只读 `MemoryCurrent` 会少算约 **50 MiB**。

与 750 MB 估算对照：实测低约 16–17%，同一量级，方向没错但偏保守。**该估算退役，后续一律引实测。**

同时作废一个数据：cgroup v1 崩溃循环期间测到的 `MemoryCurrent = 329.5 MiB` 是无效值（三次采样 137 / 322 / 337 MiB 全不一致），那是"启动到失败那一刻"的瞬时占用。稳态实测 558 → 577 MiB，比它高 70%。

### 系统水位（装 k3s 前 vs 稳定 36 小时后）

| 指标 | 装前（10-15 停机时） | 现在（10-17） | 变化 |
|---|---|---|---|
| available | ~1118 MB | **594–597 MB** | −约 520 MB |
| swap 已用 | 268 KB（刚重启） | **203.5 MB** | +203 MB |
| 磁盘水位 | 28% | **30%**（11G / 40G，可用 27G） | +2 个百分点 |
| `/var/lib/rancher` | 274 MB | **727 MB** | +453 MB（二进制 81.5 MB + 镜像 + 状态） |
| journald | 78.5 MB | **86.5 MB** | +8 MB（36 小时） |
| 负载 | 8 个 docker 容器 | 8 容器 + 3 Pod（另 1 个 Completed） | — |

两点记账：available 减少约 520 MB 与 k3s 合计 620–630 MiB 基本对应，差额是页缓存（可回收）；swap 从 268 KB 涨到 203.5 MB，控制面确有部分被换出，符合「保留 swap 并监测」的取舍，代价是控制面存在换页延迟风险，且 5.10 的 tmpfs 不支持 `noswap`，kubelet 无法为 Pod 保证"不使用 swap"（启动打 `Assuming not supported` 后继续）。

**隐患升级**：`mem_limit` 之和仍 1216 MB，而 available 已从 1020 降到 594–597 MB，且多了一整类消费方（k3s 控制面 + 3 Pod，约 620–630 MiB）。缺口从约 200 MB 扩大到约 **620 MB**，下一次变更前应先处理。当前未触发 OOM（容器合计 440 MiB），靠 2 GB swap 兜底。

### 日志速率：两次估算一高一低，实测落在中间

| 时点 | 窗口 | 当时结论 | 问题 |
|---|---|---|---|
| 10-14 19:0x | 48 分钟 | 18 MB/日 | **高估**：含 Alloy 首启回灌 12h journal 积压 |
| 10-15 21:0x | 5 分钟 | 191 KB/日 | **低估**：窗口落在静默期 |
| **10-17** | 10 分钟 + 37.3 小时 | 见下 | — |

| 口径 | 窗口 | 值 |
|---|---|---|
| 摄入（`loki_distributor_bytes_received_total`） | 10 分钟 | **479.5 KB/日**、8,064 行/日 |
| 摄入 | 37.3 小时累计 | **1.32 MB/日**、约 21,980 行 |
| 磁盘（`loki-data`） | 37.3 小时累计 | **3.02 MB → 1.94 MB/日** |

7 天 retention 稳态：3.02 MB × (168 ÷ 37.3) ≈ **约 14 MB**。

这条速率算错过两次，错因都是窗口：短窗既可能高估（赶上启动回灌）也可能低估（赶上静默期）。10 分钟的 479 KB/日与 37 小时的 1.32 MB/日相差 **2.7 倍**。判断速率类量，窗口要 ≥数小时，或改用连续累计计数器。

健康度：14 个 CRD 全部 `Established=True`（含 v1.37 新增的 gateway-api 11 个）；3 个系统 Pod 就绪；`drop_stale` 累计丢弃 **1,002 行**（10-15 时为 399）；Alloy `/metrics` HTTP 200；Loki `/ready` = `ready`。

## 七、内存预算（2026-10-17 实测校准）

本节取代此前「缺口 X MB」的结论。那个结论把 `mem_limit` 当成了预留。

| 要回答的问题 | 该看的量 | 不该看的量 |
|---|---|---|
| 上限配得合不合适 | 各容器 `memory.events` 的 `max` 计数 | 上限之和 |
| 现在有没有危险 | 各容器 `memory.current` 合计 vs `available` | 上限之和 |
| 会不会悄悄变慢 | `memory.swap.current` | — |

`mem_limit` 是上限不是预留。多个上限之和超过物理内存是正常的，像每户装 60A 电表不代表全楼同时满负荷。所以「1216 MB > available 602 MB」不是隐患。真正该报警的三件事：有容器被 OOM 杀过；某容器 `max` 计数在观察窗口内仍在增长；容器实际合计逼近 available。

实测（10-17 11:15，运行 39 小时）：

| 容器 | 原上限 | 实测当前 | 撞限累计 | swap | 判定 |
|---|---|---|---|---|---|
| **alloy** | 192 | 94–134（波动大） | **783** | 8 | 唯一撞过上限，放宽到 **256** |
| loki | 192 | 99–107 | 0 | 4 | 保留（查询突发需余量） |
| grafana | 256 | 82–99 | 0 | 9 | 收紧到 **192**（2.6× → 1.9×） |
| victoriametrics | 256 | 55–58 | 0 | 29 | 收紧到 **192**（4.4× → 3.3×） |
| alertmanager | 64 | 17–22 | 0 | 1 | 保留 |
| node-exporter | 64 | 16–18 | 0 | 1 | 保留 |
| vmalert | 64 | 8–10 | 0 | 3 | 保留（体积小，不值得重建） |
| web | 128 | 4–5 | 0 | 2 | 收紧到 **64**（25× → 12×） |

合计 **1216 → 1088 MB**，净减 128 MB，同时让唯一被限流的 alloy 拿到 1.9× 余量。上限之和 ÷ 实际合计从 2.97× 变为约 2.6×。

**alloy 的 783 次怎么判**：首次读到 `max 783` 容易得出"正在被限流"，那是错的。`memory.events` 是自容器启动以来的累计量，alloy 在 10-15 启动时做过 journal 12 小时积压回灌。判定靠跨周期观测：

```
时点 1   max 783   memory.current 103.6 MiB
时点 2   max 783   memory.current 134.1 MiB    （60 秒后，Δ = 0）
```

Δ=0，说明是历史一次性事件。旁证：`loki_write_dropped_entries_total` 五种 reason 全为 0，一条日志没丢。结论：上限对稳态够用，对启动回灌不够，处理方式是放宽余量。`scripts/check-mem-budget.py --watch` 把这件事变成可复跑的判据。

**为什么没设 `oom_score_adj`**：① 当前 `oom_kill` 全 0，没有现场；② 它只在宿主级 OOM 时影响选择，容器撞到自己的 `mem_limit` 时是 cgroup 内部击杀，与该参数无关，不澄清就设会让人误以为"设了就一定先杀 vmalert"；③ 未经验证的手段不进仓库。实际顺序是确定的：谁撞到自己的 `mem_limit`，谁被自己的 cgroup 收拾，前提是上限按实测校准过。

**与 ArgoCD 的关系**：available 约 602 MB，ArgoCD 精简部署约需 300–500 MB。本次收敛不是为它腾空间（净减仅 128 MB），而是先把现有 8 个服务的账做准。上 ArgoCD 前需单独决定：精简部署（关 Dex、限 256m）还是升配 4G。

## 八、ArgoCD 落地实测（2026-10-17 ~ 10-19）

决策选了 A：精简部署。

| 时点 | available | swap 已用 | 在做什么 |
|---|---|---|---|
| 装前（10-17 11:15） | 594 MB | 157 MB | 8 个 docker 容器 |
| 10-17 15:51 | **354 MB** | 307 MB | 正在拉镜像，含临时占用 |
| 10-17 16:22 | **459–478 MB** | 271–275 MB | 4 Pod 就绪、无 Application（空转） |
| 10-17 16:37 | 354 MB | 414 MB | 有 Application 在 reconcile |
| 10-19 09:00 | **338 MB** | **550 MB** | 两天稳态（含 self-heal / drift 演示） |

装完测一次，既不一定峰值也不一定稳态。

Pod 级实测（cgroup v2，10-19）：

| Pod | anon | limit | 利用率 |
|---|---|---|---|
| `argocd-application-controller` | **126.2 MiB** | 256 MiB | **49%** |
| `argocd-server` | 27.9 MiB | 160 MiB | 17% |
| `argocd-repo-server` | 26.3 MiB | 160 MiB | 16% |
| `kube-system/coredns` | 15.3 MiB | 170 MiB | 9% |
| `argocd-redis` | 4.3 MiB | 96 MiB | 4% |
| `hello`（被管应用） | 2.1 MiB | 48 MiB | 4% |

全部 Pod `memory.events.max = 0`、`oom_kill = 0`。

**核心结论：ArgoCD 的成本 ≠ 它 Pod 的占用**

| 项 | 数值 |
|---|---|
| 4 个 Pod 实测合计 | 约 **83 MiB**（10-17 装完时） |
| available 却掉了 | 594 → 459 = 约 **135 MB** |
| swap 同时涨了 | 157 → 271 = 约 **114 MB** |
| 差额落在哪 | `k3s.service` anon 从约 520 涨到 675 MiB，即 **apiserver 的 watch cache** |

controller 会 watch 全集群资源，自己进程很小，但让 apiserver 缓存了更多对象。**2G 机器上给 k8s 组件做内存估算，按 Pod 占用的 3 倍算，不能看 requests/limits。**

`application-controller` 会持续长大：

| 时点 | anon | 相对空转 |
|---|---|---|
| 10-17 16:22（无 Application） | 27.7 MiB | — |
| 10-17 16:37（刚建 Application） | 80.6 MiB | **×2.9** |
| 10-19 09:00（两天后） | **126.2 MiB** | **×4.6** |

它缓存目标状态 + manifests + 全集群对象，每多一个 Application 还会涨。256 MiB 在 1 个 Application 下够用，再加三四个就有撞限风险。

**一次真实重启**：`argocd-server` 在 10-17 22:45 重启 2 次。四条判据同时看才能定性：

| 判据 | 实测 | 排除什么 |
|---|---|---|
| `lastState.exitCode` | **0** | 不是崩溃（崩溃是 137/1） |
| `lastState.reason` | **Completed** | 不是异常终止 |
| `memory.events` | `oom=0`、`oom_kill=0` | 不是 OOM |
| 日志 | `Graceful shutdown of https initiated` → `All servers were gracefully shutdown. Exiting...` | 收到 SIGTERM 后自己退的 |
| 同期事件 | `Liveness probe failed: context deadline exceeded` | liveness 探测超时被 kubelet 杀 |

根因是 2C2G 上响应变慢（swap 换页 + CPU 争抢），不是配置错误。这是「A 方案能跑但余量薄」的直接证据：功能没坏，但已贴着性能边界跑。

**结论**：A 方案成立（available 338 MB、`oom_kill=0`、站点与日志链路正常）。但不要再往上加组件：`application-controller` 已占 limit 49% 且随 Application 增长；swap 两天涨 136 MB（414 → 550），唯一持续恶化；10-17 实测 apiserver 有 **109.8 MiB 被换出**，空闲无害，有真实 API 压力时会变慢。**下次加任何 k8s 侧组件，先升配 4G。**

## 九、SLO 落地实测（2026-10-19）

第 9 个容器，探针成本：

| 项 | 值 |
|---|---|
| 镜像 | `quay.io/prometheus/blackbox-exporter:v0.29.0`（37.7 MB，本地已有） |
| `mem_limit` | 48 MB |
| 实测 `current` | **16–17 MB**（含页缓存） |
| 实测 `anon` | **10–11 MB**（占 limit **22%**） |
| 撞限 / `oom_kill` | 0 / 0 |
| `swap.current` | 1 MB |
| 采集负载 | 4 目标：1 × 15s（SLI）+ 3 × 30s（存在性） |

探针 ≈ 10 MB，小到不值得为它改预算，也没有改变「2G 已到边界」的判断（[ADR 0005](adr/0005-blackbox-on-docker-compose.md)）。

整机快照（10-19 20:10–20:15）：

| 项 | 值 |
|---|---|
| 物理内存（`free`） | 1870 MB |
| available | **338 MB**（当日区间 245–338） |
| swap used | **435 MB**（当日区间 399–453） |
| 9 容器 `current` / `anon` 合计 | 328 MB / **247 MB** |
| `k3s.service` / `kubepods` `current` | 752 MB / 230 MB（均含页缓存） |
| 根分区 | 13G / 40G = **33%** |
| `oom_kill` / 各容器撞限 Δ | 0 / 0 |

与 W4 收口（available 338 / swap 550）比：available 持平、swap 降 115 MB。ArgoCD 两次异常重启后 `application-controller` 的 anon 没有继续膨胀。

**三次「工具报错、机器没坏」，错的全是口径：**

| 现象 | 错在哪 | 改成什么 |
|---|---|---|
| 近 15m 样本 23/60，判「采集有洞」 | 拿理想满窗值当基准，而序列才存在 7 分钟 | 比同期 `up` 样本数（实测 28 vs 30） |
| 探针 20 / up 60，判「采集有洞」 | 窗口里确实有洞但已愈合，把窗口量当当前状态 | 判「现在」用 1 分钟窗口 |
| 容器合计 316 MB 占 available 的 112% | `current` 含可回收页缓存，而 `MemAvailable` 也算过，同一块缓存数两遍 | 看 `memory.stat` 的 `anon`（实测 322 → 238） |

这三条直接改变「容量够不够」的结论：用 `current` 比 available，会让一台还剩 338 MB 的机器看起来已经超了 12%。容量判断的输入错了，结论再严密也没用。
