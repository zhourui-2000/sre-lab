#!/usr/bin/env bash
# sre-lab · 校验一次备份（Week 7-B · 2026-10-21）
#
# 默认只把归档解密到 /tmp 验证，**不碰任何生产文件**。
#
# 用法：
#   read -rsp '备份口令: ' SRE_BACKUP_PASS; echo; export SRE_BACKUP_PASS
#   bash scripts/restore-state.sh /root/backup/<TS>.tar.gz.enc
#
# 为什么不提供 --apply：
#   ① 覆盖面最大的操作应该最难误触发；
#   ② 「让一个干净的 k3s 用这份 db 真正起来」在 2 G 机上没法安全演练（要停生产），
#      所以它是 dr.md 第 7.5 节里明确标注的 **未证事项（L4）**，不该由脚本替你拍板。
set -euo pipefail

ARC=${1:?用法: restore-state.sh <归档.tar.gz.enc>}
[ -n "${SRE_BACKUP_PASS:-}" ] || { echo "❌ 请先 export SRE_BACKUP_PASS"; exit 2; }
[ -f "$ARC" ] || { echo "❌ 找不到 $ARC"; exit 2; }

WORK=$(mktemp -d /tmp/sre-restore.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
TREE="$WORK/tree"

say(){ printf '%s\n' "$*"; }
hdr(){ printf '\n== %s ==\n' "$*"; }

hdr "1/5 校验和"
if [ -f "$ARC.sha256" ]; then
  want=$(awk '{print $1}' "$ARC.sha256")
  got=$(sha256sum "$ARC" | awk '{print $1}')
  if [ "$want" = "$got" ]; then
    say "  ✅ 一致（${got:0:16}…）"
  else
    echo "  ❌ 校验和不符：want=$want got=$got"
    exit 3
  fi
else
  say "  ⚠️  没有 .sha256 —— 无法证明文件没被改过"
fi

hdr "2/5 解密 + 解包"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 \
  -pass env:SRE_BACKUP_PASS -in "$ARC" -out "$WORK/bundle.tar.gz"
mkdir -p "$TREE"
tar -xzf "$WORK/bundle.tar.gz" -C "$TREE"
say "  $(find "$TREE" -type f | wc -l) 个文件 · $(du -sh "$TREE" | cut -f1)"

hdr "3/5 state.db"
DB="$TREE/var/lib/rancher/k3s/server/db/state.db"
[ -f "$DB" ] || { echo "  ❌ 归档里没有 state.db"; exit 3; }
IC=$(sqlite3 "$DB" 'PRAGMA integrity_check')
ROWS=$(sqlite3 "$DB" 'select count(*) from kine')
say "  integrity=${IC} · ${ROWS} 行"
[ "$IC" = "ok" ] || { echo "  ❌ integrity 失败"; exit 3; }
[ "$ROWS" -gt 0 ] || { echo "  ❌ 0 行 —— 快照是空的"; exit 3; }
NS=$(sqlite3 "$DB" "select count(*) from kine where name like '%/registry/namespaces/%'")
APP=$(sqlite3 "$DB" "select count(*) from kine where name = '/registry/argoproj.io/applications/argocd/hello'")
say "  namespace ${NS} 个 · Application hello ${APP} 条"

hdr "4/5 证书"
TLS="$TREE/var/lib/rancher/k3s/server/tls"
if [ -f "$TLS/server-ca.crt" ] && [ -f "$TLS/serving-kube-apiserver.crt" ]; then
  r=$(openssl verify -CAfile "$TLS/server-ca.crt" "$TLS/serving-kube-apiserver.crt" 2>&1 || true)
  say "  k3s 集群链: ${r##*: }"
else
  say "  ⚠️  tls 目录不全，跳过集群链验证"
fi
L="$TREE/etc/letsencrypt/live/zhourui2000.online"
if [ -f "$L/cert.pem" ] && [ -f "$L/privkey.pem" ]; then
  a=$(openssl x509 -in "$L/cert.pem" -noout -pubkey 2>/dev/null | openssl md5 | awk '{print $NF}')
  b=$(openssl pkey -in "$L/privkey.pem" -pubout 2>/dev/null | openssl md5 | awk '{print $NF}')
  if [ -n "$a" ] && [ "$a" = "$b" ]; then
    say "  letsencrypt 公私钥配对 ✅（$(openssl x509 -in "$L/cert.pem" -noout -enddate)）"
  else
    say "  ❌ letsencrypt 公私钥不配对（cert=$a key=$b）"
    exit 3
  fi
else
  say "  ⚠️  letsencrypt 目录不全，跳过配对验证"
fi

hdr "5/5 结论"
say "  ✅ 可解密、可解包、数据完整、密钥配对"
say "  ⚠️ 未证（L4）：它能否让一个干净的 k3s 真正起来 —— 要停生产，未演练，见 dr.md 7.5"
say "  生产文件一个都没动。"
