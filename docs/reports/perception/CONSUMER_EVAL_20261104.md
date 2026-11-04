# 消费者协议评测：身份 + 水平 bearing + 可用性 + 拒绝/发射率（2026-11-04）

> **状态：** BASELINE（A 3-seed 选定 seed2/eval_last 的正式 consumer 评测完成；consumer holdout gate **FAIL**；非能力认证）
> **来源章节：** configs/perception/landmark_consumer_protocol_v1.json（PRE_REGISTERED，sha bdcc9ccd…）；LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104 §2；V2.2 §7.4–§7.8；task-23
> **证据域：** 只读已保存预测（val_main 163 帧）+ 开发帧 CPU 单线程推理（identity 62）+ 主机 CPU PROVISIONAL ONNX/raw-ORT 决策对比（24 帧）；无训练、无 final 重跑、无 Isaac、无板端
> **最后核对：** 2026-11-04

本文件实现并报告**消费者协议**评测：下游地标接力消费“确认身份 + 参考点可用性 + 水平图像 bearing + 观测有效”，不是 2D 像素误差或世界位置。旧 3px 口径与旧 exploratory 结果保留不变，本协议单列、不回溯验证旧结果。候选 A 目前只有 15 epoch seed0 pilot 模型（A 3-seed 由 train 进行中），因此 A 相关数字全部标 PROVISIONAL，不用于任何 gate 判定。

---

## 0. 结论摘要

| 项 | 结果 | 证据域 |
| --- | --- | --- |
| 协议加载 | sha bdcc9ccd…，tau_bearing=3°（PROPOSED，fx=160 时 1px≈0.358°，3°≈8.4px） | 代码 + 单元测试 |
| 实现 | src/boom_birds/evaluation/landmark_consumer_eval.py + scripts/evaluate_landmark_consumer.py；25 条测试（先失败后实现） | 单元测试 |
| val_main 163（baseline matched，只读） | all-positive 60/121=0.496；observable 60/95=0.632；reference-available 38/41=0.927；wrong claims 17（MS1_ONLY 13 + NEGATIVE 1 + WRONG_TARGET 3）；bearing n=38 median 1.09°/P90 1.84°，≤3° 通过 38/38 | 只读保存预测 |
| val_main 163（A pilot，PROVISIONAL） | all-positive 70/121=0.579；observable 70/95=0.737；wrong claims 1；bearing n=33 median 0.63°/P90 2.13°；负例 39/39 | 只读保存预测（A 3-seed 未出） |
| identity 62（baseline，CPU 推理） | all-positive 28/53=0.528；observable 28/44=0.636；reference-available 17/18=0.944；negatives 9/9；wrong claims 1（MULTI_CANDIDATE）；MS1-only 0/9 claim；false-reference 6/26=0.231；bearing n=18 median 1.07°/P90 2.05° | CPU 单线程推理（开发池） |
| identity 62（A pilot，PROVISIONAL） | all-positive 35/53=0.660；observable 35/44=0.795；wrong claims 1（MULTI_CANDIDATE）；false-reference 1/26；bearing n=18 median 1.04°/P90 2.58°（1/18 超 3°） | CPU 单线程推理（开发池） |
| identity 62（A 3-seed 选定 seed2，正式） | all-positive 27/53=0.509；observable 27/44=0.614；ref-available 18/18；negatives 9/9；claims 29/correct 29/wrong 0；MS1-only 0/9；false-reference 2/26=0.077；bearing n=18 median 0.546°/P90 1.550° | CPU 单线程推理（冻结阈值，正式） |
| appearance gate | annotated-box（proposal）模式下 diag-v2 阈值 0/44 误拦、0/35 漏拦；但**迁移到模型预测框后 pipeline 可用性崩溃**（identity all-positive 0.528→0.208 baseline / 0.660→0.302 A；val_main 0.496→0.025 / 0.579→0.074），wrong claim 归零的代价是 24/35、22/38、78 个正确目标 claim 被拦；主因 GREEN_TOO_HIGH_ON_BBOX_MS1（预测框更紧，绿点靠近框顶） | proposal + pipeline（PROPOSED，不冻结） |
| A 3-seed seed0 候选（PROVISIONAL） | all-positive：best 57/121=0.471、last 72/121=0.595、epoch20 36/121=0.298、epoch40 59/121=0.488；bearing P90：3.12° / 1.31° / 1.88° / 2.98°；wrong claims 0/3/1/3 | 只读保存预测（未选定 seed，不用于选模） |
| 身份双口径（A raw upper bound / B strict UNKNOWN） | **A（unvalidated，不能当已确认身份）**：val_main baseline 60/121、A pilot 70/121、A3 seed0 last 72/121、seed0 best 57/121；identity baseline 28/53、A pilot 35/53。**B strict UNKNOWN**：所有 GT-present 域成功 **0/分母**（val_main 0/121、0/95、0/41；identity 0/53、0/44、0/18），negatives 不受影响（39/39、9/9）；raw claims 仍记录但不计身份（val_main baseline raw 83/confirmed 0；A3 seed0 last raw 75/confirmed 0） | 只读保存预测 + CPU 推理 |
| ONNX/raw-ORT | A pilot 24 帧 CPU PROVISIONAL：identity 决策 0 翻转、reject/reason 3、reference 2、bearing 9（>0.01° 容差）但 bearing delta median 0.205°/max 0.597°，**0 帧超过消费者 3°** | 主机 CPU，PROVISIONAL |

**关键结论：** 消费者协议评测链路已可执行；单类 tower 模型在没有身份通道时会产生 MS1 误 claim（val_main baseline 13 个 MS1_ONLY）与同框/横向错误；appearance gate 在**注释框**上可分，但**不能直接迁移到单类模型预测框**——不应在本池冻结 gate 阈值，identity 应显式 UNKNOWN，身份方案 2（two-class detector）是本协议已记录但本轮 NOT_RUN 的选项。

---

## 1. 协议口径（消费端）

每 GT-present 帧成功 = 以下全部成立：

1. presence 正确；
2. identity **确认且正确**：仅当 appearance gate 通过且恰好一个候选存活时才能输出 RMUC2027_CENTRAL_TOWER_PROPOSED；否则必须输出 UNKNOWN/候选、不得更新关联区域（多候选仍 claim = 违约，计入 wrong claim）；
3. reference 处理正确：GT 参考可见 → 必须输出 keypoint；GT 参考不可见 → 必须正确拒绝（无 keypoint）；
4. 水平图像 bearing 误差 ≤ tau_bearing（3° PROPOSED），bearing=atan2(x−cx0, fx)，不是世界方位/距离；
5. 观测有效（stale/duplicate/generation mismatch = 拒绝，不算成功）。

GT-absent 帧成功 = 无确认的中央塔 claim。2D 像素误差与 bbox IoU 仅诊断；UNKNOWN/REJECTED/无 keypoint 样本留在适用分母。

三套分母：all-positive（含 TINY/截断/参考不可用/GT_UNOBSERVABLE）、observable-positive（排除 GT_UNOBSERVABLE）、reference-available（GT 参考可见）；negatives 为 wrong-claim 分母。GT_UNOBSERVABLE 进 all-positive 分母但不进 observable 成功分母，其 claim/keypoint 单列。

gate 语义（协议合规）：gate 拒绝 → 输出 UNKNOWN/不更新区域，属**正确拒绝**（可用性损失），不是 wrong claim；只有 gate 放行且身份错误才是 wrong claim。评测保留 raw_claims/gate_blocked/gate_blocked_correct_targets/gate_accepted_wrong_claims 便于分解。

---

## 2. 实现与入口

| 入口 | 说明 |
| --- | --- |
| src/boom_birds/evaluation/landmark_consumer_eval.py | load_protocol（记录 sha）/truth_from_annotation/build_frames/evaluate_frame/summarize_consumer；appearance_features（含 width/height 纵横比、green_rel_y、symmetry）/appearance_gate(v1)/appearance_gate_v2/sweep/measure_feature_cost；evaluate_saved；parse_parity_evidence |
| scripts/evaluate_landmark_consumer.py | --predictions（只读）或 --model（CPU 推理，默认 device=cpu、OMP/线程=1）+ --decisions/--images/--split/--appearance-gate/--gate-mode v1|v2/--gate-thresholds/--parity-evidence；输出 consumer_metrics.json + rows.jsonl（推理时加 predictions.jsonl）；默认拒绝覆盖（exit 3） |
| tests/evaluation/test_landmark_consumer_eval.py | 25 条（协议加载/校验、身份双口径严格 UNKNOWN/raw upper bound、truth、成功判据、多候选/同框/MS1/遮挡/负例 wrong claim、GT_UNOBSERVABLE、三套分母、bearing、gate v1/v2 特征与扫描/代价、gate 合规语义、CLI 端到端与覆盖保护） |

---

## 3. val_main 163 帧只读评测（已保存预测）

输入：labels_val_validation163.json（sha a9bfda8f…，163 帧：present 121 / absent 42，GT_UNOBSERVABLE 29，参考可见 41 / 不可见 80）；baseline=improvement_v4 baseline_seed0/eval_v41_last（163 帧）；A=candidateA_pilot15_seed0/eval_last（163 帧，PROVISIONAL）。29 帧预测为 UNKNOWN/MISSING_IMAGE（HN2 帧图像不在该 val 目录），留在 all-positive 分母、不成功。

### 3.1 三套分母上的 consumer 成功

| 域 | baseline 分子/分母 | baseline 率 | A pilot 分子/分母 | A pilot 率 |
| --- | --- | --- | --- | --- |
| all-positive | 60/121 | 0.496 | 70/121 | 0.579 |
| observable-positive | 60/95 | 0.632 | 70/95 | 0.737 |
| reference-available | 38/41 | 0.927 | 33/41 | 0.805 |
| negatives（成功=无 claim） | 25/39 | 0.641 | 39/39 | 1.000 |

### 3.2 身份与错误 claim

| 指标 | baseline | A pilot（PROVISIONAL） |
| --- | --- | --- |
| claims（确认身份输出） | 83 | 72 |
| correct claims | 66 | 71 |
| wrong claims | 17 | 1 |
| wrong 类别 | MS1_ONLY 13 / NEGATIVE 1 / WRONG_TARGET 3 | WRONG_TARGET 1 |
| identity precision / recall（分母 95） | 0.795 / 0.695 | 0.986 / 0.747 |
| claims on negatives | 14（负例分母 39 → 0.359） | 0 |
| MS1-only 分母 / claims | 13 / 13 | 0 / 0 |

baseline 的 13 个 MS1_ONLY 是单类 tower 在 map-native MS1 上的误匹配，违反“确认身份才可赋中央塔 ID”；A pilot 在该 val 批无 MS1 误匹配（A 仅 15 epoch pilot，不可外推）。

### 3.3 reference 与 bearing

| 指标 | baseline | A pilot |
| --- | --- | --- |
| 发射率（keypoint / observable） | 42/95=0.442 | 34/95=0.358 |
| GT 不可见参考拒绝正确率 | 50/54=0.926 | 53/54=0.981 |
| false-reference rate | 4/54=0.074 | 1/54=0.019 |
| bearing n | 38 | 33 |
| bearing median / P90 / max | 1.092° / 1.838° / 2.339° | 0.627° / 2.134° / 2.645° |
| ≤3° 通过 | 38/38 | 33/33 |
| 2D 像素误差 median / P90（仅诊断） | 4.55 / 9.28 px | 5.09 / 8.76 px |

### 3.4 分层（all-positive 成功率）

| 维度 | baseline | A pilot |
| --- | --- | --- |
| family | HN2 0/26；inner_north 25/30；static_low 15/15；north 20/50 | HN2 0/26；inner_north 23/30；static_low 15/15；north 32/50 |
| scale | TINY 23/58=0.397（最差非零组）；SMALL/MEDIUM/LARGE 均 1.0；NO_BBOX 0/26 | TINY 37/58=0.638；SMALL 0.75；MEDIUM 0.842；LARGE 1.0；NO_BBOX 0/26 |
| truncation | NOT_TRUNCATED 0.442；TRUNCATED 0.824 | NOT_TRUNCATED 0.596；TRUNCATED 0.471 |

GT_UNOBSERVABLE（26 个 present+occlusion）均无 claim/keypoint（correct abstention 26/26），计入 all-positive 但不成功。

### 3.5 A 3-seed 正式评测（选定 seed2/eval_last；冻结阈值下重解码）

lead 选定 **seed2/eval_last**（val joint 60/95=0.6316；seed0 last 49/95、seed1 last 43/95）。本节用选定预测 `outputs/landmark_train/runs/stage_verify_v5/seed2/eval_last/predictions.jsonl` + labels_val_validation163.json（sha a9bfda8f…），并以 **冻结阈值** 重解码（tau_det=tau_conf=0.605476、tau_margin=0.1、tau_px=3.0、tau_kpt=0.5，来自 configs/perception/landmark_model_freeze_v1.json；**未在本次 3-seed val 上重调**）。对照行同用冻结阈值重解码（--redecode-thresholds）。

| val_main 163 | all-positive | observable | ref-available | negatives | bearing n / median / P90 | wrong claims |
| --- | --- | --- | --- | --- | --- | --- |
| improvement baseline（matched） | 45/121=0.372 | 45/95=0.474 | 37/41 | 38/39 | 37 / 1.076° / 1.782° | 2（MS1_ONLY 1 + MULTI_CANDIDATE 1） |
| 候选 A pilot | 51/121=0.421 | 51/95=0.537 | 33/41 | 39/39 | 33 / 0.627° / 2.134° | 0 |
| A seed0 last | 53/121=0.438 | 53/95=0.558 | 35/41 | 39/39 | 37 / 0.661° / 1.305° | 2 |
| A seed1 last | 30/121=0.248 | 30/95=0.316 | — | — | 18 / 0.473° / 1.407° | 0 |
| **A seed2 last（选定）** | **58/121=0.479** | **58/95=0.611** | **35/41** | **39/39** | **37 / 0.453° / 1.094°** | **0** |

选定模型详情：presence（observable）TP61/FN34/FP0/TN39，P1.000/R0.642；identity claims 59、correct 59、wrong 0、claims_on_negatives 0、MS1-only claims 0/27；reference 发射 38/95=0.400、GT 不可见拒绝 53/54=0.981、false-reference 1/54=0.019；GT_UNOBSERVABLE 26 帧 0 claim/0 kpt/26 abstain（计入 all-positive 分母）；family 成功率：hn2 0/26、inner_north 20/30=0.667、static_low 15/15、north 23/50=0.460。

相对 matched baseline：all-positive +0.107（≥+0.05），但绝对值 0.479 **<0.50**；consumer 结果不用于选模/回调（seed 由 val joint 选定）。

---

## 4. identity 62 帧（development 身份池，CPU 单线程推理）

- 标签 labels_identity_dev.json（sha 79fd1745…，62 帧：present 53（含 GT_UNOBSERVABLE 9）/ absent 9；参考可见 18 / 不可见 35）；decisions：TARGET_ONLY 18 / BOTH 26 / CONFUSER_ONLY 9 / GT_UNOBSERVABLE 9；MS1 confusers 35（map-native verified）。
- 模型：baseline = improvement_v4 baseline_seed0/seed0/weights/last.pt（sha de763bae…）；A pilot = candidateA_pilot15_seed0/seed0/weights/last.pt（sha 6b319889…，PROVISIONAL）。CPU 单线程推理（device=cpu、OMP=1、torch threads=1）；tau_det 0.25/tau_margin 0.10/tau_kpt 0.50（PROPOSED，非冻结）。

| 指标（identity 62） | baseline | A pilot |
| --- | --- | --- |
| all-positive 成功 | 28/53=0.528 | 35/53=0.660 |
| observable-positive 成功 | 28/44=0.636 | 35/44=0.795 |
| reference-available 成功 | 17/18=0.944 | 16/18=0.889 |
| negatives 成功（无 claim） | 9/9 | 9/9 |
| presence（observable） | TP35/FN9/FP0/TN9；P1.000 R0.795 | TP38/FN6/FP0/TN9；P1.000 R0.864 |
| claims / correct / wrong | 35 / 34 / 1（MULTI_CANDIDATE） | 38 / 37 / 1（MULTI_CANDIDATE） |
| identity precision / recall | 0.971 / 0.773 | 0.974 / 0.841 |
| MS1-only claims | 0/9 | 0/9 |
| 发射率（keypoint/observable） | 24/44=0.545 | 19/44=0.432 |
| reference 拒绝正确率（不可见 26） | 20/26=0.769 | 25/26=0.962 |
| false-reference rate | 6/26=0.231 | 1/26=0.038 |
| bearing n / ≤3° / median / P90 / max | 18 / 18 / 1.065° / 2.052° / 2.207° | 18 / 17 / 1.041° / 2.580° / 4.131° |
| GT_UNOBSERVABLE（9 帧） | 0 claim / 0 kpt / 9 abstention | 同 |
| **A 3-seed 选定 seed2（正式，冻结阈值）** | all-positive 27/53=0.509；observable 27/44=0.614；ref 18/18；neg 9/9；claims 29/correct 29/wrong 0；MS1-only 0/9；false-ref 2/26=0.077；bearing n=18 0.546°/1.550°；GT_UNOBS 9 abstain；family：target_alone 9/9、near_trunc 9/9、both_mid 8/9、both_same_bearing 0/9、both_scale_lateral 1/8 | — |

分层（all-positive，最差组）：
- baseline：both_same_bearing 0/9（全失败）、both_scale_lateral 2/8、target_alone 9/9、near_trunc 8/9、both_mid 9/9、full_occlusion 0/9（GT_UNOBSERVABLE 不成功）。
- A pilot：both_same_bearing 3/9、both_scale_lateral 7/8、target_alone 8/9、near_trunc 8/9、both_mid 9/9、full_occlusion 0/9。

**解读：** 单类模型在 identity 池上 MS1-only 无 claim（0/9）不等于身份能力；同框同 bearing（stack）与横向两种 both 场景明显变差；false-reference 在 baseline 上 6/26 是消费者语义错误（GT 参考不可用仍发 keypoint）。GT_UNOBSERVABLE 分支在本池被触发（9 帧）且两个模型均正确 abstain。

---

## 5. appearance-gate 身份方案评估

两个方案分列；**均不冻结阈值**（协议要求：冻结需 untouched 数据；本 62 帧为 development 设计池，diag 明确不得用于冻结）。

### 5.1 v1（val_main 冻结的 bbox-aspect gate）

- 冻结规则（只用 val_main target proposals，identity 62 仅作 held-out test）：minimise val_main target false-block；tie-break 更小 max_aspect + green 可选（min_green_pixels=0）。冻结值：max h/w=2.6、min_green=0、height≥0。val_main 选中点 false-block 0/95；held-out identity 62：目标 false-block 6/44=0.136、MS1 miss-block 5/35=0.143。
- pipeline（模型预测框）效果：**gate_blocked = 0**（identity baseline/A、val_main baseline/A 全部），wrong claims 不变（17/1）。原因：单类模型在 MS1 上给出的框并不“细长”（h/w < 2.6），v1 无法拦截 MS1；该阈值只在注释框语义下有效。

### 5.2 v2（diag T24 图像特征设计：width/height、green_rel_y、高度）

- 设计依据（diag，62 帧开发池，PROPOSED_NOT_FROZEN）：目标 aspect w/h 0.63–1.78（中位 1.46）vs MS1 0.20–0.44（0.33），AUC 1.0；目标 green_rel_y 0.21–0.40（0.24）vs MS1 0.06–0.12（0.09），AUC 1.0。建议：w/h≥0.50 且（若发射 kpt）green_rel_y≥0.18；高度≥20px；否则 UNKNOWN。
- **proposal-box 模式**（注释/decisions 框，仅图像特征）：identity 目标 false-block 0/44，MS1 miss-block 0/35；val_main 可标注目标（height≥20）false-block 1/49，TINY（height<20）46 帧按设计 UNKNOWN（不计误拦）。这与 diag 的 0/0 一致（同一开发池）。
- **pipeline 模式**（模型预测框）：阈值不可迁移——
  - identity baseline：raw claims 35 → confirmed 11，gate_blocked 24（24 为正确目标 false-block）；all-positive 0.528→0.208，observable 0.636→0.250，wrong claims 1→0。
  - identity A pilot：raw 38 → confirmed 16，blocked 22（22 正确目标）；all-positive 0.660→0.302，observable 0.795→0.364，wrong claims 1→0。
  - val_main baseline：raw 83 → confirmed 5，blocked 78（61 正确目标）；all-positive 0.496→0.025，observable 0.632→0.032，wrong 17→0。
  - val_main A pilot：raw 72 → confirmed 9，blocked 63（62 正确目标）；all-positive 0.579→0.074，observable 0.737→0.095，wrong 1→0。
  - 拦截原因：identity baseline 24/24 为 GREEN_TOO_HIGH_ON_BBOX_MS1；A pilot 19/22 同因 + TOO_SMALL 3；val_main baseline 55/78 + TOO_SMALL 23；A pilot 34/63 + TOO_SMALL 28 + ASPECT 1。
- **根因**：green_rel_y 与 aspect 都是**相对注释框/对象框**定义的；单类检测器输出紧/部分框（尤其远景/截断），绿点相对预测框更靠顶，于是“目标”被判成 MS1；同时 model 在 MS1 上的预测框也不细长，v1 无法拦截。**结论：annotated-box 可分不等于 pipeline 可分；不得据此冻结 gate；单类+appearance-gate 不能作为身份通道。**
- 代价：本实现特征提取（320×240、numpy 向量化）中位 0.51 ms/帧（20 帧×10 重复；max 1.0 ms）；diag 的纯 Python 实现为 0.072–0.185 s/帧（实现口径不同，均为主机 CPU；RK3576 UNKNOWN）。

---


---

## 6. 身份策略双口径（A raw claim upper bound / B strict UNKNOWN，分开报告）

按 lead 2026-11-04 指示，identity 通道未建立时消费者评测必须分两种策略，且**不得混用**；两者都报三套分母。

### 6.1 策略定义（代码可执行）

- **A = raw_claim_upper_bound**：把模型**原始 claim**按未验证身份计入（identity_claim_unvalidated=true）；success 是“若 raw claim 可信”的**上界**，不能当已确认身份，也不能用于 identity 认证或 stage gate 通过。claim 与 GT 目标的几何匹配仅用于评测计分。
- **B = strict_unknown**：未确认身份一律 UNKNOWN（本任务无独立 identity 通道 → 实际全部 UNKNOWN）；raw claim 只记录、不计入 confirmed 身份，也不计 wrong claim；GT-present 消费者成功 = **0（上限由缺失身份通道决定）**；negatives 成功仍=无确认 claim。

### 6.2 三套分母 + 负例（A/B 对照）

| 数据集 | 策略 | all-positive | observable | ref-available | negatives | claims（confirmed/raw） | wrong claims |
| --- | --- | --- | --- | --- | --- | --- | --- |
| val_main baseline | A | 60/121 | 60/95 | 38/41 | 25/39 | 83 / 83 | 17 |
| val_main baseline | B | **0/121** | **0/95** | **0/41** | 39/39 | 0 / 83 | 0 |
| val_main A pilot | A | 70/121 | 70/95 | 33/41 | 39/39 | 72 / 72 | 1 |
| val_main A pilot | B | 0/121 | 0/95 | 0/41 | 39/39 | 0 / 72 | 0 |
| val_main A3 seed0 last | A | 72/121 | 72/95 | 36/41 | 39/39 | 75 / 75 | 3 |
| val_main A3 seed0 last | B | 0/121 | 0/95 | 0/41 | 39/39 | 0 / 75 | 0 |
| val_main A3 seed0 best | A | 57/121 | 57/95 | 30/41 | 39/39 | 62 / 62 | 0 |
| val_main A3 seed0 best | B | 0/121 | 0/95 | 0/41 | 39/39 | 0 / 62 | 0 |
| identity 62 baseline | A | 28/53 | 28/44 | 17/18 | 9/9 | 35 / 35 | 1 |
| identity 62 baseline | B | 0/53 | 0/44 | 0/18 | 9/9 | 0 / 35 | 0 |
| identity 62 A pilot | A | 35/53 | 35/44 | 16/18 | 9/9 | 38 / 38 | 1 |
| identity 62 A pilot | B | 0/53 | 0/44 | 0/18 | 9/9 | 0 / 38 | 0 |
| val_main A3 seed2（选定） | A | 58/121 | 58/95 | 35/41 | 39/39 | 59 / 59 | 0 |
| val_main A3 seed2（选定） | B | **0/121** | **0/95** | **0/41** | 39/39 | 0 / 59 | 0 |
| identity 62 A3 seed2（选定） | A | 27/53 | 27/44 | 18/18 | 9/9 | 29 / 29 | 0 |
| identity 62 A3 seed2（选定） | B | **0/53** | **0/44** | **0/18** | 9/9 | 0 / 29 | 0 |

- bearing 与 reference 数字在 A/B 下相同（身份策略只改变 identity 与 success，不改变已发射 keypoint）：例如 val_main baseline bearing n=38 median 1.09°/P90 1.84°、ref 拒绝 50/54；A3 seed0 last n=37 0.66°/1.30°、拒绝 54/54。
- identity 62 的 A 策略仍保留 false-reference（baseline 6/26、A pilot 1/26）与 GT_UNOBSERVABLE 9 帧 0 claim/0 kpt/9 abstention，这些不受身份策略影响。

### 6.3 解读

1. **B 是当前真实可交付状态**：identity 无确认通道 → 消费者 GT-present 成功上限 = 0；不能把 A 的 0.5–0.76 当作身份/消费者验收。
2. **A 只能作上界与可用性诊断**：A 的 success 含未验证 raw claim；其中 wrong claims 仍按 GT 计（baseline val_main 17、identity false-reference 6 等），因此 A 也不能写成“identity 已达标”。
3. 两策略分开报告的意义：避免用“模型有 claim”冒充“身份已确认”；在 identity 通道建立前，consumer 成功率的正式口径是 B（0），A 仅标 identity_claim_unvalidated。
4. 后续若采用 two-class detector（协议 approach 2，NOT_RUN）或独立身份模块，必须重新冻结并在 untouched 数据上以 confirmed-only 策略评测，不得用本文件的 A 数字。

---

## 7. 候选 A pilot 的 ONNX/raw-ORT 决策翻转（PROVISIONAL CPU）

- 模型：candidateA_pilot15_seed0/seed0/weights/last.pt（sha 6b319889…，PROVISIONAL；A 3-seed 选定模型未产出）。
- 导出：使用同仓 ultralytics 8.2.0 在 CPU 导出 opset18（12.0 MB，sha 54a30e8f…，写入 ignored weights 目录；host-only）。
- 对比：共用预处理（square letterbox + NMS + 阈值 + 坐标域），24 个 identity 帧，比较 consumer 决策层（landmark_onnx.observation_decision / decision_diff）。

| 指标 | 结果 |
| --- | --- |
| 帧数 | 24 |
| identity 决策翻转 | 0 |
| presence 翻转 | 0（bearing_presence_flip 2：presence 相同但 bearing 侧判据不同） |
| reject / reject_reason 翻转 | 3 / 3 |
| reference 翻转 | 2 |
| bearing 翻转（>0.01° 容差） | 9 |
| bearing delta（有值帧 n=9） | median 0.205° / max 0.597°；**0 帧 > 消费者 3°** |
| 状态 | PROVISIONAL_CPU；正式 A 3-seed parity 由 T29/后续执行 |

**解读：** 消费者身份层在 24 帧上 0 翻转；reject/reason 与 reference 各有 2–3 帧在阈值边缘差异（tau_det/tau_kpt 附近），bearing 差异均在 0.6° 内、远小于 3°；没有证据显示 ONNX 导出破坏消费者身份决策，但 n=24、pilot 模型，不能外推到正式 A 3-seed。

---

## 8. 与协议 stage gate 的对照（不作为放行）

以 **A 3-seed 选定 seed2/eval_last**、冻结阈值、val_main 163 帧对 consumer holdout gate 逐条判定（严格 UNKNOWN 为正式口径；raw upper bound 仅记录）：

| 条件（协议 stage_gates） | 实测（selected A3 seed2） | 判定 |
| --- | --- | --- |
| consumer success（all-positive）≥0.50 | 0.479（58/121）；参考口径 strict_unknown = 0/121 | **FAIL**（raw upper bound 也不足 0.50；strict 因身份通道缺失为 0） |
| 相对 matched baseline Δ ≥ +0.05 | +0.107（0.479 vs 0.372） | PASS |
| wrong-claim rate ≤0.05（负例/MS1/多候选分母） | 0/39（claims_on_negatives 0；MS1-only claims 0/27） | PASS（但 identity 通道未建立，见 FAIL 说明） |
| bearing median ≤3° 且 P90 ≤5°（参考可见已发射 n=37） | 0.453° / 1.094°（37/37 ≤3°） | PASS |
| 参考拒绝正确率 ≥0.50；false-reference ≤0.10 | 53/54=0.981；1/54=0.019 | PASS |
| worst-group 不差于 baseline worst >0.05 | selected 最差族 hn2 0/26；baseline 最差族 hn2 0/26 | PASS（均为 0，不构成改进证据） |

**consumer holdout gate 判定：FAIL。** 主要原因不是 bearing/P90 或负例误配，而是 **identity 通道缺失**：strict UNKNOWN 口径下 GT-present consumer success = 0；raw upper bound 0.479 仍 <0.50 且不是已确认身份。按协议 on_fail：STOP 该版本消费者验证，不得据此进入 holdout 采集/认证；raw 数字只作上限记录。A pilot 数字看起来更好，但它是 15 epoch pilot，且 identity 62 的 both_same_bearing only 3/9；**不宣布任何 gate 通过**。正式判定必须等 A 3-seed 选定模型 + 同一脚本重跑。

---

## 9. T25 identity pilot 批次处理（annot 更正）

- annot 更正：T25 identity 28 帧为 **PILOT run**（formal run 因 Isaac/CUDA 初始化失败无完整 run.complete），status=PROVISIONAL_DIAGNOSTIC_ONLY；文件 sha 7164a5d6…，annotations 内容 sha 82b5c392…。
- 按 annot 要求：**不得并入 dev freeze v5、不得作 val_identity GT、不得进 consumer identity 误匹配分母**；其 far 14 帧也不作为 MS1 误匹配分母。本文件**不使用**该批数据；appearance gate 的漏拦统计未包含 T25。等 capture 重跑 formal 合格机位、annot 重新标注（新 sha）后再作为补充 batch 单列。

---

## 10. 限制与不声明

- A 3-seed 选定模型已完成正式评测（seed2/eval_last）；本文 §3.5/§4/§6/§8 的“选定”数字为正式口径；早期 A pilot 数字保留标 PROVISIONAL 仅作历史对照。
- identity 62 为 development、agent-proxy 身份池；MS1 为 map-native（非合成注入）；T25 pilot 已排除；identity 结论不认证。
- val_main 29 帧 HN2 为 UNKNOWN/MISSING_IMAGE（图像不在 val 目录），保留在 all-positive 分母、单列；observable 域不含它们。
- appearance gate 只在 annotated-box 上可分；pipeline 迁移失败是**负结果**；不得据此冻结阈值，也不得用本池宣布身份能力；two-class detector（协议 approach 2）本轮 NOT_RUN。
- bearing 是图像角，不是世界方位/距离；tau_bearing 3° 为 PROPOSED，不是认证门限；2D 像素误差/IoU 仅诊断。
- ONNX 为 CPU PROVISIONAL、24 帧、A pilot（选定 seed2 的 ONNX parity 未重跑，属 T29/后续）；RKNN/板端/真实相机 UNKNOWN；无控制/PPO；不提升任何 Gate；许可仍为内部有界研究。

---

## 11. A 3-seed 正式重跑（已执行：seed2/eval_last）

选定 **seed2/eval_last**（val joint 60/95=0.6316）后已执行以下重跑（冻结阈值 tau_det=tau_conf=0.605476、tau_margin=0.1、tau_px=3.0、tau_kpt=0.5，来自 model_freeze_v1，未在本次 3-seed val 上重调）：

    & 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/evaluate_landmark_consumer.py --labels outputs/perception/dev_annotations_20261104/labels_val_validation163.json --predictions outputs/landmark_train/runs/stage_verify_v5/seed2/eval_last/predictions.jsonl --split val --identity-policy confirmed_only --redecode-thresholds --tau-det 0.605476 --tau-margin 0.1 --tau-kpt 0.5 --tau-iou 0.3 --tau-px 3.0 --tau-conf 0.605476 --output-dir outputs/perception/consumer_eval_20261104/val_main_A3seed_selected_confirmed_only --overwrite

    & 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/evaluate_landmark_consumer.py --labels outputs/perception/dev_annotations_20261104/labels_identity_dev.json --decisions outputs/perception/dev_annotations_20261104/identity/identity_decisions.json --model <A3seed_best.pt> --images outputs/sensor_shadow/lm_dev_identity_capture_20261104_sensor/images --split val --device cpu --output-dir outputs/perception/consumer_eval_20261104/identity_A3seed_selected --overwrite

ONNX/raw-ORT 正式版：用选定 best.pt 复做本文 §7（CPU），或由 T29 统一执行；在此之前 §6 数字只作 PROVISIONAL。

---

## 12. 测试与证据

- 目标测试：tests/evaluation/test_landmark_consumer_eval.py，**26 passed**（本轮先失败后实现；含冻结阈值重解码与身份双口径回归）。按 lead 资源协调，本轮未跑全量 pytest（只跑目标文件与轻量 CPU 任务）。
- 机器可读摘要：[CONSUMER_EVAL_20261104.json](CONSUMER_EVAL_20261104.json)；完整输出（ignored）在 outputs/perception/consumer_eval_20261104/。

| 内容 | 路径 / sha |
| --- | --- |
| 协议 | configs/perception/landmark_consumer_protocol_v1.json（sha bdcc9ccd…） |
| 代码 / CLI / 测试 | src/boom_birds/evaluation/landmark_consumer_eval.py、scripts/evaluate_landmark_consumer.py、tests/evaluation/test_landmark_consumer_eval.py |
| val_main baseline | outputs/perception/consumer_eval_20261104/val_main_baseline/{consumer_metrics.json,rows.jsonl}（labels sha a9bfda8f…） |
| val_main 冻结阈值对照 | val_main_baseline_frozen/、val_main_candidateA_pilot_frozen/、val_main_A3seed_seed0_last_frozen/、val_main_A3seed_seed1_last_frozen/ |
| val_main A pilot | outputs/perception/consumer_eval_20261104/val_main_candidateA_pilot/ |
| identity 62 baseline / A pilot | outputs/perception/consumer_eval_20261104/identity_baseline/、identity_candidateA_pilot/（labels sha 79fd1745…，decisions sha 含在 inputs） |
| gate frozen v1 | appearance_gate_freeze_v1.json、appearance_gate_frozen_thresholds.json、appearance_gate_recommended.json |
| gate v1/v2 pipeline | identity_*_gate/、identity_*_gate_v2/、val_main_*_gate_v2/ |
| gate v2 counters | appearance_gate_v2_counters.json |
| 身份双口径输出 | outputs/perception/consumer_eval_20261104/*_{confirmed_only,raw_claim_upper_bound,strict_unknown}/（consumer_metrics.json + rows.jsonl） |
| A3 选定正式输出 | val_main_A3seed_selected_{confirmed_only,raw_claim_upper_bound,strict_unknown}/、identity_A3seed_selected_{...}/、selected_seed_formal_summary.json |
| ONNX provisional | identity_onnx_flip_provisional.json（onnx sha 54a30e8f…） |
| diag 设计证据 | docs/reports/perception/posteval_20261104/MS1_IDENTITY_ANALYSIS_20261104.json（sha 1e9a45ad…）、IDENTITY_APPEARANCE_FEATURES_20261104.json（19981b1f…）、CONSUMER_REQUIREMENT_20261104.json（ec021bf2…） |
| T25 pilot（排除） | outputs/perception/dev_annotations_20261104/identity_t25/labels_v1.json（PROVISIONAL_DIAGNOSTIC_ONLY，sha 7164a5d6…；不入分母） |

不修改合同、不更新 Gate、不改变旧 final/旧 3px 结果；若后续模型/协议变化需新编号并说明是否作废本次结论。