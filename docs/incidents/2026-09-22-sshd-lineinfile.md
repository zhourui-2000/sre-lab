# sshd 加固改动未生效（lineinfile 命中错误行）

- **日期**：2026-09-22
- **影响**：playbook 报 X11Forwarding changed，但 `sshd -T` 仍显示 yes（**安全加固实际没生效**）
- **一句话结论**：`lineinfile` 命中了文件里注释示例块的缩进行

## 现象与诊断

- 现象：playbook 报 X11Forwarding changed，但 `sshd -T` 显示仍为 yes
- 诊断：
  - `lineinfile` 语义为「**替换最后一条匹配行**」（源码 `index[0]=lineno`，仅 `firstmatch:yes` 才 break）
  - 原 regexp `^#?\s*KEY\s+` 命中了文件内 `#Match` 示例块的缩进行（第 140 行），
    而**激活行在第 104 行** → 改动落在无效位置
  - 叠加因素：sshd 对多数指令取「**首个**有效值」，104 行在前，故 140 行的新值永不生效

## 修复

- regexp 收紧为 `^#?KEY[ \t]+`（`#` 后不允许空白，锚定行首）

## 验证

- `sshd -T` 九项生效值 + 连续两次运行 `changed=3 → changed=0`

## 教训

见 [methodology ①](../methodology.md)：`lineinfile` 只保证「改了**文件**」，不等于「改了**生效值**」。
必须用 `sshd -T` / `nginx -T` 这类配置自检命令做验收。
