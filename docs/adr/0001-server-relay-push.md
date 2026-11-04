# ADR 0001：以自有服务器中转 Git 推送

- **状态**：已采纳
- **日期**：2026-09-24

## 背景（Context）

GitHub 链路间歇不可用：`git push` 挂起，SSH 3/3 失败；本机到阿里云（SSH 2222）、阿里云到 GitHub（`git ls-remote` / `git push`）稳定。

## 决策（Decision）

本机 push 到裸仓库 relay，`post-receive` 拉到 `/opt/sre-lab` 再 push GitHub。

```bash
git init --bare ~/sre-lab-relay.git
git remote add relay lab-node:~/sre-lab-relay.git
git push relay main
```

钩子 `~/sre-lab-relay.git/hooks/post-receive`：

```sh
unset GIT_DIR GIT_WORK_TREE
cd /opt/sre-lab
git fetch /root/sre-lab-relay.git main
git merge --ff-only FETCH_HEAD
git push origin main
```

日志 `/var/log/sre-relay.log`。

## 后果（Consequences）

| 约束 | 原因 |
|---|---|
| 先 `unset GIT_DIR` | 钩子内 `GIT_DIR` 指向裸仓库 |
| 不用 `git fetch <url> main:main` | 已检出分支被拒（`fatal: refusing to fetch into branch 'refs/heads/main' checked out at ...`），改 `git pull --ff-only <url> main`（取 `FETCH_HEAD`） |
| `post-receive` 失败不拒绝推送 | 提交已进 relay，下游可能没同步；校验 `tail -3 /var/log/sre-relay.log` 与 `git log --oneline -1` |
| `merge --ff-only` 失败 | 本地有改动，未覆盖 |

## 备选方案

| 方案 | 原因 |
|---|---|
| 直连 + 自动重试 | 重试无效 |
| 手机热点 | 需开热点 |
| VPN / 代理 | 不可控依赖 |
| HTTPS + Token | 只换协议，链路仍不稳 |

## 复审条件

- 直连恢复稳定（连续 `git push` 成功）。
- 服务器或 `post-receive` 故障时中转即新单点。
- 出现第 4 周 GitOps 之外的第二条推送路径。
