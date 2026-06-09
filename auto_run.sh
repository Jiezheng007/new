#!/bin/bash
# auto_run.sh

# 从 git 记录中提取最近一次完成的阶段数字
LAST_PHASE=$(git log --oneline | grep -iE 'Phase [0-9]+' | head -n 1 | grep -oE 'Phase [0-9]+' | grep -oE '[0-9]+')
if [ -z "$LAST_PHASE" ]; then
    NEXT_PHASE=1
else
    NEXT_PHASE=$((LAST_PHASE + 1))
fi

# 从 generated-issues.md 中读取总任务数 (根据二级标题 "## 1." 匹配)
TOTAL_PHASES=$(grep -cE '^## [0-9]+\.' generated-issues.md)

echo "📊 检测到总任务数: $TOTAL_PHASES"
echo "✅ 上一个完成的任务: Phase ${LAST_PHASE:-0}"
echo "🚀 即将开始的任务: Phase $NEXT_PHASE"
echo "----------------------------------------"

for (( phase=$NEXT_PHASE; phase<=$TOTAL_PHASES; phase++ ))
do
    echo -e "\n========================================"
    echo "▶️ 正在自动化执行 Phase $phase / $TOTAL_PHASES"
    echo "========================================"
    
    # 从 generated-issues.md 抽取当前 phase 的精确规格，避免 Claude 读全 12 个 phase 浪费上下文
    PHASE_CONTENT=$(awk -v n="$phase" '
      /^## [0-9]+\./ {
        line_num = $0
        sub(/^## /, "", line_num)
        sub(/\..*/, "", line_num)
        current = line_num + 0
        if (current == n) { in_section = 1; print; next }
        if (in_section && current != n) { in_section = 0; exit }
      }
      in_section { print }
    ' generated-issues.md)
    if [ -z "$PHASE_CONTENT" ]; then
        echo -e "\n❌ 未能在 generated-issues.md 中找到 Phase $phase 的规格。请检查 phase 编号。"
        exit 1
    fi

    # 构建专属当前阶段的 Prompt
    PROMPT="We are automating our workflow. Please execute the following unit of work for Phase $phase (Issue $phase).

# Task Specification (Phase $phase)

The following is the exact specification for this phase, extracted from generated-issues.md. Do not re-read generated-issues.md — the relevant content is already provided below. You may consult @PRD.issue.md if you need broader product context.

$PHASE_CONTENT

# Do Work

Execute a complete unit of work: plan it, build it, validate it, and **commit it yourself** (the host script does not commit on your behalf — committing is your responsibility, and the next script run uses git log to find the last completed phase).

## Workflow

### 1. Understand the task

You already have the full task specification above. Explore the codebase to understand the relevant files, patterns, and conventions. Focus ONLY on the 'What to build' and 'Acceptance criteria' for Phase $phase.

### 2. Plan (optional)

If the task has not already been planned, create a plan for it.

### 3. Implement

**For backend code**: use red/green/refactor, one test at a time in a tracer-bullet style.

1. Write a single failing test for the smallest vertical slice of behavior
2. Run the test — confirm it fails (red)
3. Write the minimum code to make it pass (green)
4. Repeat from step 1 for the next slice of behavior
5. Refactor if needed while keeping tests green

Each test should target one thin vertical slice through the system. Do not write all tests upfront — write one, make it pass, then move to the next.

**For frontend code**: implement directly without TDD.

### 4. Validate

Run the feedback loops and fix any issues. Repeat until it passes cleanly.

cd backend
PYTHONPATH=. .venv/bin/pytest


### 5. Commit

Once tests pass cleanly, commit the work using git. Make sure to include "Phase $phase / Issue $phase" in the commit message."

    # 核心：每次打开一个全新的 claude 进程，利用 -p 执行单次目标并退出
    # Claude Agent 会在其内部自我循环执行 (写代码 -> 测代码 -> 改代码)，直到目标完成。
    claude -p "$PROMPT" --dangerously-skip-permissions
    
    CLAUDE_EXIT_CODE=$?
    if [ $CLAUDE_EXIT_CODE -ne 0 ]; then
        echo -e "\n❌ Claude 进程运行异常 (退出码 $CLAUDE_EXIT_CODE)，已停止自动化流程。你可以人工检查原因。"
        exit 1
    fi

    # 硬性验证：Claude 必须自己提交，且 commit message 必须包含 "Phase N / Issue N"
    # 下次脚本启动靠这个标识来定位 LAST_PHASE，不提交 = 下次重跑同一 phase = 白烧额度
    if ! git log -1 --pretty=%s | grep -q "Phase $phase / Issue $phase"; then
        echo -e "\n❌ Phase $phase 未发现预期的 commit ('Phase $phase / Issue $phase')。"
        echo "   Claude 可能没提交，或 commit 消息格式不对。脚本中止，避免下次重跑。"
        exit 1
    fi
    echo -e "\n📝 已确认 commit: $(git log -1 --pretty='%h %s')"

    # 本地硬性验收验收：在宿主机跑一次测试作为双重保险
    echo -e "\n🧪 正在执行本地最终测试验收..."
    (cd backend && PYTHONPATH=. .venv/bin/pytest -q)
    TEST_EXIT_CODE=$?
    
    if [ $TEST_EXIT_CODE -ne 0 ]; then
        echo -e "\n❌ 本地测试验收未通过！请人工介入处理或打开 claude 继续修复。脚本中止。"
        exit 1
    fi
    
    echo -e "\n📦 验收完全通过！Claude 已经完成了代码提交。"
    
    echo "✅ Phase $phase 成功归档！"
    sleep 2 # 稍微歇一下再开启下一个进程
done

echo -e "\n🎉 恭喜！所有 $TOTAL_PHASES 个阶段均已自动化执行完毕！"
