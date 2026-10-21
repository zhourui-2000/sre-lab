#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灾备可恢复性盘点（只读）

回答一个问题：**这台机器没了，每一块东西能不能回来、从哪儿回来。**

用法（在控制端 WSL 执行）：
    python3 scripts/check-recoverability.py              # 默认 ssh 别名 lab-node
    python3 scripts/check-recoverability.py lab-node --verbose

为什么需要它（而不是拍脑袋写一份"备份清单"）：
    清单谁都会写，但**清单和现实会漂移** —— 加了一个容器、换了一个配置路径，
    清单不会自动更新。这个工具每次现读现判：
      · 这块东西**在不在**仓库里（`git ls-files`，不是"我记得提交过"）
      · 不在仓库的，**有没有备份**（扫已知备份目录，不是"应该有吧"）
      · 两类都没有的 → ❌ 无恢复来源，就是 RPO 的漏洞

判定口径：
    ✅ GitHub      在版本控制里 → RPO = 上次 push 之后为 0
    ✅ IaC         由 Ansible 模板生成（会打印匹配到的模板路径）
    ✅ 程序重建     运行时产物，程序自己会再造出来（cgroup、iptables、容器层）
    ⚠️ 有备份       找到备份副本 —— 但**未验证可恢复性**（能拷回来 ≠ 能跑起来）
    ❌ 无来源       既不在库、也没备份 → 丢掉就是丢掉

退出码：0 全部有来源；1 存在 ❌；2 工具自身失效（ssh / git 不可用）。
"""
from __future__ import print_function

import subprocess
import sys

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
REPO = "/opt/sre-lab"

# (id, 名称, 路径, 类别, IaC 模板关键字)
# 类别：git / iac / state / secret / data / runtime
UNITS = [
    ("repo",         "仓库工作副本",        REPO,                                       "git",  None),
    ("nginx-compose", "站点 compose",       "nginx/docker-compose.yml",                 "git",  None),
    ("nginx-conf",   "nginx 配置",          "nginx/conf.d",                             "git",  None),
    ("nginx-html",   "站点静态内容",        "nginx/html",                               "git",  None),
    ("obs-compose",  "可观测 compose",      "observability/docker-compose.yml",         "git",  None),
    ("obs-scrape",   "采集配置",            "observability/scrape.yml",                 "git",  None),
    ("obs-rules",    "主机告警规则",        "observability/alert-rules.yml",            "git",  None),
    ("slo-rules",    "SLO 规则",            "observability/slo-rules.yml",              "git",  None),
    ("bb-conf",      "探针模块",            "observability/blackbox.yml",               "git",  None),
    ("obs-env",      "版本变量 .env",       "observability/.env",                       "git",  None),
    ("argocd-vals",  "ArgoCD values",       "k8s/argocd/values.yaml",                   "git",  None),
    ("k3s-config",   "k3s 配置",            "/etc/rancher/k3s/config.yaml",             "iac",  "/etc/rancher/k3s/config.yaml"),
    ("k3s-reg",      "镜像加速配置",        "/etc/rancher/k3s/registries.yaml",         "iac",  "/etc/rancher/k3s/registries.yaml"),
    ("docker-daemon", "docker daemon",      "/etc/docker/daemon.json",                  "iac",  "/etc/docker/daemon.json"),
    ("fail2ban",     "fail2ban 配置",       "/etc/fail2ban/jail.local",                 "iac",  "/etc/fail2ban/jail.local"),
    ("sysctl",       "sysctl 调优",         "/etc/sysctl.d/99-sre-lab.conf",            "iac",  "/etc/sysctl.d/99-sre-lab.conf"),
    ("k3s-state",    "k3s 集群状态",        "/var/lib/rancher",                         "state", None),
    ("letsencrypt",  "TLS 证书",            "/etc/letsencrypt",                         "secret", None),
    ("am-secret",    "alertmanager(密钥)",  "/root/.sre-lab-secrets/alertmanager.yml",  "secret", None),
    ("vmdata",       "指标数据",            REPO + "/observability/vmdata",             "data", None),
    ("loki-data",    "日志数据",            REPO + "/observability/loki-data",          "data", None),
    ("grafana-data", "Grafana 数据",        REPO + "/observability/grafana-data",       "data", None),
    ("am-data",      "告警静默状态",        REPO + "/observability/alertmanager-data",  "data", None),
]

BACKUP_DIRS = ["/root/backup", "/root/backups", "/var/backups/sre-lab", "/opt/backup"]


def ssh(host, script):
    proc = subprocess.run(["ssh", ] + SSH_OPTS + [host, script],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    if proc.returncode != 0:
        print("❌ ssh %s 失败（rc=%d）：%s" % (host, proc.returncode,
                                             (proc.stderr or proc.stdout).strip()))
        print("   本工具应在【控制端】运行；目标端没有 lab-node 别名。")
        sys.exit(2)
    return proc.stdout


def probe(host, paths, hints):
    """一次 ssh 里把所有路径的 exists / tracked / size / ignored 取回来"""
    lines = []
    lines.append('cd %s 2>/dev/null || { echo "E|norepo"; exit 0; }' % REPO)
    lines.append('git ls-files > /tmp/.recoverable-files.$$ 2>/dev/null')
    lines.append('for p in %s; do' % " ".join('"%s"' % p for p in paths))
    lines.append('  if [ -e "$p" ]; then e=1; else e=0; fi')
    lines.append('  if grep -qx "$p" /tmp/.recoverable-files.$$ 2>/dev/null; '
                 'then t=1; '
                 'elif [ -d "$p" ] && grep -q "^$p/" /tmp/.recoverable-files.$$ 2>/dev/null; '
                 'then t=1; else t=0; fi')
    lines.append('  s=$(du -sh "$p" 2>/dev/null | cut -f1)')
    lines.append('  ig=$(git status --ignored --porcelain -- "$p" 2>/dev/null | grep -c "^!!")')
    lines.append('  echo "P|$p|$e|$t|${s:--}|${ig:-0}"')
    lines.append('  git status --ignored --porcelain -- "$p" 2>/dev/null '
                 '| grep "^!!" | head -3 | sed "s/^!! /G|/"')
    lines.append('done')
    lines.append('rm -f /tmp/.recoverable-files.$$')
    lines.append('for d in %s; do [ -e "$d" ] && echo "B|$d"; done' % " ".join(BACKUP_DIRS))
    # IaC 单元：用「目标路径」去仓库里搜 —— 能匹配到 tasks 里的 dest 或 files/ 模板
    lines.append('for h in %s; do' % " ".join('"%s"' % h for h in hints))
    lines.append('  f=$(git grep -l -- "$h" ansible 2>/dev/null | head -1)')
    lines.append('  echo "I|$h|${f:-}"')
    lines.append('done')
    return ssh(host, "\n".join(lines))


def main():
    args = [a for a in sys.argv[1:]]
    verbose = "--verbose" in args
    if verbose:
        args.remove("--verbose")
    host = args[0] if args else "lab-node"

    paths = [u[2] for u in UNITS]
    hints = [u[4] for u in UNITS if u[3] == "iac"]
    out = probe(host, paths, hints)
    if "E|norepo" in out:
        print("❌ 目标端找不到仓库：%s" % REPO)
        return 2

    state, backups, iac_map, ignored_paths = {}, [], {}, []
    for ln in out.splitlines():
        f = ln.split("|")
        if f[0] == "P" and len(f) >= 5:
            state[f[1]] = {"exists": f[2] == "1", "tracked": f[3] == "1", "size": f[4],
                           "ignored": int(f[5]) if len(f) > 5 and f[5].isdigit() else 0}
        elif f[0] == "B" and len(f) >= 2:
            backups.append(f[1])
        elif f[0] == "G" and len(f) >= 2:
            p = f[1].strip()
            if p and p not in ignored_paths:
                ignored_paths.append(p)
        elif f[0] == "I" and len(f) >= 3:
            iac_map[f[1]] = f[2].strip()

    print("=" * 96)
    print("灾备可恢复性盘点 · %s" % host)
    print("=" * 96)
    print("  %-14s %-44s %6s %4s  %s" % ("单元", "路径", "大小", "在库", "判定"))
    print("  " + "-" * 92)

    ok = warn = bad = 0
    rows = []
    for uid, name, path, cls, hint in UNITS:
        st = state.get(path, {"exists": False, "tracked": False, "size": "-"})
        if cls == "git":
            if uid == "repo":
                verdict, tag = "✅ GitHub（就是仓库本身）", "ok"
            elif not st["tracked"]:
                verdict, tag = "❌ 路径不在版本控制里", "bad"
            elif st.get("ignored", 0) > 0:
                verdict, tag = "⚠️ 部分在库（%d 处被 .gitignore 排除）" % st["ignored"], "warn"
            else:
                verdict, tag = "✅ GitHub", "ok"
        elif cls == "iac":
            hit = iac_map.get(hint or "", "")
            if hit:
                verdict, tag = "✅ IaC：%s" % hit, "ok"
            else:
                verdict, tag = "❌ 仓库里搜不到这个目标路径", "bad"
        elif cls == "runtime":
            verdict, tag = "✅ 程序自动重建", "ok"
        else:  # state / secret / data
            if st["tracked"]:
                verdict, tag = "✅ GitHub（意外：数据进了版本控制？）", "ok"
            elif backups:
                verdict, tag = "⚠️ 有备份目录（未验可恢复）", "warn"
            else:
                verdict, tag = "❌ 无恢复来源", "bad"

        if tag == "ok":
            ok += 1
        elif tag == "warn":
            warn += 1
        else:
            bad += 1
        rows.append((name, path, st["size"], "是" if st["tracked"] else "否", verdict))


    for name, path, size, tracked, verdict in rows:
        print("  %-14s %-44s %6s %4s  %s" % (name, path[:44], size, tracked, verdict))

    print("  " + "-" * 92)
    print("  合计：✅ %d   ⚠️ %d   ❌ %d" % (ok, warn, bad))
    print()
    if ignored_paths:
        print("  ⚠️ 被 .gitignore 排除的内容（**不在仓库里**，重建时不会回来）：")
        for p in ignored_paths[:12]:
            print("     · %s" % p)
    else:
        print("  （没有被 .gitignore 排除的已跟踪路径）")
    print()
    print("  备份目录扫描：%s" % ("、".join(backups) if backups else "**一个都没有**"))
    print("  IaC 模板：仓库里 ansible/roles 下共 %d 个文件" % len(iac_files))

    if verbose:
        print()
        print("  —— 判定说明 ——")
        print("  ✅ GitHub  : RPO = 上次 push 之后（配置与静态内容的理想状态）")
        print("  ✅ IaC     : 重跑 ansible-playbook 可还原（模板路径已列出，可自行核对）")
        print("  ⚠️ 有备份  : 只能证明「有一份拷贝」，不能证明「拷回来能跑」")
        print("  ❌ 无来源  : 这块东西丢掉就是丢掉 —— 这是 RPO 的真实下界")

    print()
    print("  ★ 注意：本工具只判「有没有来源」，不判「恢复要多久」。RTO 要靠演练掐表。")
    print("=" * 96)

    if bad:
        print("结论：❌ 有 %d 个单元没有任何恢复来源 —— 这就是灾备要补的地方。" % bad)
        return 1
    print("结论：✅ 所有单元都有恢复来源。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
