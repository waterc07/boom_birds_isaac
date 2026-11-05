# Two-class 身份通道与消费者验证：R1/R2 pilot 结果与停止结论（2026-11-05）

> **状态：** NEGATIVE-RESULT / STOP（内部有界研究；两套预注册配方 pilot 均未过 pilot→3seed 门；非认证）
> **来源章节：** V2.2 §7.4/§7.5/§7.7/§9.1/§20.9/§20.11；预注册 configs/perception/landmark_two_class_protocol_v1.json（含 R2 amendment）
> **证据域：** 隔离 venv 训练 + canonical 评测文档（val_main 163 + identity 62，225 帧 union）+ 主机 ONNX/poison 证据；无板端/实机/SITL/HIL
> **最后核对：** 2026-11-05

本工作包（新预注册、新预算、新快照）为“two-class 身份通道（中央塔 vs 已验证 map-native MS1）+ 消费者验证”。两套配方各跑一次 ≤15ep pilot：**R1（直接 two-class 微调）MS1 recall 0.286 <0.50 → 拒绝；R2（加近距 MS1 训练族）MS1 recall 修复到 0.571，但 official same-frame 0.319/0.500 <0.60 且 consumer holdout 字段回退（identity false-ref 0.500、all-positive 0.434）→ 拒绝。** 按协议不进入 3 seed、不触发新 holdout（v3 保持 NOT_TRIGGERED）；本版 two-class 实验停止，交付失败分析与路线建议。

## 0. 结论摘要

| 项 | 结果 |
| --- | --- |
| 接手清理 | 旧包 47d1063 封闭；CURRENT_STATUS/AGENTS 增加日期化“当前状态”，修正历史“训练 BLOCKED/下一项”表述（历史保留） |
| 预注册 | 新 two-class 协议（类别语义、标签规范、工程 smoke / pilot→3seed / consumer holdout 三级门、预算、R1/R2 配方、R2 选模规则）先于训练冻结 |
| 数据 | T30 373 帧（class0 232/class1 123/同框 39）+ v4.1 addendum 60 帧 class1 + T38 近距 MS1 102 帧（class1 102，h 184–227px）；val = val_main 163（MS1 47）+ identity 62（MS1 35/同框 26/MS1-only 9/GT_UNOBS 9） |
| 冻结 | v6.1（train 2288/val 1006）P2 eval union 225 帧；v6.2（train 2396/val 1006，class1 285）；snapshot v7b（34 artifacts，全 VALID）；泄漏审计 0 |
| 工程 smoke | nc=2 loader、class1 kpt v=0 loss mask PASS、tiny overfit、推理无 GT、单类接口兼容、P2 GT-poison PASS（225 帧 differing=0） |
| R1 pilot（v6.1，15ep seed0） | MS1 recall identity 10/35=**0.286**、val 20/47=0.426 <0.50 → **pilot gate FAIL**（唯一硬失败）；其余 7 条 PASS |
| R1 原因 | 近距 MS1 训练 OOD：class1 训练 bbox 高度 max 114px≈2.6m vs identity 18/35>114px；class1 头 6 项重初始化 + 15ep warmup + 训练 val class1=0 → 选模盲 |
| R2 pilot（v6.2+近距 MS1，15ep seed0） | MS1 recall identity **0.571（修复）**、tower 0.853；但 **official same-frame val 15/47=0.319、identity 13/26=0.500 <0.60** → **pilot gate FAIL** |
| R2 回退 | identity false-reference 0.077→**0.500**；consumer all-positive 0.698→**0.434**；val negative claims 0→2/39=0.051；GT_UNOBS improper 0→2 |
| 预算 | 2 次 pilot（≤15ep）；**0 次完整训练**；未进入 3 seed；未触发 holdout（v3 SPEC_FROZEN_NOT_TRIGGERED） |
| 结论 | 停止 two-class 版本；单类 + 身份 UNKNOWN 的现状仍是唯一可交付基线；two-class 需重新设计 same-frame 监督/参考通道后再预注册 |

## 1. 阶段门与预注册

- 三级门（先于结果冻结）：
  1. 工程 smoke（不评价效果）：nc=2 loader、class1 keypoint v=0 且 loss mask、tiny overfit、推理无 GT、单类接口兼容、测试通过。
  2. pilot→3seed：tower recall≥0.70；MS1 recall≥0.50；MS1-only 错误塔 claim≤1/9；official same-frame≥0.60；identity precision≥0.95；consumer confirmed all-positive≥0.30；bearing median≤3°；tower recall 不比单类 0.821 差>0.08。
  3. consumer development→holdout：all-positive≥0.50；identity precision≥0.95 且错误 claim≤0.05；same-frame≥0.70；bearing median≤3°/P90≤5°；ref 拒绝≥0.50/false-ref≤0.10；worst-group 不差>0.05。
- 预算：最多 2 套配方，各 1 次 ≤15ep pilot；优胜者 3 seed ≤60ep；完整训练 ≤4 次；不追加候选/seed/epoch。实际：R1/R2 各 1 次 pilot，0 次完整训练。
- R2 amendment（先于 R2）：唯一变量=加入近距 MS1 训练族；选模规则 r2_joint（tower recall+MS1 recall 等权→same-frame tie）冻结（sha 4d486b3e…，approve 记录 d26aacae…）。

## 2. 数据（two-class）

| 数据块 | 帧/组 | 内容 |
| --- | --- | --- |
| T30 two-class 训练批 | 373 pool（8 新族） | class0 232、class1 123、同框 39；class1 高度 42–114px |
| v4.1 addendum | 60 帧 | 同框/空帧补 class1；高度 20–69px |
| T38 近距 MS1 | 102（2 新族） | class1 102，高度 184–227px，塔不在 FOV；discarded pilot 不登记 |
| val_main | 163 帧 | tower 95 observable；MS1 47（同框）；negatives 39；GT_UNOBS 29 |
| identity | 62 帧 | tower 44、MS1 35、同框 26、MS1-only 9、GT_UNOBS 9 |

- 标签规范：class0=central_tower（绿顶灯 kpt v=1/0）；class1=map-native MS1（kpt 恒 v=0，禁止 bbox 中心替代）；同框必须标全部可见实例；class1 不映射中央塔 ID；不把合成/未知结构当 class1（记 other_structures）。
- 冻结与快照：v6.1 canonical 3532df1a…（含 P2 eval union 225、五类 139/9/73/38/39、与 train 重叠 0）；v6.2 canonical d8ad5ca0…（train 2396/val 1006；class1 285）；snapshot v7b sha 5daef982…（34 artifacts，dry verify VALID）；泄漏审计/外部索引 PASS。
- 标注性质：投影/几何 draft+agent 目视复核，非独立人工 GT；TINY/截断/GT_UNOBS 保留在 all-domain，不删难例。

## 3. 实现与工程验证

- 两-class 训练 CLI/转换（nc=2、names、kpt_shape[1,3]）；class1 keypoint v=0 且 loss mask 验证（独立复算 PASS）；base 单类权重 397 张量中 391 转移，仅 6 个 final cls conv 重初始化。
- 评测：canonical flags（tower/GT_UNOBS/negative/MS1-only/same-frame）单一分母；identity 错误 claim 分母=negatives∪ms1_only；GT 隔离（decode 只收 frame_id；GT-poison/rename/静态 guard 测试）；keypoint 归一化修复与有效性过滤（越界/bbox 0.5 外=未发射）。
- P2 GT-poison：225 帧 union，real vs poisoned observations 逐帧 canonical sha 全部相同，differing=[]；coverage 139/38/39/73/9；**PASS**（模型 R1 last 508a0430…，nc=2；审计 V3/V4 记录）。
- ONNX：对 R2 pilot last（非选定/未验证模型）做 two-class 导出与三路径决策层对齐（见 §7；若未完成则标 NOT_RUN/UNKNOWN）。

## 4. R1 pilot（v6.1，15ep seed0）

| 指标（canonical） | last | best | 门 |
| --- | --- | --- | --- |
| tower recall val（/95） | 78/95=0.821 | 73/95=0.768 | PASS |
| MS1 recall val（/47） | 20/47=0.426 | 14/47=0.298 | — |
| MS1 recall identity（/35） | **10/35=0.286** | 7/35=0.200 | **FAIL (<0.50)** |
| MS1-only 错误塔 claim（/9） | 0 | 0 | PASS |
| official same-frame val / identity（后补复算） | 16/47=0.340 | 10/26=0.385 | （原 gate 用 consumer 口径，不影响 MS1 recall 硬失败） |
| identity precision | 1.000 | 1.000 | PASS |
| consumer all-positive val / identity | 0.595 / 0.698 | 0.579 / 0.660 | PASS (≥0.30) |
| bearing median val / identity | 0.822° / 1.194° | 0.751° / 1.892° | PASS |

- **pilot gate FAIL（唯一硬失败：MS1 recall）**；按协议拒绝 R1，不加 epoch/seed。按 official same-frame 复算 R1 也只有 0.340/0.385（<0.60），但当时 gate 记录使用 consumer 口径（0.787/1.000）；无论口径如何，MS1 recall 已足以拒绝 R1。
- 原因（已确认）：近距 MS1 训练 OOD（训练 class1 高度≤114px≈2.6m；identity 18/35>114px、17/35>146px）；class1 head 重初始化+15ep 低 LR+warmup；训练 val class1=0 使选模对 class1 盲。

### 4.1 same-frame 定义裁定（diag 独立复核，用于 R2 门）

- 预注册文字 “same-frame target disambiguation correct (both-visible frames denominator) >= 0.60” 的分母是 GT 同框帧，分子=class0 与 class1 **均被正确检出且正确分类**（official detector-side ①）。
- consumer-side ②（“有塔 claim 的帧里塔 claim 正确”：val 0.809、identity 0.962）不计 MS1 是否检出/分类，且剔除未检出帧，等价于删难例，**不得作为 gate 输入**；仅作 conditional tower-claim precision 诊断单列。
- 因此 R2 官方 same-frame = val 15/47=0.319、identity 13/26=0.500（best 14/47=0.298、9/26=0.346）→ FAIL。

## 5. R2 pilot（v6.2 + 近距 MS1 102，15ep seed0；唯一变量=数据）

| 指标（canonical，last=选定） | val_main | identity | 门 |
| --- | --- | --- | --- |
| tower recall | 81/95=**0.853** | 43/44=0.977 | PASS |
| MS1 recall | 21/47=0.447 | 20/35=**0.571** | PASS（R1 0.286→修复） |
| MS1-only 错误塔 claim | — | 0/9 | PASS |
| **official same-frame** | **15/47=0.319** | **13/26=0.500** | **FAIL (<0.60)** |
| identity precision | 0.953 | 1.000 | PASS |
| consumer all-positive | 78/121=0.645 | 23/53=0.434 | PASS (≥0.30) |
| bearing median/P90 | 0.802°/1.969° | 1.043°/4.318° | PASS |
| reference coverage / false-ref | 38/41 / 0.037 | 18/18 / **0.500** | 见下 |
| GT_UNOBS improper / negative claims | 2 / 2（FMR 0.051） | 0 / 0 | 见下 |

- **pilot gate FAIL（官方 same-frame 0.319/0.500）**；consumer-side “塔 claim 正确率” 0.809/0.962 为不同指标（分母剔除未检出帧），单列、不得替代 official（diag 裁定：official ① 正确，② 仅诊断）。
- 即使忽略 same-frame 定义，consumer development→holdout 条件仍不满足：identity false-ref 0.500（>0.10）、val negative claims 2/39=0.051（>0.05）。
- R2 相对 R1 的回退（已确认）：identity consumer all-positive 0.698→0.434、false-ref 0.077→0.500、val negative claims 0→2、GT_UNOBS improper 0→2。近距 class1 数据修复了 recall，但破坏了参考通道/负例声明。

## 6. 预算、holdout 与停止依据

- 预算使用：pilot 2/2（各 ≤15ep），完整训练 **0/4**；未进入 3 seed；未新增候选/epoch。
- 停止规则：pilot→3seed 门 FAIL（R1 MS1 recall；R2 official same-frame）→ 按协议拒绝该配方、不进入 3 seed。
- holdout：consumer development→holdout 门从未被触发（pilot 门已失败）；landmark_holdout_freeze_v3 保持 **SPEC_FROZEN_NOT_TRIGGERED**，未采集/未评价；v2/v1 不改。
- 该结论只否定**本版 two-class 配方**，不否定 two-class 方向本身；证据是 same-frame 监督/参考通道回退，而非“two-class 不可能”。

## 7. ONNX 与工程边界

- ONNX：**NOT_RUN（本包未执行）**——两套 two-class 配方均被 pilot 门拒绝，**不存在最终选定/验证的 two-class 权重**；按“为最终选定权重导出”的定义无可导出对象。若仅需工程一致性证据，可对 R2 pilot last（64ac3822…）导出并为 NOT_SELECTED_VALIDATED_PILOT_ONLY，但不得作为效果/身份证据（本包未做）。
- P2 GT-poison：R1 last 模型 225 帧 PASS（见 §3）；R2 权重不改变管线语义。
- RKNN/板端/真实相机/INT8/延迟：UNKNOWN（无板卡）；许可仍仅内部有界研究。

## 8. 已确认原因 / 仍未证实

**已确认**：
- R1 失败主因是近距 MS1（1.4–2.0m）训练分布缺失（OOD）；补近距数据后 MS1 recall 0.286→0.571。
- R2 失败主因转为 **same-frame 双目标正确分类/匹配**（official 0.319/0.500）与参考通道回退（false-ref 0.500）；不是 MS1 recall 不足。
- class1 head 重初始化（6 张量）+ 15ep 预算 + 训练 val 无 class1 导致选择盲，是 R1 的叠加因素。
- keypoint (0,0) 是模型真实输出（raw kobj 非零），主口径采用 GT-free 有效性过滤；literal 仅敏感性。

**仍未证实**：
- R2 的回退中有多少来自近距 class1 样本挤占 keypoint/负例监督、多少来自数据量/训练预算；未做消融。
- 更长训练/class-balanced/separate identity head/参考通道 guard 能否同时修复 same-frame 与 false-ref（未跑）。
- two-class 在真实相机/赛场/开放集下的行为（本包明确不声明开放集能力）。

## 9. 路线建议与需用户决定

1. **停止本版 two-class 配方**（R1/R2 均已按协议拒绝），不进入 3 seed、不采 holdout。
2. 若要继续 two-class：先做 same-frame 监督与参考通道的专项设计（双目标联合选择、MS1-only/同框均衡采样、class1 不干扰 kpt 分支的隔离/aux head），重新预注册后**新工作包**（新预算、新数据冻结）。
3. 当前可交付基线仍是单类检测 + identity 显式 UNKNOWN + bearing-primary 诊断；不把 two-class 的 raw/consumer 数字用于身份验收。
4. 认证级结论需独立人工标注与新 untouched holdout；板卡/真实相机保持 UNKNOWN；许可分发另行决策。

## 10. 证据路径

| 内容 | 路径 |
| --- | --- |
| 预注册协议 | configs/perception/landmark_two_class_protocol_v1.json（含 R1 结果、R2 amendment、选模规则） |
| 标签规范 | configs/perception/landmark_two_class_label_spec_v1.json |
| 数据冻结 | configs/perception/landmark_split_freeze_v6_1.json、landmark_split_freeze_v6_2.json；DATASET_FREEZE_V6_1/V6_2 报告；snapshot v7/v7b |
| R1 训练/评测 | docs/reports/perception/training_20261104/TWO_CLASS_PILOT_20261105.md；CONSUMER_EVAL_20261105.md 的 R1 canonical 节 |
| R2 训练/评测 | docs/reports/perception/training_20261104/TWO_CLASS_R2_PILOT_20261105.md；CONSUMER_EVAL_20261105.md 的 R2 节 |
| 消费者评测 | docs/reports/perception/CONSUMER_EVAL_20261105.md（+ JSON）；two-class 评测报告 TWO_CLASS_EVAL_20261105.md（final sha e219916a…）、R2 最终记录 TWO_CLASS_EVAL_R2_20261105.json（final sha 26c9944d…；中间版已 superseded） |
| 原因分析/P2 | posteval_20261104/TWO_CLASS_SEMANTICS_MASK_GT_REVIEW_20261105.md、TWO_CLASS_GT_ISOLATION_AUDIT_20261105_V2/V3、P2 poison evidence |
| 数据和标注 | capture T30/T38 目录；annot T31/T32/T39 报告；dev_annotations_20261105 |
| 运行证据（ignored） | outputs/landmark_train/runs/two_class_pilot_v61/、two_class_pilot_v7b/；outputs/perception/two_class_eval_20261105/ |

验证：`pytest -q`、`scripts/planning/audit_documents.py`、v6.2 dataset verify 于收尾执行（结果见提交说明）。

**边界：** 非认证；旧包/旧模型/旧协议/hash 保留；不接控制/PPO；不提升 Gate。
