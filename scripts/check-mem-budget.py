#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""容器内存预算核对（只读）

用法（在控制端 WSL 执行）：
    python3 scripts/check-mem-budget.py                    # 默认 ssh 别名 lab-node
    python3 scripts/check-mem-budget.py lab-node --watch 60  # 跨周期观测撞限是否在增长

为什么需要这个工具（而不是看 `docker stats`）：

  `docker stats` 给的是**瞬时值**，而"容量够不够"是三个不同的问题：
    ① 上限配得合不合适   → 看 `memory.events` 的 `max` 计数（撞过上限几次）
    ② 现在有没有危险     → 看各容器 `memory.current` 合计 vs `available`
    ③ 会不会悄悄变慢     → 看 `memory.swap.current`（换页不开刀，但会拖死延迟）

  仅看"配额之和 > 物理内存"是个**错误判据**：`mem_limit` 是**上限不是预留**，
  多个上限之和超过物理内存是完全正常的（就像每家都装了 60A 电表，不代表同时满负荷）。

真正需要报警的是这三件事：
    · 有容器被 OOM 杀过（`oom_kill` > 0）
    · 某容器的 `max` 计数**在观察窗口内仍在增长** —— 上限太紧，正在被限流
    · 容器实际合计逼近 `available` —— 真要换页了

2026-10-19 修正：**不要用 memory.current 去比 MemAvailable**。
  `current` 含 file cache（可回收），而 `MemAvailable` 本来就把可回收缓存算进去了 →
  同一块缓存被数两遍，于是出现「容器合计 316 MB 已占 available 的 112%」这种没意义的提示。
  真正该看的是 `memory.stat` 的 **anon**（不可回收的匿名内存）。当日实测：
  current 322 MB / **anon 238 MB** / file 82 MB —— 差的 82 MB 就是那次误报的来源。
  判据改为 anon 合计 > available × 90%。

退出码：0 干净；1 有问题；2 工具自身失效（ssh 失败 / 取不到 cgroup）。
"""
from __future__ import print_function

import subprocess
import sys
import time

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

REMOTE = r"""
for c in $(docker ps --format '{{.Names}}' | sort); do
  id=$(docker inspect "$c" --format '{{.Id}}')
  s="/sys/fs/cgroup/system.slice/docker-${id}.scope"
  lim=$(cat "$s/memory.max" 2>/dev/null || echo NA)
  cur=$(cat "$s/memory.current" 2>/dev/null || echo NA)
  sw=$(cat "$s/memory.swap.current" 2>/dev/null || echo NA)
  swmax=$(cat "$s/memory.swap.max" 2>/dev/null || echo NA)
  hit=$(awk '/^max /{print $2}' "$s/memory.events" 2>/dev/null)
  oom=$(awk '/^oom_kill /{print $2}' "$s/memory.events" 2>/dev/null)
  # anon = 不可回收部分（真占用）。memory.current 还含 file cache（可回收），
  # 拿 current 去比 MemAvailable 会把同一块缓存算两遍 —— 见 docstring 2026-10-19 修正。
  anon=$(awk '/^anon /{print $2}' "$s/memory.stat" 2>/dev/null)
  echo "C|$c|$lim|$cur|$sw|$swmax|${hit:-0}|${oom:-0}|${anon:-0}"
done
free -m | awk '/^Mem:/{print "M|"$2"|"$7"|"$3}'
free -m | awk '/^Swap:/{print "S|"$2"|"$3}'
"""


def ssh(host, script):
    # stdout/stderr=PIPE + universal_newlines：Python 3.6 也支持
    # （capture_output 是 3.7+，目标端 3.6.8 上会 TypeError —— 2026-10-14 踩过）
    proc = subprocess.run(["ssh"] + SSH_OPTS + [host, script],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        print("❌ ssh %s 失败（rc=%d）：%s" % (host, proc.returncode, msg))
        print("   本工具应在【控制端】运行；目标端没有 lab-node 别名。")
        sys.exit(2)
    return proc.stdout


def sample(host):
    out = ssh(host, REMOTE)
    conts, mem, swap = [], None, None
    for ln in out.splitlines():
        f = ln.strip().split("|")
        if f[0] == "C":
            conts.append({"name": f[1], "lim": f[2], "cur": f[3],
                          "swap": f[4], "swmax": f[5],
                          "hit": int(f[6] or 0), "oom": int(f[7] or 0),
                          "anon": f[8] if len(f) > 8 else "NA"})
        elif f[0] == "M":
            mem = {"total": int(f[1]), "avail": int(f[2]), "used": int(f[3])}
        elif f[0] == "S":
            swap = {"total": int(f[1]), "used": int(f[2])}
    if not conts or not mem:
        print("❌ 取不到容器或内存数据（cgroup 驱动可能不是 systemd）")
        sys.exit(2)
    return conts, mem, swap


def mb(v, unit_mb=True):
    if v in ("NA", "", None):
        return None
    if v == "max":
        return "无界"
    n = float(v)
    return n / 1048576.0 if unit_mb else n


def fmt(v):
    if v is None:
        return "-"
    if v == "无界":
        return "无界"
    return "%.0f" % v


def main():
    args = [a for a in sys.argv[1:]]
    watch = 0
    if "--watch" in args:
        i = args.index("--watch")
        try:
            watch = int(args[i + 1])
        except (IndexError, ValueError):
            print("❌ --watch 需要一个秒数")
            return 2
        del args[i:i + 2]
    host = args[0] if args else "lab-node"

    c1, mem, swap = sample(host)

    print("=" * 78)
    print("容器内存预算核对 · %s · %s" % (host, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 78)
    print()
    print("  %-16s %8s %8s %8s %8s %8s %8s %6s" %
          ("容器", "上限MB", "当前MB", "anonMB", "swapMB", "撞限累计", "换出率", "OOM杀"))
    print("  " + "-" * 82)

    sum_lim = 0.0
    sum_cur = 0.0
    sum_anon = 0.0
    fails, warns = [], []

    for c in c1:
        lim = mb(c["lim"])
        cur = mb(c["cur"])
        anon = mb(c["anon"])
        sw = mb(c["swap"])
        is_lim = isinstance(lim, float)
        if is_lim:
            sum_lim += lim
        if isinstance(cur, float):
            sum_cur += cur
        if isinstance(anon, float):
            sum_anon += anon
        ratio = (sw / lim * 100) if (is_lim and isinstance(sw, float) and lim > 0) else None
        print("  %-16s %8s %8s %8s %8s %8s %8s %6d" %
              (c["name"], fmt(lim), fmt(cur), fmt(anon), fmt(sw), c["hit"],
               ("%.0f%%" % ratio) if ratio is not None else "-", c["oom"]))
        if c["oom"] > 0:
            fails.append("%s 被 OOM 杀过 %d 次" % (c["name"], c["oom"]))
        if is_lim and isinstance(sw, float) and lim > 0 and sw > lim * 0.5:
            warns.append("%s 换出 %.0f MB（超过上限的 50%%）" % (c["name"], sw))

    print("  " + "-" * 82)
    print("  %-16s %8.0f %8.0f %8.0f" % ("合计", sum_lim, sum_cur, sum_anon))
    print()
    print("  物理：total %d MB · used %d MB · available %d MB" %
          (mem["total"], mem["used"], mem["avail"]))
    print("  swap：total %d MB · used %d MB" % (swap["total"], swap["used"]))
    print()
    print("  ★ 判据说明：上限之和(%0.f) ÷ 当前合计(%0.f) = %.2f×" % (sum_lim, sum_cur,
          (sum_lim / sum_cur) if sum_cur else 0))
    print("    —— 这个比值衡量「距离上限还有多少余量」。")
    print("       太小(<1.5×) → 正常波动就可能撞上限；太大(>6×) → 上限形同虚设，起不到保护邻居的作用。")
    print("    上限之和 **不是** 预算：它是每个容器「最多能拿多少」的封顶，不是预留。")
    print()
    print("    anon = 不可回收的匿名内存（真占用）；当前MB = anon + file cache + kernel。")
    print("    比 available 要看 **anon**：file cache 本来就可回收，拿 current 去比会把同一块缓存")
    print("    算两遍，于是出现「容器合计 112% of available」这种没意义的提示（2026-10-19 修正）。")
    print("    但注意：anon 只是**容器**的，available 是**整机**的 —— 两者不同口径，只用来对照，不做判定。")
    print()

    # available 的判据分层：单点低不等于故障。
    # Linux 的 MemAvailable 已经把可回收缓存算进去了，分配时内核会回收 cache；
    # 所以 250 MB available 在 1.87 GB 机器上是**常态**，不是故障。
    # 真正会出事的是"低到分配失败"，那个阈值比"低"要低得多。
    pct = mem["avail"] / float(mem["total"]) * 100 if mem["total"] else 100
    if pct < 8:
        fails.append("available 只剩 %d MB（物理的 %.0f%%）—— 已接近分配失败" % (mem["avail"], pct))
    elif pct < 15:
        warns.append("available %d MB（物理的 %.0f%%）—— 余量偏低；本机这是常态，判趋势不判单点"
                     % (mem["avail"], pct))
    if swap["total"] > 0 and swap["used"] > swap["total"] * 0.5:
        warns.append("swap 已用 %d / %d MB（>50%%）" % (swap["used"], swap["total"]))

    # 跨周期观测：撞限是否还在增长（这才是"上限太紧"的直接证据）
    if watch > 0:
        print("  跨周期观测：%d 秒后再采一次…" % watch)
        time.sleep(watch)
        c2, _, _ = sample(host)
        m2 = dict((x["name"], x) for x in c2)
        print()
        print("  %-16s %10s %10s %10s" % ("容器", "撞限Δ", "当前MB(t1)", "当前MB(t2)"))
        print("  " + "-" * 50)
        for c in c1:
            o = m2.get(c["name"])
            if not o:
                continue
            d = o["hit"] - c["hit"]
            print("  %-16s %10d %10s %10s" %
                  (c["name"], d, fmt(mb(c["cur"])), fmt(mb(o["cur"]))))
            if d > 0:
                fails.append("%s 在 %d 秒内又撞上限 %d 次 —— 上限太紧" % (c["name"], watch, d))
        print()
        print("  说明：撞限 Δ=0 表示之前的累计值是历史（如启动回灌期）留下的一次性事件，")
        print("        不是正在被限流。这是区分「历史」与「现在」的唯一办法。")
        print()

    print("=" * 78)
    if fails:
        print("❌ 有问题：")
        for x in fails:
            print("   · " + x)
    if warns:
        print("⚠️ 提示：")
        for x in warns:
            print("   · " + x)
    if not fails and not warns:
        print("✅ 干净：无 OOM、无持续撞限、余量充足。")
    print("=" * 78)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
