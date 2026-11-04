# 陌生环境 + 陌生人 + 一条命令 —— 这是「可复现」的可用定义
#
#   make verify      跑全部一致性测试（只读仓库，不碰服务器）
#
# 依赖：仅 python3 标准库。不装 anything 是刻意的 ——
# 「先 pip install 才能验证」会让验证本身变成一个失败点。

PY ?= python3

.PHONY: verify test help

help:
	@echo "make verify   = 跑全部一致性测试（零依赖，只读仓库）"
	@echo "make test     = 同 verify"

verify: test

test:
	@$(PY) tests/run.py
