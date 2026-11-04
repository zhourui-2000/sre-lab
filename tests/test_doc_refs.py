#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档引用完整性：文档里承诺存在的文件，仓库里必须真的存在。

审稿意见的出发点很直接：这份材料最常犯的错不是「写得少」，而是「文档承诺 ≠ 仓库事实」——
比如把一个没入库的脚本写成 `scripts/check-three-ends.sh`，或者引用一个已经删掉的 ADR。

两类引用都查：
  ① 反引号里的路径（`scripts/x.py`、`observability/y.yml`）→ 相对仓库根解析
  ② markdown 链接（`[..](x.md)`）→ 先按文件所在目录解析，再回退到仓库根
  ③ `方法论 ⑰` 这类编号引用 → 对应的 `## ⑰` 标题必须存在
"""

import io
import os
import re
import sys

from _common import ROOT, md_files, tracked

ROOTS = ("scripts/", "docs/", "observability/", "k8s/", "ansible/", "nginx/")
FILE_EXT = (".py", ".md", ".yml", ".yaml", ".sh", ".json", ".conf", ".example")

TICK = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")
NUM_REF = re.compile(r"方法论\s*([\u2460-\u2473\u3251-\u325f]+)")
NUM_HEAD = re.compile(r"^##\s*([\u2460-\u2473\u3251-\u325f])", re.M)


def looks_like_path(tok):
    tok = tok.strip()
    if not tok or " " in tok:
        return None
    if any(c in tok for c in "*{}<>|$") or "..." in tok:
        return None
    if tok.startswith(("http://", "https://", "#")):
        return None
    if tok.startswith(ROOTS):
        return tok
    return None


def _exists(rel, tracked_set):
    rel = rel.replace(os.sep, "/").rstrip("/")
    if tracked_set is not None:
        if rel in tracked_set:
            return True
        # 目录在 git ls-files 里没有独立条目 —— 看有没有以它开头的文件
        return any(t.startswith(rel + "/") for t in tracked_set)
    return os.path.exists(os.path.join(ROOT, rel))


def check_path_refs():
    tracked_set = tracked()
    if tracked_set is None:
        print("        （不在 git 仓库里，退化为文件系统检查）")
    bad = []
    for p in md_files():
        with io.open(p, encoding="utf-8") as f:
            text = f.read()
        base = os.path.dirname(p)
        for tok in TICK.findall(text):
            t = looks_like_path(tok)
            if not t:
                continue
            if t.endswith(FILE_EXT) or os.path.splitext(t)[1]:
                if not _exists(t, tracked_set):
                    bad.append("%s → `%s`（不在版本控制里）" % (os.path.relpath(p, ROOT), t))
        for href in LINK.findall(text):
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            href = href.split("#")[0]
            if not href:
                continue
            cand = os.path.relpath(os.path.normpath(os.path.join(base, href)), ROOT)
            if not _exists(cand, tracked_set):
                cand2 = href
                if not _exists(cand2, tracked_set):
                    bad.append("%s → [..](%s)（不在版本控制里）" % (os.path.relpath(p, ROOT), href))
            continue
    assert not bad, "引用了不存在的文件：\n        " + "\n        ".join(sorted(set(bad)))


def check_methodology_refs():
    with io.open(os.path.join(ROOT, "docs", "methodology.md"), encoding="utf-8") as f:
        heads = set(NUM_HEAD.findall(f.read()))
    assert heads, "methodology.md 里没找到 `## ①` 形式的编号标题"
    bad = []
    for p in md_files():
        if p.endswith("methodology.md"):
            continue
        with io.open(p, encoding="utf-8") as f:
            text = f.read()
        for grp in NUM_REF.findall(text):
            for ch in grp:
                if ch not in heads:
                    bad.append("%s → 方法论 %s" % (os.path.relpath(p, ROOT), ch))
    assert not bad, "引用了不存在的方法论编号：\n        " + "\n        ".join(sorted(set(bad)))


CHECKS = [
    ("文件引用存在", check_path_refs),
    ("方法论编号对得上", check_methodology_refs),
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
