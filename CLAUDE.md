# CLAUDE.md — 项目级规则

## 测试必须在专用 conda 环境中运行

**禁止在系统 Python 或其它已有 conda 环境里跑 backend 的 pytest。**
所有 backend 测试必须在名称为 `yuqing-test` 的 conda 环境中执行(见
`backend/requirements.txt` 锁定依赖)。原因:

- 避免污染用户现有的 `claude-agent` / `pytorch` / `llm` 等环境的包;
- 统一依赖版本,避免 `passlib` / `bcrypt` / `python-jose` 在不同 Python
  小版本上的兼容问题;
- PR / 回归测试在所有人机器上行为一致。

### 一次性环境搭建

```bash
# 1) 创建环境(已创建好,不需要重复执行)
conda create -n yuqing-test python=3.11 -y

# 2) 安装 backend 依赖
conda run -n yuqing-test pip install -r backend/requirements.txt
```

### 跑测试的标准命令

在仓库根目录 `D:\code\new` 下:

```bash
# 跑某一只文件
cd backend && conda run -n yuqing-test python -m pytest tests/test_db.py -v

# 跑全量
cd backend && conda run -n yuqing-test python -m pytest
```

> 推荐用 `conda run -n yuqing-test ...` 而不是先 `conda activate`,这样
> 在非交互式 shell(脚本、CI、本工具的 Bash 工具)里也稳定可用。

### 创建 / 修复新依赖时

- 任何 `pip install` 必须落到 `yuqing-test` 环境内;
- 如果新加了依赖,同步追加到 `backend/requirements.txt`,别只装在本地。
