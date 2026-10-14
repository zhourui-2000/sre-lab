# ADR 0001：以自有服务器中转 Git 推送

- **状态**：已采纳
- **日期**：2026-09-24

## 背景（Context）

公司网络到 GitHub 的链路**间歇性不可用**：`git push` 挂起且无输出，SSH 连通性采样 3/3 失败。
但同一网络下另有两条稳定链路：

| 路径 | 状态 |
|---|---|
| 本机 → 阿里云服务器（SSH 2222） | ✅ 稳定 |
| 阿里云服务器 → GitHub | ✅ 稳定（`git ls-remote` / `git push` 均正常） |

附带问题：Docker Hub（docker.io）直连超时，需走镜像前缀（见 [baseline 环境前提](../baseline.md)）。

## 决策（Decision）

用自有服务器做中转，把"本机 → GitHub"拆成两段稳定链路：

```text
本机(WSL) --push--> 阿里云裸仓库 relay --post-receive--> /opt/sre-lab 工作副本 --push--> GitHub
    稳定链路段 ①                        服务器内部                    稳定链路段 ②
```

一次性落地：

```bash
# 服务器：建裸仓库作为中转站
git init --bare ~/sre-lab-relay.git

# 本机：登记 remote
git remote add relay lab-node:~/sre-lab-relay.git
```

日常（一条命令）：

```bash
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

日志：`/var/log/sre-relay.log`

## 后果（Consequences）

**收益**：推送从"看运气"变为稳定；服务器成为同步中枢，与第 4 周 GitOps（服务器主动同步）同构。

**代价与必须注意的点**：

1. **钩子内必须先 `unset GIT_DIR`** —— 钩子运行时 `GIT_DIR` 指向裸仓库，
   清理前操作别的仓库会让 git 继续作用于裸仓库。
2. **不要用 `git fetch <url> main:main` 更新"已被检出的分支"** —— git 会拒绝
   （`fatal: refusing to fetch into branch 'refs/heads/main' checked out at ...`）。
   正确写法是 `git pull --ff-only <url> main`（先抓到 `FETCH_HEAD` 再合并），或抓到临时分支再 merge。
3. **钩子是 `post-receive`，失败不会拒绝推送** —— relay 已收到提交，但 GitHub / 工作副本可能没同步。
   推完必须校验：`tail -3 /var/log/sre-relay.log` + `git log --oneline -1`。
4. **工作副本有本地改动时 `merge --ff-only` 会失败** —— 这是有意的安全设计，
   把"服务器不该改文件"的违规暴露出来，而不是静默覆盖。

## 未采纳的替代方案

| 方案 | 未采用的原因 |
|---|---|
| 直连 + 自动重试 | 链路整段不可用时重试无效，只是把失败延后 |
| 仅在手机热点下推送 | 可行，但需要随时开热点，不便于日常迭代 |
| 引入 VPN / 第三方代理 | 增加不可控外部依赖，在受限网络中未必可用 |
| 改用 HTTPS + Token 替代 SSH | 没有解决链路本身的不稳定，只换了协议 |
