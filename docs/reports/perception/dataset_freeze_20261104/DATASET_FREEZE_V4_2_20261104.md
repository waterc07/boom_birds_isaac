# 地标 dev 划分冻结 v4.2：identity/confuser 案例并入 val（2026-11-04）

> **状态：** PASS（v4.2 清单 / identity_dev_batch 登记 / 泄漏审计 / 外部产物索引的 QA）；identity 数据为 DEVELOPMENT（非 sealed/final）；模型效果、板端、导航 NOT RUN
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §20.11.1/§20.11.3/Phase 6；configs/perception/landmark_improvement_gate_v1.json；T15/T19 identity development 案例
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真采集/标注产物索引（离线只读；未运行 Isaac、未训练、未上传数据）
> **最后核对：** 2026-11-04

## 0. 结论摘要

- **v4.2 已冻结**：`configs/perception/landmark_split_freeze_v4_2.json`
  - canonical sha256 `7708cd5817208a3013f6058703a70f67cd9db0c8c0ae1ad4d315cfbfb9e31aee`
  - file sha256 `0acbae8766cb183e975b922f72f5be8f98e8e95dce190dc3074255b8f62cc796`
  - **train 16 组 / 1772 帧（1697 accepted，与 v4.1 完全一致）**
  - **val 14 组 / 1006 帧（964 accepted）**：val_main 7 组 / 816 帧（795 accepted，同 v4.1）+ val_identity 7 组 / 190 帧（169 accepted）
  - test 0；excluded 9 组 / 1107 帧（1071）；合计 39 组 / 3885 帧。
  - 校验：**PASS，0 error，168 warning**（155 原有 + 6 复用组 warmup 重复 + 7 identity 组 warmup 重复）。
- **v4.1→v4.2 delta**：`+7 组 / +190 帧`（7 个 identity case 整组进 val）；train 不变；base v4.1 canonical `36840e7f…`。
- **splits_subset**：`val_main` = v4.1 的 7 组（阈值冻结 / checkpoint 选择）；`val_identity` = 7 个 identity/confuser 组（identity/同框歧义/遮挡分层报告）；`train_main` = 16 组。两者都在 val split 内，不跨 split。
- **标注引用**：
  - train：dev 160 + 复用 exploratory 279 = **439 帧**（labels 01977b9f… / 7115ee04…）
  - val_main：**163 帧**，稳定文件 `labels_val_validation163.json` sha `a9bfda8f…`（identity 行已排除，train 固定读取）
  - val_identity：**62 帧**，`labels_identity_dev.json` sha `79fd1745…`（62/62 resolved、0 sha mismatch）
  - lists config `2dceb5fc…`（status `DEV_VAL_HN_COMPLETE_IDENTITY_DEV_INDEPENDENT_PENDING_V4_2`）；spec v2.1 `010255d9…`。
- **泄漏/近重复审计 PASS**：train-val sha 0、像素近重复 0、同轨迹跨 split 0、family/group/连续帧泄漏 0；identity family 与 val_main/train family 无 ID 重叠；同轨迹相邻 3834 对（预期）。
- **外部产物索引 PASS**：17 数据集 / 3885 帧 PNG 可读 320×240、逐帧 sha 与清单一致、obs sha 一致。
- **exposure_registry_v2 已更新**：sha `a367e2a4…`，39 组全部 exposed_development、12 条事件（新增 identity 标注事件）、357 帧 override；`identity_cases_pending=false`。
- **holdout 仍 NOT_TRIGGERED**（improvement gate 未评估）；identity 数据不得称 sealed/final；U1/U2 仍因 map-native MS1 被证伪。

## 1. v4.2 结构

| split / subset | 组数 | 帧数（accepted） | 说明 |
| --- | ---: | ---: | --- |
| train | 16 | 1772（1697） | 与 v4.1 一致（含旧 exploratory 复用 6 组/297 帧/279 accepted） |
| val_main | 7 | 816（795） | 阈值冻结/选模；与 v4.1 val 完全一致 |
| val_identity | 7 | 190（169） | identity/confuser 分层报告；不并入主 joint 阈值选择 |
| test | 0 | 0 | 无 sealed/final |
| excluded | 9 | 1107（1071） | 不变 |
| 合计 | 39 | 3885 | train+val+excluded |

- identity 7 组：target_alone、ms1_alone、both_scale_lateral、both_mid_similar_scale、both_same_bearing、target_near_trunc、full_occlusion；每组一个 case，连续帧不拆 split。
- identity 采集：`outputs/sensor_shadow/lm_dev_identity_capture_20261104_sensor` = **190 RGB / 169 accepted**（7 case：27/24、31/28、22/19、26/23、25/22、27/24、32/29）；run.complete PASS。
- identity 标注（T19）：62 代表帧（每 case ≤10 的系统代表规则）：present 53（含 **9 GT_UNOBSERVABLE**，full occlusion）/ absent 9（MS1 confuser-only，SIMILAR_STRUCTURE + verified MS1）/ ambiguous 0 / undecidable 0；keypoint 18；confusers 35（全 verified）；截断 16（right 16、bottom 9）。
- MS1 是 **map-native**（map probe verified，非注入）；本批唯一合成注入是 `hn2_occluder_v1`（EXTERNAL_EVIDENCE + SYNTHETIC_INJECTED，非真实分布）；full occlusion 全部 GT_UNOBSERVABLE，**不是负例**。
- identity 判定只用外观；几何候选仅作 bbox draft，未用 GT 位置/oracle；ambiguous=0 为实测判定（未虚构）。

## 2. 用法边界（对 train / 评测）

1. **阈值/checkpoint 选择用 val_main（163 标注帧/816 帧）**，保持与 candidate A 的 v4.1 val 可比；identity 指标在 val_identity 分层报告，若要混入主 joint 阈值选择必须显式记录，不能默认混用。
2. identity 数据是 **DEVELOPMENT**，不是 sealed/final；不得用于任何 final 认证声明。
3. full_occlusion 的 GT_UNOBSERVABLE（29 accepted 帧，62 标注中 9 帧）不评定位、不进 presence 四格、训练损失排除，**不是负例**；ms1_alone/both 的 MS1 是 map-native confuser，negative_type=SIMILAR_STRUCTURE。
4. **candidate A 继续用 v4.1**；其 matched baseline 用 **v4 train（不含 reuse）**，不得用 v4.1 train 做 baseline（否则会抵消 A 的变更）。
5. 旧 exploratory 池已在 v4.1 作为 train；旧 exploratory 指标只能作 traceability，不能当 fair final。
6. identity labels 保持独立文件，不并入 labels_val.json / labels_val_validation163.json。

## 3. 泄漏 / 近重复审计

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v4_2_20261104.json`（**PASS**）。

- 集合：train 1772 帧、val 1006 帧（含 val_identity 190）。
- 结果：sha 跨 split **0**；像素近重复对 **0**；同轨迹跨 split **0**；family/group/连续帧泄漏 **0**；同轨迹相邻 3834 对（预期非泄漏）。
- family 隔离：identity family（devid_*）与 val_main/train family 无重叠；identity 组全部在 val_identity。
- 阈值：16×12 灰度 mean abs ≤2.0 预筛 + 全分辨率 mean ≤3.0/max ≤40 确认；sha 单独检查；启发式不替代人工视觉复核。
- 已知邻接：identity 采集与既有 18 个 *_sensor sha 交集 0、无相同 waypoint 序列（capture 已核对）；map-native MS1 与 T9 static_negative 中同一结构的世界位姿一致，属同一物理结构的合法多视角（不是跨 split 重复帧）。

## 4. 外部产物索引

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v4_2_20261104.json`（**PASS**）。

- 17 数据集 / 3885 帧：PNG 可读 320×240、逐帧 sha256 与清单一致、observations sha 一致；0 缺失 / 0 不匹配。
- ignored `outputs/` 仍是唯一原始位置；仓库只存 freeze/registry/清单/hash/报告；外部备份仅建议、未上传。

## 5. exposure_registry_v2 更新

- 文件 sha `a367e2a4bf459ac72f351ac407d8798d3db97c1e4736453cef253f650dac68b7`；`revision_for_freeze='v4_2'`；freezes 含 dev_v4 / old_exploratory / dev_v4_1 / dev_v4_2。
- 39 组全部 `exposed_development`、0 exploratory、0 untouched；12 条事件（新增 `ev_identity_dev_annotation_20261104`；identity capture 事件 ingest_status=INGESTED_V4_2）；357 帧 override。
- identity_certification：U1/U2 FALSIFIED（map-native MS1）；identity INCOMPLETE。
- 校验证据：`landmark_exposure_registry_v2_verify_20261104.json` PASS 0/0（sources=dev_v4_2）。

## 6. holdout

- `configs/perception/landmark_holdout_freeze_v1.json` status **NOT_TRIGGERED**（gate 未评估）；本 v4.2 不改变 holdout 条件与预注册规则。

## 7. 复现与证据

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py scripts/verify_landmark_dataset.py --build --profile v4_2 --freeze configs/perception/landmark_split_freeze_v4_2.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v4_2_20261104.json
& $py scripts/verify_landmark_dataset.py --build-exposure-registry-v2
& $py scripts/verify_landmark_dataset.py --audit-near-duplicates --audit-freezes configs/perception/landmark_split_freeze_v4_2.json --audit-seal none --audit-output docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v4_2_20261104.json
& $py scripts/verify_landmark_dataset.py --external-index --index-freezes configs/perception/landmark_split_freeze_v4_2.json --index-seal none --index-output docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v4_2_20261104.json
& $py -m pytest -q tests/evaluation/test_landmark_dataset.py
```

| 证据 | 结果 |
| --- | --- |
| v4.2 冻结校验 | PASS，0 error，168 warning |
| 暴露登记 v2 校验 | PASS，0 error / 0 warning（39 组、12 事件、357 override） |
| 泄漏/近重复审计 v4.2 | PASS，0 泄漏 / 0 近重复 |
| 外部产物索引 v4.2 | PASS，3885/3885 帧 |
| dataset 专项 pytest | **50 passed** |
| 全量 pytest | 其他进行中模块（posteval import 等）仍有失败，与 v4.2 文件无关 |

## 8. 剩余缺口

- identity 数据为单代理标注、单仿真资产、合成域；MS1 为 map-native 但只代表当前资产；不构成真实赛场泛化证据。
- U1/U2 仍被 MS1 证伪：identity 认证 INCOMPLETE；identity 指标只能按多候选/UNKNOWN 分层报告。
- holdout 未触发、无 untouched final；A3/A8 仍 INCOMPLETE。
- val_identity 若用于阈值/选模必须显式记录；默认只用于分层报告。
