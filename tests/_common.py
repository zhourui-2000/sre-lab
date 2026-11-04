#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试公共工具：仓库定位、读文件、最小 YAML 抽取。

刻意**不依赖第三方库**（不用 PyYAML / pytest）：
陌生环境 clone 下来 `make verify` 必须能直接跑，装依赖这一步本身就是失败点。
"""

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RULES = os.path.join(ROOT, "observability", "slo-rules.yml")


def read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def exists(*parts):
    return os.path.exists(os.path.join(ROOT, *parts))


def md_files():
    """所有要参与校验的 markdown：README + docs/**/*.md"""
    out = [os.path.join(ROOT, "README.md")]
    for dp, _dn, fn in os.walk(os.path.join(ROOT, "docs")):
        for f in fn:
            if f.endswith(".md"):
                out.append(os.path.join(dp, f))
    return [p for p in out if os.path.isfile(p)]


def iter_alerts(text):
    """从 slo-rules.yml 里抽出 [(name, for, severity)]。

    只做「这个项目实际用到的子集」，不假装是 YAML 解析器 ——
    真正的语法校验交给 CI 里的 vmalert -dryRun（那才是权威）。
    """
    out = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\s*-\s+alert:\s*(\S+)\s*$", line)
        if m:
            if cur:
                out.append(cur)
            cur = {"name": m.group(1), "for": None, "severity": None}
            continue
        if cur is None:
            continue
        m = re.match(r"^\s*for:\s*(\S+)\s*$", line)
        if m:
            cur["for"] = m.group(1)
            continue
        m = re.search(r"severity:\s*(\w+)", line)
        if m and cur["severity"] is None:
            cur["severity"] = m.group(1)
    if cur:
        out.append(cur)
    # 只保留真正带 for: 的（记录规则没有 alert:）
    return [a for a in out if a["for"]]
