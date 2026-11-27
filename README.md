# multiagent_dev_assistant

仓库级智能研发助手：**多 Agent 协同 + 双层记忆 + 工具体系 + 评测 harness**，交互形态为 **CLI**（`devassist`）。

输入任务描述（缺陷/特性），LangGraph 五节点图（planner / explorer / coder / tester / reviewer，有界循环）在沙箱 workspace 中真实执行测试，产出**带测试通过证据的代码 diff** 与量化指标报告。

> 设计基准见 [`docs/architecture.md`](docs/architecture.md)，执行顺序见 [`docs/plan.md`](docs/plan.md)。

## 环境要求

- Windows 11 + Git Bash（或兼容 shell）
- Python **3.12**（由 [uv](https://docs.astral.sh/uv/) 管理）
- [Ollama](https://ollama.com)，默认模型 `qwen3.5:9b`、`qwen3-embedding:4b`

```bash
uv sync
uv run python --version   # 应输出 3.12.x
```

## 快速上手

```bash
# 复制并按需修改配置
cp .env.example .env

# 单任务运行（终端真流式事件）
uv run devassist run --task T001 --suite smoke --provider ollama

# 批量评测
uv run devassist eval --suite smoke --k 1 --provider ollama

# 历史与回放
uv run devassist runs list
uv run devassist runs show <id> --events
uv run devassist runs show <id> --diff
```

## 开发

```bash
uv run ruff check .
uv run pytest -q
```

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 架构、决策、数据模型、事件协议 |
| [`docs/plan.md`](docs/plan.md) | 里程碑 M1–M4、feature 清单、Gate 验收 |
| [`CLAUDE.md`](CLAUDE.md) | 执行指引与质量红线 |

## License

MIT
