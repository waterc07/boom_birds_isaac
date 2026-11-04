# 地标 dev 划分冻结 v4.1：旧 exploratory 池并入 TRAIN（2026-11-04）

> **状态：** PASS（v4.1 清单 / 复用登记 / 泄漏审计 / 外部产物索引的 QA）；仅用于有界改进候选 A 的 scale 覆盖；**不是 final/sealed、不是认证、模型效果 NOT RUN**
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §20.11.1/§20.11.3/Phase 6；configs/perception/landmark_improvement_gate_v1.json；docs/reports/perception/posteval_20261104（diag 根因：dev train 缺 LARGE(near)/TINY(far) 尺度覆盖）
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真产物索引（离线只读；未运行 Isaac、未训练、未上传数据）
> **最后核对：** 2026-11-04

本文件只记录 v4.1 的划分 delta、复用声明、审计与索引结果。v4.1 是为了让改进候选 A 在训练集里获得 LARGE(near)/TINY(far) 尺度覆盖；**凡是进入训练的数据，从此不得再作 final/sealed 或独立测试**。

## 0. 结论摘要

- **v4.1 已冻结**：`configs/perception/landmark_split_freeze_v4_1.json`
  - canonical sha256 `36840e7f87379b710ce20a17ee2ed54df6761b8c42ae54a6a693c12f5da5cee0`
  - file sha256 `531565a25d77d4d1bf3cc3292c55fc9ee4dda23a36280e0ce63ecd01f67f8923`
  - **train 16 组 / 1772 帧（1697 accepted）**；**val 7 组 / 816 帧（795 accepted，与 v4 完全一致）**；test 0；excluded 9 组 / 1107 帧（1071）；合计 32 组 / 3695 帧。
  - v4.1 校验：**PASS，0 error，161 warning**（v4 的 155 + 复用 6 组各自的组内 warmup 重复 sha 6 条）。
- **v4→v4.1 delta**：`+6 组 / +297 帧`（旧 exploratory 池 297 RGB / 279 accepted）；base v4 canonical `afa5caa4…`；val 不变。
- **训练标签引用**：
  - dev train：160 帧 `01977b9f…`（labels lists `0c1c75ae…`，与原 v4 一致）
  - 复用 exploratory：279 接受帧 `7115ee04cd2db33381047e6952541ee2bb5214df994a35df8f55ec24d7d79504`（labels_v1）
  - train 可用标注合计 **439 帧**（160 + 279）；val 标注 **163 帧**（`8c215597…`）。
- **复用登记**：`development_train_reuse` 记录 dataset_role=`DEVELOPMENT_TRAIN`、source pool seal `cedbbc7e…`、source file sha `c852f0e5…`、逐组/帧数/标签 sha、暴露事件 `ev_exploratory_reused_as_train_20261104`，并声明：**这些帧用过后永远不能再作 final/sealed/独立测试**。
- **泄漏/近重复审计 PASS**：v4.1 train-val sha 0、像素近重复 0、同轨迹跨 split 0、family/group/连续帧泄漏 0；复用 family（lmf_*）与 v4 val family（fam_*）**无 ID 重叠**，复用组全部在 train。
- **外部产物索引 PASS**：3695/3695 帧 PNG 可读 320×240、逐帧 sha 与清单一致、obs sha 一致。
- **exposure_registry_v2 已更新**：sha `a98cce2daeb5d5935861a89e35ae9c46b0e440aa3688411ad5ca9f5a8b010a4a`，32 组全部 exposed_development、11 条事件（新增"exploratory 用于训练"）、357 帧 override。
- **holdout 仍 NOT_TRIGGERED**（improvement gate 未评估；无 holdout 数据）。
- **认证结论**：A3/identity/holdout 仍 INCOMPLETE；v4.1 只是候选 A 的 development 训练数据版本。

## 1. v4.1 结构

| split | v4 组/帧(accepted) | v4.1 组/帧(accepted) | 说明 |
| --- | ---: | ---: | --- |
| train | 10 / 1475（1418） | **16 / 1772（1697）** | +6 组旧 exploratory（297 帧 / 279 accepted） |
| val | 7 / 816（795） | 7 / 816（795） | **不变**（163 标注帧） |
| test | 0 | 0 | 无 sealed/final |
| excluded | 9 / 1107（1071） | 9 / 1107（1071） | 不变 |
| 合计 | 26 / 3398 | 32 / 3695 | +6 组 / +297 帧 |

- 复用组（family 沿用旧池，group id 用 `g_reuse_*` 避免与旧 seal 混淆）：g_reuse_lmf_sweep / backoff / near / edge / similar_negative / side_negative；全部 split=train、sealed=false、dataset_role=DEVELOPMENT_TRAIN。
- 复用数据来自 `outputs/sensor_shadow/lm_final_candidate_20261104_sensor`（297 RGB / 279 accepted）；旧池的 34 帧试点与 279 exploratory 标签都已登记为 exposed；它们在 v4.1 中是训练数据。
- 本批 identity 案例（T15，169 accepted，capture 已完成）**不并入 v4.1**；T19 标注未开始 → 归 v4.2，不阻塞候选 A。

## 2. 复用声明（不可再作 final）

- `development_train_reuse.declaration`：这些帧曾是 exploratory/final-like；**作为 TRAIN 使用后，不得再作为 final/sealed 或独立测试池**。
- 旧 exploratory 一次性指标（presence P1.000/R0.916、joint 0.298 等）保留为 traceability-only；**不能作为见过这些训练数据的模型的公平 final 结果**。
- 候选 A 必须与 **相同 v4.1 split** 训练的 matched baseline 比较；不得拿旧 exploratory 指标当 baseline。
- registry v2 事件 `ev_exploratory_reused_as_train_20261104` 记录执行者/用途/时点/证据/声明。

## 3. 泄漏 / 近重复审计（v4.1）

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v4_1_20261104.json`（**PASS**）。

- 集合：train 1772 帧（含复用 297）、val 816 帧。
- 结果：sha 跨 split **0**；像素近重复对 **0**；同轨迹跨 split **0**；family/group/连续帧泄漏 **0**；同轨迹相邻 3651 对（预期非泄漏）。
- family 隔离：复用 family = lmf_sweep / backoff / near / edge / similar_negative / side_negative，全部 train；v4 val family = fam_north / fam_inner_north / fam_static_low_oblique / fam_HN1_confuser / fam_HN2_occluder → **无 family ID 重叠**，复用组不进入 val。
- 需要知情的邻接（均已登记、非本次泄漏）：旧 final 池与 dev 的最近起点 lmf_edge vs pilot_east_center 0.30 m/yaw 0.60 rad、similar_negative vs pilot_east_away 0.54 m/同 yaw；最接近图像对 mean abs ≥7.69/255，高于近重复阈值；这些 dev 组均不在 val（pilot 系列在 train），因此不构成 train-val 泄漏。
- 阈值：16×12 灰度 mean abs ≤2.0 预筛 + 全分辨率 mean ≤3.0/max ≤40 确认；sha 单独检查；启发式不替代人工视觉复核。

## 4. 外部产物索引

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v4_1_20261104.json`（**PASS**）。

- 16 数据集 / 3695 帧：PNG 可读 320×240、逐帧 sha256 与清单一致、observations sha 一致；0 缺失 / 0 不匹配。
- ignored `outputs/` 仍是唯一原始位置；仓库只存 freeze/registry/清单/hash/报告；外部备份仅建议、未上传。

## 5. exposure_registry_v2 更新

- 文件 sha `a98cce2d…`；`revision_for_freeze='v4_1'`；`freezes` 含 dev_v4 / old_exploratory / dev_v4_1。
- 32 组全部 `exposed_development`、0 exploratory、0 untouched；旧 final 6 组仍为 development（且现被用作 train）；新增事件 `ev_exploratory_reused_as_train_20261104`。
- 校验证据：`landmark_exposure_registry_v2_verify_20261104.json` PASS 0 error/0 warning（sources=dev_v4_1）。
- identity_certification 仍记录 U1/U2 FALSIFIED（MS1）；identity 认证 INCOMPLETE。

## 6. holdout

- `configs/perception/landmark_holdout_freeze_v1.json` status **NOT_TRIGGERED**（file sha `958ebf48…`，gate sha `7c81ae51…`）：improvement gate 尚未评估；无 holdout 数据/采样；采样与覆盖规则已预注册、不可在看到触发结果后重定。

## 7. 复现与测试

`@powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py scripts/verify_landmark_dataset.py --build --profile v4_1 --freeze configs/perception/landmark_split_freeze_v4_1.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v4_1_20261104.json
& $py scripts/verify_landmark_dataset.py --build-exposure-registry-v2
& $py scripts/verify_landmark_dataset.py --audit-near-duplicates --audit-freezes configs/perception/landmark_split_freeze_v4_1.json --audit-seal none --audit-output docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v4_1_20261104.json
& $py scripts/verify_landmark_dataset.py --external-index --index-freezes configs/perception/landmark_split_freeze_v4_1.json --index-seal none --index-output docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v4_1_20261104.json
& $py -m pytest -q tests/evaluation/test_landmark_dataset.py
`@

| 证据 | 结果 |
| --- | --- |
| v4.1 冻结校验 | PASS，0 error，161 warning |
| 暴露登记 v2 校验 | PASS，0 error / 0 warning |
| 泄漏/近重复审计 v4.1 | PASS，0 泄漏 / 0 近重复 |
| 外部产物索引 v4.1 | PASS，3695/3695 帧 |
| dataset 专项 pytest | **49 passed** |
| 全量 pytest | 其他进行中模块存在失败（posteval import / onnx / train_cli），与 v4.1 文件无关 |

## 8. 使用边界（对 train / candidate A）

1. 候选 A 训练用 v4.1 train：**439 帧有标签**（160 dev + 279 复用 exploratory）+ 其余 v4 train 未标注帧不得当有标签数据；val 用 v4 val 163 标注帧（816 帧全量清单不变）。
2. 复用 279 帧已用于训练 → 旧 exploratory 指标不可再当 fair final；任何 final 必须来自**新采集、未触碰**数据（holdout 触发后另行冻结）。
3. v4.1 不改变 HN/GT_UNOBSERVABLE 口径：HN2 GT_UNOBSERVABLE 不是负例、不评定位/不进四格；undecidable 排除；HN1 合成来源注明。
4. identity 案例（T15 已完成采集、T19 未标注）属 v4.2，不并入本版本；identity 认证仍 INCOMPLETE（MS1 证伪 U1/U2）。
5. 所有结论仍为数据/清单 QA，不是模型效果、板端、导航或 Gate 验收。
