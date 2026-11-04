# SLO：canonical 入口可用性

- 建立 2026-10-19　对象 `https://zhourui2000.online/healthz`
- 规则 `observability/slo-rules.yml`　探针 `observability/blackbox.yml`　判据 `scripts/slo-report.py`
- 相关 [ADR 0005](adr/0005-blackbox-on-docker-compose.md) · [ADR 0003](adr/0003-blackbox-exporter-deferred.md) · [事故 2026-10-19](incidents/2026-10-19-healthz-missing-on-canonical-https.md)

## 1. SLI

```
SLI = 30 天内 probe_success 的平均值 = 成功探测次数 / 有效探测次数
```

| 项 | 取值 | 理由 |
|---|---|---|
| 探针 | `blackbox-exporter v0.29.0`（compose，不进 k3s） | ADR 0005 |
| 目标 | `https://zhourui2000.online/healthz` | 只测规范化后的入口；www 与 http 是跳转层，正确结果是 301 |
| 判定 | HTTP 严格 200，`follow_redirects: false` | 跟随后的 200 会把跳转配置的错掩盖成"能用" |
| 间隔 | 15s | 30 天 ≈ 17.3 万样本；更密只增存储 |
| 数据源 | `probe_success{job="blackbox"}` | 唯一参与 SLI 的 job |

`job="blackbox_follow"`（www / http / 裸域根）只做存在性检查，不进 SLI。

## 2. SLO 与预算

| 项 | 值 |
|---|---|
| SLO | 99.5% / 30 天滚动 |
| 错误预算 | 0.5% = 30 × 1440 × 0.5% = **216 分钟**（≈3 h 36 min） |
| 折算次数 | 216 min ÷ 15 s = **864 次** |

选 99.5% 而非 99.9%：99.9% 每月只有 43 分钟，而这台机器要跑 k3s + ArgoCD + 8 个容器，一次滚动重建、一次内核重启或一次证书续期演练就能吃掉大半；注定烧光的目标只会让人学会忽略告警。初始值无历史支撑，第一个 30 天窗口后按实际分布复核（写入 `capacity.md`）。

## 3. 烧钱率

```
烧钱率 = 当前错误率 ÷ 0.005
```

1× = 按此速率恰好在 30 天内用完预算；14.4× = 1 小时烧掉 2% 预算。

| 告警 | 长窗口 | 短窗口 | 阈值 | 消耗 | severity | 动作 |
|---|---|---|---|---|---|---|
| `SloFastBurn` | 1h | 5m | 14.4× | 2% / 1h | critical | 立刻处理 |
| `SloMediumBurn` | 6h | 30m | 6× | 5% / 6h | warning | 本班次内 |
| `SloSlowBurn` | 3d | 6h | 1× | 10% / 3d | info | 排期 |

两个窗口必须同时成立：长窗口判严重程度，短窗口判是否还在烧。只用长窗口，修好了告警还挂着；只用短窗口，一次抖动就响。

`SiteDown` 只覆盖"探针明确看到失败"，短暂抖动、间歇失败、慢速劣化只有烧钱率看得见。

## 4. 探针挂了 ≠ 站点挂了

`avg_over_time` 会跳过没有样本的时间段：

| 实际情况 | `probe_success` | SLI | 应触发 |
|---|---|---|---|
| 正常 | 全 1 | 100% | 无 |
| 站点真坏 | 全 0 | 掉到 0% | `SiteDown` + 烧钱率 |
| 探针 / 采集链路坏 | 无样本 | **停在最后一个值** | `ProbePipelineDown` / `SloNoData` |
| blackbox 活着但没产出 | 无样本 | 同上 | `SloNoData` |

监控自己坏掉时仪表盘最平静。必须有一条告警不依赖 SLI 的分母，直接看 `up{job=~"blackbox.*"}` 与样本数。这是方法论 ⑯ 的形态之一，假信号不是缓存而是**空洞**。

## 5. 测量点偏差

探针在服务器上拨自己的公网域名，依赖 hairpin NAT（10-17 实测通：301 / 0.090 s，与外部一致）。

能证明 nginx 活着、TLS 握手成立、路由与 location 正确、证书链完整。不能证明公网 DNS 正常（走本机 resolver 缓存）、外部链路可达、安全组只拦了外部流量。

结论：这是**服务内部可用性** SLI，不是端到端可用性 SLI。外部视角需一台外部探针（GitHub Actions 定时 curl 后推 VM），不在本轮范围，记在 `baseline.md` 待补基线。

## 6. 证书不进 SLI

两个 blackbox 模块都是 `insecure_skip_verify: true`（仍解析叶子证书，`probe_ssl_earliest_cert_expiry` 可用）。证书过期与服务不可用是两种故障，混进 `probe_success` 会互相掩盖：证书过期但服务正常会被算成站点挂了，告警指向错方向。故单列 `CertExpiringSoon`（21 天），不进错误预算：证书只有到时候全挂，没有灰度。

## 7. 未证事项

- `SiteDown` 的"红"已实测两次：2026-10-22 R1 停站 105 s、2026-11-04 受控停站 197 s。`probe_success` 变 0、告警进 pending 都成立；但 105 s 那次 `for: 3m` 追不上，**零 firing**，见第 11 节。
- 99.5% 无历史数据支撑。
- 前 30 天的 SLI 是"到目前为止"，不是完整窗口。

## 8. 验收

```bash
python3 scripts/slo-report.py
```

| 项 | 期望 |
|---|---|
| SLI（30 天） / 预算剩余 | 接近 100% / 接近 100% |
| 烧钱率 5m / 1h / 6h / 3d | 0.00× |
| 探针 up / 近 15m 样本数 | 1 / 60 |
| 退出码 | 0 |

`slo-canonical` 组 17 条规则（9 记录 + 8 告警）。

## 9. 启动期现象（2026-10-19 首次落地）

**窗口没填满 ≠ 采集有洞。** 刚建立 5 分钟的序列，`count_over_time(probe_success[15m])` 只能有 ~20 个样本。判据要拿同期 `up` 的样本数当基准（同 job、同间隔）。实测报告显示 23 个样本时同期 `up` 是 30 个，说明没有洞，只是序列才存在 7 分钟。

**记录规则互相引用会逐层晚一个周期。** `slo:sli_ratio:30d` 6 个样本 / `error_ratio` 5 / `budget_remaining:ratio` 4 / `:minutes` 3，链式三跳 ≈3 分钟。vmalert 重启后这 3 分钟里错误预算面板是 No data，而重启后恰恰有人盯盘。v2 已把三条改成全部直接从 `probe_success` 计算，代价是 `avg_over_time(probe_success[30d])` 被算 3 次而不是 1 次（可忽略）。

## 10. 演练：停探针 13 分钟

这套 SLO 唯一能安全制造的故障：站点不受影响，监控链路断了。

| 时刻 | 事件 |
|---|---|
| T | `docker stop blackbox` |
| T + ≤30 s | VM 抓取失败，开始写 `up = 0`（`probe_success` 停止出现） |
| T + 4 m | pending |
| T + 4 m 15 s | firing |

```
停容器 → VM 下次抓取失败才写 up=0        ≤15 s（follow job 30 s → ≤30 s）
       → vmalert 下一轮评估才进 pending  ≤60 s
       → 再连续 pending 满 3 分钟        180 s
                                        ─────
                                    最多 255 s
```

停摆第 9 分钟实测：SLI 1 / 预算 1 / 烧钱率 0、`SiteDown` 0 条、`SloNoData` 0 条（需连续 15 分钟无样本）、`ProbePipelineDown` 4 条 firing。整套 SLO 面板全绿。

状态机的坑：`pending` 与 `firing` 是两条独立序列（`alertstate` 是标签），vmalert 停写后 VM 仍保留到 lookback 结束（≈5 分钟）。判断"已恢复"不能看查询结果为空，要数 `count(ALERTS{alertname=…,alertstate="firing"}) or vector(0)` 是否回 0。

## 11. MTTR：四段口径与首次实测（2026-11-04）

**四段**：`T_break` 故障开始 → **`T_detect` 有人知道（告警 fire）** → `T_ack` 开始处置 → `T_fix` 恢复。
`MTTD = T_detect − T_break`，`MTTR = T_fix − T_detect`。

演练本身填不了 `T_detect` —— 你就在现场，检测时间恒为 0，测出来的是 RTO。能填它的只有**告警自己**。
所以先补了一条 `SiteDownFast`（`for: 1m`、`severity: warning`），与 `SiteDown`（`for: 3m`、critical）**同表达式分层**；
`group_by: ['alertname']` 让它们分成两封邮件，互不淹没。

首次受控中断实测（停 web 197 s）：

| 时刻 | 事件 | 距 `T_break` |
|---|---|---|
| 21:05:52 | `docker compose down`（`T_break`） | — |
| 21:06:15 | 探针首个 `probe_success = 0` | +23 s |
| 21:07:00 | 两条告警**同时**进 pending | +68 s |
| **21:08:00** | **`SiteDownFast` firing（`T_detect`）** | **+128 s** |
| 21:09:09 | `/healthz` 200（`T_fix`） | +197 s |

- **MTTD = 128 s**（设计最坏 135 s，吻合）；**MTTR = 69 s**（firing → 恢复）。
- `SiteDown` 全程只有 pending、**零 firing** —— 197 s 仍不够 `for: 3m` + 评估周期，分层达到设计目的。
- 成本：13 个失败样本 = 195 s，约占按比例预算（116 分钟）的 **2.8%**。

**n = 1，且 `T_ack` 仍是空的**（人就在现场，没有"开始处置"这个动作）。这是「一次演练样本」，不是「稳定 MTTR」；
累计 3 次「告警真的 fire 过」的故障后再谈均值。

同日修了一个口径 bug：`slo-report.py` 的「还能坏多久」原先拿 ratio（分母是**已采集窗口**）直接乘 216（**30 天**），
窗口没填满时会高估。现按 `216 × 已运行天数 / 30` 折算并在行尾注明。实测 2026-11-04：旧 **203.9** 分钟 → 新 **109.4** 分钟。
