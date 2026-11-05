| **two-class R2 pilot（v7b, selected last 64ac3822…）** | val last tower 81/95=0.853、MS1 21/47=0.447、claims 85/81/4、consumer same-frame 0.809、ref false-ref 0.037、bearing 0.802/1.969、all 0.645、neg claims 2/39、GT_UNOBS improper 2；identity last tower 43/44=0.977、MS1 20/35=0.571、claims 41/41/0、same 0.962、all 0.434、ref false-ref 0.500；**official same-frame 0.319/0.500 <0.60 → pilot gate FAIL**（train pilot_gate pass=false）；consumer 字段：all/false-ref/negative claims 有回退；**gate 口径已定稿为 official detector-side（0.319/0.500）→ FAIL**；consumer same-frame 0.809/0.962 仅 claim 条件正确率 |
| **two-class R1 pilot（最终记录，canonical eval docs+flags）** | val last tower 78/95=0.821、MS1 20/47=0.426、claims 76/76/0、同框 37/47=0.787、bearing 0.822°/1.901°、all 72/121=0.595、neg 39/39；identity last tower 43/44=0.977、MS1 10/35=0.286、claims 43/43/0、同框 26/26=1.000、all 37/53=0.698；**pilot gate FAIL，唯一硬失败 MS1 recall**；legacy pilot_v61_current 数字作废 | 冻结预测 + canonical eval docs（d6c6a252/7471c408/union a188fca7） || **two-class pilot（15ep seed0，当前快照）** | val last tower 78/95=0.821、MS1 20/47=0.426、claims 76/76/0、同框 37/47=0.787、bearing 0.822°/1.901°、all-positive 72/121=0.595；identity last tower 43/44=0.977、MS1 10/35=0.286、claims 43/43/0、同框 26/26=1.000、all 37/53=0.698；**pilot_to_three_seed gate FAIL（唯一硬失败：MS1 recall 0.286/0.200<0.50）** | 保存预测只读评测（当前 sha；旧快照 metrics 作废） |# Two-class 消费者评测（central tower vs MS1）：模块、同口径基线与待接入项（2026-11-05）

> **状态：** DRAFT / PILOT_EVALUATED（two-class 评测模块+CLI+测试可执行；冻结单类 v2 基线已评测；**15ep seed0 pilot 已出三口径 consumer 指标，pilot_to_three_seed gate FAIL（MS1 recall）**；正式/冻结数字仍 PENDING）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json（PRE_REGISTERED，sha b3701461…）；configs/perception/landmark_two_class_label_spec_v1.json；task-34；V2.2 §7.4–§7.8
> **证据域：** 单元测试（16 条）+ 62 帧 development identity pool 上冻结单类 v2 预测的只读重算（非 two-class 模型、非认证、非 untouched）；无训练、无 Isaac、无板端
> **最后核对：** 2026-11-05

本文件把消费者评测扩展到 **two-class**：class0 = central_tower，class1 = similar_structure_ms1；按预注册协议，class1 **永不**映射中央塔 landmark_id，class1 keypoint 恒不可用（不得用 bbox 中心代替）。GT 只用于打分，不用于生成身份 claim。

---

## 0. 结论摘要

| 项 | 结果 | 证据域 |
| --- | --- | --- |
| 协议加载 | two-class protocol sha b3701461…（PRE_REGISTERED_2026_11_05_BEFORE_TRAINING） | 代码 + 单测 |
| GT 隔离（T35 R1 修复） | decode_detections 只收 frame_id，不再接受 truth_row；新增 GT-poison（改乱 GT bbox/kpt/class/position → observations 逐字节一致）/rename 独立性/静态 guard（decode/adapter/infer 无 gt_*/ground_truth/oracle/target_world 访问）测试 | 单测（21 passed） |
| class1 范围 | class1 GT 仅 verified map-native MS1；合成 HN1/未验证/其他结构进 other_structures 单列（不进 class1 分母）；塔 claim 落在 other 上记 OTHER_STRUCTURE | 单测 + 推断 |
| **two-class pilot（15ep seed0）** | val_main last tower 74/95=0.779、MS1 18/47=0.383、claims 75/correct 73/wrong 2、同框 38/47=0.809、bearing 1.176°/2.743°、all-positive 70/121=0.579；identity last tower 40/44=0.909、MS1 9/35=0.257、claims 42/40/2（MS1_ONLY×2）、同框 22/26=0.846、all 35/53=0.660；**pilot_to_three_seed gate FAIL（MS1 recall<0.50；identity-last MS1-only 错误 claim 2>1；identity-best 同框 0.385<0.60）** | 保存预测只读评测（非冻结标签） |
| 模块/CLI | src/boom_birds/evaluation/landmark_two_class_eval.py + scripts/evaluate_landmark_two_class.py；--predictions 只读 / --model（CPU 推理）/ --baseline-predictions 同口径对照 | 单测 |
| 测试 | tests/evaluation/test_landmark_two_class_eval.py **21 passed**（先失败后实现） | 单测 |
| 冻结单类 v2 基线（62 帧，同口径） | class0 recall 35/44=0.795；**class1 recall 0/35=0.000**（单类无 class1 通道）；identity raw claims 35/35、wrong 0、FMR 0/9；MS1-only 帧 9、错误塔声明 0；同框目标选择 17/26=0.654；reference coverage 18/18、false-reference 6/26=0.231；bearing n=18 median 1.065°/P90 2.052°；all-positive consumer 29/53=0.547（strict UNKNOWN 下 0/53） | 只读 62 帧开发池 |
| two-class 模型数字 | **PENDING**（T33 训练/R1 pilot 尚未产出；标注/采集 T30–T32 未完成）；模块已按预注册字段接入，无需改评测口径 | — |
| val_main two-class 指标 | **PENDING**（val_main MS1 附加标注 T32 未完成；当前 val_main 只有 class0/负例标签） | — |
| T25 identity pilot | 按 annot 更正继续**排除**（PROVISIONAL_DIAGNOSTIC_ONLY，不进任何分母） | annot 回执 |

---

## 1. 评测口径（与协议一致）

### 1.1 两类与身份规则

- class0 central_tower：class 证据 + 绿色灯参考点；只有 class0 且 score≥tau_det 且**无类别冲突**（class0 与 class1 候选 IoU≥tau_conflict 时判 UNKNOWN）才可输出中央塔 landmark_id；多 class0 候选且 margin<tau_margin → MULTIPLE_CANDIDATES / UNKNOWN。
- class1 similar_structure_ms1：**永不**映射 landmark_id；keypoint 恒不可用（v=0），评测中 class1 若出现 keypoint 计为语义错误（class1_keypoint_emissions）。
- 解码不使用 GT 位置/oracle/文件名；GT 仅用于计分。

### 1.2 指标与分母

| 指标 | 定义/分母 |
| --- | --- |
| 两类混淆/召回 | 按 IoU≥tau_iou 对每类做 greedy 匹配：TP/FP/FN、precision/recall（分母=该类 GT 实例数）；混淆矩阵 gt_c_pred_c；**misclassified**（未匹配预测与另一类 GT 几何重合）单列 |
| 塔身份 claim | claims / correct / wrong；precision=correct/claims；recall=correct/observable tower-positive 帧；FMR=负例帧上的塔 claim / negatives 分母（含 MS1-only、negatives） |
| MS1 单独帧 | tower 不存在但 MS1 存在：帧数 + 其上错误塔 claim 数 |
| 同框选择率 | 同框（tower+MS1 同时可见且可判）分母：tower_selected / ms1_selected / not_selected；tower_selection_rate（选 MS1 = 错误；拒绝=UNKNOWN 不计正确但单列） |
| reference availability | N_avail（GT tower 参考可见）分母：coverage=正确 keypoint/ N_avail；N_unavail：correct refusal / false-reference 单列；class1 keypoint emission 单列 |
| bearing | 仅 GT tower 参考可见且发射 keypoint：水平图像 bearing 误差 median/P90/max 与 ≤3° 通过数（PROPOSED，非认证门限） |
| consumer success | all-positive（含 GT_UNOBSERVABLE/GT_UNCERTAIN，UNKNOWN/REJECTED 留分母）、observable-positive（排除不可观测/不确定）、reference-available、negatives 四套；success=类别正确+身份确认正确+reference 正确+bearing 达标+观测有效 |
| GT 不确定/完全遮挡 | GT_UNCERTAIN / GT_UNOBSERVABLE 帧不评定位、单列其塔 claim/keypoint/improper_claim/correct_abstention |
| 身份策略 | confirmed_only / raw_claim_upper_bound（未验证上界）/ strict_unknown（无身份通道→GT-present 成功=0），与单类评测同义，供同口径对照 |

### 1.3 同口径基线对照

compare_summaries() 固定比较：四套 domain 的 success 分子/分母/率与 delta、class0/class1 recall/precision、identity claims/wrong categories、same-frame 选择率、reference coverage/declaration/false-reference、confusion matrix；并检查双方分母一致（denominator_same）。只允许“同一 GT/分母、不同模型”。

---

## 2. 实现与入口

| 入口 | 内容 |
| --- | --- |
| src/boom_birds/evaluation/landmark_two_class_eval.py | load_protocol/merge_protocol；truth_from_two_class_annotation（label spec v1 格式，并兼容 train 侧 dsh.landmark_two_class_annotations.v1 的 frames[]/instances[]：bbox source-pixel xyxy、class0 keypoint 可为归一化 [0,1]、class1 keypoint null/v=0）；build_truth_from_identity_pool（现有 62 帧 v2.1 labels+decisions → class0/class1 GT）；decode_detections(detections, frame_id, protocol)（GT 隔离：只收 frame_id；class0 claim/class conflict/margin/class1 无 kpt）；infer_observations（仅用 frame_id+image path，GT 字段不参与推理）；evaluate_frame；summarize；compare_summaries；evaluate_rows/evaluate_saved |
| scripts/evaluate_landmark_two_class.py | --labels（two-class annotation doc）+ --predictions（two-class 或单类预测自适应）；--model + --images（ultralytics nc=2，CPU 默认；class1 keypoint 忽略）；--baseline-predictions（单类冻结预测同口径对照）；--identity-policy 三态；--tau-*；输出 two_class_metrics.json + rows.jsonl（model 模式另存 predictions.jsonl）；默认拒绝覆盖（exit 3） |
| tests/evaluation/test_landmark_two_class_eval.py | 21 条：协议/truth、GT 隔离（poison/rename/static guard）、class1-only-map-native（two-class 与现有 identity pool 两种来源）、解码（class0-only claim/class conflict/multi-candidate/class1 kpt 禁止）、两类混淆与误分类、MS1-only 错误 claim、同框选择率、reference/bearing、consumer 四域、GT uncertain/occluded improper claim、汇总与 confusion matrix、基线对照、CLI（含覆盖保护）、GT-poison/rename 独立性/静态 guard、class1-only-map-native/other 单列、真实 62 帧基线（skipif 缺数据） |

**GT 隔离结构性说明（T35 R1 修复）**：推理/解码路径（decode_detections / detections_from_ultralytics_result / infer_observations）只使用模型输出与 frame_id/image path；truth_row 只在 evaluate_frame 计分阶段出现。测试覆盖：把 GT bbox/keypoint/class/position 全部改乱后 observations 逐字节一致（GT-poison）、误导性文件名不影响 observations（rename 独立性）、静态 guard 断言推理/解码源码不含 gt_*/ground_truth/oracle/target_world 访问。

**独立复审（diag T35 V2，2026-11-05）**：R1 结论由 RISK_API_COUPLING 升级为 **PASS**，G1–G11 全 PASS；以本文件最终 sha（module db8ca0e8… / CLI 006c5e09… / tests febb847d…）复跑 21 passed。证据：TWO_CLASS_GT_ISOLATION_AUDIT_20261105_V2.json（sha baf08a2b…）、语义复审报告（sha 368b8c42…）；旧 V1（a5267429…）保留为决策记录。复审保留 2 条文档性注意：
1. 评测图像定位仍用 truth 的 image/frame_id 配对（部署侧用 payload.ref；属评测面，不涉及推理身份）；
2. 当前 GT-poison 测试用 stub Model；**P2 smoke 建议补一次“real v6 标签 + 冻结模型”的动态 poison 回归**（已列入 §4 待办）。

---

## 3. 冻结单类 v2 基线（62 帧开发池，同口径；只读）

输入：identity 62 帧 two-class truth（由 labels_identity_dev.json sha 79fd1745… + identity/identity_decisions.json 构建；PENDING_FROZEN 诊断用；tower GT 实例 44、MS1 实例 35、GT_UNOBSERVABLE 9、同框 26）；预测=冻结单类 v2（seed2/eval_last 在 identity 62 的只读 CPU 推理结果，sha 见 consumer eval 报告）。protocol sha b3701461…；tau_bearing 3°。

### 3.0 分母对齐（与 T35 审查一致；建议冻结进评测协议）

| 分母 | 值/定义 | 来源/口径 |
| --- | --- | --- |
| val_main tower observable | 95（present 121 − GT_UNOBS 26；GT_UNOBS 全部在 all-domain 单列） | val_main labels_val_validation163.json |
| consumer all-positive（val_main） | 121（GT present 全部，含 TINY/截断/参考不可用/不可观测；UNKNOWN/REJECTED 留分母） | 同上 |
| identity 池塔对象 / MS1 对象 | 44 / 35（verified map-native MS1：9 ms1-only + 26 同框） | identity labels + decisions（sha 79fd1745…） |
| 同框帧 | 26 | identity decisions（both_in_frame_*） |
| MS1-only 错误塔 claim | 帧级 9；对象级分母 35 | identity 池 |
| GT_UNOBS / GT_UNCERTAIN | 9 / 0（identity 池；all-domain 单列、不作负例、不评定位） | identity 池 |
| reference N_avail / N_unavail | 18 / 26（identity 池，GT tower 参考可见/不可用） | identity labels |
| class1 keypoint emissions | 单列（必须为 0；不得用 bbox 中心代替） | 模块 reference.class1_keypoint_emissions |
| TINY | 留 all-domain 单列（不以不可标注为由删除帧） | 协议 tiny_policy |

**B2 修复（canonical flags）**：two-class truth loader 现优先消费冻结 eval 文档的显式 flags（tower_observable/gt_unobservable/negative/ms1_only/same_frame）；一致性测试断言 frozen union loader counts == doc flags = **139/38/39/73/9（0 mismatch）**；identity 错误 claim 分母改为 **negatives ∪ ms1_only**（union 48；identity 9），不再用 tower_present 重算。pilot 派生 truth 无这些 flags，回退语义与旧版一致，已用新模块复跑确认 pilot 数字不变（summary sha da869af3…）。

### 3.1 两类召回与混淆（单类基线）

| class | gt_instances | tp | fp | fn | precision | recall |
| --- | --- | --- | --- | --- | --- | --- |
| 0 central_tower | 44 | 35 | 0 | 9 | 1.000 | 0.795 |
| 1 similar_structure_ms1 | 35 | 0 | 0 | 35 | — | **0.000** |

混淆矩阵 gt_0_pred_0=35、gt_1_pred_1=0；misclassified=0。**单类模型没有 class1 输出通道**，因此 class1 recall 恒为 0（这正是 two-class 要解决的问题；不是 two-class 模型的结果）。

### 3.2 身份、MS1、同框（raw_claim_upper_bound / 单类基线）

| 指标 | 值 |
| --- | --- |
| claims / correct / wrong | 35 / 35 / 0（raw upper bound；未验证） |
| identity precision / recall | 1.000 / 0.795（分母 44 observable tower） |
| false-match rate（负例分母 9） | 0/9 = 0.000 |
| MS1-only 帧 / 其上错误塔 claim | 9 / 0（单类未检到远景 MS1-only 帧） |
| class1_mapped_violations | 0 |
| 同框分母 / 选塔 / 选 MS1 / 未选 | 26 / 17 / 0 / 9；tower_selection_rate 0.654 |
| GT_UNOBSERVABLE（9 帧） | 0 claim / 0 kpt / 9 correct abstention / 0 improper |
| GT_UNCERTAIN（0 帧） | —（本池无 uncertain） |

strict_unknown 口径：claims 0（raw 35 记录）、同框选塔 0、all-positive/observable/reference 成功均 0/分母；negatives 9/9。

### 3.3 reference / bearing / consumer 四域（raw upper bound）

| 指标 | 值 |
| --- | --- |
| N_avail / coverage | 18 / 18 = 1.000 |
| N_unavail / correct refusal / false-reference | 26 / 20 = 0.769 / 6 = 0.231 |
| class1 keypoint emissions | 0 |
| bearing n / median / P90 / max | 18 / 1.065° / 2.052° / 2.207°（18/18 ≤3°） |
| all-positive success | 29/53 = 0.547 |
| observable success | 29/44 = 0.659 |
| reference-available success | 18/18 = 1.000 |
| negatives success（无塔 claim） | 9/9 = 1.000 |
| 2D 像素误差（仅诊断） | n=18 median 4.79 / P90 7.74 px |

解读：单类基线在 two-class 口径下的“成功”全部来自 class0 通道可用性与 reference/bearing，**class1 通道与同框选择率是结构性缺口**（同框 26 帧中 9 帧未选、class1 recall 0）；该数字仅作 two-class 模型的同口径基线，不能当能力结论。

---

### 3.5 数据风险与语义审查（T35 输入，供解释 future two-class 数字）

- v4.1 训练输入 MS1 风险：436 个实际训练输入中 69（15.8%）在投影上可见 MS1（38 同框遗漏 / 31 背景），若训练继续复用单类标签，会使 class1 recall / 同框选择率偏低；这是训练数据风险，不是模型结果（diag JSON V41_MS1_RISK_ACTUAL_INPUTS_20261105.json，sha dc61dad2…）。
- class1 语义：class1 只应 = verified map-native MS1；T31 允许合成注入属 HIGH 缺口；未验证/其他结构必须进入 other_structures 单列错误声明分母（本模块已实现），不得混入 class1 recall 分母。
- 同框完整性：以投影 gate 校验（datafreeze 侧负责，不在本评测模块内）；本模块只消费其冻结标签并在 same_frame 分母中报告选塔/选 MS1/未选。
- 语义审查 JSON sha dac596ed…、报告 sha 059f3475…（diag T35）。

### 3.6 two-class R1 pilot 最终记录（15ep seed0；canonical eval docs + canonical flags；2026-11-05）

> **作废声明（supersede）**：所有此前的 pilot 数字均不再是 R1 记录——① 12:15 旧预测快照已被 train 12:19:54 重写覆盖（旧 metrics 作废）；② 「pilot_v61_current」使用 legacy 派生 truth（非冻结 eval docs），其 same_frame 0.385、MS1-only 2/9 等在 current predictions 上不可复现，**整组作废**。以下为 R1 最终记录：current predictions + **canonical frozen eval docs**（val_main d6c6a252…、identity 7471c408…）+ **canonical flags**（module 183b6d22…）。

输入：pilot 冻结预测 val_last 96587369… / val_best a77eac9e… / id_last 81fac15e… / id_best 5daad2c7…；权重 last 508a0430…/best 6877e37b…；canonical eval docs：val_main 163 帧（tower_observable 95 / GT_UNOBS 29 / negatives 39 / same_frame 47 / ms1_only 0）、identity 62 帧（44/9/0/26/9；identity negatives=0，MS1-only 单列 9）；canonical union 225 帧（a188fca7…，FROZEN_P2_UNION，datafreeze T36）与 handoff cc59fcc9…。baseline 冻结单类 v2（val 92f6be54… / identity d08db699…）。

**三口径**：confirmed_only 与 raw_claim_upper_bound 数值相同（two-class identity 可用）；strict_unknown 下 GT-present 成功=0、claims=0（raw claims 记录）、negatives 39/39（identity negatives=0）。

| 指标（confirmed） | val last | val best | identity last | identity best |
| --- | --- | --- | --- | --- |
| tower recall（/95，/44） | 78/95=0.821（P0.867） | 73/95=0.768（P0.839） | 43/44=0.977（P0.896） | 38/44=0.864（P0.950） |
| MS1 recall（/47，/35） | 20/47=0.426（P0.500） | 14/47=0.298（P0.560） | 10/35=0.286（P0.909） | 7/35=0.200（P0.875） |
| identity claims/correct/wrong | 76/76/0（P1.000） | 73/73/0（P1.000） | 43/43/0（P1.000） | 38/38/0（P1.000） |
| 错误 claim 分母（negatives∪ms1_only） | 39（FMR 0） | 39（0） | 9（FMR 0） | 9（0） |
| MS1-only 错误塔 claim | —（val 无） | — | 0/9 | 0/9 |
| same-frame 正确选择 | 37/47=0.787 | 32/47=0.681 | 26/26=1.000 | 20/26=0.769 |
| reference coverage（/41，/18） | 33/41=0.805 | 35/41=0.854 | 17/18=0.944 | 18/18=1.000 |
| GT-unavail 拒绝 / false-ref（/54，/26） | 0.944 / 0.056 | 0.963 / 0.037 | 0.923 / 0.077 | 0.962 / 0.038 |
| bearing n / median / P90 / max | 33 / 0.822° / 1.901° / 2.378°（33/33） | 35 / 0.751° / 1.911° / 2.835°（35/35） | 17 / 1.194° / 4.178° / 4.383°（13/17） | 18 / 1.892° / 3.476° / 3.583°（16/18） |
| consumer all/observable/ref/negatives | 0.595/0.758/0.805/1.000（39） | 0.579/0.737/0.854/1.000（39） | 0.698/0.841/0.722/—（neg=0） | 0.660/0.795/0.889/— |
| GT_UNOBS improper | 0（29 abstain） | 0（29） | 0（9） | 0（9） |
| worst family（all-positive） | hn2 0/26 | hn2 0/26 | full_occlusion 0/9 | full_occlusion 0/9 |

**pilot_to_three_seed gate（canonical 口径，last / best）**：tower recall ≥0.70 **PASS**（0.821/0.768）；**MS1 recall ≥0.50 FAIL（identity 0.286/0.200；val 0.426/0.298 也低于 0.50）**；MS1-only 错误 claim ≤1 帧 **PASS**（0/0）；same-frame ≥0.60 **PASS**（val 0.787/0.681；identity 1.000/0.769）；identity precision ≥0.95 **PASS**（1.000/1.000）；consumer all-positive ≥0.30 **PASS**（0.595/0.579、0.698/0.660）；bearing median ≤3° **PASS**（0.822/0.751、1.194/1.892）；tower recall 不比单类基线 0.821 差 >0.08 **PASS**（0.000/−0.053）。→ **总体 FAIL，唯一硬失败 = MS1 recall**；按 on_fail reject recipe、停止，不进入 3-seed/holdout。

**与冻结单类同口径基线**：val baseline tower 0.821 / MS1 0 / claims 80（correct 76, wrong 4, P0.95）/ 同框 0.766 / ref 0.927/0.963/0.037 / bearing 0.483°,1.094° / all 0.612；identity baseline tower 0.659 / MS1 0 / claims 29（P1.0）/ 同框 0.423 / ref 1.0/0.923/0.077 / bearing 0.546°,1.550° / all 0.509。last 相对基线：val all −0.017、identity +0.189；tower val 0.000、identity +0.318；MS1 +0.426/+0.286；同框 +0.021/+0.577；identity FMR 0。

**consumer_development_to_holdout 字段（仅信息，pilot gate 未过不触发）**：val_main last confirmed — all-positive 0.595≥0.50、identity precision 1.000≥0.95、错误 claim 0/39=0（identity 0/9）、同框 0.787≥0.70、bearing 0.822/1.901（median≤3、P90≤5）、ref declaration 0.944≥0.50 且 false-ref 0.056≤0.10、worst-group hn2 0/26 vs baseline hn2 0/26；为 confirmed-identity 数（76 claims）。

**方法披露（keypoint 0,0 处理）**：train 已确认 [0,0] 为模型真实输出（kobj_conf 非零，非 sentinel）；主表按 GT-free 有效性过滤（越界/不在 bbox 0.5 扩展内=未发射）后解码；literal 不滤波敏感性：val false-ref 44/54、identity 26/26，all-positive 0.273/0.245。canonical eval doc 的 class0 keypoint 为归一化 [0,1]，loader 已按 image 尺寸还原像素（module 183b6d22…；修复前会误当像素导致 bearing 60°+，该 bug 已修并加测试）。

| pilot 输出（canonical） | 路径 |
| --- | --- |
| metrics/rows | outputs/perception/two_class_eval_20261105/pilot_v61_canonical/<dataset>_<policy>/{two_class_metrics.json,rows.jsonl} |
| 汇总 | pilot_v61_canonical/pilot_v61_canonical_summary.json（sha 6de15568…） |
| 输入/输出 sha | pilot_v61_canonical/pilot_v61_canonical_evidence_shas.json（sha f1f65e2b…） |
| 已作废 | pilot_v61_current/（legacy truth；旧快照 metrics）不再作为 R1 记录 |
### 3.7 two-class R2 pilot（v7b, 15ep seed0；canonical eval docs + flags；2026-11-05）

输入：R2 预测 val_last 52fa71f5… / val_best b6f29eb1… / id_last 595cc5a5… / id_best 6d87ae55…；权重 last 64ac3822…/best f55ec138…；R2 evidence two_class_pilot_seed0.json sha a6ef7fdb…（snapshot 76ba28b8…，train 报 93ee18fc…）；**冻结 r2_joint 选 last**（rule sha 4d486b3e：tower recall + MS1 recall 等权 → same-frame → name）。canonical eval docs 同 §3.6（d6c6a252…/7471c408…）。

| 指标（confirmed） | val last | val best | identity last | identity best |
| --- | --- | --- | --- | --- |
| tower recall（/95，/44） | 81/95=0.853 | 73/95=0.768 | 43/44=0.977 | 32/44=0.727 |
| MS1 recall（/47，/35） | 21/47=0.447 | 19/47=0.404 | **20/35=0.571** | 19/35=0.543 |
| claims/correct/wrong | 85/81/4（P0.953） | 73/72/1（P0.986） | 41/41/0（P1.000） | 31/30/1（P0.968） |
| 错误 claim 分母 / FMR | 39 / 2/39=0.051（NEGATIVE 2） | 39 / 0 | 9 / 0 | 9 / 0 |
| MS1-only 错误塔 claim | —（val 无） | — | 0/9 | 0/9 |
| consumer same-frame 选择 | 38/47=0.809 | 30/47=0.638 | 25/26=0.962 | 14/26=0.538 |
| ref coverage（/41，/18） | 38/41=0.927 | 36/41=0.878 | 18/18=1.000 | 17/18=0.944 |
| GT-unavail 拒绝 / false-ref（/54，/26） | 0.963 / 0.037 | 0.981 / 0.019 | **0.500 / 0.500（13/26）** | 1.000 / 0.000 |
| bearing n / median / P90 / max | 38 / 0.802° / 1.969° / 2.492° | 36 / 0.573° / 2.015° / 2.756° | 18 / 1.043° / 4.318° / 4.374° | 17 / 1.071° / 3.506° / 3.749° |
| consumer all/observable/ref | 0.645/0.821/0.927 | 0.579/0.737/0.878 | 0.434/0.523/0.611 | 0.491/0.591/0.667 |
| GT_UNOBS improper | **2（29 帧）** | 1 | 0（9） | 0（9） |
| worst family | hn2 0/26 | hn2 0/26 | both_scale_lateral 0/8 | full_occ 0/9 |

**pilot_to_three_seed gate（选 last；official detector-side 与 consumer 两套 same-frame 定义并列）**
1) tower recall ≥0.70：0.853 PASS；2) MS1 recall（identity）≥0.50：**0.571 PASS（R1 0.286 → 修复）**；3) MS1-only 错误 claim ≤1：0/9 PASS；4) same-frame ≥0.60：**official detector-side val 15/47=0.319、identity 13/26=0.500 → FAIL**（consumer evaluator 的“塔 claim 正确选择”为 val 0.809、identity 0.962，属不同指标）；5) identity precision ≥0.95：identity P1.000 PASS（val claim P0.953）；6) consumer confirmed all-positive ≥0.30：val 0.645、identity 0.434 PASS（consumer 条件由 evaltool 填）；7) bearing median ≤3°：0.802/1.043 PASS；8) tower 不比单类基线 0.821 差 >0.08：+0.032 PASS。→ **official pilot gate FAIL（唯一硬失败：official same-frame 0.319/0.500 <0.60）**；另 trainer-side pilot_gate JSON 亦 pass=false（same_frame 条件 false，consumer condition 原 pending，现由本文件填 PASS）。

**口径说明（lead 2026-11-05 定稿，后续版本不得切换）**：pilot gate 第 4 条的 same-frame 固定为 **official detector-side 双匹配**（同一帧内 class0 塔检测与 GT 塔 IoU≥0.3，且全部 class1 MS1 GT 均被 class1 检测 IoU≥0.3 匹配；即 train evaluate_two_class 定义）。consumer evaluator 的“塔 claim 正确选择率”（val 0.809、identity 0.962）是 **claim 条件正确率**，仅作诊断对照，**不得替代** official same-frame，也不得用于事后切换口径。

**跨版本说明（train 确认）**：R1 的 FAIL 结论与口径无关——R1 当时 gate 用 consumer 口径，但按同一 canonical detector-side 复算 R1 last 也 <0.60（val 0.340、identity 0.385），且 R1 MS1 recall 0.257 本来就是硬失败；R2 在 detector-side 下 MS1 recall 修好但 same-frame/参考通道回退 → 同样 FAIL。

**R1 与 R2 的 official same-frame 并列（同一 canonical evaluator 复算 R1 预测）**：
| 版本（last） | val official same-frame | identity official same-frame |
| --- | --- | --- |
| R1（预测 96587369…/81fac15e…） | 16/47=0.340 | 10/26=0.385 |
| R2（预测 52fa71f5…/595cc5a5…） | 15/47=0.319 | 13/26=0.500 |
（best：R1 val 13/47=0.277、identity 6/26=0.231；R2 val 14/47=0.298、identity 9/26=0.346。）
→ 按 official 定义，R1 与 R2 均 <0.60。**R1 当时的 pilot gate 表使用 consumer 口径（val 0.787、identity 1.000）**，因此 R1 的“gate 通过/失败”叙述与 official 定义不直接可比；本文件以 official 定义作为跨版本唯一 gate 口径，R1 的 consumer 数字仅保留为 claim 条件正确率。

**R1 → R2 对照（selected last，canonical evaluator）**：val tower 0.821→0.853、MS1 0.426→0.447、same 0.787→0.809、all-positive 0.595→0.645、negative claims 0→2（FMR 0→0.051）、GT_UNOBS improper 0→2；identity tower 0.977→0.977、MS1 0.286→0.571、same 1.000→0.962、all-positive 0.698→**0.434**、ref false-ref 0.077→**0.500**。→ R2 修好 MS1 recall，但**identity 参考通道与 negative/GT_UNOBS 声明出现回退**。

**R2 回退项（selected last；consumer canonical 口径）**：
1. identity GT-unavailable 26 帧：false-reference **13/26=0.500**、declaration 0.500 → consumer holdout false-ref ≤0.10 不满足；
2. identity consumer all-positive 0.698→**0.434**（reference-available success 0.611，6/18 帧 bearing>3°）；
3. val negatives 错误 claim **2/39=0.051**（>0.05），错误类别 NEGATIVE 2；
4. val GT_UNOBS 29 帧上 **improper claim 2**（GT 完全遮挡/不可判定时不应声明身份）；
5. R2 official same-frame 0.319/0.500（R1 official 0.340/0.385）→ 两版均未过 0.60；**R2 版本停止**，不进入 3-seed，不采 holdout。

**consumer_development_to_holdout 字段（仅信息；pilot gate official FAIL 不触发）**：val_main last — all-positive 0.645≥0.50 PASS；identity precision 0.953≥0.95 PASS（identity 集 1.0）；MS1/负例错误 claim 2/39=0.051 **FAIL（>0.05）**；same-frame 0.809≥0.70 PASS；bearing 0.802/1.969 PASS；ref declaration 0.963≥0.50、false-ref 0.037≤0.10 PASS；worst-group hn2 0/26（baseline 0/26）PASS。identity last — all-positive 0.434≥0.30（trend）、错误 claim 0/9、same 0.962、bearing 1.043/4.318（P90≤5）PASS；**ref declaration 0.500 且 false-ref 0.500 → FAIL（>0.10）**。→ 即使 official same-frame 口径修正为 consumer 定义，consumer holdout 的 false-reference 条件当前也不满足。

| R2 输出 | 路径 |
| --- | --- |
| metrics/rows | outputs/perception/two_class_eval_20261105/pilot_v7b_canonical/<dataset>_<policy>/{two_class_metrics.json,rows.jsonl} |
| 汇总/证据 | pilot_v7b_canonical/pilot_v7b_canonical_summary.json（sha a0e2cf06…）、pilot_v7b_canonical_evidence_shas.json（sha 5c0bcb1f…） |
| train 侧证据 | two_class_pilot_seed0.json（sha a6ef7fdb…）、run_snapshot.json（sha 76ba28b8…） |
| P2 poison（R2 last 模型，可选归档） | p2_smoke/run_r2_last_union_a188fca7_v4/poison_smoke_evidence_v3.json（sha c40db8e4…）：canonical union a188fca7、model 64ac3822、module 183b6d22、225 帧、differing_frames=[]、coverage 139/38/39/73/9、PASS |
| 最终 R2 记录 JSON | docs/reports/perception/TWO_CLASS_EVAL_R2_20261105.json（本文件定稿后生成；含 gate 口径、两套 same-frame、回退项与全部证据 sha） |

## 4. 待接入项（two-class 模型/标注到位后）

| 项 | 状态 | 接入方式 |
| --- | --- | --- |
| two-class 训练/标注数据（T30–T32） | PENDING | 标注文档按 label spec v1（instances[class,bbox,keypoint,v,reference_available]）→ truth_from_two_class_annotation 直接消费 |
| two-class R1 pilot/三 seed（T33） | **pilot 已评测；pilot gate FAIL → 按协议 reject/stop，不进入 3-seed** | 已用 --predictions（train 保存 jsonl）；三口径输出见 §3.6 |
| val_main MS1 附加标注 | **已有 labels_val_main_ms1（sha 05670eae…）**；pilot 用 val163+ms1 派生合并 truth（a4334576…） | 冻结 v6.1 merged eval doc（单一文档+5 类 coverage+sha+不重叠审计）仍由 datafreeze 产出，用于 P2 smoke/正式 |
| 冻结单类 v2 同口径对照 | 已支持 | --baseline-predictions（单类 metric predictions 自适应为 class0-only） |
| ONNX/raw-ORT two-class 对齐 | 后续任务（P8/T29 类） | 不在本任务范围 |
| P2 smoke：动态 GT-poison 回归 | 建议新增（diag 复审保留项） | real v6 标签 + 冻结 two-class 模型，改乱 GT 后 observations 不变；在 P2 冻结 sha 下执行 |
| T25 identity pilot | 排除 | PROVISIONAL_DIAGNOSTIC_ONLY，不进分母 |

---

## 5. 与 consumer holdout gate 的关系（本任务不判定）

two-class 协议 stage_gates 的 consumer 条件复用本模块字段。**pilot 阶段已判：pilot_to_three_seed gate FAIL（唯一硬失败：MS1 recall identity 10/35=0.286、val 20/47=0.426，均 <0.50；其余条件 PASS）**；按 on_fail 停止该 recipe，不进入 3-seed、不触发 consumer_development_to_holdout（holdout 未采）。本文件不宣布 holdout 通过，也不把 pilot consumer 数字当认证。

---

## 6. 限制与不声明

- 62 帧 identity 与 val_main pilot truth 均为派生 two-class truth（分别由 v2.1 labels+decisions、val163+labels_val_main_ms1 构建），非冻结 v6.1 merged eval 标签、非 untouched；不得用于认证或阈值冻结。
- class1 GT 仅覆盖已验证 map-native MS1（含 MS1-only 9 帧 + 同框 26 帧），不含开放集/未验证 confuser；协议明确 class1 不是开放集 catch-all。
- 单类基线 class1 recall=0 是结构性（无 class1 输出），不是性能退化；two-class pilot 数字已出（§3.6），但为派生标签 + 保存预测、非冻结正式评测；pilot gate FAIL。
- GT 只用于打分；two-class 解码不使用 GT 位置/oracle/文件名。T25 pilot 排除。
- bearing 是图像角（非世界方位/距离）；3° 为 PROPOSED；无板端/RKNN/真实相机；无控制/PPO；不提升 Gate；许可仍为内部有界研究。

---

## 7. 证据路径

| 内容 | 路径 |
| pilot keypoint 语义披露 | §3.6：train 已确认 [0,0] 为模型真实输出（非 sentinel），GT-free 有效性过滤必要且正确；literal 敏感性 false-ref val 44/54、identity 26/26 |
| **P2 GT-poison smoke（v4 canonical union）** | **PASS**：datafreeze canonical union（status FROZEN_P2_UNION，created_by datafreeze T36）225 帧=val_main 163（d6c6a252…）+identity 62（7471c408…），union sha **a188fca7…**、handoff cc59fcc9…；coverage doc flags **139/38/39/73/9** 五类>0；模型 last 508a0430…（nc=2）；real/poisoned observations 逐帧 canonical sha 全相同，differing_frames=[]；225/225 图像可解析、144 个 distinct observation sha；环境 python3.11.9/torch2.7.0+cu128/ultralytics8.2.0；证据 p2_smoke/run_last_union_a188fca7_v4/poison_smoke_evidence_v3.json（schema v4，sha 5a77d689…，module 183b6d22…/tests a101eb43…）；harness v4 58985ae0…；V3 审计记录 6686019c…（B1/B2 关闭）。**B1 修复**：预跑版 union 7bb785fa 被 datafreeze canonical union 替换，已用 a188fca7 重跑绑定，非事后改字段。 |
| --- | --- |
| 协议/标签规范 | configs/perception/landmark_two_class_protocol_v1.json（sha b3701461…）、landmark_two_class_label_spec_v1.json |
| 模块/CLI/测试 | src/boom_birds/evaluation/landmark_two_class_eval.py、scripts/evaluate_landmark_two_class.py、tests/evaluation/test_landmark_two_class_eval.py（16 passed） |
| 62 帧 two-class truth（派生，ignored） | outputs/perception/two_class_eval_20261105/identity62_two_class_truth.json |
| 单类基线同口径输出（ignored） | outputs/perception/two_class_eval_20261105/identity62_single_class_{raw_claim_upper_bound,strict_unknown}/{two_class_metrics.json,rows.jsonl} |
| GT 隔离审计（diag，旧 module sha 8ba54cfb 时点） | docs/reports/perception/posteval_20261104/TWO_CLASS_GT_ISOLATION_AUDIT_20261105.json（sha a5267429…）；本文件修复后模块 sha db8ca0e8…，P2 冻结时请以最终 sha 重跑该审计 |
| v4.1 MS1 训练风险 | V41_MS1_RISK_ACTUAL_INPUTS_20261105.json（sha dc61dad2…） |
| 语义审查 | diag T35 semantic JSON（sha dac596ed…）、报告（sha 059f3475…） |
| P2 smoke 输入/证据 | p2_smoke/：labels_union_eval_frozen.json（7bb785fa…，源 d6c6a252/7471c408）、run_last/poison_smoke_evidence_v3.json（c7ce5d99…）；handoff two_class_eval_handoff_v1 sha cc59fcc9…（v6.1 freeze 记录；datafreeze 消息里的 65cd1a89 为旧/笔误，以 freeze 记录为准） |
| pilot 评测输入/输出（当前快照） | pilot_v61_current/：val_main_two_class_pilot_truth.json（a4334576…）、identity62_two_class_truth.json（833c4b85…）、<dataset>_<policy>/{two_class_metrics.json,rows.jsonl}、pilot_two_class_summary.json（c2a6302f…）、pilot_v61_evidence_shas.json |
| 当前文件 sha（2026-11-05，B1/B2 修复后） | module **183b6d22…**、CLI 006c5e09…、tests **a101eb43…**（B2 canonical-flags + 归一化 keypoint 修复）；P2 harness v4 58985ae0…；report 见本文件 |
| 单类基线预测来源 | outputs/perception/consumer_eval_20261104/identity_A3seed_selected_confirmed_only/predictions.jsonl（本报告使用 identity_baseline 同模型口径；见 metrics inputs sha） |

当 two-class 模型/标注到位，重跑命令（无需改口径）：

    & 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/evaluate_landmark_two_class.py --labels <two_class_labels.json> --predictions <two_class_predictions.jsonl> --protocol configs/perception/landmark_two_class_protocol_v1.json --identity-policy confirmed_only --baseline-predictions outputs/perception/consumer_eval_20261104/identity_A3seed_selected_confirmed_only/predictions.jsonl --output-dir outputs/perception/two_class_eval_20261105/<run> --overwrite