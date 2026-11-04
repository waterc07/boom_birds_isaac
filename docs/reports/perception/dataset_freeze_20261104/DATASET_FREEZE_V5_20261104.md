# 地标 dev 划分冻结 v5：identity train/val 划分与不可变运行快照（2026-11-04）

> **状态：** PASS（v5 冻结 / identity train-val 划分 / 泄漏审计 / 外部产物索引 / 暴露登记 v2 v5 revision / dataset 测试 53 passed）；T25/T26 新 case **EXCLUDED/INCOMPLETE**（formal run CUDA OOM、pilot 机位未确认，不伪造）；运行快照 v5 已冻结；模型效果、板端、导航 NOT RUN
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §20.11.1/§20.11.3/Phase 6；configs/perception/landmark_improvement_gate_v1.json；LANDMARK_DIAGNOSIS_AND_IMPROVEMENT_RESULTS_20261104.md（identity 缺口与 STOP 结论）
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真产物索引（离线只读；未运行 Isaac、未训练、未上传数据；本轮遵守资源协调暂停重 CPU 任务）
> **最后核对：** 2026-11-04 21:33

## 0. 结论摘要

- **v5 已冻结**：`configs/perception/landmark_split_freeze_v5.json`
  - canonical sha256 `7815936c9cf2d7c5f23cf6160bab455bf85259e2afb90596a5ca1d261be3f358`
  - file sha256 `55976eaf7ba70cabbcccff4eafe34017ed00af7671d408a11858df593ac73a0f`
  - **train 19 组 / 1857 帧（1773 accepted）** = v4.1 train 16 组/1772 + identity train 3 组/85（76 accepted）
  - **val 11 组 / 921 帧（888 accepted）** = val_main 7 组/816（795） + val_identity 4 组/105（93）
  - test 0；excluded 9 组/1107（1071）；合计 39 组 / 3885 帧；verify PASS 0 error（168 warning，均为既有 warmup/历史类）
- **v4.2→v5 delta**：无新增数据集（T25 未纳）；3 个 identity 组 val→train（整组移动，不拆帧）；total 3885 帧不变。
- **identity 划分**：train = target_alone / target_near_trunc / ms1_alone（身份正例 + MS1 confuser 负例）；val_identity = both_scale_lateral / both_mid_similar / both_same_bearing / full_occlusion。组不跨 split、独立轨迹族。
- **标注**：train 439+27=**466 帧可用**（dev 160、reuse exploratory 279、identity train 27）；val_main **163 帧**（稳定文件 a9bfda8f…）；val_identity **35 帧**（labels_identity_dev 79fd1745…）；spec v2.1 010255d9…。
- **运行快照 v5**：`configs/perception/landmark_run_snapshot_v5.json`（file sha `@deedb9b4f6f18d0986ef27034c8bec916cd5eb775e8beac326a1ca3134059680`）：tracked_artifacts 13 项（split/labels×5/spec/protocol×3/gate/model/dataset×2），phases pre_train/pre_selection/post_train，on_mismatch=INVALID；与 train 的 scripts/landmark_run_snapshot.py 对齐（v1 保留给 v4.1 candidate A runs）。
- **holdout**：`configs/perception/landmark_holdout_freeze_v2.json`（sha `6d24e26f0ebfcee7a048a1522d4a181a64f5b971c8101fc81855e9c6c3bcb1ca`）status **SPEC_FROZEN_NOT_TRIGGERED**：≥3 新族/200–400 帧、6 类覆盖（近距 1.5–3m、远景小目标、边缘截断、MS1 单独、同框歧义、目标缺席）、固定 midpoint systematic 抽样、一次性评测；improvement gate STOP 未触发。
- **T25/T26 缺口**：T25 formal run CUDA OOM 无 run.complete、pilot 机位未确认；T26 已标 28 帧（labels sha **7164a5d6…（顶层 status=PROVISIONAL_DIAGNOSTIC_ONLY，annotations 内容 sha 82b5c392…）**，QA PASS 28/28）但来源为 pilot、未确认 → **v5 不含 mutual/far 组与标签**；报告标 INCOMPLETE，待 capture 确认后另立版本，不伪造。
- **泄漏审计 PASS**：train-val sha 0、像素近重复 0、同轨迹跨 split 0（同轨迹相邻 3834 对预期）；**外部索引 PASS**：17 数据集/3885 帧 PNG 可读、逐帧 sha 与清单一致。
- **暴露登记 v2**：重建后 sha `1658a145…`，39 组全 exposed_development、14 事件（新增 T25 capture 失败/T26 provisional/v5 revision）、357 覆盖、verify PASS 0/0；修复此前 evidence sha mismatch。

## 1. v5 结构与 delta

| split / subset | 组数 | 帧数（accepted） | 说明 |
| --- | ---: | ---: | --- |
| train | 19 | 1857（1773） | v4.1 train 16 组/1772 + identity train 3 组/85 |
| val_main | 7 | 816（795） | 与 v4.1/v4.2 val_main 完全一致（阈值/选模） |
| val_identity | 4 | 105（93） | both×3 + full_occlusion（身份/同框/遮挡分层报告） |
| test | 0 | 0 | 无 sealed/final |
| excluded | 9 | 1107（1071） | 不变 |
| 合计 | 39 | 3885 | train+val+excluded |

- v4.2→v5 split_changes：g_devid_target_alone、g_devid_ms1_alone、g_devid_target_near_trunc 由 val→train（整组，不拆连续帧）；无新增/删除帧。
- identity 组细节：train target_alone 27/24、ms1_alone 31/28、near_trunc 27/24；val both_scale_lateral 22/19、both_mid_similar 26/23、both_same_bearing 25/22、full_occlusion 32/29。
- 旧 exploratory 279 帧仍是 DEVELOPMENT_TRAIN（v4.1 起），不得再作 final；v5 保持登记。

## 2. 标注来源与分母

- train：dev 160 帧 `01977b9f…`；reuse exploratory 279 帧 `7115ee04…`；identity train 代表帧 27 帧（labels_identity_dev：target_alone 9 / near_trunc 9 / ms1_alone 9）→ **466 帧可用**。
- val_main：163 帧稳定文件 `labels_val_validation163.json` sha `a9bfda8f…`（identity 行已排除，训练固定读取）。
- val_identity：35 帧（both_scale_lateral 8 + both_mid 9 + both_same_bearing 9 + full_occlusion 9），labels_identity_dev sha `79fd1745…`。
- identity 口径：target_alone 全 present；ms1_alone 全 absent（TARGET_ABSENT，MS1 map-native confuser verified=WORLD_POSE_OR_MAP_DB，negative_type=SIMILAR_STRUCTURE）；full_occlusion 为 present+occluded、bbox/keypoint null、reference UNAVAILABLE 的 **GT_UNOBSERVABLE**，不是负例；both_* 为 BOTH_TARGET_IDENTIFIED（各配 verified MS1 confuser）。
- 全遮挡/歧义帧不评定位、不进 presence 四格，但必须单列；undecidable/ambiguous 不入训练损失。

## 3. 运行快照 v5（不可变）

- manifest：`configs/perception/landmark_run_snapshot_v5.json`（file sha `deedb9b4…`），schema `dsh.landmark_run_snapshot.v1`，status FROZEN。
- tracked_artifacts（13）：split_freeze_v5；dev_train_labels；reuse_train_labels；identity_train_labels；train_merged_labels；val_main_labels；annotation_spec_v2_1；training_protocol；improvement_protocol；improvement_gate；train_cli_config；model_yaml；dataset_build_v5；dataset_data_yaml。
- checks.phases = pre_train / pre_selection / post_train；规则：任一 sha/size/缺失 → 整次运行 INVALID，训练 CLI 必须非零退出且不写出可选模型；快照创建后不再重写，校验结果写独立 check log。
- 与 train 对接：scripts/landmark_run_snapshot.py --create/--verify/--record-check 完全 config 驱动；训练 CLI 以 --run-snapshot-config 指定本文件；v1 manifest（T22，v4.1 candidate A runs）保留不覆盖。
- 期望：train 在 --prepare-dataset 生成 merged labels 与 dev_v5 dataset 后再 --create；当前这 3 个文件尚不存在，属预期（create 时须存在）。

## 4. 泄漏审计与外部产物索引

- 泄漏审计：`docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v5_20261104.json`（见证据；对 train 1857 帧 vs val 921 帧做 sha / 像素近重复 / 同轨迹跨 split / family-group 检查；identity train 3 组 vs val_main / val_identity / 旧 exploratory train）。
- 外部产物索引：`docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v5_20261104.json`（17 数据集 / 3885 帧 PNG 可读、shas 与清单一致）。
- 审计阈值：16×12 灰度 mean abs ≤2.0 预筛 + 全分辨率 mean ≤3.0/max ≤40 确认；sha 单独；启发式不替代人工视觉复核。

## 5. T25/T26 缺口（INCOMPLETE，不伪造）

- T25 目标：mutual-occlusion（目标与 MS1 前后景重叠）+ far-MS1（8–12 m），60–120 accepted。
- 实际：run `outputs/sensor_shadow/lm_dev_identity_capture_t25_20261104` 有 91 RGB/85 accepted 的 pilot 数据（sha 与既有 identity 0 重叠），但 **formal run CUDA OOM 无 run.complete、pilot 机位有问题**；capture 未确认。
- T26：annot 已基于 pilot 图像标 28 帧（mutual 14 / far 14；labels 顶层 status=**PROVISIONAL_DIAGNOSTIC_ONLY**、sha `7164a5d6…`（annotations 内容 sha 82b5c392…），selection `1ddb0931…`，QA `0c85d5ed…`，28/28 PASS；mutual present+occluded+PARTIAL、reference UNAVAILABLE，far present=false+TARGET_ABSENT+SIMILAR_STRUCTURE、MS1 verified）；但来源未确认 → **不纳入 v5**。
- 处置：v5 identity_extra_cases.status=`EXCLUDED_T25_PENDING_CAPTURE_CONFIRMATION`、`t26_provisional_diagnostic_only=true`；待 capture 确认/重采后另立 v6（或 v5.1）纳入，届时重新冻结快照；不得把 28 帧当正式 val_identity。

## 6. holdout 预注册（SPEC_FROZEN_NOT_TRIGGERED）

- 文件：`configs/perception/landmark_holdout_freeze_v2.json` sha `6d24e26f…`；v1 placeholder 保留为历史，v2 为当前规格。
- 触发：development→holdout gate（improvement gate sha 7c81ae51…）通过后由 lead 触发；当前 improvement STOP，无 holdout 采集。
- 规格：≥3 新族、200–400 帧；6 类覆盖（近距 1.5–3.0m large、远景 small/far、边缘截断、MS1 confuser 单独、同框歧义、目标缺席；每类最少 30–40 帧，合计 minima 200）；每族独立物理轨迹，组/帧不跨 split、不复用既有帧。
- 抽样：采样前冻结、按 family accepted 帧序 midpoint systematic、端点/极值条件强制、**不按预测质量选帧**、事后不得重采样。
- 标注/评测：spec v2.1+；独立文件 + hash + 谁看过/用途/时点；一次性评测（runs=1），模型/阈值/解码/评价规则先冻结，不回调/不重调/不重跑；失败按分母报 FAIL/INCOMPLETE。
- 触发后填 captured_run/frames/hashes 到**新** holdout 文件，v2 永不重写。

## 7. 复现与验证

`@powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py scripts/verify_landmark_dataset.py --build --profile v5 --freeze configs/perception/landmark_split_freeze_v5.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v5_20261104.json
& $py scripts/verify_landmark_dataset.py --audit-near-duplicates --audit-freezes configs/perception/landmark_split_freeze_v5.json --audit-seal none --audit-output docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v5_20261104.json
& $py scripts/verify_landmark_dataset.py --external-index --index-freezes configs/perception/landmark_split_freeze_v5.json --index-seal none --index-output docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v5_20261104.json
& $py -m pytest -q tests/evaluation/test_landmark_dataset.py
`@

| 证据 | 结果 |
| --- | --- |
| v5 冻结校验 | PASS，0 error，168 warning |
| 泄漏审计 v5 | PASS（0 泄漏/0 近重复；同轨迹相邻 3834 预期） |
| 外部产物索引 v5 | PASS（3885/3885 帧 PNG 可读、sha 一致） |
| 快照 manifest | FROZEN（sha `deedb9b4…`）；create 前需 train 生成 merged/dev_v5 三文件 |
| 暴露登记 v2（v5 revision） | sha `1658a145…`；39 组/14 事件/357 override；verify PASS 0/0；T25 FAILED（OOM）与 T26 PROVISIONAL 已登记 |
| holdout v2 | SPEC_FROZEN_NOT_TRIGGERED |
| dataset 专项 pytest | **53 passed**（含 v5 freeze / registry v5 / snapshot v5 / holdout v2 测试） |

## 8. 使用边界

1. train 用 v5 train（19 组/1857 帧；466 帧有标签）；val 选模/阈值只用 **val_main**（163 标注帧）。
2. val_identity 只做 identity/同框/遮挡分层报告；若混入主 joint 阈值选择必须显式记录。
3. identity 数据 DEVELOPMENT，非 sealed/final；U1/U2 仍被 map-native MS1 证伪，identity 认证 INCOMPLETE。
4. 旧 exploratory 已训练，旧 exploratory 指标不得当 fair final；candidate A/baseline 使用各自冻结快照。
5. T25/T26 未纳入，mutual/far MS1 缺口保持 INCOMPLETE；不得用未确认 pilot 数据冒充正式 val。
6. 本报告与全部 v5 配置不提升任何 Gate；控制/PPO/板端/导航未接。