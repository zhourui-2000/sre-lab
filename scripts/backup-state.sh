#!/usr/bin/env bash
# sre-lab · B 层状态备份（Week 7-B · 2026-10-22 加固版）
#
# 只备「不可再生」的东西，并在服务器上就加密 —— 离开这台机的那一刻已是密文。
#
# 不备（可再生产，2026-10-21 实测）：
#   /var/lib/rancher/k3s/agent   1.5 G   containerd 镜像层 → 重新 pull 即得
#   /var/lib/rancher/k3s/data    271 M   k3s 解包的二进制 → 重装即得
# 不备（数据层：压不动且可弃）：
#   observability/vmdata 63 M（gzip 比率 0.98）、loki-data 11 M、grafana-data 15 M
#
# 用法：
#   read -rsp '备份口令: ' SRE_BACKUP_PASS; echo      ← ★ 单独一行，不要整块粘贴
#   export SRE_BACKUP_PASS
#   bash scripts/backup-state.sh /root/backup
#
# ⚠️ 口令不落盘、也不写进这个脚本。丢了 = 备份作废（没有第二把钥匙）。
#
# 2026-10-22 加的三道护栏（起因见 docs/dr.md 7.7）：
#   ① 前置：口令长度 <6 或 >64 直接拒绝（>64 几乎一定是整块粘贴吃了后续命令）
#   ② 加密后**立刻自解一次**，解不开就删掉产物 —— 绝不留下打不开的归档
#   ③ meta 里写 pass_len（字节数），恢复时可对比，不必等 bad decrypt 才知道
set -euo pipefail

OUT=${1:?用法: backup-state.sh <输出目录>}
[ -n "${SRE_BACKUP_PASS:-}" ] || { echo "❌ 请先 export SRE_BACKUP_PASS"; exit 2; }

K3S=/var/lib/rancher/k3s/server
TS=$(date +%Y%m%d-%H%M%S)
WORK=$(mktemp -d /tmp/sre-backup.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
TREE="$WORK/tree"

say(){ printf '%s\n' "$*"; }
hdr(){ printf '\n== %s ==\n' "$*"; }

hdr "前置"
for c in sqlite3 openssl tar sha256sum; do
  command -v "$c" >/dev/null || { echo "❌ 缺命令：$c"; exit 2; }
done
[ -f "$K3S/db/state.db" ] || { echo "❌ 找不到 $K3S/db/state.db"; exit 2; }

PLEN=$(printf %s "$SRE_BACKUP_PASS" | wc -c)
if [ "$PLEN" -lt 6 ]; then
  echo "❌ 口令只有 ${PLEN} 字节，太短"; exit 2
fi
if [ "$PLEN" -gt 64 ]; then
  echo "❌ 口令有 ${PLEN} 字节，异常长"
  echo "   多半是整块粘贴时，read 把后面的命令也吃进了口令（2026-10-22 真实事故）"
  echo "   → 请只粘贴/输入「read」那一行，然后手工敲口令"
  exit 2
fi
say "  口令 ${PLEN} 字节"
mkdir -p "$OUT"
say "  输出 $OUT"

hdr "1/5 一致快照（sqlite .backup，不是 cp）"
mkdir -p "$TREE$K3S/db"
S=$(date +%s%N)
sqlite3 "$K3S/db/state.db" ".backup $TREE$K3S/db/state.db"
E=$(date +%s%N)
MS=$(( (E-S)/1000000 ))
DB="$TREE$K3S/db/state.db"
ROWS=$(sqlite3 "$DB" 'select count(*) from kine')
IC=$(sqlite3 "$DB" 'PRAGMA integrity_check')
say "  ${MS} ms · ${ROWS} 行 · integrity=${IC}"
[ "$IC" = "ok" ] || { echo "❌ 快照完整性检查失败"; exit 3; }

hdr "2/5 收集其余单元"
for p in "$K3S/tls" "$K3S/token" "$K3S/cred" "$K3S/etc" \
         /etc/letsencrypt /root/.sre-lab-secrets/alertmanager.yml; do
  if [ -e "$p" ]; then
    mkdir -p "$TREE$(dirname "$p")"
    cp -a "$p" "$TREE$p"
    say "  ✅ $p"
  else
    say "  ⚠️  缺 $p（跳过）"
  fi
done

hdr "3/5 打包 + 加密"
tar -czf "$WORK/bundle.tar.gz" -C "$TREE" .
PLAIN=$(stat -c%s "$WORK/bundle.tar.gz")
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt \
  -pass env:SRE_BACKUP_PASS \
  -in "$WORK/bundle.tar.gz" -out "$OUT/$TS.tar.gz.enc"
ENC=$(stat -c%s "$OUT/$TS.tar.gz.enc")
say "  明文 ${PLAIN} B → 密文 ${ENC} B（aes-256-cbc / pbkdf2 20 万轮 / sha256）"

hdr "4/5 自解验证（★ 这一份就是防「口令打错却不知道」）"
if openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 \
     -pass env:SRE_BACKUP_PASS -in "$OUT/$TS.tar.gz.enc" -out "$WORK/verify.tar.gz" 2>/dev/null \
   && cmp -s "$WORK/bundle.tar.gz" "$WORK/verify.tar.gz"; then
  say "  ✅ 用当前口令能原样解开，且与明文逐字节相同"
else
  echo "  ❌ 自解验证失败 —— 当前口令解不开刚生成的文件"
  rm -f "$OUT/$TS.tar.gz.enc"
  echo "  已删除产物，不留一份打不开的归档。"
  exit 4
fi

hdr "5/5 校验 + 元信息"
( cd "$OUT" && sha256sum "$TS.tar.gz.enc" > "$TS.tar.gz.enc.sha256" )
say "  $(cut -c1-70 "$OUT/$TS.tar.gz.enc.sha256")"
{
  echo "created: $(date -Is)"
  echo "host: $(hostname)"
  echo "kine_rows: $ROWS"
  echo "snapshot_ms: $MS"
  echo "plain_bytes: $PLAIN"
  echo "enc_bytes: $ENC"
  echo "pass_len: $PLEN"
  echo "cipher: aes-256-cbc pbkdf2-200000 sha256"
} > "$OUT/$TS.meta"

hdr "完成"
say "  $OUT/$TS.tar.gz.enc"
say "  ★ 口令没有落盘 —— 忘了就再也解不开。"
say "  ★ 已自解验证：这个口令确实能解开这份文件。"
say "  下一步：异地留存（scp 到控制端），见 dr.md 第 7 节"
