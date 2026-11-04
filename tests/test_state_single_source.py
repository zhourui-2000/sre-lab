#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态断言单一真源（评审原则 P2）。

评审实证过：同一组 RTO 被复述 6 处，其中 1 处已过期。
「复述」本身不可避免（README 要给人看），会出事的是**漂移**。
所以这里不禁止复述，只做两件事：

  ① 结构：`baseline.md` 必须有「状态真源」表，且每行带「测量命令」列
  ② 漂移：维护一份**过期值黑名单** —— 每次改数，把旧值加进来，谁抄错谁红

黑名单是这个测试的核心资产：它把「我记得改过」变成「机器保证没漏」。
"""

import io
import os
import sys

from _common import ROOT, md_files, read

# 过期值黑名单：出现即为漂移。改数时把旧值加到这里。
STALE = [
    ("203.9", "旧的错误预算分钟（ratio×216 时代的值），真实约 109 分钟"),
    ("MTTR 未测", "MTTR 已实测（128 s / 69 s），见 slo.md §11"),
    ("7 条告警", "SLO 告警已是 8 条（多了 SiteDownFast）"),
    ("16 条规则", "slo-canonical 已是 17 条（9 记录 + 8 告警）"),
    ("94 commit", "commit 计数已变（2026-11-04 为 100）"),
    ("4057", "文档行数已变（精简后约 2500）"),
    ("L4「让干净的 k3s 用这份 db 真正起来」未证", "L4 已于 2026-10-22 验证"),
]


def check_state_table():
    base = read("docs", "baseline.md")
    assert "## 状态真源" in base, "baseline.md 缺少 `## 状态真源` 段"
    seg = base.split("## 状态真源", 1)[1]
    seg = seg.split("\n## ", 1)[0]

    header = [l for l in seg.splitlines() if l.strip().startswith("|")]
    assert len(header) >= 3, "状态真源段里没有表格"
    assert "测量" in header[0], "状态真源的表格必须有「测量命令」列（判据要可执行，不能只写值）"

    rows = [l for l in header[2:] if l.strip(" |")]
    assert len(rows) >= 5, "状态真源至少要有 5 行（RTO / 备份 / RPO / MTTR / 预算），实际 %d" % len(rows)

    for key in ("RTO", "L1", "RPO", "MTTR", "预算"):
        assert key in seg, "状态真源缺关键行：%s" % key


def check_readme_points_to_source():
    rd = read("README.md")
    assert "状态真源" in rd, "README 必须写明「状态类数字的真源在哪」——否则它自己就成了第二份真源"
    assert "baseline.md" in rd, "README 里要给出 baseline.md 的链接"


# 明确标注为「历史值」的写法是合法的记录，不是漂移。
# 例如 slo.md 里的「旧 203.9 分钟 → 新 109.4 分钟」是修 bug 的证据，删掉反而丢信息。
HISTORICAL_MARKERS = ("旧 ", "旧**", "修正前", "曾", "deprecated", "已废弃")


def _is_historical(line):
    return any(m in line for m in HISTORICAL_MARKERS)


def check_no_stale_values():
    bad = []
    for p in md_files():
        with io.open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()
        for i, line in enumerate(lines, 1):
            for old, why in STALE:
                if old not in line:
                    continue
                if _is_historical(line):
                    continue          # 标注过的历史值放行
                bad.append("%s:%d 里还有「%s」—— %s" % (os.path.relpath(p, ROOT), i, old, why))
    assert not bad, ("过期值残留（未标注为历史值）：\n        "
                     + "\n        ".join(bad))


CHECKS = [
    ("baseline 有状态真源表（含测量命令）", check_state_table),
    ("README 指向真源", check_readme_points_to_source),
    ("无过期值残留", check_no_stale_values),
]


def main():
    print("仓库：%s" % ROOT)
    failed = 0
    for name, fn in CHECKS:
        try:
            fn()
            print("  ok    %s" % name)
        except AssertionError as e:
            failed += 1
            print("  FAIL  %s\n        %s" % (name, e))
    print("  → %d 项，%d 失败" % (len(CHECKS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
