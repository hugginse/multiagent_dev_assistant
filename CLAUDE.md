# CLAUDE.md — multiagent_dev_assistant 执行指引

## 项目定位

仓库级智能研发助手（**多 Agent 协同 + 双层记忆 + 工具体系 + 评测 harness**），个人求职作品，交付物为 **GitHub 公开仓库 `multiagent_dev_assistant`**。

系统能力：任务套件 → LangGraph 五节点图（planner / explorer / coder / tester / reviewer，有界循环）→ 沙箱真实执行测试 → diff + 量化报告；短期记忆 = 图内 AgentState 黑板，长期记忆 = 仓库约定 + 历史任务（检索注入、可开关 A/B）；harness 对任务集批量评测，产出 pass@k / 指标对比报告。**交互形态为 CLI**（typer + rich，console script `devassist`）；静态页面挂路由**后续再定**，M1–M4 不做 Web。

本文件与 `docs/plan.md`、`docs/architecture.md` **自包含**：仅凭本仓库文档即可完整开工。

## 文档地图（开工前必读，顺序固定）

1. **`docs/plan.md`** — 四个里程碑、逐条 feature commit 清单、每个 Gate 的验收命令与 git 动作 → 回答「做什么、按什么顺序、何时提交推送」
2. **`docs/architecture.md`** — 已确认决策、架构、五节点图协议、双层记忆、工具 tier、harness 指标、数据模型、事件协议与 CLI、配置表 → 回答「做成长什么样」

冲突处理：**做什么**以 architecture.md 为准；**顺序 / 提交 / 验收**以 plan.md 为准。需求方决策变更 → 先改 architecture.md 再动代码。

## 环境铁律（Windows 11 / Git Bash）

- 环境管理**只用 uv**：`.python-version` 钉 3.12，`uv sync` 建环境，日常一律 `uv run ...`（如 `uv run pytest`、`uv run devassist eval --suite smoke`）
- **禁止**：`python3`（本机是损坏的商店别名）、裸 `python`（3.14，依赖无 wheel）、conda 环境
- 依赖增改后必须 `uv sync` 并**提交 `uv.lock`**；`.venv/` 不提交
- 主机 **9950X + RTX 5060 Ti 16GB**；Ollama 默认模型 **`qwen3.5:9b`**（Q4 约 6.6GB，显存留足 KV cache 余量），Embedding **`qwen3-embedding:4b`**；`OLLAMA_NUM_CTX=16384`（防 KV cache 挤爆显存，OOM 时下调）
- Docker 已装但本项目 **M1–M4 不引入 Docker 沙箱**（进程级 workspace jail 即可）
- 所有 Gate 命令均为 Git Bash 形式（见 plan.md 各节）

## Git 工作流（需求方已定，不得更改）

- 分支固定 `main`；**远端空仓库由需求方预先在 GitHub 创建**，开工第一步即 `git remote add origin <URL>`；若拿不到 URL，**停下来询问**，不要自行建仓
- 顺序固定 M1 → M2 → M3 → M4；每个里程碑内按 plan.md 的 feature 清单分批 commit
- commit 规范：中文、conventional 前缀（`feat:` / `fix:` / `test:` / `docs:` / `ci:` / `chore:`），**每条末尾加** `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- 每个 commit 前：`uv run ruff check .` 0 error + 相关 `uv run pytest` 通过
- **每个 Gate 全绿 → 打 annotated tag（`m1`/`m2`/`m3`/`m4`）→ 一次性 push（全部 commit + tag）**；Gate 失败先修复并 commit、重跑 Gate，全绿前不打 tag 不 push；Gate 之外不 push；禁止 force push
- 永不提交：`.env`、`data/`、`.venv/`、`__pycache__/`、checkpoint 数据

## 质量红线（细节见 architecture.md）

- 工具**路径 jail** 必须单测覆盖（`..`、绝对路径、符号链接逃逸）；写/执行只落在 workspace 内
- **隐藏测试 Agent 全程不可见**（评分阶段才注入）；测试**真实执行**，禁止 mock 评分结果
- 节点工具授权**硬校验**（registry 层拒绝越权，非提示词约定）；无任意 shell，执行白名单只有 `run_tests` / `run_lint`
- 双通道缺 key **显式失败**，禁止静默降级；本地默认 `qwen3.5:9b` 不得降级
- 事件顺序固定（`run_started → node/tool/llm_delta/test_result×N → run_finished|error`），`seq` 单调，**先落库再展示**；`llm_delta` CLI 真流式，禁止整段切片伪装
- **核心与展示解耦**：runner 不依赖 CLI/Web；M1–M4 不引入 HTTP 路由；未来加静态页只加展示层
- 循环必须有界（`MAX_ITERATIONS=8`），触顶产出当前 diff 与报告（失败也是数据）
- 记忆必须可开关（`--memory on/off`），A/B 报告可复现
- SWE-bench 接入必须注明「本地沙箱执行口径 ≠ 官方 Docker 分数」，不冒充官方成绩
- 不做范围外功能：M1–M4 的 Web/SSE/静态页、多语言、IDE 插件、自动开 PR、多用户权限、WebSocket、K8s、Docker 沙箱、rerank/BM25、computer use

## sample_repo 与任务套件

- `sample_repo/`：自建演示仓库（约 20 文件、自带 pytest 基线绿），**M1 创建**；任务围绕它出题（bugfix / feature / refactor）
- `suites/smoke/`：3 条（M1 Gate 用）；`suites/main/`：10–15 条（M3 扩充）；均含 `tasks/*.yaml` + `hidden_tests/`
- 任务 YAML 结构、隐藏测试注入时机见 architecture.md §6

## CLI 一览（console script `devassist`）

```bash
uv run devassist run --task T001 --suite smoke --provider ollama --memory on   # 单任务，终端真流式
uv run devassist eval --suite smoke --k 1 --provider ollama                    # 批量评测
uv run devassist report --eval <id>                                            # 单份报告
uv run devassist compare <a.json> <b.json>                                     # A/B 对比
uv run devassist tasks list --suite smoke                                      # 套件浏览
uv run devassist runs list / show <id> --events / show <id> --diff             # 历史与回放
uv run devassist memory onboarding --path sample_repo / list / search "..."    # 记忆
```

退出码约定：`0` 全部成功，`1` 存在失败任务，`2` 配置/环境错误。

## 开工检查（首次运行，逐项确认）

1. `uv --version`、`ollama --version`；`curl -s http://localhost:11434/api/tags` 含 `qwen3.5:9b` 与 `qwen3-embedding:4b`（缺则 `ollama pull qwen3.5:9b`）
2. `CLAUDE.md`、`docs/plan.md`、`docs/architecture.md` 在仓库根
3. `git config user.name` / `user.email` 已配置（仓库级即可）；未配置则**询问需求方**，不要伪造身份
4. `uv sync && uv run python --version` 输出 3.12
5. 读完 plan.md 与 architecture.md，从 **M1 feature commit #1** 开始执行

## 阻塞时的处置

- 环境不满足（模型缺失、显存 OOM 降不下来）、远端 URL 缺失、需求方决策缺失 → **停下报告，不要绕过、不要静默降级**
- 技术方案疑问 → 查 architecture.md；文档未覆盖的取舍 → 按最小范围实现并在报告中说明，不擅自扩大范围
