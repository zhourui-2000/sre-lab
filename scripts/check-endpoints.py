#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站点对外入口的健康检查矩阵（只读）

为什么需要这个工具（2026-10-19）：
    之前所有"`/healthz` 返回 200"的验证，**只验了 http 入口**。
    `https://zhourui2000.online/healthz` 实际是 **404** —— 因为规范化（www→裸域）
    之后那个 443 server 块里没有 /healthz 的 location。
    单点验证会给出"健康"的错觉，而用户真正访问的路径是坏的。

用法：
    python3 scripts/check-endpoints.py            # 从当前主机发起
    python3 scripts/check-endpoints.py --json     # 机器可读

设计要点：
    · **不跟随重定向地看第一跳**，再单独看"跟随之后"的最终状态 ——
      两个都要对。只看最终 200 会漏掉"跳转到了错误的地方"；
      只看第一跳 301 会漏掉"跳过去是 404"。
    · SSL 证书不校验：本工具验的是**可达性与状态码**，证书有效性是另一件事，
      混在一起会互相掩盖（证书过期 vs 服务挂了，是两种故障）。
    · 退出码：0 全部符合；1 有不符合；2 环境问题（DNS 失败等）。
"""
import json
import ssl
import sys
import urllib.error
import urllib.request

# (标签, URL, 期望第一跳状态, 是否跟随重定向, 期望最终状态)
# 最终状态填 None 表示该行不检查跟随结果
MATRIX = [
    ("http 裸域 /healthz",        "http://zhourui2000.online/healthz",        200, False, None),
    ("http www  /healthz",        "http://www.zhourui2000.online/healthz",    200, False, None),
    ("https 裸域 /healthz",       "https://zhourui2000.online/healthz",       200, False, None),
    ("https www /healthz",        "https://www.zhourui2000.online/healthz",   301, True, 200),
    ("http 裸域 /",               "http://zhourui2000.online/",               301, True, 200),
    ("https www /",               "https://www.zhourui2000.online/",          301, True, 200),
    ("https 裸域 /",              "https://zhourui2000.online/",              200, False, None),
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 不自动跟随 → 3xx 会以 HTTPError 抛出，便于读第一跳


def _open(url, follow, timeout=15):
    handlers = [urllib.request.HTTPSHandler(context=CTX)]
    if not follow:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "sre-lab-endpoint-check/1.0"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.headers.get("Location"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), url
    except Exception as e:
        return "ERR:%s" % e, None, url


def main():
    as_json = "--json" in sys.argv
    rows = []
    fail = 0

    for label, url, exp_first, follow, exp_final in MATRIX:
        first, loc, _ = _open(url, follow=False)
        final = None
        final_url = None
        if follow:
            final, _, final_url = _open(url, follow=True)

        ok_first = (first == exp_first)
        ok_final = (exp_final is None) or (final == exp_final)
        ok = ok_first and ok_final
        if not ok:
            fail += 1
        rows.append(dict(label=label, url=url, first=first, expect_first=exp_first,
                         location=loc, final=final, expect_final=exp_final,
                         ok=ok))

    if as_json:
        print(json.dumps({"rows": rows, "fail": fail}, ensure_ascii=False, indent=2))
        return 1 if fail else 0

    print("=" * 78)
    print("站点对外入口 · 健康检查矩阵")
    print("=" * 78)
    print("  %-22s %-9s %-7s %-7s %s" % ("入口", "第一跳", "期望", "跟随终态", "结果"))
    print("  " + "-" * 72)
    for r in rows:
        f = str(r["first"])
        exp = str(r["expect_first"])
        fin = "—" if r["final"] is None else str(r["final"])
        if r["expect_final"] is not None:
            fin = "%s(期望%s)" % (fin, r["expect_final"])
        print("  %-22s %-9s %-7s %-7s %s" % (r["label"], f, exp, fin,
                                             "✅" if r["ok"] else "❌"))
        if r["location"]:
            print("  %-22s   ↳ Location: %s" % ("", r["location"]))
        if isinstance(r["first"], str) and r["first"].startswith("ERR:"):
            print("  %-22s   ↳ %s" % ("", r["first"]))

    print()
    if fail:
        print("❌ %d/%d 个入口不符合预期" % (fail, len(rows)))
        print("   常见原因：")
        print("     · https 裸域 /healthz = 404 → 443 的裸域 server 块里缺 `location = /healthz`")
        print("     · 全部 ERR → DNS 解析失败（先在控制端 `getent hosts <域名>` 确认）")
        print("     · 改了 nginx 配置但没生效 → 挂载的配置需要 `docker exec web nginx -s reload`")
        return 1
    print("✅ 全部 %d 个入口符合预期" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
