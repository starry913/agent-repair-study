# RQ1.2 Data

本目录保存 `RQ1.2-pro.md` 的可复现中间数据与正式统计结果。分析总体为 Pre-12 中 `1,491` 条 `complete_repair=1` 的轨迹。

## 生成顺序

```bash
python3 RQ1/rq1_2_task_fit_analysis.py
python3 RQ1/rq1_2_mechanism_analysis.py
python3 RQ1/rq1_2_findings_analysis.py
```

## 文件说明

| 路径 | 含义 |
| --- | --- |
| `task_fit/task_features.csv` | 500 个 SWE-bench Verified instance 的 outcome-blind 任务特征 |
| `task_fit/trajectories_enriched.csv` | 任务特征、pathway 与 resolved 的轨迹级连接表 |
| `mechanisms/preloop_pairs.csv` | 每个 `FR -> FL` 对及其 reference-file 范围增益 |
| `mechanisms/postloop_pairs.csv` | 每个 `PV -> PR` 对及其首次/重复、同范围/扩范围机制 |
| `findings/distinct_by_task_type.csv` | Finding 1 的任务类型与 `D=4/5/6` 统计 |
| `findings/loop_windows.csv` | 表 A、C 的循环次数与 RR |
| `findings/loop_mechanisms.csv` | 表 B、D 的机制占比与关联轨迹 RR |
| `findings/matched_loop_contrasts.csv` | 同一 instance 的跨 agent 配对差值及 bootstrap CI |
| `findings/task_taxonomy_audit.csv` | 候选任务划分的 outcome-blind separation audit |
| `findings/mechanism_separation_audit.csv` | 新旧机制划分的 Cramer's V 与 outcome 使用审计 |

任务类型仅由 reference patch 拓扑定义：一个 source file、一个 hunk；一个 source file、多个 hunks；同目录多 source files；跨目录多 source files。机制允许使用 reference source files，但不使用 final resolved 定义类别。
