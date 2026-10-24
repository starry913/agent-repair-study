# RQ1.1 Pro：不同 subtask 的 local outcome 与最终 resolved 有什么关系？

## 分析设置

本节首先检验不同 local outcome 与最终 resolved 的关联，再分析两类不一致结果：

- `+ / unresolved`：局部结果与 oracle evidence 对齐，但最终修复失败；
- `- / resolved`：局部结果未与 oracle evidence 对齐，但最终修复成功。

为避免长轨迹因重复出现同一 subtask 而被过度加权，分析单位为 `trajectory × subtask anchor`：

| Subtask | Anchor |
| --- | --- |
| `PU`、`PC` | 首次出现 |
| `FR`、`FL`、`PR`、`PV` | 最后一次出现 |

机制分析同时使用原始轨迹、命令与测试输出、编辑内容、最终 patch 和 reference patch。自动规则只形成可复核的 evidence profile，不把文件或词法重合直接解释为语义正确性。

## 1. Local outcome 与最终 resolved 的宏观关联

单元格为 `n / RR`。

| Subtask | Outcome | Total | Lingxi | Moatless | OpenHands |
| --- | --- | ---: | ---: | ---: | ---: |
| `PU` | `+` | 958 / 0.733 | 417 / 0.746 | 356 / 0.713 | 185 / 0.741 |
| `PU` | `-` | 67 / 0.642 | 7 / 0.714 | 23 / 0.565 | 37 / 0.676 |
| `FR` | `+` | 863 / 0.745 | 225 / 0.796 | 290 / 0.731 | 348 / 0.724 |
| `FR` | `-` | 607 / 0.684 | 269 / 0.706 | 204 / 0.672 | 134 / 0.657 |
| `FR` | `?` | 30 / 0.700 | 6 / 0.667 | 6 / 0.833 | 18 / 0.667 |
| `FL` | `+` | 1022 / 0.736 | 334 / 0.769 | 324 / 0.728 | 364 / 0.712 |
| `FL` | `-` | 410 / 0.671 | 166 / 0.699 | 126 / 0.627 | 118 / 0.678 |
| `PC` | `+` | 1365 / 0.754 | 460 / 0.780 | 452 / 0.737 | 453 / 0.744 |
| `PC` | `-` | 127 / 0.394 | 39 / 0.359 | 44 / 0.477 | 44 / 0.341 |
| `PR` | `+` | 354 / 0.636 | 92 / 0.630 | 109 / 0.606 | 153 / 0.660 |
| `PR` | `-` | 185 / 0.595 | 50 / 0.600 | 53 / 0.623 | 82 / 0.573 |
| `PR` | `?` | 9 / 0.778 | 1 / 1.000 | 3 / 1.000 | 5 / 0.600 |
| `PV` | `+` | 1122 / 0.739 | 348 / 0.787 | 449 / 0.726 | 325 / 0.705 |
| `PV` | `-` | 369 / 0.678 | 151 / 0.656 | 46 / 0.609 | 172 / 0.715 |

`PC` 形成最强且跨 agent 一致的分叉：`PC+` 的 RR 为 0.754，`PC-` 仅为 0.394。相比之下，`FR`、`FL` 和 `PV` 的正负差距均约为 0.06，`PR` 仅为 0.041。这说明首次 patch direction 与最终结果的关联最强，但复现、定位、修正和验证的 local outcome 仍包含明显的不一致样本。

`PU` 暂不作语义解释。当前 `PU+/-` 来自 reference token overlap，而词法重合不能可靠判断 agent 是否形成了正确的 fault model。

## 2. 为什么 local outcome 为正，最终仍 unresolved？

表中 `Total` 为 `n / cell share`，三个 agent 列为样本数。各组内部机制互斥，组内 share 之和为 1。

| Cell | Evidence profile | Operational criterion | Total | Lingxi | Moatless | OpenHands | Example |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `FR+ / U` | 仅有测试文本 | 提到 oracle test，但没有可执行 run | 107 / 48.6% | 41 | 54 | 12 | `astropy__astropy-14369` |
| `FR+ / U` | 非目标 failure | 只有与 oracle tests 无关的 failing run | 90 / 40.9% | 0 | 16 | 74 | `django__django-12406` |
| `FR+ / U` | 目标执行不可判定 | 执行 target-related run，但无明确结果 | 8 / 3.6% | 5 | 0 | 3 | `django__django-11141` |
| `FR+ / U` | 目标执行通过 | target-related run 通过，未观察到目标 failure | 5 / 2.3% | 0 | 1 | 4 | `matplotlib__matplotlib-21568` |
| `FR+ / U` | 粗粒度相关 failure | 同 reference test file 失败，但未匹配 exact target | 5 / 2.3% | 0 | 5 | 0 | `django__django-11265` |
| `FR+ / U` | 真正复现目标 failure | exact `FAIL_TO_PASS` 被执行并失败 | 5 / 2.3% | 0 | 2 | 3 | `django__django-11400` |
| `FL+ / U` | 定位范围不完整 | 多文件 reference patch 只命中部分文件 | 78 / 28.9% | 22 | 25 | 31 | `astropy__astropy-14369` |
| `FL+ / U` | 只有文件级定位 | 命中 reference 文件，但无 hunk-level evidence | 76 / 28.1% | 34 | 7 | 35 | `astropy__astropy-13033` |
| `FL+ / U` | 定位成立但未转化为正确 patch | reference 文件与 changed-hunk evidence 均命中 | 116 / 43.0% | 21 | 56 | 39 | `astropy__astropy-8707` |
| `PC+ / U` | Patch scope 不完整 | 最终 patch 只覆盖部分 reference 文件 | 93 / 27.7% | 30 | 36 | 27 | `astropy__astropy-13398` |
| `PC+ / U` | 文件正确但内容偏离 | 覆盖全部 reference 文件，exact changed-line overlap 为 0 | 73 / 21.7% | 18 | 20 | 35 | `django__django-10999` |
| `PC+ / U` | Patch 内容不完整 | 覆盖全部 reference 文件，但只部分覆盖 changed lines | 165 / 49.1% | 53 | 62 | 50 | `astropy__astropy-13033` |
| `PC+ / U` | 放弃初始方向 | 最终 patch 不再包含 reference 文件 | 4 / 1.2% | 0 | 0 | 4 | `django__django-16502` |
| `PC+ / U` | 行相同但程序位置错误 | 覆盖全部 changed lines，但修改位于错误方法 | 1 / 0.3% | 0 | 1 | 0 | `pylint-dev__pylint-4970` |
| `PR+ / U` | Refinement scope 不完整 | 最终 patch 只覆盖部分 reference 文件 | 31 / 24.0% | 11 | 12 | 8 | `astropy__astropy-14369` |
| `PR+ / U` | 正向增量未形成正确状态 | 覆盖全部 reference 文件，exact changed-line overlap 为 0 | 34 / 26.4% | 7 | 10 | 17 | `django__django-11433` |
| `PR+ / U` | 正向增量仍不完整 | 覆盖全部 reference 文件，但只部分覆盖 changed lines | 63 / 48.8% | 16 | 21 | 26 | `astropy__astropy-13033` |
| `PR+ / U` | Refinement 后偏离 reference 文件 | 最终 patch 不含 reference 文件 | 1 / 0.8% | 0 | 0 | 1 | `django__django-16502` |
| `PV+ / U` | 验证范围不足 | 相关 scope 通过，但未执行 exact `FAIL_TO_PASS` | 117 / 39.9% | 0 | 90 | 27 | `astropy__astropy-13977` |
| `PV+ / U` | Exact target 与 evaluator 不一致 | exact `FAIL_TO_PASS` 通过，但官方仍 unresolved | 43 / 14.7% | 0 | 0 | 43 | `astropy__astropy-13033` |
| `PV+ / U` | Exact target 实际失败 | exact `FAIL_TO_PASS` 最终失败 | 22 / 7.5% | 0 | 15 | 7 | `astropy__astropy-8707` |
| `PV+ / U` | 相关 scope 实际失败 | 相关测试失败，且未执行 exact target | 27 / 9.2% | 0 | 17 | 10 | `astropy__astropy-13236` |
| `PV+ / U` | Exact target 结果不可判定 | 执行 exact target，但没有明确 pass/fail | 38 / 13.0% | 34 | 1 | 3 | `astropy__astropy-14598` |
| `PV+ / U` | 相关验证结果不可判定 | 有 target-related activity，但无明确结果 | 46 / 15.7% | 40 | 0 | 6 | `astropy__astropy-14365` |

这里最重要的不是列出更多“可能原因”，而是先识别反常是否真实。`FR+ / unresolved` 中，202/220（91.8%）没有形成可验证的目标 failure：107 条没有执行、90 条只出现非目标 failure、5 条目标执行反而通过。真正执行 exact `FAIL_TO_PASS` 并失败的只有 5 条。因此，大部分 `FR+ / unresolved` 是 outcome 判据过宽，而不是“成功复现后仍然修复失败”。

`FL+ / unresolved` 则呈现粒度递进：57.0% 只达到部分文件或文件级位置，43.0% 才具有 hunk-level evidence。这说明“命中 reference 文件”不是充分的 fault localization，定位质量需要同时考虑 scope 与 granularity。

`PC+ / unresolved` 的主要问题不是没有进入 reference 文件，而是 patch 内容和程序位置没有完整对齐。唯一完整覆盖 reference changed lines 的 unresolved 案例 `pylint-dev__pylint-4970`，将相同行插入了错误方法，进一步说明 changed-line overlap 也不是语义正确性的充分条件。

`PV+ / unresolved` 中只有 43/293（14.7%）能够确认 exact target 通过。其余样本要么验证范围不足，要么仍然失败，要么公开日志不可判定。因此，当前 `PV+` 更接近“进行了 target-related validation”，不能直接等同于“当前 patch 已通过目标验证”。公开数据没有统一的 evaluator-level per-test report，43 条 exact-target-pass 案例只能称为 evaluator gap，不能直接归因为 hidden-test failure。

## 3. 为什么 local outcome 为负，最终仍 resolved？

| Cell | Evidence profile | Operational criterion | Total | Lingxi | Moatless | OpenHands | Example |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `FR- / R` | Reproduction 不可观测 | 有 run，但公开输出无法形成明确结论 | 269 / 64.8% | 188 | 7 | 74 | `astropy__astropy-13453` |
| `FR- / R` | 跳过 reproduction | 没有可执行 reproduction run | 132 / 31.8% | 2 | 128 | 2 | `django__django-13741` |
| `FR- / R` | 未观察到 failure | 执行通过且没有目标 failure | 14 / 3.4% | 0 | 2 | 12 | `django__django-15268` |
| `FL- / R` | 定位隐含在首次 patch 中 | 显式 `FL-` 后，首次 patch 直接修改 reference 文件 | 243 / 88.4% | 106 | 63 | 74 | `astropy__astropy-13453` |
| `FL- / R` | 后续重新定向 | 后续 refinement 首次转向 reference 文件 | 9 / 3.3% | 1 | 5 | 3 | `django__django-16315` |
| `FL- / R` | 非 reference 实现 | resolved patch 不修改 reference 文件 | 23 / 8.4% | 9 | 11 | 3 | `django__django-12663` |
| `PC- / R` | 替代实现 | 最终 patch 不修改 reference 文件 | 36 / 72.0% | 12 | 14 | 10 | `django__django-11211` |
| `PC- / R` | 后续恢复 | 首次 patch 偏离，后续编辑转向 reference 文件 | 14 / 28.0% | 2 | 7 | 5 | `django__django-16315` |
| `PR- / R` | 累计 patch state 已经对齐 | 最后一次 `PR-` 前已有 `PC+` 或 `PR+` | 89 / 80.9% | 25 | 23 | 41 | `django__django-11138` |
| `PR- / R` | 非 reference 实现 | 此前无 aligned state，最终 patch 不修改 reference 文件 | 21 / 19.1% | 5 | 10 | 6 | `django__django-11211` |
| `PV- / R` | Proxy validation 通过 | 最后一次非目标或 proxy run 通过 | 139 / 55.6% | 0 | 23 | 116 | `django__django-10097` |
| `PV- / R` | 验证不可观测 | 没有可判定的 run result | 103 / 41.2% | 99 | 2 | 2 | `django__django-10880` |
| `PV- / R` | Proxy failure 与 evaluator 不一致 | 非目标 run 失败，但官方 resolved | 8 / 3.2% | 0 | 3 | 5 | `django__django-15278` |

`FL- / resolved` 中有 88.4% 在首次 patch 时已经修改 reference 文件。这里并不是 agent 在错误定位后偶然成功，而是定位行为隐含在 edit 中，当前 segmentation 没有将其记录为显式 `FL+`。

`PC- / resolved` 中有 72.0% 使用不修改 reference 文件的替代实现，说明 reference patch 不是唯一合法解。以 `django__django-11211` 为例，resolved patch 通过另一条实现路径满足官方评测，因此不能将“不重合 reference 文件”直接解释为 patch 错误。

`PR- / resolved` 暴露了另一种测量错位：89/110（80.9%）在最后一次负向 refinement 前已经具有 aligned patch。`PR-` 描述的是最后一次编辑增量，官方 resolved 描述的是累计 patch state，两者不是同一测量对象。因此，`PR` 的 local outcome 更适合评价 refinement 后的 patch state，而不是孤立评价最后一次 edit direction。

## 4. Matched-instance 检验

为降低任务难度的混杂影响，进一步选择同时存在 resolved 与 unresolved 轨迹的 87 个 instance，比较其最终 patch 与 reference patch 的结构关系。

| Feature | Matched instances | Mean `resolved - unresolved` | Resolved higher | Unresolved higher | Ties | Sign-test `p` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Reference-direction recall | 87 | +0.1592 | 55 | 24 | 8 | 0.0006 |
| Reference-file recall | 87 | +0.0896 | 16 | 5 | 66 | 0.0266 |

在控制 instance 后，resolved patch 的 reference-direction recall 仍显著更高，而 file recall 在 66/87 个 instance 中完全相同。这支持一个更具体的解释：最终成败主要区分于 patch 是否覆盖正确的修改语义和程序位置，而不是是否找到 reference 文件。

## 5. Findings

**Finding 1：首次 patch quality 是最强的局部分叉点。** `PC+` 与 `PC-` 的 RR 相差 0.360，且三个 agent 方向一致；matched-instance 结果进一步表明，真正产生区分的是修改方向和内容，而不是文件命中。

**Finding 2：不同 subtask 的 outcome discordance 来自不同机制，不能统一解释。** `FR/PV` 主要受执行范围和日志可观测性影响，`FL` 主要受定位粒度和隐式定位影响，`PR` 主要受增量 outcome 与累计 patch state 错位影响，`PC- / resolved` 还受到正确实现非唯一性的影响。

**Finding 3：local success 既非充分条件，也非必要条件，但两种不一致并不对称。** `+ / unresolved` 多由局部证据过粗或 patch state 不完整造成；`- / resolved` 则多由隐式行为、后续恢复和替代实现造成。因而，local outcome 应被解释为阶段性 evidence，而不能被当作 final correctness 的缩小版。

## 6. Validity notes

1. `PU` 的语义机制尚未完成双人编码。正式结果应区分 symptom restatement、correct fault model、missing repair constraint、incorrect causal hypothesis 和 no recorded understanding，并报告 Cohen's kappa。
2. Exact changed-line overlap 仅用于构造可复核的 patch profile，不被视为语义等价判据。
3. Lingxi 的公开轨迹通常不保存 stdout/stderr；Moatless 经常不执行显式 reproduction。跨 agent 的 `FR/PV` 差异同时包含 instrumentation 与 agent policy 差异。
4. OpenHands 的 498 个可用 final patches 中有 394 个由 event reconstruction 获得，正式报告前需要进行 patch provenance sensitivity analysis。
5. 本文件使用当前 `pre12_recompute.py` 从 1,500 条原始轨迹重新生成的同口径候选结果，不替换现有 `RQ1.md`。
