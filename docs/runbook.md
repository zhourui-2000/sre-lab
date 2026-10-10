# Runbook（症状速查）

> 面向"出事时快速出手"：**症状 → 一条命令定位 → 修复**。原理与故事见 [`incidents/`](incidents/)。

## 部署类

| 症状 | 一条命令定位 | 修复 |
|---|---|---|
| 改了配置但没生效 | `git -C /opt/sre-lab log --oneline -1` 与本机对比 | 服务器 `git status`；有 `M` 先处理，再 `git pull` |
| **改了挂载的配置文件，容器却没变** | `docker exec <c> cat <容器内配置路径>` 与宿主机对比 | `docker compose up -d --force-recreate <c>`（见下节） |
| 容器是旧版本 | `docker inspect <c> --format '{{.Config.Image}}'` | `docker compose up -d --force-recreate <c>` |
| 容器 crash loop，日志 `permission denied` | `docker inspect <c> --format '{{.Config.User}}'` + `ls -la <配置文件>` | 按**消费方身份**调权限；或见下节「密钥文件」 |
| `docker compose up` 直接退出无提示 | `docker compose config` | 按报错修 YAML（注意 `test` 数组里的数字要加引号） |
| Ansible 报模块错误 / ping 失败 | `ansible lab -m ping -vvv`，看 `module_stderr` | 确认 inventory 用 `/usr/bin/python3.11` |
| 推送后服务器没变 | `tail -3 /var/log/sre-relay.log` + `git log --oneline -1` | 钩子失败不回滚，需手工重推 |
| `git push` 挂起无输出 | `ssh -T git@github.com` | 切手机热点，或 `git push relay main` |

## 观测类

| 症状 | 一条命令定位 | 修复 |
|---|---|---|
| Grafana 无数据 / `up=0` | `curl -s 127.0.0.1:8428/api/v1/targets` | 查 firewalld 是否拦 trusted 网段；确认容器同一网络 |
| 告警规则不触发 | `curl -s 127.0.0.1:8880/api/v1/rules` 看 `health` | 查规则文件是否挂载、表达式是否成立 |
| **改了告警规则但没触发** | `curl -s 127.0.0.1:8880/api/v1/rules` → 比对 `query`/`duration` 与文件内容 | `docker compose up -d --force-recreate vmalert` |
| 规则 firing 但 VM 查不到 `ALERTS` | `docker inspect vmalert --format '{{.Config.Cmd}}'` | 补 `--remoteWrite.url` |
| 规则 firing 但 alertmanager 收不到 | `docker logs vmalert --tail 40 \| grep -i notifier` | 确认 alertmanager 服务存在、`--notifier.url` 可达 |
| 收到告警但没人被通知 | 三点同验 + 查收件箱，见 [`methodology ⑦`](methodology.md) | 查 `docker logs alertmanager \| grep -i smtp` |
| 容器恒 unhealthy | `docker inspect <c> --format '{{json .State.Health}}'` | healthcheck 别用 `localhost`，改 `127.0.0.1` |
| 镜像拉不下来 | `docker pull <img>` 看卡在哪一步 | 加前缀 `docker.m.daocloud.io/...` 再 `docker tag` |

## 改了被挂载的配置文件（★ 最容易踩）

> **改配置 ≠ 容器生效。** `docker compose up -d` 只比较**服务定义**，不比较挂载文件内容；
> 而且 `cp` / 编辑器 / `git pull` 覆盖文件都是 **rename 替换** → **换 inode**，旧容器仍指向旧 inode —— 连 `restart` 都不管用。
> **一律 `--force-recreate`。**

> **热重载不是兜底。** 程序自带的文件监视（vmalert / nginx 等）靠 **inotify**，而 inotify 盯的是 **inode**；
> 文件被 rename 替换后监视对象就消失了，**不会自动重载**（2026-10-10 实测踩到）。
> 只有 `--force-recreate` 可靠。

```sh
cd /opt/sre-lab/observability
docker compose config >/dev/null && echo "配置合法" || echo "语法错，别重建"
docker compose up -d --force-recreate <svc>
docker inspect <svc> --format '{{.Config.Cmd}}'   # ① 确认启动参数
docker exec <svc> cat <容器内配置路径> | head      # ② 确认容器读到的是新内容 ← 真正的判据
```

### alertmanager 配置（密钥文件，不在仓库里）

真实配置在 **`/root/.sre-lab-secrets/alertmanager.yml`**；目录 `700`、文件 **`644`**。

```sh
vim /root/.sre-lab-secrets/alertmanager.yml
docker exec alertmanager cat /etc/alertmanager/alertmanager.yml >/dev/null && echo "容器可读 ✅"
cd /opt/sre-lab/observability && docker compose up -d --force-recreate alertmanager
docker logs alertmanager --tail 10 | grep -iE "permission|error|Listening"
```

> ⚠️ **判据必须在容器视角下取**（`docker exec`）。在宿主用 `sudo -u nobody cat /root/.sre-lab-secrets/...`
> 会被 `/root` 的 750 挡住，输出 `Permission denied` —— 那是**假阴性**，不代表容器读不到。
>
> ⚠️ **文件权限保持 `644`，不要改成 600**：容器以 `nobody` 运行，600 会让它读不到而 crash loop。
> 保护来自目录权限，不来自文件权限（见 [ADR 0002](../adr/0002-secret-file-permissions.md)）。

## 推送后必做（relay 链）

```sh
tail -3 /var/log/sre-relay.log              # 钩子是否执行成功
cd /opt/sre-lab && git log --oneline -1     # 工作副本是否已同步
```

> `post-receive` 钩子**失败不会拒绝推送**——relay 已收到提交，但 GitHub / 工作副本可能没同步。
> 所以推完必须校验这两条，不能只看"推送成功"。
