#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SLO 文档 ↔ 规则的一致性。

审稿意见里点名的「欠条」：`slo.md` 的预算/阈值/告警靠手工和 `slo-rules.yml` 同步。
手工同步必然漂移 —— 这个项目已经用 17 篇复盘证明过这一点。

范围划清：
  这里只校验「两边说同一个数」，**不**校验「规则写得对不对」。
  后者是 `vmalert -dryRun` 的事（见 .github/workflows/lint.yml）。
  两者混在一起，就会变成又一个只会返回成功的校验器。

已知缺口用 xfail 标注：现在还红，修好后**必须**把标记去掉（否则 xpass 会反过来让 CI 红）。
"""

import io
import os
import re
import sys

from _common import ROOT, iter_alerts, md_files, read

BUDGET_MINUTES = 216.0
SCRAPE_SECONDS = 15
SLO_WINDOW_DAYS = 30
SLO_TARGET = 0.995

EXPECTED_ALERTS = {
    "SiteDown", "SiteDownFast", "ProbePipelineDown", "SloNoData",
    "SloFastBurn", "SloMediumBurn", "SloSlowBurn", "CertExpiringSoon",
}
ALLOWED_SEVERITY = {"critical", "warning", "info"}


def _read_path(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def check_budget_math():
    assert abs(SLO_WINDOW_DAYS * 1440 * (1 - SLO_TARGET) - BUDGET_MINUTES) < 1e-9, \
        "预算分钟与 SLO 目标不自洽"
    probes = BUDGET_MINUTES * 60 / SCRAPE_SECONDS
    assert abs(probes - 864) < 1e-9, "折算次数应为 864，实际 %s" % probes

    slo = read("docs", "slo.md")
    for needle in ("216", "864", "99.5"):
        assert needle in slo, "slo.md 缺少 %s" % needle

    rep = read("scripts", "slo-report.py")
    m = re.search(r"^BUDGET_MINUTES\s*=\s*([\d.]+)", rep, re.M)
    assert m, "slo-report.py 里找不到 BUDGET_MINUTES"
    assert abs(float(m.group(1)) - BUDGET_MINUTES) < 1e-9, \
        "slo-report.py 的 BUDGET_MINUTES=%s，文档是 %s" % (m.group(1), BUDGET_MINUTES)
    m = re.search(r"^SCRAPE_SECONDS\s*=\s*(\d+)", rep, re.M)
    assert m and int(m.group(1)) == SCRAPE_SECONDS, "slo-report.py 的 SCRAPE_SECONDS 与文档不一致"


def check_alert_set():
    alerts = iter_alerts(read("observability", "slo-rules.yml"))
    names = {a["name"] for a in alerts}
    assert not (EXPECTED_ALERTS - names), "规则里缺告警：%s" % sorted(EXPECTED_ALERTS - names)
    assert not (names - EXPECTED_ALERTS), \
        "规则里有未登记的告警（请同时更新本测试与文档）：%s" % sorted(names - EXPECTED_ALERTS)

    bad = [a["name"] for a in alerts if a["severity"] not in ALLOWED_SEVERITY]
    assert not bad, "severity 取值非法：%s" % bad

    corpus = "\n".join(_read_path(p) for p in md_files())
    undocumented = [a["name"] for a in alerts if a["name"] not in corpus]
    assert not undocumented, "告警没写进任何文档：%s" % undocumented


def check_burn_thresholds():
    rules = read("observability", "slo-rules.yml")
    slo = read("docs", "slo.md")
    for th in ("14.4", "6", "1"):
        assert re.search(r">\s*%s(\.\d+)?\b" % re.escape(th), rules), \
            "规则里找不到烧钱率阈值 %s" % th
    for th in ("14.4×", "6×", "1×"):
        assert th in slo, "slo.md 缺少烧钱率阈值 %s" % th


def check_window_vs_retention():
    """SLO 窗口 30 天；VM retention 若也是 30d，左边界样本会被裁掉，SLI 永远算不满。"""
    compose = read("observability", "docker-compose.yml")
    m = re.search(r"--retentionPeriod=(\d+)d", compose)
    assert m, "docker-compose.yml 里找不到 --retentionPeriod（口径变了，请更新本测试）"
    days = int(m.group(1))
    assert days > SLO_WINDOW_DAYS, \
        "retention=%dd 不大于 SLO 窗口 %dd —— 滚动窗口左边界样本会被裁掉" % (days, SLO_WINDOW_DAYS)


def check_for_table():
    """slo.md 里的「告警与 for:」清单必须与 rules 逐条一致。

    这条对应审稿的意见：改 `for:` 而不同步文档，是最容易悄悄发生的一种漂移 ——
    `for` 决定「多久才响」，写错了没人会发现，直到真出事。
    """
    slo = read("docs", "slo.md")
    marker = "告警与 `for:`（唯一清单）"
    assert marker in slo, "slo.md 缺少「%s」段" % marker
    seg = slo.split(marker, 1)[1].split("\n## ", 1)[0]

    row = re.compile(r"^\|\s*`([\w]+)`\s*\|\s*(\S+)\s*\|\s*(\w+)\s*\|", re.M)
    doc = {m.group(1): (m.group(2), m.group(3)) for m in row.finditer(seg)}
    rules = {a["name"]: (a["for"], a["severity"]) for a in iter_alerts(read("observability", "slo-rules.yml"))}

    missing = set(rules) - set(doc)
    extra = set(doc) - set(rules)
    assert not missing, "文档缺这些告警的 for 行：%s" % sorted(missing)
    assert not extra, "文档里有规则中不存在的告警：%s" % sorted(extra)
    diff = ["%s：规则 %s / 文档 %s" % (k, rules[k], doc[k]) for k in sorted(rules) if rules[k] != doc[k]]
    assert not diff, "for / severity 不一致：\n        " + "\n        ".join(diff)


# (名称, 函数, 是否已知缺口)
CHECKS = [
    ("预算算式自洽（216 / 864）", check_budget_math, False),
    ("告警名单与文档覆盖", check_alert_set, False),
    ("烧钱率阈值两边一致", check_burn_thresholds, False),
    ("for: / severity 清单一致", check_for_table, False),
    ("retention > SLO 窗口", check_window_vs_retention, True),   # B3，批次 3 修
]


def main():
    print("仓库：%s" % ROOT)
    failed = 0
    for name, fn, known_gap in CHECKS:
        try:
            fn()
        except AssertionError as e:
            if known_gap:
                print("  xfail %s  ← 已知缺口：%s" % (name, e))
                continue
            failed += 1
            print("  FAIL  %s\n        %s" % (name, e))
            continue
        if known_gap:
            failed += 1
            print("  XPASS %s  ← 缺口已修，请去掉 CHECKS 里的 known_gap 标记" % name)
            continue
        print("  ok    %s" % name)
    print("  → %d 项，%d 失败" % (len(CHECKS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
