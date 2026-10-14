#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-fw-drift.py —— 只读核对：服务器防火墙持久配置是否等于 IaC 声明。

用法（在控制端执行）：
    python3 scripts/check-fw-drift.py [ssh别名]              # 默认 lab-node
    SRE_LAB_REPO=/root/sre-lab python3 check-fw-drift.py     # 指定仓库根（测试用）

判据（不需要维护任何白名单）：
    出厂态  /usr/lib/firewalld/zones/*.xml   RPM 出厂定义；本地改动不写这个目录
    当前态  /etc/firewalld/zones/*.xml       firewalld 只在本地有改动时才生成
    全部本地改动     = 当前态 − 出厂态
    无主改动（漂移） = 全部本地改动 − IaC 声明     ← 重建时会丢掉的正是这一部分
    缺失             = IaC 声明 − 当前态           ← playbook 未应用，或被人手工删掉

退出码：0 干净；1 有漂移或缺失；2 脚本前提失效（解析不到声明 / ssh 失败）。
"""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

# XML 子元素 -> (kind, 取值属性)；kind 与 security 角色 loop 里的 item.kind 对齐
KINDS = {
    "service":   ("service",   "name"),
    "source":    ("source",    "address"),
    "interface": ("interface", "name"),
    "protocol":  ("protocol",  "value"),
    "ipset":     ("ipset",     "name"),
}

REMOTE_DUMP = r"""
cd /etc/firewalld/zones 2>/dev/null || exit 3
for f in *.xml; do
  printf '\n@@ZONE %s\n' "${f%.xml}"
  printf '@@FACTORY\n'
  cat "/usr/lib/firewalld/zones/$f" 2>/dev/null || true
  printf '@@CURRENT\n'
  cat "$f" 2>/dev/null || true
done
"""


def ssh(host, script):
    proc = subprocess.run(["ssh"] + SSH_OPTS + [host, script],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        print("❌ ssh %s 失败（rc=%d）：%s" % (host, proc.returncode, msg))
        sys.exit(2)
    return proc.stdout


def parse_declared(path):
    """从 security 角色解析出 IaC 声明的规则集合（'zone\\tkind\\tvalue'）。"""
    try:
        import yaml
    except ImportError:
        print("❌ 控制端缺少 PyYAML（ansible-core 的依赖），无法解析 IaC 声明。")
        sys.exit(2)
    if not os.path.isfile(path):
        print("❌ 找不到 %s" % path)
        sys.exit(2)
    with open(path, encoding="utf-8") as fh:
        docs = yaml.safe_load(fh)
    rules = set()
    for task in docs or []:
        if not isinstance(task, dict):
            continue
        if "预检 firewalld" not in str(task.get("name", "")):
            continue
        for item in task.get("loop") or []:
            if isinstance(item, dict) and {"zone", "kind", "value"} <= set(item):
                rules.add("%s\t%s\t%s" % (item["zone"], item["kind"], item["value"]))
    return rules


def parse_dump(text):
    """把远程 dump 解析成 {zone: {'factory': xml, 'current': xml}}。"""
    zones, zone, section, buf = {}, None, None, []
    for line in text.splitlines():
        if line.startswith("@@ZONE "):
            if zone and section:
                zones.setdefault(zone, {})[section] = "\n".join(buf)
            zone, section, buf = line[7:].strip(), None, []
        elif line == "@@FACTORY" or line == "@@CURRENT":
            if zone and section:
                zones.setdefault(zone, {})[section] = "\n".join(buf)
            section, buf = ("factory" if line == "@@FACTORY" else "current"), []
        else:
            buf.append(line)
    if zone and section:
        zones.setdefault(zone, {})[section] = "\n".join(buf)
    return zones


def entries_of(xml_text):
    """把 zone XML 解析成条目集合（'kind\\tvalue'）。"""
    out = set()
    if not xml_text or not xml_text.strip():
        return out
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for el in root:
        tag = el.tag
        if tag == "port" and el.get("port") and el.get("protocol"):
            out.add("port\t%s/%s" % (el.get("port"), el.get("protocol")))
        elif tag in KINDS:
            kind, attr = KINDS[tag]
            value = el.get(attr)
            if value:
                out.add("%s\t%s" % (kind, value))
        elif tag in ("masquerade", "forward"):
            out.add("%s\t%s" % (tag, (el.text or "yes").strip()))
        elif tag == "rule":
            out.add("rich\t%s" % " ".join(ET.tostring(el, encoding="unicode").split()))
    return out


def split3(item):
    zone, kind, value = item.split("\t", 2)
    return zone, kind, value


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "lab-node"
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.environ.get("SRE_LAB_REPO") or os.path.dirname(here)
    tasks = os.path.join(repo, "ansible", "roles", "security", "tasks", "main.yml")

    print("sre-lab 防火墙漂移核对（只读）")
    print("  控制端仓库：%s" % repo)
    print("  目标主机　：%s" % host)
    print()

    declared = parse_declared(tasks)
    if not declared:
        print("❌ 未能从 %s 解析出任何声明规则。" % tasks)
        print("   脚本前提（任务名含『预检 firewalld』且 loop 为列表）可能已失效，请检查。")
        return 2

    zones = parse_dump(ssh(host, REMOTE_DUMP))

    present, local_changes, program_zones = set(), set(), []
    for zone, parts in zones.items():
        cur_xml = parts.get("current", "")
        fac_xml = parts.get("factory", "")
        if not fac_xml.strip():
            program_zones.append(zone)
        cur, fac = entries_of(cur_xml), entries_of(fac_xml)
        for ent in cur:
            present.add("%s\t%s" % (zone, ent))
        for ent in (cur - fac):
            local_changes.add("%s\t%s" % (zone, ent))

    drift = sorted(local_changes - declared)
    missing = sorted(declared - present)

    print("IaC 声明 %d 条规则：" % len(declared))
    for item in sorted(declared):
        print("    %-9s %-9s %s" % split3(item))
    print()

    print("本机相对出厂态的全部本地改动 %d 条：" % len(local_changes))
    for item in sorted(local_changes):
        zone, kind, value = split3(item)
        mark = "✅ IaC 已声明" if item in declared else "❌ 无主改动（漂移）"
        print("    %-9s %-9s %-20s %s" % (zone, kind, value, mark))
    print()

    if missing:
        print("缺失（IaC 声明但机器上没有）%d 条：" % len(missing))
        for item in missing:
            print("    %-9s %-9s %s" % split3(item))
    else:
        print("缺失（IaC 声明但机器上没有）：无")
    print()

    if program_zones:
        print("程序自建 zone（/usr/lib 无对应文件，属运行时产物）：%s" % ", ".join(sorted(program_zones)))
        print()

    if drift or missing:
        print("❌ 结论：漂移 %d 条、缺失 %d 条。" % (len(drift), len(missing)))
        if drift:
            print("   无主改动在重建机器时会丢失 —— 补进 IaC（security 角色的 loop）或从服务器移除。")
        if missing:
            print("   缺失说明 playbook 尚未应用，或有人手工删掉了 IaC 管理的条目 —— 跑一遍 site.yml。")
        return 1

    print("✅ 结论：持久配置与 IaC 声明完全一致（无漂移、无缺失）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
