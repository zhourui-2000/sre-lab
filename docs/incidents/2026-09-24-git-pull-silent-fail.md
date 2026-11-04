# 服务器配置未生效：git pull 静默失败

2026-09-24。服务器仍是旧配置 / 镜像。

## 诊断

已推送锁定版本提交；`docker compose up -d --force-recreate web` 后 `docker ps` 仍显示 `nginx:alpine`。

| 命令 | 结果 |
|---|---|
| `git log --oneline -1` | HEAD 落后 8 提交（`265f687`） |
| `git status --short` | 本地改动 `nginx/conf.d/default.conf`、`nginx/html/index.html` |

被改文件远端也变，git 拒绝 pull，报错混在长输出中。根因：服务器只 pull、不改文件的约定被破坏。

## 修复

| # | 动作 |
|---|---|
| 1 | 备份`git stash push <两个文件>`，`git pull`（通过） |
| 2 | 复核 stash：`default.conf` 与既有提交同内容（可丢弃） |
| 3 | `daemon.json` 加速器失效、直连 `registry-1.docker.io` 超时，改走前缀：`docker pull docker.m.daocloud.io/library/nginx:1.24-alpine`，`docker tag` 回原名 |
| 4 | 清理 `.bak`、旧镜像 |

## 判据

`M` 即红灯，先处理后部署。`git log -1` 加 `docker inspect` 看镜像。手工 pull 无中断，促成 GitOps。
