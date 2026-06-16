# 测试结果收集区

请团队中负责“测试”的同学，将运行脚本后得到的图表、截图保存在对应的子目录下。

## 1. 性能测试证据 (`performance/`)
- 保存 Locust 压测完成后的网页截图（Charts 选项卡下的折线图）。
- 重点截图：并发量（Users）与响应时间（Response Times）的对比曲线。

## 2. 可用性测试证据 (`availability/`)
- 保存运行 `pytest test_availability.py` 成功通过的终端绿字截图。
- 截图能够证明在故障注入下系统依然存活。

## 3. 可修改性测试证据 (`modifiability/`)
- 运行 `run_modifiability_test.bat`。
- 将输出结果中显示圈复杂度为 "A"，维护性指数评分为 "A" 的终端画面截图保存下来。

**评估同学须知**：提取这些目录中的截图直接贴入“系统测试与评估结果”相关的 PPT 或 Word 章节即可。
