# multiagent_dev_assistant 开发计划

> 执行入口：仓库根 `CLAUDE.md`；设计基准：`docs/architecture.md`；本文回答**做什么、按什么顺序、何时提交推送**。
> 流程：**远端建仓（需求方）→ 本地关联 → M1…M4 逐 feature commit → 每个 Gate 全绿后打 tag 并推送一次**。
> 顺序固定 M1 → M2 → M3 → M4；**上一里程碑 Gate 未过不得进入下一里程碑**；任一 Gate 失败先修复。
> 交互形态（D5）：**CLI 优先**，M1–M4 无 Web；静态页面挂路由后续再定，不进本计划。

---

## 0. Git 工作流（需求方已定，不得更改）

### 0.1 远端与本地关联（开工第一步）

远端空仓库由**需求方**在 GitHub 预先创建（public，不初始化 README），仓库名 **`multiagent_dev_assistant`**（若需求方另定名以其为准）。执行终端拿到 URL 后：

```bash
# 本地目录已由需求方放入：CLAUDE.md、docs/
git init -b main
git remote add origin <需求方提供的 URL>
git config user.name <...> && git config user.email <...>   # 若全局未配置；不要伪造身份，缺就问
uv sync && uv run python --version                          # 确认 3.12，生成 uv.lock
```

拿不到 URL → **停下询问**，不要自行建仓。

### 0.2 提交与推送规则

- **commit 粒度 = 下文每条 feature 条目**（一条 feature 一个 commit；确需拆分/合并时保持语义不变并在报告说明）
- message 格式：`feat: 中文描述`（前缀按 feat/fix/test/docs/ci/chore），**每条末尾加**：
  ```
  Co-Authored-By: Claude Code <noreply@anthropic.com>
  ```
- 每个 commit 前：`uv run ruff check .` 0 error + 相关 `uv run pytest` 通过
- **每个 Gate 全绿 → 打 annotated tag → 一次性 push（全部 commit + tag）**：

  | Gate | tag | push 命令 |
  |---|---|---|
  | Gate-M1 | `m1` | `git push -u origin main m1`（首次，带 -u） |
  | Gate-M2 | `m2` | `git push origin main m2` |
  | Gate-M3 | `m3` | `git push origin main m3` |
  | Gate-M4 | `m4` | `git push origin main m4` |

- Gate 失败 → 修复并 commit → 重跑 Gate → 全绿前**不打 tag 不 push**；Gate 之外不 push；禁止 force push
- 永不提交：`.env`、`data/`（sqlite/chroma/workspaces/runs/reports）、`.venv/`、`__pycache__/`、checkpoint 数据

### 0.3 提交历史预期形态

```
* chore: 初始化仓库（uv 工程骨架与项目文档）      ← m1 之前
* feat: ...（M1）
* feat: ...（M2）
* feat: ...（M3）
* feat: ...（M4）
```

---

## M1 — 单 Agent 最小闭环 + Harness v0 + CLI 骨架

**目标**：一个任务从 YAML 到「真实跑测试 → diff + 指标报告」端到端跑通，全程 CLI 操作；多 Agent 图先以单节点桩起步（结构预留，M2 拆分）。

### Feature 清单（每条一个 commit）

1. `feat: 初始化仓库（uv 工程骨架、ruff/pytest 配置、项目文档）`
2. `feat: 配置与双通道 LLM 客户端（ollama 默认 qwen3.5:9b，openai/anthropic 显式失败）`
3. `feat: 双通道 Embedding 客户端（ollama 默认 qwen3-embedding:4b）`
4. `feat: SQLite 数据层（runs/run_events/evals/eval_items/memories/repos 表 + SqliteSaver checkpointer）`
5. `feat: 工具注册表与 tier 授权（R/W/X/M，越权拒绝）`
6. `feat: 只读工具 read_file/grep/list_dir（路径 jail）`
7. `feat: 写入工具 write_file/edit_file（workspace 约束）`
8. `feat: 沙箱 workspace（run 副本、路径 jail、超时、输出截断）`
9. `feat: 执行工具 run_tests/run_lint（白名单命令）`
10. `feat: sample_repo 演示仓库（约 20 文件，自带 pytest 基线绿）`
11. `feat: 任务套件格式与 smoke 套件（3 条任务 + 隐藏测试）`
12. `feat: AgentState 与单节点 Agent 循环（plan→code→test 雏形，LangGraph + checkpointer）`
13. `feat: harness runner（workspace 准备、执行、隐藏测试评分、metrics 落库、事件流产出）`
14. `feat: devassist CLI 骨架（typer：run/eval/report/compare/tasks/runs 子命令）`
15. `feat: run 子命令终端事件订阅（node/tool/llm_delta/test_result 逐条打印，真流式）`
16. `feat: eval/report/compare 子命令（JSON+MD+rich 表报告）`
17. `test: 工具 jail/授权负向测试、harness 评分测试、事件顺序测试（LLM mock）`

### Gate-M1 验收

```bash
uv run ruff check .                                            # 0 error
uv run pytest -q                                                # 全绿
uv run devassist eval --suite smoke --k 1 --provider ollama     # 3 任务端到端出报告
# 报告含 resolve/test_pass_ratio/iterations/tokens/wall_s 字段
uv run devassist run --task T001 --suite smoke --provider ollama
# 终端可见 node/tool/llm_delta/test_result 实时事件流
uv run devassist runs show <id> --events                        # 事件可回放，seq 单调
git tag -a m1 -m "Gate-M1" && git push -u origin main m1
```

---

## M2 — 多 Agent 协同 + 短期记忆完善

**目标**：五节点图 + 有界循环 + 黑板状态正式化；授权从提示词约束升级为硬校验。

### Feature 清单

1. `feat: 五节点图（planner/explorer/coder/tester/reviewer）与条件边`
2. `feat: 有界循环（tester fail→coder、reviewer reject→coder、连续 reject→planner、触顶 timeout）`
3. `feat: AgentState 正式 schema（plan/exploration/diff/test_history/review/memory_context）`
4. `feat: 节点级工具授权硬校验（explorer 只 R、coder R+W、tester R+X）`
5. `feat: run_events 全节点覆盖（node_enter/exit、tool_call/result、test_result）`
6. `feat: 短期记忆压缩（exploration 摘要去重、test_history 保留最近 N 条 + 失败摘要）`
7. `feat: harness 指标扩展（tool_calls 按 tier、max_hit、pass@k k>1）`
8. `test: 图结构/条件边/循环上限/授权负向测试`

### Gate-M2 验收

```bash
uv run ruff check . && uv run pytest -q
uv run devassist run --task T001 --suite smoke --provider ollama
# 终端事件流覆盖五个节点
uv run devassist eval --suite smoke --k 3 --provider ollama     # pass@k 出报告
# 报告含 tool_calls 分 tier 统计；越权调用在事件中可见为 rejected
git tag -a m2 -m "Gate-M2" && git push origin main m2
```

---

## M3 — 长期记忆 + 自建任务集扩充

**目标**：约定与历史任务沉淀、检索注入、可 A/B；main 套件 10–15 条。

### Feature 清单

1. `feat: memories 数据层与 Chroma 向量（cosine、repo_id 过滤）`
2. `feat: 仓库 onboarding 约定抽取（LLM → convention 记忆）`
3. `feat: episode 沉淀（run 终态 → LLM 压缩 → 落库）`
4. `feat: 记忆检索注入（top-k、阈值、prompt 模板、开关 --memory on/off）`
5. `feat: main 任务套件（10–15 条，覆盖 bugfix/feature/refactor，难度分层）`
6. `feat: 记忆 A/B 模式（同套件 on/off 双跑 → 对比报告）`
7. `feat: devassist memory 子命令（onboarding/list/search 调试）`
8. `test: 检索阈值/注入格式/episode 沉淀测试（LLM mock）`

### Gate-M3 验收

```bash
uv run ruff check . && uv run pytest -q
uv run devassist memory onboarding --path sample_repo
uv run devassist eval --suite main --k 1 --provider ollama --memory on
uv run devassist eval --suite main --k 1 --provider ollama --memory off
uv run devassist compare <on.json> <off.json>                   # A/B delta 表可读
# memories 表有 convention + episode 数据
git tag -a m3 -m "Gate-M3" && git push origin main m3
```

---

## M4 — 交付完善 + 公开 Benchmark 接入

**目标**：CLI 全功能收口、可脚本化；BenchmarkAdapter 接口 + SWE-bench Lite 子集（≤10 条）；交付物齐。静态页面是否后补由需求方后续单独决定，**不进本 Gate**。

### Feature 清单

1. `feat: runs 子命令完善（列表/详情/--events 回放/--diff 查看、退出码约定）`
2. `feat: eval 进度与 rich 终端报告增强（逐任务进度行、汇总表）`
3. `feat: BenchmarkAdapter 接口与 SWE-bench Lite 子集适配（≤10 条，本地沙箱执行）`
4. `feat: 启动时 workspace/死状态清理与 CLI 生命周期收尾`
5. `feat: memory 子命令完善（kind 过滤、注入预览、episode 浏览）`
6. `docs: README（安装/快速上手/CLI 手册/架构图）、eval_report.md 汇总`
7. `docs: 终端演示截图 ≥4 张（run 事件流、eval 表、compare diff、memory list）`
8. `ci: GitHub Actions（ruff + pytest）`

### Gate-M4 验收

```bash
uv run ruff check . && uv run pytest -q
uv run devassist eval --suite smoke --k 1 --provider ollama     # 全套 CLI 回归
uv run devassist run --task T001 --suite smoke --provider ollama
uv run devassist runs show <id> --events && uv run devassist runs show <id> --diff
uv run devassist memory list --kind convention
# SWE-bench 子集 devassist eval 至少 1 条端到端（或明确记录 blocked 原因）
ls docs/screenshots/*.png                                        # ≥4 张真实截图
# README 含安装与快速上手；eval_report.md 已汇总 M1–M4 关键数字
git tag -a m4 -m "Gate-M4" && git push origin main m4
```

---

## 附：里程碑外必做（穿插执行，不单独占 Gate）

- 每 commit 前 ruff + pytest（已含在工作流）
- `eval_report.md` 在 M3 起持续更新，M4 定稿
- 需求方决策变更 → 先改 `docs/architecture.md` 再改代码，plan 同步
- **静态页面挂路由**：需求方后续单独决策；若做，只加展示层（FastAPI/SSE 或纯静态读导出 JSON），不改核心，另开计划不塞进 M1–M4
