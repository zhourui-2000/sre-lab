# sshd 加固改动未生效（lineinfile 命中错误行）

2026-09-22。playbook 报 X11Forwarding changed，`sshd -T` 仍为 yes，加固实际没生效。

## 根因

`lineinfile` 替换最后一条匹配行（`index[0]=lineno`，仅 `firstmatch:yes` 才 break）。原 regexp `^#?\s*KEY\s+` 命中 `#Match` 示例块的缩进行（第 140 行），激活行在第 104 行；sshd 取首个有效值，140 行的新值永不生效。

## 修复与判据

regexp 收紧为 `^#?KEY[ \t]+`。`sshd -T` 九项生效值正确，连跑 `changed=3` 后 `changed=0`。验收打生效值：`sshd -T` / `nginx -T`（见 [methodology ①](../methodology.md)）。
