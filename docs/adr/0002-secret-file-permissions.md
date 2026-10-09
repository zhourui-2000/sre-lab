# ADR 0002：密钥文件的权限策略（目录保护 + 644）

- **状态**：已采纳
- **日期**：2026-10-09

## 背景（Context）

`alertmanager.yml` 含 QQ 邮箱 SMTP 授权码，需要满足两个**互相拉扯**的目标：

1. **不能被读到** —— 它是一份凭据；
2. **必须被容器读到** —— alertmanager 进程以 **`nobody`（uid 65534）** 运行
   （`docker inspect --format '{{.Config.User}}'` 实测为 `nobody`），启动时要加载这份配置。

最初的直觉做法是 `chmod 600` + `chown nobody`。**实测结果是容器 crash loop**：

```text
ERROR msg="alertmanager exited with error"
  err="error loading configuration file: open /etc/alertmanager/alertmanager.yml: permission denied"
```

因为 `nano` / `sed` 等编辑会重建文件、把属主改回 `root:root`，
于是每次改配置都要记得重新 `chown` —— **这个"记得"就是故障源**（当天已经因此崩了一次）。

## 决策（Decision）

**把「保护」和「可读」两个目标解耦，各自用最合适的机制承担：**

| 目标 | 机制 | 说明 |
|---|---|---|
| 不能被读到 | **目录不可穿越** | `/root` 本身 750；密钥目录 `/root/.sre-lab-secrets` 设 700 |
| 必须能被容器读到 | **文件 644** | 与属主无关，root / nobody 都能读 |

落点：`/root/.sre-lab-secrets/alertmanager.yml`（目录 700，文件 644）。
compose 挂载：`/root/.sre-lab-secrets/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro`

> 容器读该文件**不需要穿越宿主的 `/root`**：bind mount 由 dockerd（root）在挂载时解析，
> 挂进容器后就是容器自身命名空间里的一个普通文件。

## 为什么"更严的 600"反而更差

威胁模型逐条对照（均实测）：

| 威胁 | 644 是否挡得住 | 说明 |
|---|---|---|
| 宿主机其他非 root 用户 | ✅ | 靠 `/root` 750，**不看文件权限**（实测 `sudo -u nobody ls` → Permission denied） |
| 其他容器的进程 | ✅ | 不同 mount namespace，根本没挂这个文件 |
| alertmanager 进程本身被攻破 | ❌ | **任何权限都挡不住** —— 消费方必须能读 |
| 宿主 root / docker 组 | ❌ | `docker.sock` 是 `srw-rw---- root docker`，这两个身份等效 root，能读任意文件 |
| 同一容器内未来出现第二个执行身份 | ⚠️ | 唯一真正被 644 放宽的路径；**当前不存在**（实测容器内只有 PID 1 一个进程） |

结论：600 挡不住它真正需要挡的（宿主 root / docker 组本来就能读），
它唯一多挡的那条路径当前不存在；而它的代价是**每次编辑都要 chown，漏了就崩**。

## 未采纳的替代方案

| 方案 | 未采纳原因 |
|---|---|
| `chown nobody` + `600` | 抗漂移失败：编辑后属主重置为 root → 容器读不到 → crash loop（已实测） |
| `user: "root"` + `600 root:root` | 文件权限确实更严且抗漂移，但把**进程从 nobody 提权到 root** —— 拿大的换小的 |
| Compose `secrets:`（非 Swarm） | 挂到 `/run/secrets` 且模式 0444，**同样是所有人可读**，没有更好 |
| 外部密钥管理（Vault 等） | 单机学习环境，复杂度远超收益 |
| 密码走环境变量 / 命令行参数 | 会出现在 `docker inspect` 里，比文件更暴露 |

## 后果（Consequences）

- ✅ 编辑配置后**不需要再 chown**；只要权限位保持 644，属主怎么变都无所谓。
- ✅ 密钥不进 Git（`.gitignore`），宿主其他用户不可达。
- ⚠️ **依赖 `/root` 的目录权限作为安全边界** —— 若哪天放宽了 `/root` 或密钥目录权限，保护即失效。
- ⚠️ 若将来该容器内出现**第二个执行身份**（sidecar、调试进程），需要重新评估（回到 `user: root` 或拆容器）。
- 📌 **部署时不得 `chmod 600`** —— 这一条必须写进 README 与 runbook（已写）。

## 验证方式（受控实验，可复现）

```sh
# ① 容器视角可读
docker exec alertmanager cat /etc/alertmanager/alertmanager.yml >/dev/null && echo "✅ 容器可读"

# ② 制造属主漂移，确认免疫
chown root:root /root/.sre-lab-secrets/alertmanager.yml
docker exec alertmanager cat /etc/alertmanager/alertmanager.yml >/dev/null && echo "✅ 漂移后仍可读"

# ③ 非 root 宿主用户不可达（目录层）
sudo -u nobody ls /root/.sre-lab-secrets/        # 期望 Permission denied
```

## 相关

- [`../methodology.md`](../methodology.md) ⑫「收紧权限前，先确认谁要读它」
- [`../incidents/2026-10-09-alert-chain-silent.md`](../incidents/2026-10-09-alert-chain-silent.md)
