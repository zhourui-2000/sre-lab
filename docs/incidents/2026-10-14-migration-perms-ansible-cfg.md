# 控制端迁移：权限漂移 0777 让 Ansible 静默忽略配置

- **日期**：2026-10-14
- **影响**：控制端「看起来已经修好了」，但 inventory 与 `roles_path` 全部失效 —— **一条命令都没生效，而且没有任何报错**
- **一句话结论**：迁移时文件经 `/mnt/c`（DrvFs）中转进入 WSL，Unix 权限位未被保留、整棵树回落 **0777**；
  而 Ansible 的安全设计**拒绝从全局可写目录加载 `ansible.cfg`** —— 只留一条 WARNING，不中断执行

## 背景

控制端在 2026-09 进水事故后重建（见 [2026-09-26](2026-09-26-control-node-rebuild.md)）。
2026-10-13 把项目打包成归档并在新机上复原；2026-10-14 逐项核对时发现**控制端跑不动 playbook**。

## 现象

`ansible lab -m ping` 既没成功、也没失败，只吐出四条 WARNING：

```text
[WARNING]: Ansible is being run in a world writable directory (/root/sre-lab/ansible),
           ignoring it as an ansible.cfg source. For more information see
           https://docs.ansible.com/ansible/devel/reference_appendices/config.html#cfg-in-world-writable-dir
[WARNING]: No inventory was parsed, only implicit localhost is available
[WARNING]: provided hosts list is empty, only localhost is available. Note that
           the implicit localhost does not match 'all'
[WARNING]: Could not match supplied host pattern, ignoring: lab
```

**关键：exit code 是 0。** 没有报错、没有非零退出码 —— 只有"忽略 / 跳过 / 降级"。

## 诊断

```sh
# ① 确认配置到底有没有被读取
ansible --version | head -3
#   config file = None            ← 期望 /root/sre-lab/ansible/ansible.cfg

# ② 复核目录权限
ls -ld /root/sre-lab /root/sre-lab/ansible
#   drwxrwxrwx ... /root/sre-lab          ← 0777

# ③ 量化受影响范围
find /root/sre-lab -perm -o+w -type d | wc -l   # 135
find /root/sre-lab -perm -o+w -type f | wc -l   # 150
```

## 根因

两层叠加：

1. **迁移路径不保留权限语义。**
   归档在 Windows 侧解包后、经 `/mnt/c`（DrvFs，底层 NTFS）拷进 WSL。
   这一路**没有 `tar -p` 那样的权限保留**，NTFS 也没有 Unix 权限位 → 所有条目按挂载默认值落盘。
   **证据**：整棵树**无差别** 0777 —— 连 `.git/objects/` 内部对象目录都是 ——
   这是"按挂载默认值落盘"的特征，而不是某个工具的选择性行为。
2. **Ansible 把"目录可被他人写"当作安全红线。**
   从全局可写目录加载 `ansible.cfg`，等于把 `roles_path`、`inventory` 交给任何能写该目录的人
   （例如往 `roles_path` 里塞一个同名角色）。所以 Ansible 宁可**不读配置**，也不冒这个险 ——
   **这是正确的安全设计**。

两者相遇 → **配置文本在、但从未被加载**。

## 为什么最危险的是"没有报错"

- `ansible-playbook site.yml --syntax-check` **照样通过**（它不依赖 inventory）；
- `ansible-playbook site.yml` 会以 `skipping: no hosts matched` **优雅结束**；
- 复盘时扫一眼输出，极易读成"跑完了，没事"。

**这是一个"安静的成功"**：命令返回 0、日志里有内容、但什么都没做。
它比直接报错危险得多 —— 报错会打断你，安静的成功只会让你以为已经完成。

## 修复

```sh
# 只去掉 group/other 的写位，保留属主权限
chmod -R go-w /root/sre-lab

# 判据：应为 0
find /root/sre-lab -perm -o+w | wc -l
```

修复后 `ansible --version` 的 `config file` 正确指向 `/root/sre-lab/ansible/ansible.cfg`。

顺带修掉同一批迁移遗留（都不在仓库内）：

```sh
chmod 644 /root/.gitconfig            # 曾是 0777
chmod 600 /root/.ssh/known_hosts.old  # 曾是 0777
```

## 验证

| 检查 | 修复前 | 修复后 |
|---|---|---|
| `ansible --version` → `config file` | `None` | `/root/sre-lab/ansible/ansible.cfg` |
| `ansible lab -m ping` | `Could not match supplied host pattern, ignoring: lab` | `lab-node \| SUCCESS => { "ping": "pong" }` |
| 目标解释器 | — | `ansible_python_version: 3.11.13` |
| `site.yml --syntax-check` | 通过（**假的安全感**） | 通过 |
| 仓库内 `-perm -o+w` 计数 | 135 目录 / 150 文件 | **0** |

## 教训

- 见 [methodology ⑭](../methodology.md)：迁移 / 拷贝不保留权限语义，而工具可能把权限当安全前提、**静默降级**
- 复核 [methodology ⑩](../methodology.md)：验证手段必须先于被验证对象可用 ——
  这次坏掉的恰恰是**验证工具链本身**（Ansible 读不到配置），而 `--syntax-check` 通过反而提供了假的安全感
- **"没有报错"不是验收判据。** exit code 0、日志非空，都不等于动作真的发生了。
  判据必须是**生效值**：`config file` 的指向、`ping` 的 pong、实跑的 `changed=N`
- **归档 / 迁移类交付，权限必须显式重建**，不能假设拷贝工具会保留

## 遗留

- `ansible-core` 版本随控制端重建而漂移（原 `2.20.1` / Python 3.14 → 现 `2.17.14` / Python 3.10.6），
  已在 README 环境段记录，但仍**未纳入 IaC 或引导脚本强制** ——
  见 [methodology ⑧](../methodology.md)：路径与流程无约束 = 隐性真源泄漏
