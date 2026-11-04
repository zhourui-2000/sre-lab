# 控制端迁移：权限漂移 0777 让 Ansible 静默忽略配置

2026-10-14。控制端在 2026-09 进水事故后重建（见 [2026-09-26](2026-09-26-control-node-rebuild.md)），10-13 打包复原后发现跑不动。它「看起来已修好」，但 inventory 与 `roles_path` 全部失效，一条命令都没生效，也没有任何报错。

## 现象

`ansible lab -m ping` 既没成功也没失败，只吐四条 WARNING：

```text
[WARNING]: Ansible is being run in a world writable directory (/root/sre-lab/ansible),
           ignoring it as an ansible.cfg source.
[WARNING]: No inventory was parsed, only implicit localhost is available
[WARNING]: provided hosts list is empty, only localhost is available.
[WARNING]: Could not match supplied host pattern, ignoring: lab
```

exit code 是 0。

## 诊断

```sh
ansible --version | head -3      # config file = None，期望 /root/sre-lab/ansible/ansible.cfg
ls -ld /root/sre-lab             # drwxrwxrwx，即 0777
find /root/sre-lab -perm -o+w -type d | wc -l   # 135
find /root/sre-lab -perm -o+w -type f | wc -l   # 150
```

## 根因

1）迁移路径不保留权限：归档在 Windows 侧解包，经 `/mnt/c`（DrvFs，底层 NTFS）拷进 WSL，没有 `tar -p`，整棵树无差别 0777（连 `.git/objects/` 都是）。

2）Ansible 把「目录可被他人写」当安全红线：从全局可写目录加载 `ansible.cfg` 等于把 `roles_path`、`inventory` 交给任何能写该目录的人，所以宁可不读，这是正确设计。

两者相遇：配置文本在，但从未加载。最危险的是没有报错：`ansible-playbook site.yml --syntax-check` 照样通过（不依赖 inventory），`ansible-playbook site.yml` 以 `skipping: no hosts matched` 结束。

## 修复

```sh
chmod -R go-w /root/sre-lab
find /root/sre-lab -perm -o+w | wc -l   # 应为 0
chmod 644 /root/.gitconfig              # 曾是 0777
chmod 600 /root/.ssh/known_hosts.old    # 曾是 0777
```

## 判据

| 检查 | 修复前 | 修复后 |
|---|---|---|
| `ansible --version` 的 `config file` | `None` | `/root/sre-lab/ansible/ansible.cfg` |
| `ansible lab -m ping` | `Could not match supplied host pattern, ignoring: lab` | `lab-node \| SUCCESS => { "ping": "pong" }` |
| 目标解释器 | — | `ansible_python_version: 3.11.13` |
| `site.yml --syntax-check` | 通过（假的安全感） | 通过 |
| 仓库内 `-perm -o+w` 计数 | 135 目录 / 150 文件 | 0 |

「没有报错」不是验收判据，`--syntax-check` 通过反而是假的安全感：exit 0、日志非空都不等于动作发生了。判据必须是生效值：`config file` 指向、`ping` 的 pong、实跑 `changed=N`（[methodology ⑭⑩](../methodology.md)）。

## 遗留

`ansible-core` 随重建漂移（原 `2.20.1` / Python 3.14，现 `2.17.14` / Python 3.10.6），已记入 README，但未纳入 IaC 或引导脚本强制。
