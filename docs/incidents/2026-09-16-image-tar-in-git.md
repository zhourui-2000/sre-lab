# Docker 镜像 tar 包误入 Git

- **日期**：2026-09-16
- **影响**：`git push` 被拒 —— `File grafana.tar is 126.58 MB; exceeds 100.00 MB`
- **一句话结论**：`git add .` 把镜像归档一并暂存了

## 现象与根因

- `git add .` 将 `grafana.tar` 一并暂存
- 后续删除该文件**仅新增一个删除 commit，历史中大对象仍然存在** → 推送仍被拒

## 修复

```bash
git filter-repo --invert-paths --path grafana.tar
```

`.gitignore` 补充 `*.tar`

## 教训

- **构建产物不进版本控制**
- `git add .` 前先 `git status` 确认暂存内容
