# ADR 0002：密钥文件的权限策略（目录保护 + 644）

- **状态**：已采纳
- **日期**：2026-10-09

## 背景（Context）

`alertmanager.yml` 含 QQ 邮箱 SMTP 授权码，需防读又需容器可读。alertmanager 以 `nobody`（uid 65534）运行（`docker inspect --format '{{.Config.User}}'` 实测）。

`chmod 600` + `chown nobody` 实测 crash loop：

```text
ERROR msg="alertmanager exited with error"
  err="error loading configuration file: open /etc/alertmanager/alertmanager.yml: permission denied"
```

`nano` / `sed` 重建文件、属主回 `root:root`，每次都得重新 `chown`，忘了就崩（当天崩过）。

## 决策（Decision）

保护与可读解耦：`/root` 750、`/root/.sre-lab-secrets` 700 挡穿越；文件 644，与属主无关。

落点 `/root/.sre-lab-secrets/alertmanager.yml`；挂载 `/root/.sre-lab-secrets/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro`；bind mount 由 dockerd 解析，容器内不穿越 `/root`。

## 600 为何更差

| 威胁 | 结果 |
|---|---|
| 宿主非 root 用户 | 挡：`/root` 750，`sudo -u nobody ls` 被拒 |
| 其他容器 | 挡：mount namespace 不同 |
| alertmanager 被攻破 | 不挡：消费方必须能读 |
| 宿主 root / docker 组 | 不挡：`docker.sock` 为 `srw-rw---- root docker`，等效 root |
| 同容器第二执行身份 | 部分：唯一被 644 放宽处，当前仅 PID 1 |

## 未采纳的替代方案

| 方案 | 原因 |
|---|---|
| `chown nobody` + `600` | 属主回 root 读不到（实测） |
| `user: "root"` + `600 root:root` | 权限更严，但提权到 root |
| Compose `secrets:`（非 Swarm） | `/run/secrets` 0444，同样可读 |
| Vault 等外部管理 | 单机过重 |
| 环境变量 / 命令行参数 | 进 `docker inspect`，更暴露 |

## 后果（Consequences）

- 编辑后不用再 chown。

- 密钥不进 Git（`.gitignore`），宿主不可达。

- ⚠️ 边界是 `/root` 目录权限，放宽即失效。

- ⚠️ 出现第二执行身份需重评（回到 `user: root` 或拆容器）。

- 📌 不得 `chmod 600`，已写进 README 与 runbook。

## 验证方式

```sh
docker exec alertmanager cat /etc/alertmanager/alertmanager.yml >/dev/null && echo "容器可读"
chown root:root /root/.sre-lab-secrets/alertmanager.yml
docker exec alertmanager cat /etc/alertmanager/alertmanager.yml >/dev/null && echo "漂移后仍可读"
sudo -u nobody ls /root/.sre-lab-secrets/        # 期望 Permission denied
```

## 相关

- [`../methodology.md`](../methodology.md) ⑫「收紧权限前，先确认谁要读它」
- [`../incidents/2026-10-09-alert-chain-silent.md`](../incidents/2026-10-09-alert-chain-silent.md)
