# Docker 镜像 tar 包误入 Git

2026-09-16。`git add .` 暂存 `grafana.tar`，`git push` 被拒：`File grafana.tar is 126.58 MB; exceeds 100.00 MB`。删除文件无效，历史仍留大对象。

```bash
git filter-repo --invert-paths --path grafana.tar
```

`.gitignore` 补 `*.tar`；`git add .` 前先 `git status`。
