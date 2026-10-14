# 服务器配置未生效：git pull 静默失败

- **日期**：2026-09-24
- **影响**：服务器跑的还是旧配置 / 旧镜像，表现为「我明明改了却没生效」
- **一句话结论**：服务器上有本地改动 → git 拒绝 pull，而报错混在长输出里被当成噪音划过

## 现象

- 本机已推送「锁定 nginx 镜像版本」等提交
- 服务器执行 `docker compose up -d --force-recreate web` 后，`docker ps` 仍显示旧镜像 `nginx:alpine`

## 第一层误判

以为 compose 没改或重建命令无效 —— 实际是**服务器上的仓库根本没更新**。

## 诊断路径

- `git log --oneline -1` → 服务器 HEAD 仍停在 8 个提交之前（`265f687`）
- `git status --short` → 存在两处本地改动（`nginx/conf.d/default.conf`、`nginx/html/index.html`）
- 结论：被改动的文件在远端本次提交中也要变更 → **git 拒绝 pull**

## 叠加因素

`daemon.json` 的原镜像加速器已失效，docker 回退直连 `registry-1.docker.io` 后超时
→ 即使 compose 更新，目标镜像也拉不下来。

## 修复

1. 备份 → `git stash push <两个文件>` → `git pull`（通过）
2. 复核 stash：`default.conf` 的改动与仓库既有提交同内容（重复修改，可丢弃）
3. 镜像改走前缀：`docker pull docker.m.daocloud.io/library/nginx:1.24-alpine` → `docker tag` 回原名
4. 清理 `.bak` 残留与旧镜像

## 根因

**「服务器只 pull、不改文件」的约定被破坏。** 一旦服务器上有本地改动，pull 就失败，
而这条报错混在长输出里极易被当成噪音划过，最终表现为「我明明改了配置却没生效」。

## 教训

- 服务器上出现 `M` 状态文件即是**红灯**，必须先处理再谈部署
- 「改了配置」与「配置生效」之间必须有一次校验：`git log -1` + `docker inspect` 实际镜像
- 手工 pull 流程没有失败中断机制 → **这是第 4 周引入 GitOps 的直接动机**
