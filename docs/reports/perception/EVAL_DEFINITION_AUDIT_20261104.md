# 评价定义审计：四项分离、joint 正确拒绝与 3px/bearing 口径分离（2026-11-04）

> **状态：** BASELINE（定义审计已代码化并用只读重算验证；不重新判定旧实验，不表示能力达标）
> **来源章节：** docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §1–§2；configs/perception/landmark_training_plan_v2.json（metrics_definition）；configs/perception/landmark_final_eval_protocol_v1.json；task-20 交付要求
> **证据域：** 单元测试 + 只读已保存 predictions/labels 重算（无模型推理、无训练、无 Isaac）；旧 final 仅从已保存产物重算，未重跑模型
> **最后核对：** 2026-11-04

本文件把 post-evaluation 阶段的“评价定义审计”落成可执行代码、测试与只读重算证据，供 diag（task-13）消费。不改写旧 final 结果：旧 final 只执行过一次，本轮不做推理、不做解码、不重跑模型、不调阈值、不回调；重算输入是已保存的 predictions.jsonl（sha 8cdfe558…）与 labels（sha 7115ee04…）。

---

## 0. 结论摘要

| 项 | 结论 | 证据域 |
| --- | --- | --- |
| 四项分离已代码化 | presence / identity / reference-availability / localization 四个量各自带分子与分母；joint 拆成 localization 与 availability 两条分支 | 单元测试 45 条 PASS |
| joint 正确拒绝显式化 | final：joint 71/238 = localization 分支 62/218 + availability 分支（参考点不可见且正确拒绝）9/20；availability 分支记 joint-ok 但不进定位误差分母、单列计数 | 只读重算（279 帧） |
| 分母不丢项 | final 帧数对账 279/279；UNKNOWN/REJECTED 0；漏检 20 全部留在 recall 与 localization 分母；错误身份声明 0 | 只读重算 |
| 3px 2D 与 bearing 分开 | 3px 2D 通过 62/218（0.284）；同一批已发射 keypoint 中，87 帧 2D 失败但水平 bearing 通过（垂直误差主导）；bearing 等价通过 149/218（0.683），但这是不同量，不是同一门限的“通过” | 只读重算 |
| 消费者需求写清 | 下游消费的是图像 bearing（且不是世界方位/距离）；3px 是历史 2D 代理，单列保留；bearing 预算 3°/5° 为 PROPOSED_NOT_FROZEN | 文档 + 代码常量 |
| GT_UNOBSERVABLE | final 池 0 帧（分支未在 final 触发）；val 交叉校验 14 帧（FULL_OCCLUSION 11 + UNDECIDABLE 3）已排除分母且 0 claim / 0 keypoint 输出 | 只读重算 |
| 实现一致性 | val 数据集口径重算与已保存 val metrics 逐项一致（TP75/FP10/FN20/TN15、joint 55/95、GT_UNOBSERVABLE 14），证明重算实现可信 | 只读重算 |
| 对旧结论 | 旧 exploratory 3px 结果保留且不重新判定；新口径只增加分解，不宣布旧实验通过 | — |

---

## 1. 定义（可执行口径）

四类量彼此独立，任何一类都不得用另一类的分母“补数”：

| # | 量 | 适用帧（分母） | 成功/失败定义 | 明确排除 |
| --- | --- | --- | --- | --- |
| 1 | presence | N_pos = GT 可观测正例；N_neg = GT 可观测负例 | TP = 正例且检测（IoU≥tau_iou）；FN = 正例但未检测（含预测 UNKNOWN/REJECTED）；FP/TN 对称 | GT 不可观测（undecidable / 完全遮挡无可见框 / ambiguous）单列，不进四格与分母 |
| 2 | identity | claims（全部身份声明）/ N_pos / N_neg 三个分母 | 正确 claim / claims = precision；正确 claim / N_pos = recall；高置信误配 / N_neg | 单类 tower 输出不得无条件映射中央塔 ID；无相似结构负例时 identity 不可认证 |
| 3 | reference availability | N_avail = GT 参考点可见正例；N_unavail = GT 参考点标为不可见正例 | N_avail：正确输出 keypoint（≤tau_px）计数；N_unavail：正确声明 UNAVAILABLE 计数；在 N_unavail 上仍输出 keypoint = false-reference 语义错误 | 与定位误差分母分离：正确拒绝不产生定位误差样本 |
| 4 | localization accuracy | 通过率分母 = N_avail 全部适用帧（漏检/无 keypoint 也算未命中）；误差分布分母 = 已发射 keypoint 帧 | 3px 2D 通过计数；2D/水平/垂直像素误差与图像 bearing 误差分别统计 median/P90/max | 仅 GT 参考可见正例；GT 不可观测、参考不可见帧不评定位 |

joint 显式规则（两条分支，禁止混算）：

- localization 分支（GT 参考点可见）：joint-ok = presence TP + identity 正确 + 已发射 keypoint 误差 ≤ tau_px；
- availability 分支（GT 参考点不可见）：joint-ok = presence TP + identity 正确 + 正确声明 UNAVAILABLE（无 keypoint）；该分支计入 joint-ok 并单列，但永远不进 localization 误差分母，也不得用来放大 reference coverage；
- joint 分母 = 上述两条分支之和（GT 可观测且 bbox+reference 标签完整的正例）；joint 失败原因细分为 PRESENCE / IDENTITY / REFERENCE_LOCALIZATION / REFERENCE_AVAILABILITY。

误差口径（分开报告，禁止混用）：

- 历史 3 px 2D：√(dx²+dy²) ≤ 3 px，是标注噪声代理（盲复标 keypoint 差 max 2.236 px），保留为历史口径单列；
- 水平 bearing：|Δbearing| = |atan2(x_pred−cx, fx) − atan2(x_gt−cx, fx)|，单位度；这是下游区域方位实际消费的量；fx=160 时 1 px ≈ 0.358°，3 px ≈ 1.074°；
- 二者判定可翻转：垂直误差大而水平误差小的帧会“2D 失败、bearing 通过”。

---

## 2. 可执行入口（代码 / CLI / 输出）

| 入口 | 内容 |
| --- | --- |
| src/boom_birds/evaluation/landmark_eval_definitions.py | audit(rows) 四项分离 + joint 分支 + GT_UNOBSERVABLE + 分母损失审计 + placement 分离；placement_split(rows) 3px/bearing 翻转计数；consumer_requirement() 消费者需求常量；load_saved_predictions()/build_rows()/recompute() 从已保存文件重算 |
| src/boom_birds/evaluation/landmark_metrics.py（仅加性字段） | evaluate_frame 行新增 keypoint_emitted / gt_reference_available / gt_reference_unavailable / dx_px / dy_px / joint_branch；summarize() 语义不变，旧 metrics.json 口径不受影响 |
| scripts/recompute_landmark_metrics.py | 只读重算 CLI：--predictions --labels --split --output-dir [--tau-px --tau-iou --tau-conf --px-tolerance --drop-missing-predictions --overwrite]；输出 metrics.json（旧口径，可核对历史文件）+ audit.json（新口径）；默认拒绝覆盖（exit 3） |

示例（本轮实际运行；输入只读，输出到 ignored 目录，不覆盖旧 final）：

    & 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/recompute_landmark_metrics.py --predictions outputs/perception/final_exploratory_eval_20261104/predictions.jsonl --labels outputs/perception/final_exploratory_20261104/labels_v1.json --split test --output-dir outputs/perception/eval_definition_audit_20261104/final --tau-px 3.0 --tau-iou 0.3 --tau-conf 0.605476

    & 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/recompute_landmark_metrics.py --predictions outputs/landmark_train/runs/bounded_v2/seed1/eval_last/predictions.jsonl --labels outputs/perception/dev_annotations_20261104/labels_val.json --split val --output-dir outputs/perception/eval_definition_audit_20261104/val_dataset_scope --tau-px 3.0 --tau-iou 0.3 --tau-conf 0.605476 --drop-missing-predictions

--drop-missing-predictions 仅用于复现“原数据集评估范围”（当前 val 标签文件 163 帧、已保存 val 预测 134 帧；29 帧无预测被记录到 inputs.dropped_without_prediction 且不计分）。默认行为（不加该开关）会把缺预测的标签帧当作模型侧 UNKNOWN 保留在适用分母——对应“预测 UNKNOWN 不得从分母消失”。

机器可读摘要：[EVAL_DEFINITION_AUDIT_20261104.json](EVAL_DEFINITION_AUDIT_20261104.json)；完整重算输出（ignored）：outputs/perception/eval_definition_audit_20261104/{final,val_dataset_scope}/{metrics.json,audit.json}。

---

## 3. 旧 final 只读重算（279 帧；预测 8cdfe558… / 标签 7115ee04…）

### 3.1 四项分离

| 量 | 分子/分母 | 值 |
| --- | --- | --- |
| presence | TP218 / FP0 / FN20 / TN41；N_pos 238 / N_neg 41 | P 218/218=1.000；R 218/238=0.916；负例覆盖 41/41=1.000 |
| identity | claims 218，correct 218，wrong 0；claims on negatives 0；claims on GT_UNOBSERVABLE 0 | P 218/218=1.000；R 218/238=0.916；高置信误配 0/41 |
| reference availability | N_avail 218 / N_unavail 20；declared correct 20/20；false-reference 0/20；available emitted 181、not emitted 37 | declaration rate 20/20=1.000；false-reference rate 0/20=0.000；3px coverage 62/218=0.284 |
| localization | applicable 218 / emitted 181 / within 3px 62 | 3px 通过率 62/218=0.284；误差 n=181 |

localization 误差分布（分母 = 181 已发射，与 3px 通过率分母 218 不同，禁止混用）：

| 误差 | median | P90 | max |
| --- | --- | --- | --- |
| 2D 像素 √(dx²+dy²) | 3.72 px | 5.96 px | 8.44 px |
| 水平 /dx/ | 1.67 px | 3.74 px | 6.53 px |
| 垂直 /dy/ | 2.84 px | 5.28 px | 8.16 px |
| 图像 bearing（度） | 0.546° | 1.188° | 2.248° |

presence 漏检分解（20 FN，全部为 NOT_DETECTED）：参考可见正例 9、参考不可见正例 11（不可见原因全部为 REFERENCE_TOO_SMALL）。即漏检并非均匀分布，参考点不可见的远景帧贡献了 11/20。

### 3.2 joint 显式分解

| joint 项 | 分子/分母 | 值 |
| --- | --- | --- |
| joint 窄口径 | 71/238 | 0.298（旧值不变） |
| localization 分支 | 62/218 | 0.284（= 3px 定位通过数） |
| availability 分支（正确拒绝） | 9/20 | 0.450，单列，不进 localization 误差分母 |
| 失败原因 | PRESENCE 20 + REFERENCE_LOCALIZATION 147 | 147 = 119 错误 anchor（>3px）+ 28 检测到但无 keypoint |

对账：218 参考可见正例 = 62 ok + 147 reference 失败 + 9 presence 漏检；20 参考不可见正例 = 9 joint-ok + 11 presence 漏检；合计 joint 分母 238，joint-ok 71。availability 分支的 9 个 joint-ok 不是定位成功，旧口径把它们混在 71 里会造成误读。

### 3.3 分母损失审计与 GT_UNOBSERVABLE

- 帧数对账：presence 各类计数 TP218+FP0+FN20+TN41+GT_UNOBSERVABLE 0+NEGATIVE_UNOBSERVABLE 0 = 279 = 帧数（accounting_ok）。
- 预测 UNKNOWN/REJECTED：final 为 0（on_positive/on_negative/on_gt_unobservable 均 0）。
- 漏检 20：已计入 presence FN 与 localization applicable 未命中，不消失。
- 错误身份声明：0（若存在会计入 identity claims 分母与 identity recall 分母）。
- GT_UNOBSERVABLE：final 0 帧；该分支在 final 未被触发（只在 val 交叉校验中触发 14 帧：FULL_OCCLUSION 11 + UNDECIDABLE 3，0 claim、0 keypoint 输出、全部排除出四格与分母）。因此不能宣称“GT 不可观测处理已在 final 数据上验证”。

---

## 4. 旧/新口径差异与对旧 3px 结论的影响

| 项 | 旧（已保存 metrics.json） | 新审计口径 | 关系/影响 |
| --- | --- | --- | --- |
| reference coverage | 62/218=0.284 | 保留为 localization 的 3px 通过率；另单列 availability 声明 20/20、false-reference 0/20 | 3px coverage 不等于“参考可用性”；正确拒绝不可见参考点本身是成功但不是定位 |
| joint | 71/238=0.298；失败 presence20+reference147 | 71/238 = localization 62 + availability 9；147 = 119 错误 anchor + 28 无 keypoint | 旧数字不变；新增分支说明为什么 71 里含 9 个“正确拒绝” |
| anchor/bearing | anchor 全部 n=181 median 3.72px；bearing n=181 median 0.546° | 增加 dx/dy 分量、bearing 与 3px 的翻转计数 | 旧 3px 结论保留；但 3px 2D 不能当作 bearing 能力 |
| presence 漏检 | 20 FN | 拆成参考可见 9 + 参考不可见 11（REFERENCE_TOO_SMALL） | 漏检集中在小目标/参考不可见帧，影响 joint 的 presence 失败构成 |
| identity | P1.000（218 claims） | 不变；另列 wrong claims 0、claims on negatives 0 | 无 HN1 → 仍不作身份认证 |

对旧 3px 结论的影响（明确）：

1. 旧 exploratory 数字全部保留且有效于其原口径（3px 2D + 其分母），本轮不改写、不重算 final 模型、不重跑 final。
2. 旧 reference coverage 0.284 是“3px 2D 通过 / N_avail”，不是“参考可用性”、也不是 bearing 能力；新口径证明 87/181 已发射帧的 3px 失败来自垂直分量，而水平 bearing 在同等单轴角度容差内通过。
3. 旧 joint 0.298 不因本次审计改变；但必须写作“71/238 = 定位分支 62 + 正确拒绝分支 9”，不能把 71 全部解释为定位成功。
4. 不把任何新数字写成“达到计划门限/通过”：joint 0.298、3px 0.284 仍远离计划门（joint≥0.80、coverage≥0.90），bearing 相关数字是 PROPOSED 诊断量、未冻结、分母为已发射子集。

---

## 5. 3px 2D 与 bearing：消费者需求与翻转计数

消费者需求（consumer_requirement()）：下游区域方位消费的是图像 bearing（atan2(x−cx0, fx)，单位度）；它不是世界方位、不是距离、不是 ToF。3 px 是历史 2D 标注噪声代理（LEGACY_2D_PROXY_NOT_CONSUMER_UNIT），单列保留；PROPOSED bearing 预算为 aggregate median ≤3°、P90 ≤5°（PROPOSED_NOT_FROZEN，来源任务定义 §2.2，不是门限）。

final 翻转计数（判定阈值：3px 2D vs 3px 的单轴等价角度 1.074°，n=181 已发射）：

| 判定 | 计数 | 读法 |
| --- | --- | --- |
| both_ok | 62 | 3px 与 bearing 同时通过 |
| px_ok_bearing_fail | 0 | 水平超差但 2D 通过（当前容差下不会出现，保留通用性） |
| px_fail_bearing_ok | 87 | 2D 失败但水平 bearing 通过；垂直误差主导，3px 2D 与消费量不一致 |
| both_fail | 32 | 两者均失败 |
| bearing 等价通过 | 149/181 已发射 = 0.823；149/218 适用 = 0.683 | 每帧单轴等价规则，不是 aggregate 预算，也不是能力结论 |

误差分布（n=181）落在 PROPOSED 预算（median 3° / P90 5°）内：median 0.546°、P90 1.188° —— 这是已发射子集的 bearing 诊断，不含 37 帧无 keypoint 与 20 帧漏检；因此不能用它宣称参考可用性/定位达标。下游若需要 bearing，应把“可给出 bearing 的帧数 / 适用帧数”与 bearing 误差分布分开报告；若需要垂直方向信息（本项目当前区域方位不需要），才应使用 2D 误差。

---

## 6. 实现一致性校验（val 数据集口径重算）

- 输入：已保存 val 预测（sha a0df2a53…，134 帧）与当前 labels_val.json（sha 8c215597…，163 帧；训练时报告为 c3944e08… 134 帧 → 标签文件版本已前进，多出 29 帧 HN1/HN2，无对应预测）。
- 用 --drop-missing-predictions 复现原数据集范围（29 帧记录为 dropped，不计分）后，重算结果与已保存 val metrics 逐项一致：presence TP75/FP10/FN20/TN15、joint 55/95、GT_UNOBSERVABLE 14、reference 分母 41/54。这证明重算实现与旧评价脚本同口径。
- 该 val 交叉校验仅用于实现一致性，不作为新的 val 结论；val 的 HN1 不含“真实相似塔”（合成注入），identity 仍不可认证。

---

## 7. 测试与命令

    cd E:\isaac\proj_boom_birds
    & 'E:\isaac\env_isaaclab\Scripts\python.exe' -m pytest -q tests/evaluation/test_landmark_metrics.py tests/evaluation/test_landmark_eval_definitions.py
    # 45 passed（metrics 31 + audit definitions 14；本轮先写失败测试后实现）

- test_landmark_eval_definitions.py（14 条）：四项分离分母互不混用；availability 分支 joint-ok 单列且不进定位分母；UNKNOWN/漏检/错误身份留在分母；GT_UNOBSERVABLE 的 claim/keypoint 计数但不评分；placement 3px/bearing 翻转；分母对账；saved predictions+labels 重建；--drop-missing-predictions 范围复现；CLI 端到端与覆盖保护；真实已保存 final 重算（skipif 数据缺失）复现 218/0/20/41 与 71/238。
- test_landmark_metrics.py（31 条）：原 28 条口径回归 + 3 条加性字段回归（keypoint_emitted/gt_reference 标志/dx/dy/joint_branch）。
- 全量 pytest 当前工作树状态：tests/evaluation/test_landmark_posteval.py 因 diag 并行未完成而 collection error；tests/evaluation/test_landmark_onnx.py、tests/evaluation/test_landmark_dataset.py 有并行任务（license/datafreeze）未完成失败。这些均不在本任务写域；排除 diag 文件后全量为 1028 passed / 3 failed（均为其他 teammate 并行文件）。本任务目标文件 45/45 PASS。

---

## 8. 限制与不声明

- 单次 exploratory 池；final 只读一次，本轮未重跑模型/未重跑 final/未改阈值/未回调；
- final 池无已验证 HN1（相似结构）→ identity 不可认证；GT_UNOBSERVABLE 在 final 为 0，该分支只在 val 交叉校验触发；
- 标注为单代理 AGENT_PROXY + SELF_CHECKED，参考点 COLOR_CUE_ASSISTED（与绿色 cue 同源），非人工独立审查；
- bearing 是图像角，不是世界方位/距离；3px 为历史 2D 代理；PROPOSED bearing 预算未冻结，不是门限；
- 本审计是定义与测量口径证据，不是模型效果、板端、导航或任何 Gate 的验收；不改变许可状态。

---

## 9. 文件与证据

| 内容 | 路径 |
| --- | --- |
| 审计代码 | src/boom_birds/evaluation/landmark_eval_definitions.py |
| metrics 加性字段 | src/boom_birds/evaluation/landmark_metrics.py |
| 重算 CLI | scripts/recompute_landmark_metrics.py |
| 测试 | tests/evaluation/test_landmark_eval_definitions.py、tests/evaluation/test_landmark_metrics.py |
| 机器可读摘要 | docs/reports/perception/EVAL_DEFINITION_AUDIT_20261104.json |
| final 重算输出（ignored） | outputs/perception/eval_definition_audit_20261104/final/{metrics.json,audit.json} |
| val 数据口径重算（ignored） | outputs/perception/eval_definition_audit_20261104/val_dataset_scope/{metrics.json,audit.json} |
| 旧 final（只读，未改） | outputs/perception/final_exploratory_eval_20261104/{predictions.jsonl,metrics.json}（sha 8cdfe558… / a01c08ec…） |
| 旧 val metrics（只读，未改） | outputs/landmark_train/runs/bounded_v2/seed1/eval_last/metrics.json |
| 定义来源 | docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §2 |

本文件不修改合同、不更新 Gate、不改变旧 final 结论；若后续定义变化（例如冻结新的 bearing 门限或引入垂直误差需求），必须新编号并说明是否作废本次审计口径。
