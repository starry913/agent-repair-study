# Pre 12.0

## 1. 数据设置

| 项目 | 设置 |
| --- | --- |
| 基准数据集 | SWE-bench Verified |
| 轨迹来源 | leaderboard public trajectories |
| 基础模型 | Claude 4 Sonnet |
| Agent | Lingxi、Moatless Tools、OpenHands |
| 轨迹数量 | 1,500 条 agent-instance trajectories |
| 最终结果 | 官方 resolved 标签 |
| 抽象版本 | `pre12_frfl_prdelta_reason2_outcome3` |

| Agent | Trajectories | Resolved | RR |
| --- | ---: | ---: | ---: |
| Lingxi | 500 | 373 | 0.746 |
| Moatless Tools | 500 | 354 | 0.708 |
| OpenHands | 500 | 352 | 0.704 |
| Total | 1,500 | 1,079 | 0.719 |

## 2. 轨迹表示

APR 轨迹同时包含阅读、搜索、运行、编辑和推理。`Action` 描述可观察行为，`Subtask` 描述行为服务的局部目标。

给定轨迹 $T$：

$$
S(T)=\langle s_1,s_2,\dots,s_m\rangle,
\qquad
s_i=\langle \tau_i,A_i,o_i\rangle
$$

其中，$\tau_i$ 为 subtask，$A_i$ 为 action sequence，$o_i\in\{+,-,?\}$ 为基于 reference patch 的 retrospective local outcome。最终结果只使用官方 resolved 标签。

## 3. Subtask 设计

| Code | Subtask | 严格界定 |
| --- | --- | --- |
| `PU` | Problem Understanding | 围绕 issue、期望行为和修复方向形成问题级理解 |
| `FR` | Failure Reproduction | 获取、构造或观察目标 failure evidence |
| `FL` | Fault Localization | 根据问题或 failure evidence 定位 fault-relevant 源文件、符号或逻辑 |
| `PC` | Patch Construction | 形成首个产品源码 candidate patch |
| `PR` | Patch Refinement | 在已有 candidate patch 经历验证反馈后，继续修改产品源码 |
| `PV` | Patch Validation | 运行测试、脚本或解释验证反馈，评价当前 patch |

边界规则：

- `FR` 产生 failure evidence；`FL` 将 evidence 转化为 fault target；两者不按固定先后强行排序。
- `PC` 是轨迹中第一次产品源码编辑；未改变产品源码的测试、复现和诊断材料不算 `PC`。
- `PR` 必须同时满足：已有 `PC`、其后出现验证事件、随后再次编辑产品源码。
- 验证事件包括执行测试或脚本、实质性解释验证反馈，以及在已有 patch 后创建或修改诊断材料。
- 测试、复现、debug、verification 脚本及其清理操作归入 `PV`，不归入 `PR`。
- 紧邻产品源码 refinement 的最多两个 `Read/Search/Reason` 动作并入同一 `PR`；环境准备并入其服务的 subtask。

## 4. Action 设计

| Action | 严格界定 |
| --- | --- |
| `Reason` | 明确分析问题、推断 root cause、解释反馈或说明 patch rationale |
| `Read` | 查看文件、代码、目录、日志或上下文 |
| `Search` | 搜索关键词、符号、文件名、调用点或相关实现 |
| `Run` | 执行测试、脚本、构建、lint 或其他命令 |
| `Add` | 新建文件，或向已有文件新增内容 |
| `Revise` | 在已有内容上替换、调整或同时增删 |
| `Remove` | 删除文件、代码块，或将已有内容替换为空 |
| `Setup` | 安装依赖、创建目录、配置环境、权限或资源 |

`Reason` 只保留具有具体问题、证据、假设或决策内容的文本；工具调用说明、过渡句、空泛计划和 final summary 不计入 `Reason`。

## 5. 文件 provenance 与 PR 重整

每个 action event 额外记录 `is_file_creation`、`created_by_agent`、`is_diagnostic_path`、`is_source_path`、`is_diagnostic_artifact` 和 `is_product_source_edit`。

| 类型 | 判定规则 |
| --- | --- |
| 测试路径 | 路径位于 `test/tests/testing/fixtures`，或文件名为 `test_*`、`*_test` |
| 诊断命名 | 文件名包含独立词 `repro`、`debug`、`verify`、`validation`、`demo`、`investigate`、`edge_case`、`scratch`、`temporary`、`tmp` 或 `script` |
| Agent 新建文件 | 明确的 create 工具、`CreatePythonFileArgs` 或新建命令 |
| 新建根目录文件 | 默认视为诊断材料；若属于 reference patch 的非测试源码则按产品源码处理 |
| 产品源码 | 已有源码文件，或非诊断的嵌套产品源码；reference patch 中的非测试源码优先按产品源码处理 |

`PR` 的 local outcome 不由 agent 自称完成，也不由最终 resolved 反推，而是使用 reference patch 和验证反馈进行事后标注：

| Outcome | 判定 |
| --- | --- |
| `+` | refinement 修改 reference-relevant 源码并沿 reference 的增删方向推进，或验证反馈出现 fail-to-pass / 非负改善 |
| `-` | 修改 reference 之外的源码、明确背离 reference 方向，或反馈出现 pass-to-fail |
| `?` | 编辑路径或编辑内容不可获得，无法判断相对方向 |

当内容级证据正负相抵时，预先规定的 tie-break 是：目标为 reference 源文件且没有负向验证反馈则记 `+`；有负向反馈则记 `-`。该规则不使用最终 resolved 标签。

统一的 local outcome 含义为：

| Outcome | 含义 |
| --- | --- |
| `+` | 当前局部行为与 oracle evidence 对齐 |
| `-` | 有明确行为或反馈，但未与 oracle evidence 对齐 |
| `?` | 缺少足够证据 |

## 6. 统计情况

| 项目 | 数量 |
| --- | ---: |
| Trajectories | 1,500 |
| Resolved trajectories | 1,079 |
| Overall RR | 0.719 |
| Complete trajectories with `PC` and `PV` | 1,491 |
| Subtask records | 21,140 |
| Action records | 155,836 |

### Agent + Action

| Agent | `Reason` | `Read` | `Search` | `Run` | `Add` | `Revise` | `Remove` | `Setup` | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Lingxi | 10,265 | 34,973 | 23,331 | 9,926 | 2,244 | 5,048 | 178 | 19 | 85,984 |
| Moatless | 8,308 | 7,094 | 4,732 | 3,657 | 2,777 | 2,730 | 15 | 651 | 29,964 |
| OpenHands | 6,452 | 8,855 | 6,120 | 11,713 | 2,626 | 3,670 | 375 | 77 | 39,888 |
| Total | 25,025 | 50,922 | 34,183 | 25,296 | 7,647 | 11,448 | 568 | 747 | 155,836 |

### Agent + Subtask records

| Agent | `PU` | `FR` | `FL` | `PC` | `PR` | `PV` | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Lingxi | 424 | 4,408 | 3,998 | 499 | 336 | 830 | 10,495 |
| Moatless | 379 | 1,402 | 1,054 | 496 | 400 | 882 | 4,613 |
| OpenHands | 222 | 1,668 | 1,235 | 497 | 960 | 1,452 | 6,034 |
| Total | 1,025 | 7,478 | 6,287 | 1,492 | 1,696 | 3,164 | 21,142 |

### Local outcome 与最终 resolved

单元格为 `n / resolved rate`。

| Subtask | `+` | `-` | `?` |
| --- | ---: | ---: | ---: |
| `PU` | 958 / 0.733 | 67 / 0.642 | 0 |
| `FR` | 4,074 / 0.740 | 3,036 / 0.680 | 368 / 0.674 |
| `FL` | 4,335 / 0.730 | 1,952 / 0.654 | 0 |
| `PC` | 1,365 / 0.754 | 127 / 0.394 | 0 |
| `PR` | 1,061 / 0.594 | 629 / 0.501 | 6 / 0.667 |
| `PV` | 1,536 / 0.701 | 1,600 / 0.576 | 28 / 0.571 |

| Subtask | `?` share |
| --- | ---: |
| `PU` | 0.0% |
| `FR` | 4.9% |
| `FL` | 0.0% |
| `PC` | 0.0% |
| `PR` | 0.4% |
| `PV` | 0.9% |

## 7. 文件说明

| 文件 | 含义 |
| --- | --- |
| `dataset/pre12_actions.csv` | action-level 原始抽象数据，含 `is_file_creation`、`created_by_agent`、路径类型和产品源码判定字段 |
| `dataset/pre12_subtasks.csv` | subtask-level 原始抽象数据，含 local outcome 与判定依据 |
| `dataset/pre12_trajectories.csv` | trajectory-level 数据，含 canonical path、distinct types 和 resolved |
| `summary/` | 从核心 dataset 派生的统计表 |
| `summary/pre12_pr_quality.csv` | PR 边界和未知比例的一致性检查 |
| `metadata/pre12_reference_patch_meta.csv` | reference patch、test files、FAIL_TO_PASS 元信息 |
| `metadata/pre12_report.md` | 自动生成的基础统计报告 |

所有结果由 `swe_verified_claude4_traj/scripts/pre12_recompute.py` 从原始轨迹重新生成。
