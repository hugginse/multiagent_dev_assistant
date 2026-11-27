# Eval Report 汇总（M1–M4）

> 数据来源：`data/reports/eval_*.json`（本机 Ollama `qwen3.5:9b`，`OLLAMA_NUM_CTX=65536`）。
> **口径**：本地 sample_repo 沙箱 + 隐藏测试评分；非公开 benchmark 官方分数。

## 关键运行

| 里程碑 | eval_id | suite | k | memory | resolve_rate | pass@k | tool_calls (tier) | 备注 |
|---|---|---|---|---|---|---|---|---|
| M1 Gate | `eval_20261127_054339_2b1b1d` | smoke | 1 | off | **33.33%** | T001=0, T002=0, T003=1 | —（旧 schema） | 首次端到端 |
| M2 Gate | `eval_20261127_090248_86d49d` | smoke | 3 | off | **33.33%** | T001=0, T002=0, T003=1 | M:9 R:18 X:9 | pass@k + 分 tier |
| M3 Gate ON | `eval_20261127_100927_4dda6f` | main | 1 | **on** | **33.33%** | T102/T104/T105/T106=1，其余 0 | M:12 R:24 X:12 | 含 episode 沉淀 |
| M3 Gate OFF | `eval_20261127_101510_ad284d` | main | 1 | **off** | **33.33%** | 同上 | M:12 R:24 X:12 | A/B 对照臂 |

## 记忆 A/B（M3 main k=1）

- compare：`data/reports/compare_eval_20261127_100927_4dda6f_vs_eval_20261127_101510_ad284d.md`
- **Δresolve_rate = 0**（两侧均为 33.33%）
- 解读：单次 k=1、任务难度偏硬时记忆增益不显著；注入链路（event `memory_injected`、convention/episode 检索）已打通，A/B 可复现。

## 长期记忆存量（Gate-M3 时点）

| kind | count | 说明 |
|---|---|---|
| convention | 26 | `memory onboarding --path sample_repo` 等写入 |
| episode | 12 | main 套件 memory-on 运行终态自动沉淀 |

## 套件规模

| 套件 | 任务数 | 覆盖 |
|---|---|---|
| smoke | 3 | bugfix / feature / refactor 冒烟 |
| main | 12 | T101–T112，easy/medium/hard，三类标签齐全 |
| swe_bench 子集 | 3 | SWE-bench Lite 字段格式，本地沙箱口径 |

## 质量门禁（每 commit / 每 Gate）

```text
uv run ruff check .     → 0 error
uv run pytest -q        → 全绿（当前 ~200+ tests）
```

## 已知限制

1. Agent 单轮迭代常在 1 次测试后进入 reviewer（工具循环仍偏浅），复杂任务 resolve 受限。
2. 记忆 A/B 在 k=1 下无 delta；需更大 k / 更易任务集才能拉开差距。
3. SWE-bench 为**本地演示子集**，执行口径 ≠ 官方 Docker。
4. tokens 对本地模型为估算口径（Ollama usage 字段可用时取真实值）。

---

*生成说明：M4 定稿时由 harness 报告汇总；后续新 eval 请追加行并保持日期升序。*
