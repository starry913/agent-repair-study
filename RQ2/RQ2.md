# RQ2：Subtask local outcome 之间有什么关系？

> 历史分析版本：本文件保留早期子任务边界下的统计与解释。当前结果请参阅 [RQ2-pro.md](RQ2-pro.md) 和 [data/pro/audit.csv](data/pro/audit.csv)。尤其注意：`PV+` 表示验证对象与参考证据对齐，并不表示实际测试通过；不要沿用本文件对正负验证反馈的解释。

给定相邻或连续子任务：

$$
s_i=\langle \tau_i,A_i,o_i\rangle,\quad s_{i+1}=\langle \tau_{i+1},A_{i+1},o_{i+1}\rangle
$$

RQ2 研究局部结果如何在修复过程中传递，即：

$$
P(o_{i+1}\mid \tau_i,o_i,\tau_{i+1})
$$

与 RQ1 不同，RQ2 不使用最终 resolved 结果，只分析 subtask local outcome 之间的条件分布。表中每个单元为 `n / conditional share`。

---

## RQ2.1：Failure Reproduction 的 local outcome 与后续 Fault Localization 有什么关系？

RQ2.1 使用所有相邻 `FR -> FL` 转移，共 6,175 次。

| Agent | `FR+ -> FL+` | `FR+ -> FL-` | `FR- -> FL+` | `FR- -> FL-` | `FR? -> FL+` | `FR? -> FL-` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Total | 2479 / 75.2% | 819 / 24.8% | 1553 / 61.7% | 965 / 38.3% | 249 / 69.4% | 110 / 30.6% |
| Lingxi | 1875 / 76.8% | 566 / 23.2% | 927 / 74.2% | 322 / 25.8% | 200 / 81.0% | 47 / 19.0% |
| Moatless | 212 / 70.2% | 90 / 29.8% | 385 / 60.8% | 248 / 39.2% | 41 / 58.6% | 29 / 41.4% |
| OpenHands | 392 / 70.6% | 163 / 29.4% | 241 / 37.9% | 395 / 62.1% | 8 / 19.0% | 34 / 81.0% |

**分析。**  
总体上，`FR+` 更容易传递到 `FL+`：`FR+ -> FL+` 为 75.2%，高于 `FR- -> FL+` 的 61.7%。这说明 failure reproduction 的局部结果会影响 fault localization 的质量；更可靠的 failure evidence 更容易导向 oracle-aligned fault target。

但这个传递并不是决定性的。即使 `FR-`，后续仍有 61.7% 的 `FL+`。这说明 agent 并不完全依赖一次成功复现；它仍可能通过 issue 描述、测试文件、错误文本或已有上下文继续定位到正确目标。

agent 差异非常明显。Lingxi 在 `FR-` 后仍有 74.2% 转向 `FL+`，说明它对不理想 reproduction 的恢复能力较强；OpenHands 的 `FR- -> FL+` 只有 37.9%，而 `FR- -> FL-` 达到 62.1%，说明它更依赖 reproduction 结果质量；Moatless 介于两者之间。也就是说，`FR -> FL` 的传递不是简单的“正向结果传染”，而是与 agent 的定位策略强相关。

---

## RQ2.2：Fault Localization 的 local outcome 与首次 Patch Construction 有什么关系？

对于 `FL -> PC`，如果只统计相邻转移，会丢弃大量在 localization 和 first patch 之间插入其他上下文动作的轨迹。因此，RQ2.2 将每条轨迹中的 first `PC` 与其之前最近一次 `FL` 配对。共得到 1,420 个配对；另有 73 条存在 first `PC` 但此前没有可配对 `FL`，不纳入本表。

| Agent | `FL+ -> PC+` | `FL+ -> PC-` | `FL+ -> PC?` | `FL- -> PC+` | `FL- -> PC-` | `FL- -> PC?` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Total | 935 / 91.2% | 74 / 7.2% | 16 / 1.6% | 302 / 76.5% | 90 / 22.8% | 3 / 0.8% |
| Lingxi | 302 / 90.7% | 22 / 6.6% | 9 / 2.7% | 135 / 81.8% | 29 / 17.6% | 1 / 0.6% |
| Moatless | 304 / 92.4% | 21 / 6.4% | 4 / 1.2% | 77 / 67.0% | 38 / 33.0% | 0 / 0.0% |
| OpenHands | 329 / 90.6% | 31 / 8.5% | 3 / 0.8% | 90 / 78.3% | 23 / 20.0% | 2 / 1.7% |

**分析。**  
`FL+` 对 first `PC+` 的传递最强。总体上，`FL+ -> PC+` 为 91.2%，而 `FL- -> PC+` 为 76.5%；同时，`FL- -> PC-` 上升到 22.8%。这说明 fault localization 是 first patch direction 的直接前置环节：当 agent 已经定位到 oracle-aligned target 时，首次 patch 很大概率也会进入正确方向。

但 `FL-` 并不必然导致 `PC-`。仍有 76.5% 的 `FL-` 最终接到 `PC+`，说明 first patch 可能受到最近一次 `FL` 之外的上下文影响，例如 earlier localization、problem understanding、测试线索或 patch 前的隐式推理。因此，这里的关系是强关联，而不是因果断言。

agent 层面，Moatless 对 `FL-` 最敏感：`FL- -> PC-` 为 33.0%，高于 Lingxi 的 17.6% 和 OpenHands 的 20.0%。这意味着 Moatless 的 first patch 更依赖最近一次 localization 的准确性；Lingxi 和 OpenHands 在 `FL-` 后仍更常生成 `PC+`，说明它们可能保留了更多跨片段上下文或存在额外纠偏路径。

---

## RQ2.3：Patch Validation 的 local outcome 如何通过 Patch Refinement 传递？

RQ2.3 分析 post-patch 阶段的局部结果传递。首先统计相邻 `PV -> PR`，共 2,244 次。

| Agent | `PV+ -> PR+` | `PV+ -> PR-` | `PV+ -> PR?` | `PV- -> PR+` | `PV- -> PR-` | `PV- -> PR?` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Total | 338 / 43.2% | 440 / 56.3% | 4 / 0.5% | 941 / 64.7% | 461 / 31.7% | 53 / 3.6% |
| Lingxi | 52 / 27.1% | 140 / 72.9% | 0 / 0.0% | 199 / 46.7% | 214 / 50.2% | 13 / 3.1% |
| Moatless | 100 / 34.6% | 189 / 65.4% | 0 / 0.0% | 203 / 66.6% | 96 / 31.5% | 6 / 2.0% |
| OpenHands | 186 / 61.8% | 111 / 36.9% | 4 / 1.3% | 539 / 74.4% | 151 / 20.9% | 34 / 4.7% |

**分析。**  
总体上，负向 validation feedback 更容易触发 oracle-aligned refinement。`PV- -> PR+` 为 64.7%，明显高于 `PV+ -> PR+` 的 43.2%。这说明 `PV-` 并不只是失败信号，它也能成为有效的 correction signal，推动 agent 对已有 patch 进行有方向的修正。

但 `PV+` 后继续进入 `PR` 时，风险更高。总体上，`PV+ -> PR-` 为 56.3%，高于 `PV+ -> PR+`。这说明当 validation 已经给出正向局部反馈后，继续修改 patch 并不一定有益，反而可能打开错误修改方向。

agent 差异同样明显。OpenHands 在 `PV-` 后最容易产生 `PR+`，达到 74.4%；Moatless 为 66.6%；Lingxi 只有 46.7%，并且 `PV+ -> PR-` 高达 72.9%。这表明不同 agent 对 validation feedback 的利用能力不同：OpenHands 更像 feedback-driven refinement，Lingxi 的 post-patch 修改更容易偏离 oracle direction。

进一步地，RQ2.3 统计连续三段 `PV -> PR -> PV`，共 2,186 次，用于观察 refinement 后下一次 validation 是否改善。

| previous `PV` | `PR` | next `PV+` | next `PV-` | next `PV?` | n |
| --- | --- | ---: | ---: | ---: | ---: |
| `PV+` | `PR+` | 227 / 67.2% | 111 / 32.8% | 0 / 0.0% | 338 |
| `PV+` | `PR-` | 136 / 34.3% | 204 / 51.5% | 56 / 14.1% | 396 |
| `PV-` | `PR+` | 284 / 30.2% | 656 / 69.8% | 0 / 0.0% | 940 |
| `PV-` | `PR-` | 114 / 25.4% | 325 / 72.5% | 9 / 2.0% | 448 |

**分析。**  
当已有 `PV+` 后，如果 refinement 仍是 `PR+`，下一次 validation 继续为 `PV+` 的比例达到 67.2%；但如果 refinement 是 `PR-`，下一次 `PV+` 下降到 34.3%，`PV-` 上升到 51.5%。这说明在已有正向验证状态下，refinement 的方向非常关键：错误 refinement 很容易破坏当前 patch 状态。

当已有 `PV-` 后，即使出现 `PR+`，下一次 `PV+` 也只有 30.2%，而 `PV-` 仍有 69.8%。这说明负向 validation feedback 具有较强粘性：一次 oracle-aligned refinement 不一定立刻转化为正向 validation。换句话说，`PV- -> PR+` 是必要的 recovery step，但不是充分条件。

因此，post-patch 阶段存在两种不同的局部传递机制：`PV-` 可以触发有方向的修正，但负向验证状态很难被一次 refinement 立即翻转；`PV+` 后继续 refinement 则需要更加谨慎，因为错误 refinement 会显著增加下一次负向 validation 的概率。

---

## RQ2 小结

| Finding | Evidence | Interpretation |
| --- | --- | --- |
| Failure evidence 会影响 localization，但不是决定因素 | `FR+ -> FL+` 为 75.2%，`FR- -> FL+` 仍有 61.7% | reproduction 结果会传递到 localization，但 agent 可通过其他上下文恢复 |
| Localization 是 first patch direction 的强前置环节 | `FL+ -> PC+` 为 91.2%，`FL- -> PC-` 升至 22.8% | first patch 很大程度上依赖 patch 前最近的 fault target |
| 负向 validation 能触发 correction | `PV- -> PR+` 为 64.7%，高于 `PV+ -> PR+` 的 43.2% | validation failure 可作为有效 refinement signal |
| post-patch 负向状态具有粘性 | `PV- -> PR+ -> PV+` 只有 30.2% | oracle-aligned refinement 不一定立刻修复 validation state |
| 正向 validation 后继续错误 refinement 风险高 | `PV+ -> PR- -> PV-` 为 51.5% | 已有正向反馈时应避免不必要的 patch reopening |

总体来看，local outcome 的传递不是简单的 `+` 传染或 `-` 传染。修复过程更像一组局部 handoff：`FR` 将 failure evidence 交给 `FL`，`FL` 将 fault target 交给 first `PC`，而 `PV` 通过 `PR` 重新打开 patch state。真正困难的是 post-patch 阶段：负向验证可以触发修正，但不容易被一次 refinement 消解；正向验证后的错误 refinement 反而可能破坏已有 patch 状态。
