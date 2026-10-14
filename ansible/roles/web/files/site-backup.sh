#!/bin/bash
set -euo pipefail
D=/var/backups/site
T=$(date +%F)
# 目的：只备份「不可再生」的静态站点目录，不碰可从 Git 重建的配置
tar czf "$D/site-$T.tar.gz" -C /opt/sre-lab/nginx/html dtb story 2>/dev/null || true
# 目的：保留 7 天，防止 40G 盘被自己的备份撑爆
find "$D" -name 'site-*.tar.gz' -mtime +7 -delete
echo "[$(date '+%F %T')] site backup done: $D/site-$T.tar.gz"
