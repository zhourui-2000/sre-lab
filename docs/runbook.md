# Runbook（症状速查）

> 面向"出事时快速出手"：**症状 → 一条命令定位 → 修复**。原理与故事见 [`incidents/`](incidents/)。

## 部署类

| 症状 | 一条命令定位 | 修复 |
|---|---|---|
| 改了配置但没生效 | `git -C /opt/sre-lab log --oneline -1` 与本机对比 | 服务器 `git status`；有 `M` 先处理，再 `git pull` |
| 容器是旧版本 | `docker inspect <c> --format '{{.Config.Image}}'` | `docker compose up -d --force-recreate <c>` |
| `docker compose up` 直接退出无提示 | `docker compose config` | 按报错修 YAML（注意 `test` 数组里的数字要加引号） |
| Ansible 报模块错误 / ping 失败 | `ansible lab -m ping -vvv`，看 `module_stderr` | 确认 inventory 用 `/usr/bin/python3.11` |
| 推送后服务器没变 | `tail -3 /var/log/sre-relay.log` + `git log --oneline -1` | 钩子失败不回滚，需手工重推 |
| `git push` 挂起无输出 | `ssh -T git@github.com` | 切手机热点，或 `git push relay main` |

## 观测类

| 症状 | 一条命令定位 | 修复 |
|---|---|---|
| Grafana 无数据 / `up=0` | `curl -s 127.0.0.1:8428/api/v1/targets` | 查 firewalld 是否拦 trusted 网段；确认容器同一网络 |
| 告警规则不触发 | `curl -s 127.0.0.1:8880/api/v1/rules` 看 `health` | 查规则文件是否挂载、表达式是否成立 |
| 规则 firing 但 VM 查不到 `ALERTS` | `docker inspect vmalert --format '{{.Config.Cmd}}'` | 补 `--remoteWrite.url` |
| 告警触发了但没人收到 | 三点同验，见 [`methodology ⑦`](methodology.md) | 补 alertmanager 服务 / 查 notifier 日志 |
| 容器恒 unhealthy | `docker inspect <c> --format '{{json .State.Health}}'` | healthcheck 别用 `localhost`，改 `127.0.0.1` |
| 镜像拉不下来 | `docker pull <img>` 看卡在哪一步 | 加前缀 `docker.m.daocloud.io/...` 再 `docker tag` |

## 推送后必做（relay 链）

```sh
tail -3 /var/log/sre-relay.log              # 钩子是否执行成功
cd /opt/sre-lab && git log --oneline -1     # 工作副本是否已同步
```

> `post-receive` 钩子**失败不会拒绝推送**——relay 已收到提交，但 GitHub / 工作副本可能没同步。
> 所以推完必须校验这两条，不能只看"推送成功"。

## 改完 compose 的固定动作

```sh
cd /opt/sre-lab/observability
docker compose config >/dev/null && echo "配置合法" || echo "语法错，别重建"
docker compose up -d <svc>
docker inspect <svc> --format '{{.Config.Cmd}}'    # 确认新参数真的进了容器
```
