#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试入口：`python3 tests/run.py`（或 `make verify`）。

设计约束：**零第三方依赖**。陌生环境 clone 下来必须能直接跑，
装依赖这一步本身就是「一条命令跑通」的失败点。
"""

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    mods = sorted(
        f[:-3] for f in os.listdir(HERE)
        if f.startswith("test_") and f.endswith(".py")
    )
    if not mods:
        print("没有找到测试")
        return 1

    rc = 0
    for name in mods:
        print("\n" + "=" * 66)
        print("  " + name)
        print("=" * 66)
        mod = importlib.import_module(name)
        if not hasattr(mod, "main"):
            print("  FAIL 缺少 main()")
            rc = 1
            continue
        rc = mod.main() or rc

    print("\n" + "=" * 66)
    print("  %s" % ("全部通过" if rc == 0 else "有失败"))
    print("=" * 66)
    return rc


if __name__ == "__main__":
    sys.exit(main())
