#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SLO 报告：当前 SLI / 错误预算 / 烧钱率（只读）

用法（在控制端 WSL 执行）：
    python3 scripts/slo-report.py                  # 默认 ssh 别名 lab-node
    python3 scripts/slo-report.py lab-node --json  # 机器可读

为什么需要这个工具（而不是截图 Grafana）：

  面板给的是**曲线**，而 SLO 要回答的只有一句话：**这个月还能坏多久**。
  把三样东西打在同一屏里，才能区分「已经出事了」和「正在往出事的方向走」——
  后者只有烧钱率看得见，可用性曲线在几十秒的尺度上几乎是平的。

  另外，`probe_success` 无样本时 `avg_over_time` 会跳过空洞，
  SLI 会**停在最后一个值**（看起来还是 99.9%）。所以这个工具必须
  同时报「样本数」和「探针 up」——只看百分比会被"无数据"骗。

2026-10-19 v2 修正（三个假报警，都是判据本身的问题）：

  ① **"近 15m 样本数 < 60" 不等于采集有洞。**
     序列刚建立时窗口本来就没填满 —— 启动 5 分钟只有 20 个样本是**正常**的。
     正确判据是「探针样本数 ≈ 同期 up 的样本数」（两者同为 15s 一跳）：
     相等 → 没有洞；探针显著少于 up → 才是洞（探针挂了但 VM 还在写 up=0）。
  ② **`count(ALERTS{...})` 在"没有告警"时返回空向量，不是 0**，
     于是健康状态被显示成"无数据"。改成 `or vector(0)`。
  ③ **记录规则链式引用会逐层延迟一个周期。** 实测（2026-10-19）：
     sli 6 个样本 / error_ratio 5 / budget 4 / minutes 3 —— 每跳晚 60 秒。
     规则已改成全部直接算（v2 补丁），这里再加一层本地换算兜底。

数据来源：VictoriaMetrics 的 /api/v1/query，经 ssh 隧道访问（端口从不对外开）。

退出码：0 健康；1 有风险（预算耗尽 / 快烧 / 链路断 / 无数据）；2 工具自身失效。
"""
from __future__ import print_function

import json
import shlex
import subprocess
import sys
import time

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
VM = "http://127.0.0.1:8428"

SLO_TARGET = 0.995          # 与 observability/slo-rules.yml 保持一致
BUDGET_MINUTES = 216.0      # 30 天 × 1440 × 0.5%
SCRAPE_SECONDS = 15         # SLI job 的采集间隔

# (key, 显示名, 表达式, 格式)
QUERIES = [
    ("sli",     "SLI（30 天）",            'slo:sli_ratio:30d',                                   "pct"),
    ("budget",  "错误预算剩余",            'slo:error_budget_remaining:ratio',                     "pct"),
    ("bmin",    "还能坏多久（分钟）",       'slo:error_budget_remaining:minutes',                   "num1"),
    ("burn5m",  "烧钱率 5m",               'slo:burn_rate:5m',                                     "x"),
    ("burn1h",  "烧钱率 1h",               'slo:burn_rate:1h',                                     "x"),
    ("burn6h",  "烧钱率 6h",               'slo:burn_rate:6h',                                     "x"),
    ("burn3d",  "烧钱率 3d",               'slo:burn_rate:3d',                                     "x"),
    ("up",      "探针 up（取最小）",        'min(up{job=~"blackbox.*"})',                           "num0"),
    ("samples", "近 15m 探针样本数",        'count_over_time(probe_success{job="blackbox"}[15m])',  "num0"),
    ("upsamp",  "近 15m up 样本数",         'count_over_time(up{job="blackbox"}[15m])',             "num0"),
    ("firing",  "正在 firing 的告警",       'count(ALERTS{alertstate="firing"}) or vector(0)',      "num0"),
]


def ssh(host, script):
    # universal_newlines + PIPE：Python 3.6 也支持（capture_output 是 3.7+）
    proc = subprocess.run(["ssh"] + SSH_OPTS + [host, script],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        print("❌ ssh %s 失败（rc=%d）：%s" % (host, proc.returncode, msg))
        print("   本工具应在【控制端】运行；目标端没有 lab-node 别名。")
        sys.exit(2)
    return proc.stdout


def fetch(host):
    parts = []
    for key, _label, expr, _fmt in QUERIES:
        url = "%s/api/v1/query" % VM
        parts.append("printf '@@@%s\\n'; curl -sG --data-urlencode %s %s"
                     % (key, shlex.quote("query=" + expr), url))
        parts.append("printf '\\n'")
    out = ssh(host, "\n".join(parts))

    blocks, cur, buf = {}, None, []
    for line in out.splitlines():
        if line.startswith("@@@"):
            if cur is not None:
                blocks[cur] = "\n".join(buf)
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        blocks[cur] = "\n".join(buf)
    return blocks


def value_of(txt):
    """返回 (float|None, 错误说明|None)"""
    if not txt or not txt.strip():
        return None, "空返回"
    try:
        d = json.loads(txt)
    except ValueError:
        return None, "返回不是 JSON（VM 不可达？）"
    if d.get("status") != "success":
        return None, d.get("error") or "status != success"
    res = d.get("data", {}).get("result", [])
    if not res:
        return None, "无数据"
    return float(res[0]["value"][1]), None


def fmt(val, style):
    if val is None:
        return "—"
    if style == "pct":
        return "%.3f%%" % (val * 100.0)
    if style == "num1":
        return "%.1f" % val
    if style == "num0":
        return "%d" % round(val)
    return "%.2f×" % val


def main():
    args = [a for a in sys.argv[1:]]
    as_json = "--json" in args
    if as_json:
        args.remove("--json")
    host = args[0] if args else "lab-node"

    blocks = fetch(host)

    data, errs = {}, {}
    for key, _label, _expr, _fmt in QUERIES:
        data[key], errs[key] = value_of(blocks.get(key))

    notes = {}

    # ③ 兜底：记录规则还没产出 minutes 时本地换算（并明确标出来，不静默）
    if data["bmin"] is None and data["budget"] is not None:
        data["bmin"] = data["budget"] * BUDGET_MINUTES
        notes["bmin"] = "⚠️ 记录规则尚未产出，此值由脚本本地换算（ratio × 216）"

    if as_json:
        print(json.dumps({"host": host, "ts": int(time.time()),
                          "slo_target": SLO_TARGET,
                          "values": data, "errors": errs, "notes": notes},
                         ensure_ascii=False, indent=2))
        return 0 if data.get("sli") is not None and (data.get("up") or 0) >= 1 else 1

    print("=" * 74)
    print("SLO 报告 · canonical（https://zhourui2000.online/healthz）")
    print("  %s · %s" % (host, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("  目标 %.1f%% / 30 天滚动 · 错误预算 %.0f 分钟" %
          (SLO_TARGET * 100, BUDGET_MINUTES))
    print("=" * 74)
    print("  %-22s %14s   %s" % ("项目", "数值", "说明"))
    print("  " + "-" * 70)

    hints = {
        "sli":     "成功探测占比",
        "budget":  "100% = 满，0% = 用光，负数 = 已超支",
        "bmin":    "人能决策的单位",
        "burn5m":  ">1× 表示正在超支（短窗口，看瞬时）",
        "burn1h":  "快烧阈值 14.4×（1 小时烧 2% 预算）",
        "burn6h":  "中烧阈值 6×（6 小时烧 5% 预算）",
        "burn3d":  "慢烧阈值 1×（3 天烧 10% 预算）",
        "up":      "0 = VM 抓不到探针（链路问题，不是站点问题）",
        "samples": "应与下面 up 的样本数相同",
        "upsamp":  "同一 job 另一条序列，用作「应有的样本数」基准",
        "firing":  "含主机的 4 条规则；0 才是常态",
    }
    for key, label, _expr, style in QUERIES:
        v = data[key]
        note = notes.get(key) or hints.get(key, "")
        if v is None and key not in notes:
            note = "⚠️ " + (errs.get(key) or "无数据")
        print("  %-22s %14s   %s" % (label, fmt(v, style), note))
    print("  " + "-" * 70)

    fails, warns = [], []

    # ── SLI / 预算 ──
    if data["sli"] is None:
        fails.append("SLI 无数据 —— 探针可能还没落库或 job 名不对")
    elif data["sli"] < SLO_TARGET:
        fails.append("SLI %.3f%% 已低于目标 %.1f%%" % (data["sli"] * 100, SLO_TARGET * 100))
    if data["budget"] is not None and data["budget"] < 0:
        fails.append("错误预算已超支 %.1f%%" % (-data["budget"] * 100))

    # ── 探针链路 ──
    if data["up"] is None or data["up"] < 1:
        fails.append("探针链路断（up=%s）—— 此时 SLI 不可信" % fmt(data["up"], "num0"))

    # ── 采样完整性（v2 判据：探针样本 vs up 样本，而不是拍一个 60）──
    n_p, n_u = data["samples"], data["upsamp"]
    if n_u is None or n_u == 0:
        fails.append("近 15 分钟连 up 都没有样本 —— 采集完全停摆")
    elif n_p is None:
        fails.append("探针序列无样本（同期 up 有 %d 个）—— 探针挂了或过滤条件不对" % round(n_u))
    elif n_p < n_u * 0.8:
        fails.append("探针样本 %d 个，同期 up 有 %d 个 —— 采集有洞" % (round(n_p), round(n_u)))

    # ── 烧钱率 ──
    if data["burn1h"] is not None and data["burn1h"] > 14.4:
        fails.append("1 小时烧钱率 %.1f× > 14.4× —— 快速燃烧" % data["burn1h"])
    if data["burn6h"] is not None and data["burn6h"] > 6:
        warns.append("6 小时烧钱率 %.1f× > 6× —— 中速燃烧" % data["burn6h"])
    if data["burn3d"] is not None and data["burn3d"] > 1:
        warns.append("3 天烧钱率 %.1f× > 1× —— 按此速率会超支" % data["burn3d"])
    if data["firing"]:
        warns.append("有 %d 条告警正在 firing（用 ALERTS 查是哪条）" % round(data["firing"]))

    # ── 信息性提示（不算失败）──
    if n_u is not None and data["sli"] is not None and n_u < 60:
        warns.append("采样窗口还没填满（up 只有 %d 个样本，满窗是 60）—— 刚启动的正常现象，不是故障"
                     % round(n_u))

    print("判据：")
    if not fails and not warns:
        print("  ✅ 预算未耗尽 · 链路在 · 采样完整 · 无燃烧")
    for x in fails:
        print("  ❌ " + x)
    for x in warns:
        print("  ⚠️ " + x)
    print("=" * 74)
    print("结论：%s" % ("✅ 健康" if not fails else "❌ 有风险（见上）"))
    print("注意：这是**从服务器自拨公网入口**的结果（hairpin NAT，已实测可达）。")
    print("      它测不到 DNS 解析失败、运营商链路中断、安全组只拦外部 —— 那是测量点偏差。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
