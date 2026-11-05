# 交接：Two-class 身份通道与消费者验证（2026-11-05，STOP）

## 状态

- 开工 HEAD 47d1063（旧包封闭）；本包 two-class 新预注册、新预算、新快照；**结论 STOP**：R1/R2 pilot 均未过 pilot→3seed 门，未进入 3 seed，未触发 holdout。
- 预算：2 次 pilot（≤15ep），0 次完整训练；未推送、未接控制/PPO、未提升 Gate。

## 结果

| 配方 | 数据 | MS1 recall（identity/35） | tower recall（val/95） | official same-frame（val/identity） | 结论 |
| --- | --- | --- | --- | --- | --- |
| R1 | v6.1（class1 183） | 10/35=0.286 | 0.821 | 见 R2 口径裁定 | FAIL（MS1 recall） |
| R2 | v6.2（class1 285，近距 102） | 20/35=0.571 | 0.853 | 15/47=0.319 / 13/26=0.500 | FAIL（same-frame） |

- R1 原因：近距 MS1 OOD（训练 class1 高度≤114px≈2.6m vs identity 18/35>114px）；class1 head 6 张量重初始化+15ep 低 LR+warmup；训练 val class1=0 选模盲。
- R2 回退（已确认）：identity false-ref 0.077→0.500、consumer all-positive 0.698→0.434、val negative claims 2/39=0.051、GT_UNOBS improper 0→2。
- same-frame 官方定义：both-visible GT 帧中 class0 与 class1 均正确检出且正确分类；consumer-side claim 口径仅诊断（diag 裁定）。

## 数据/证据

- T30 two-class 373 帧（class0 232/class1 123/同框 39）+ v4.1 addendum 60 + T38 近距 MS1 102（class1 102，h 184–227px）；T38 discarded pilot 不登记。
- v6.1 canonical 3532df1a…（P2 eval union 225 帧，五类 139/9/73/38/39、train 重叠 0）；v6.2 canonical d8ad5ca0…（train 2396/val 1006，class1 285）；snapshot v7b 5daef982…（34 artifacts VALID）；泄漏/外部索引 PASS。
- P2 GT-poison PASS（225 帧 differing=0，模型 R1 last 508a0430…；R2 last 为 second-model 加固）；ONNX two-class 对 R2 pilot last（NOT_SELECTED_VALIDATED_PILOT_ONLY）导出+三路径 12 决策层 × 3 对 0 翻转（225 帧，ONNX 8bc01a40…），仅证明路径等价。
- 训练证据（ignored）：outputs/landmark_train/runs/two_class_pilot_v61/、two_class_pilot_v7b/；评测：outputs/perception/two_class_eval_20261105/。

## 下一版建议

1. 停止本版 two-class；若继续需新工作包/新预注册：same-frame 联合监督（双目标匹配、class-balanced 采样）、reference availability guard、negatives/GT_UNOBS claim 约束、class1 与 kpt 分支隔离。
2. 当前可交付基线：单类检测 + identity 显式 UNKNOWN + bearing-primary 诊断；不把 two-class raw/consumer 数字用于身份验收。
3. 认证级结论仍需独立人工标注、新 untouched holdout、板卡/真实相机（UNKNOWN）；许可分发另行决策。

## 证据入口

- 结果报告：docs/reports/perception/LANDMARK_TWO_CLASS_RESULTS_20261105.md
- 预注册/规范：configs/perception/landmark_two_class_protocol_v1.json、landmark_two_class_label_spec_v1.json
- 训练报告：training_20261104/TWO_CLASS_PILOT_20261105.md、TWO_CLASS_R2_PILOT_20261105.md、R2_SELECTION_RULE_20261105.md
- 评测：CONSUMER_EVAL_20261105.md、TWO_CLASS_EVAL_20261105.md、pilot_v61_canonical/、pilot_v7b_canonical/
- 审计/原因：posteval_20261104/TWO_CLASS_SEMANTICS_MASK_GT_REVIEW_20261105.md、TWO_CLASS_GT_ISOLATION_AUDIT_20261105_V2/V3
- 数据冻结：DATASET_FREEZE_V6_1_20261105.md、DATASET_FREEZE_V6_2_20261105.md、SNAPSHOT_V7B_RELEASE_NOTE_20261105.md
