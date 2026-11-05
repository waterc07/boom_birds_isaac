# 地标 two-class 数据冻结 v6 / v6.1（B-lite）与运行快照 v7（2026-11-05）

> **状态：** PASS（v6.1 冻结 / 标签策略 B-lite / 泄漏审计 / 外部产物索引 / snapshot v7 22 artifacts VALID）；v6（A 方案）保留为历史；两类别仅限定域（central_tower vs map-native MS1），不是开放集身份识别；模型效果/板端/导航 NOT RUN
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json（PRE_REGISTERED）、landmark_two_class_label_spec_v1.json（FROZEN）；task-36 任务书；diag T35 MS1 投影风险
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真采集/标注产物索引（离线只读；未运行 Isaac、未训练、未上传数据；旧包 47d1063 封闭未改）
> **最后核对：** 2026-11-05（仓库 E:\isaac\proj_boom_birds，分支 feat/v2.2-simulation-perception，开工 HEAD 47d1063；未 commit/push）

## 0. 结论摘要

- **当前数据版本 = v6.1（B-lite）**：`configs/perception/landmark_split_freeze_v6_1.json`
  - canonical sha256 `3532df1a48c240e61966251443583fd8a92c9f210a65c905e0c5145d2f98ba48`
  - file sha256 `99b0cd536ffc0ea762d115e4cf89619cddf2af7ba4e6f150714f7223b5bc9df0`
  - **train 24 组 / 2288 帧** = v4.1 tower train 16 组/1772 + T30 two-class 8 组/516（训练 pool 373）
  - **val 14 组 / 1006 帧** = val_main 7 组/816（163 tower 标签 + MS1 附加 47）+ T19 identity 7 组/190（62 标签，两类）
  - test 0；excluded 9 组/1107；合计 4401；verify PASS 0 error（176 warning 既有 warmup/历史类）。
- **v6（A 方案）为历史版本**：`landmark_split_freeze_v6.json` canonical `657b2505…`、file `8f345b97…`；A 方案排除 69 帧（v4.1 保留 367），已被 v6.1 取代但不删除。
- **v6.1 B-lite 标签策略**：v4.1 436 实际训练输入中，**60 帧有 class1 addendum 保留**（annot 38 同框 + annot2 22），**9 帧未被 addendum 覆盖的投影风险帧排除**（v4.1 保留 427）；T30 pool 373 全标注。
- **实际标注计数**：T30 pool frames **373/373**；class0 **232** instances（shard A 136 + B 96）；class1 **123**（A 84 + B 39）；addendum class1 **+60**；**class1 合计 183**；same-frame **39+38=77**；全分类别 v=0 且无 keypoint；class1 仅 map-native MS1（合成 HN1 不入 class1 GT，列 other_structures）。
- **泄漏审计 PASS**：train-val sha 0、像素近重复 0、同轨迹跨 split 0（同轨迹相邻 4342 预期）；family/group 无跨 split。**外部索引 PASS**：4401/4401 帧 PNG 可读、逐帧 sha 一致。
- **snapshot v7**：`configs/perception/landmark_run_snapshot_v7.json` sha `7d95c72d89e8dec13bd8485ce47520f52571d959c8586eab8f2a4ebe951c5c13`；**25 tracked artifacts 全部存在且 dry-create --verify VALID**（fingerprint match，0 mismatch），phases pre_train/pre_selection/post_train，on_mismatch=INVALID。
- **holdout v3 预注册**：`landmark_holdout_freeze_v3.json` sha `0a1fb8d7…` status SPEC_FROZEN_NOT_TRIGGERED（v2 不改）；等 two-class consumer 门判定。
- **T25/T26 仍未纳入**（v5 起即排除，formal OOM/PROVISIONAL）：本包 v6/v6.1 不使用 T25 数据。

## 1. v6 → v6.1 delta

| 项 | v6（A，历史） | v6.1（B-lite，当前） |
| --- | --- | --- |
| split 结构 | train 24/2288、val 14/1006、excluded 9/1107、total 4401 | 完全一致 |
| v4.1 two-class 输入 | 436 − 69 = **367** | **427**（436 − 9 未覆盖风险帧） |
| addendum | 无（排除 69） | **60 帧 class1**（38 同框 + 22 空帧） |
| class1 instances | T30 123 | **183**（123 + 60） |
| same-frame | 39 | **77**（39 + 38） |
| 状态 | 历史版本 | **当前冻结** |

- freeze.two_class.train_v41_exclusion：status `APPLIED_B_LITE_9_UNCOVERED_EXCLUDED`，excluded_frames 9、covered_by_addendum 60、included_frames 427；risk_evidence `e5e83b15…`。
- freeze.two_class.v41_train_ms1_addendum_gate：status `PASS_ADDENDUM_B_LITE_9_EXCLUDED`（60/69 有 class1，9 帧有明确排除记录）。

## 2. 数据与标签来源

| 内容 | 路径 / sha256 |
| --- | --- |
| v6.1 freeze | configs/perception/landmark_split_freeze_v6_1.json（file 424642d4… / canonical fe3fa426…） |
| T30 capture | outputs/sensor_shadow/lm_two_class_train_20261105{,_sensor}；run.complete PASS；raw RGB 516 / accepted 492；**pool 373**（采集前规则：raw accepted>420 时 i%4!=3，非检测器分数/非随机） |
| T30 cases | configs/scenarios/landmark_two_class_train_cases_v1.json（8 families，CAP_FIELD 采集辅助区） |
| T30 frame conditions/provenance | docs/reports/perception/capture_dev_20261104/two_class_train_20261105/t30_frame_conditions.json（492 行，in_pool 标志）、t30_provenance_20261105.json、t30_dedup_vs_existing.json（22 个既有 sensor sha 交集 0）、t30_overlap_vs_existing_families.json（无相同 waypoint 序列） |
| shard A labels | outputs/perception/dev_annotations_20261105/two_class/shard_a/labels_v1.json sha 8874eb79…（181 pool；class0 136/class1 84/同框 39；QA PASS 181/181） |
| shard B labels | outputs/perception/dev_annotations_20261105/two_class/shard_b/labels_v1.json sha fe38e4a3…（192 pool；class0 96/class1 39；QA PASS 192/192） |
| v4.1 addendum annot | outputs/perception/dev_annotations_20261105/two_class/v41_ms1_addendum/labels_addendum.json sha d08514aa…（38 同框帧 class1，QA PASS） |
| v4.1 addendum annot2 | .../labels_v41_ms1_addendum.json sha 6b59f3c7…（22 帧 class1，QA PASS） |
| v4.1 MS1 risk evidence | docs/reports/perception/dataset_freeze_20261104/two_class_v41_ms1_risk_20261105.json sha e5e83b15…（69 帧 = 38 同框 + 31 空帧；436 分母） |
| val_main tower labels | outputs/perception/dev_annotations_20261104/labels_val_validation163.json sha a9bfda8f…（未改） |
| val_main MS1 addendum | outputs/perception/dev_annotations_20261104/labels_val_main_ms1.json sha 05670eae…；47/163 可见、同框 47、截断 3、远景小 9 |
| identity 标签 | outputs/perception/dev_annotations_20261104/labels_identity_dev.json sha 79fd1745…（62 帧，7 组） |
| two-class protocol/spec | configs/perception/landmark_two_class_protocol_v1.json / landmark_two_class_label_spec_v1.json |

- T30 与既有 22 个 sensor 目录 sha 交集 0；pool 内部无重复；与 T19 identity/既有 dev/final/holdout 草案无相同 waypoint 序列。
- class1 规则：keypoint 恒 null/v=0，不用 bbox 中心替代；MS1 verified=WORLD_POSE_OR_MAP_DB；class1 **永不映射 central tower ID**。
- T30 GT_UNOBSERVABLE 0；f6 远景小 MS1 12 帧 scale_note；f8 负例 46、f6 负例 11。

## 3. 运行快照 v7

- manifest：configs/perception/landmark_run_snapshot_v7.json sha `b6575568…`；schema `dsh.landmark_run_snapshot.v1`，status FROZEN。
- 25 tracked artifacts：v6.1 split；two_class protocol/label spec；annotation spec v2.1；dev train labels；reuse labels；shard A/B labels；v4.1 addendum ×2；v41 risk exclusion；merged train labels；val_main labels；val_main MS1 addendum；identity labels；training/consumer protocol；train CLI config；base weights（stage_verify_v5/seed2 last，sha 6b86ef1f…）；2-class model yaml；dev_v6 dataset_build + data.yaml。
- dry-create + --verify：**VALID**，checked_artifacts 22、fingerprint_match true、mismatches []（snapshot sha 799666a5… 为临时校验文件，不作为正式运行快照）。
- 规则：pre_train/pre_selection/post_train 三次校验；任一 sha/size/缺失 → run INVALID，训练 CLI 非零退出且不写可选模型；快照创建后不重写，check 结果写独立 log。
- train 侧：若已用旧 manifest（7e0e00a0…）--create，需按新 sha 重建；merged labels 必须应用：9 帧排除、T30 仅 pool 373、class1 kpt v=0 loss mask、addendum 60 帧 class1。


## 3b. 冻结评估标签集（P2 harness 直接消费）

- 目的：给 P2 动态 GT-poison smoke 一次性通过 coverage gate（五类均 >0），与 train 不重叠；class1 GT 仅 verified map-native MS1（合成 HN1/其他结构不计 class1 分母）。
- 交接清单：@@docs/reports/perception/dataset_freeze_20261104/two_class_eval_handoff_v1_20261105.json@@ sha @@65cd1a89dda06c55e8459bb0ece73f78fe8b625b3f7143f8a53ea58c632ca0ea@@（eval_set_rule、sets、combined、train_overlap）。
- 集合① val_main：@@outputs/perception/two_class_eval_20261105/eval_val_main_163_two_class.json@@ sha @@d6c6a25249c1c8fd2bf334ae7f9e399e9f69b7ebe0534c79e98fb2fefd934436@@，163 帧；tower_present_observable 95 / GT_UNOBS 29 / negatives 39 / same_frame 47 / ms1_only 0。
- 集合② identity：@@outputs/perception/two_class_eval_20261105/eval_identity_62_two_class.json@@ sha @@7471c408e84c0774425ad852e2c4ab99b14ea1968210f09fbd6b9ff8035d8b17@@，62 帧；tower_present_observable 44 / GT_UNOBS 9 / negatives 0 / same_frame 26 / ms1_only 9。
- **并集（P2 冻结评估集）**：225 帧；五类计数 **139 / 38 / 39 / 73 / 9**（均 >0）；与 train 重叠帧 **0**（v6.1 train 逐一比对，PASS）。
- 记录位置：v6.1 freeze @@two_class.eval_label_sets@@（sets/combined/train_overlap/handoff sha）+ snapshot v7 新增 eval_labels/eval_manifest 三项（共 25 artifacts）。
- 边界：这些是 DEVELOPMENT 评估标签（agent proxy / projection-aid），不是 sealed final；不得用于训练或认证声明。

## 4. 泄漏审计与外部产物索引

- 审计：`landmark_leakage_audit_v6_1_20261105.json`（**PASS**）：train 2288 帧 vs val 1006 帧；near_duplicate_pairs 0、train_val_leakage_pairs 0、dev_exploratory_contamination_pairs 0、same_trajectory_cross_split 0、same_trajectory_adjacent_pairs 4342（预期非泄漏）；sha_cross_set train_val 0/exploratory_dev 0。
- T30 新族 vs val_main / T19 identity / 旧 exploratory：family/group/sha 均无重叠；与 holdout v3 规格无采样帧（尚未采集）。
- 外部索引：`landmark_external_index_v6_1_20261105.json`（**PASS**）：17 数据集 / 4401 帧；png_readable 4401、missing 0、sha_mismatch 0、observations_sha_mismatch 0。
- 阈值：16×12 灰度 mean abs ≤2.0 预筛 + 全分辨率 mean ≤3.0/max ≤40 确认；sha 单独；启发式不替代人工视觉复核。

## 5. 边界与不声明

1. 两类别只做“中央塔 vs 已验证 map-native MS1”的限定域辨识，**不是开放集身份识别**；class1 永不映射 central tower ID。
2. 标注为 AGENT_PROXY/SELF_CHECKED，几何/投影辅助 + 目视抽查，非独立人工 GT；bbox 误差约 ±3–8px。
3. v6/v6.1 均为 DEVELOPMENT；val_main 用于阈值/选模，val_identity 仅 identity/class1 分层报告；不得当 sealed/final。
4. T25/T26 数据不纳入；addendum 9 帧未覆盖缺口以排除处理，待 diag 精确帧列表后可补 v6.2（v6.1 不重开）。
5. 不提升任何 Gate；控制/PPO/板端/导航未接；未 commit/push。

## 6. 复现与验证

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py scripts/verify_landmark_dataset.py --build --profile v6 --freeze configs/perception/landmark_split_freeze_v6.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v6_20261105.json
& $py scripts/verify_landmark_dataset.py --freeze configs/perception/landmark_split_freeze_v6_1.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v6_1_20261105.json
& $py scripts/verify_landmark_dataset.py --audit-near-duplicates --audit-freezes configs/perception/landmark_split_freeze_v6_1.json --audit-seal none --audit-output docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v6_1_20261105.json
& $py scripts/verify_landmark_dataset.py --external-index --index-freezes configs/perception/landmark_split_freeze_v6_1.json --index-seal none --index-output docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v6_1_20261105.json
& $py scripts/landmark_run_snapshot.py --create --config configs/perception/landmark_run_snapshot_v7.json --run-id <run> --out <ignored outputs>
```

| 证据 | 结果 |
| --- | --- |
| v6（A）冻结校验 | PASS，0 error（历史版本） |
| v6.1（B-lite）冻结校验 | PASS，0 error，176 warning |
| 泄漏审计 v6.1 | PASS（0 泄漏 / 0 近重复） |
| 外部索引 v6.1 | PASS（4401/4401 帧） |
| snapshot v7 dry create/verify | VALID（25 artifacts，0 mismatch） |
| dataset 专项 pytest | 见最终验证 |

## 7. 剩余缺口

- 9 帧风险帧无 addendum 被排除；diag 精确 31 帧列表后可补 v6.2（不影响 v6.1）。
- T25/T26 mutual/far MS1 未纳入（v5 起排除）；holdout v3 未触发。
- identity 认证仍 INCOMPLETE（MS1 证伪 U1/U2）；two-class 认证未开始。
- registry v2 仍为 v5 revision；T30/T31/T32/T35 暴露/标注事件待登记（需 lead 授权写域）。
