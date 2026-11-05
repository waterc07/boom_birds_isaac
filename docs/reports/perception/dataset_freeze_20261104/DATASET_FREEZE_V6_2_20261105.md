# 地标 two-class 数据冻结 v6.2（+终版近距 MS1）与运行快照 v7b（2026-11-05）

> **状态：** PASS（v6.2 冻结 / T38 final 标签 / 泄漏审计 / 外部产物索引 / snapshot v7b 34 artifacts VALID）；discarded pilot 未登记；v6/v6.1/v7 保留历史；两类别限定域（central_tower vs map-native MS1），非开放集身份识别；模型效果/板端/导航 NOT RUN
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json、landmark_two_class_label_spec_v1.json；task-40 任务书；diag T35 MS1 风险与 R2 选模规则
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真采集/标注产物索引（离线只读；未运行 Isaac、未训练、未上传数据；旧包 47d1063 未改）
> **最后核对：** 2026-11-05（仓库 E:\isaac\proj_boom_birds，分支 feat/v2.2-simulation-perception，开工 HEAD 47d1063；未 commit/push）

## 0. 结论摘要

- **当前数据版本 = v6.2**：`configs/perception/landmark_split_freeze_v6_2.json`
  - canonical sha256 `d8ad5ca033be0f9655db5d32e4f69224a7d947bb1bc7b28375acc3a75e1d8cd0`
  - file sha256 `71a4eef0305402fab66fdbe002165f20b246d6aa97a636298550a7ff71d4491c`
  - **train 26 组 / 2396 帧** = v6.1 train（v4.1 16 组/1772 + T30 8 组/516）+ T38 final 近距 MS1 2 组/108（pool 102）
  - **val 14 组 / 1006 帧** = val_main 7/816（163 tower 标签 + MS1 addendum 47）+ T19 identity 7/190（62 标签）
  - test 0；excluded 9 组/1107；合计 4509；verify PASS 0 error（178 warning 既有 warmup/历史类）
- **v6.1→v6.2 delta**：+2 组 / +108 RGB 帧（accepted 102）；val 不变；v6/v6.1 保留历史。
- **T38 final 标签（discarded pilot 未登记）**：shard A 52 帧 labels `deef8284f46384c218b77bc6f90a9a7c7cfa77781b3e4950b4bee9b9817bf504`（selection cc35eb2e…、qa f6b0b7f1…）；shard B 50 帧 labels `bfb73d6828c1d3711376ea304a348e77200e4d73c9ad8b3acbd84b3449f00f49`（selection 6f3d9af0…、qa 7926090c…）；A∩B=0、A∪B=102=final pool。
- **计数**：T30 class0 232 / class1 123 / same-frame 39；v4.1 addendum class1 60；T38 class1 **102**（class0 0、same-frame 0）；**class1 合计 285**；T30 pool frames 373。
- **class1 bbox 高度分布（px）**：T30 n123 42.3/56.99/104.34/114.1；near-MS1 n102 **184.1/209.35/220.15/226.7**；addendum n60 20.1/27.8/56.08/68.9；合计 n285 20.1/93.16/214.52/226.7（min/median/p90/max）。
- **泄漏审计 PASS**：train-val sha 0、像素近重复 0、同轨迹跨 split 0（同轨迹相邻 4448 预期）；family/group 无跨 split。**外部索引 PASS**：4509/4509 帧 PNG 可读、逐帧 sha 一致。
- **snapshot v7b**：`configs/perception/landmark_run_snapshot_v7b.json` sha `5daef9824dd0a2538f2fd422fc5bf4a2fcefacb1d86df5407bf813030c7b200e`（旧 ec0ea6e9 作为历史副本归档，见 SNAPSHOT_V7B_RELEASE_NOTE_20261105.md）；**34 tracked artifacts 全部存在、dry create/--verify VALID（0 mismatch）**；含 R2 选模规则 sha `4d486b3e95c35d35…`、T38 final pool/conditions/provenance、eval union、base weights 6b86ef1f。
- **eval 标签集不变**：v6.1 冻结的五类评估集（val_main 163 + identity 62，union 225；139/9/73/38/39）继续有效，union 文档 sha `a188fca7…` 已登记。

## 1. v6.1 → v6.2

| 项 | v6.1 | v6.2 |
| --- | --- | --- |
| train | 24 组 / 2288 帧 | **26 组 / 2396 帧**（+T38 2 组/108） |
| val | 14 组 / 1006 帧 | 14 组 / 1006 帧（不变） |
| excluded | 9 / 1107 | 9 / 1107 |
| 合计 | 4401 | 4509 |
| class1 实例 | 183 | **285**（+102 near-MS1） |
| same-frame | 77 | 77（near 无同框，塔均在 FOV 外） |

- T38 两族：g_t38_f1_ms1_near_north（f1 近距北视角）、g_t38_f2_ms1_near_se（f2 近距东南视角）；整组进 train，不跨 split；class1 only。
- final run：outputs/sensor_shadow/lm_two_class_near_ms1_20261105{,_sensor}，run.complete PASS 2/2（12:30:41），raw 108 / accepted 102；pool 102（N=1，90–120 内全保留，非分数/随机选择）。
- discarded pilotA（108 帧/旧标签 46ab0f39…/a2da4339…）仅审计归档，不进入任何冻结/训练。

## 2. 数据与标签来源

| 内容 | 路径 / sha256 |
| --- | --- |
| v6.2 freeze | configs/perception/landmark_split_freeze_v6_2.json（file 71a4eef03… / canonical d8ad5ca03…） |
| T30 pool 373 | outputs/perception/dev_annotations_20261105/two_class/shard_a|b/labels_v1.json（8874eb79… / fe38e4a3…） |
| v4.1 addendum 60 | .../v41_ms1_addendum/labels_addendum.json（d08514aa…，38 同框）+ labels_v41_ms1_addendum.json（6b59f3c7…，22） |
| T38 A 52 | outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a/labels_v1.json（deef8284…） |
| T38 B 50 | .../near_ms1/shard_b/labels_v1.json（bfb73d68…） |
| T38 final pool/conditions | docs/reports/perception/capture_dev_20261104/two_class_near_ms1_20261105/t38_pool_selection.json（102）+ t38_frame_conditions.json + t38_provenance_20261105.json |
| val_main | labels_val_validation163.json（a9bfda8f…）+ labels_val_main_ms1.json（05670eae…，47/163） |
| identity | labels_identity_dev.json（79fd1745…，62 帧 7 组） |
| R2 选模规则 | outputs/landmark_train/runs/r2_selection_rule.json（4d486b3e…） |
| eval 集 | val_main union 文档（d6c6a252… / 7471c408… / union a188fca7…） |

- T38 class1 规则：v=0、keypoint null、仅 map-native MS1；f1 红色灯臂结构记 other_structures，不标 class1；截断 bottom 39/50 帧，QA 触边通过。
- class1 高度分布覆盖远/中/近：T30 42–114 px、addendum 20–69 px、near 184–227 px。

## 3. 运行快照 v7b

- manifest：configs/perception/landmark_run_snapshot_v7b.json sha `5daef982…`（旧 ec0ea6e9 仅历史副本）；schema dsh.landmark_run_snapshot.v1，status FROZEN。
- 34 tracked artifacts：v6.2 split；two-class protocol/spec；annotation spec；dev/reuse labels；addendum×2；T30 shard A/B + val MS1 + identity；T38 shard A/B labels/selection/qa；T38 pool/conditions/provenance；eval val/identity/union/handoff；R2 selection rule；training/consumer protocol；train CLI config；base weights（6b86ef1f）；2-class model yaml；dev_v7 dataset_build/data.yaml；labels_train_v6_2_merged.json。
- dry create + --verify：**VALID**（checked_artifacts 34、fingerprint_match true、mismatches []）。
- train 生成 merged labels/dev_v7 后 --create；R2 选模规则与数据/标签一起被 hash 锁定。

## 4. 泄漏审计与索引

- 审计：`landmark_leakage_audit_v6_2_20261105.json` **PASS**：train 2396 vs val 1006；near_duplicate_pairs 0、train_val_leakage_pairs 0、dev_exploratory_contamination_pairs 0、same_trajectory_cross_split 0、same_trajectory_adjacent_pairs 4448（预期）；sha 跨 split 0。
- T38 新族 vs val_main/identity/旧 exploratory/holdout 草案：family/group/sha 无重叠；T38 final pool vs 24 个既有 sensor 目录 sha 交集 0（capture 证据）。
- 索引：`landmark_external_index_v6_2_20261105.json` **PASS**：4509/4509 帧可读、sha 一致。

## 5. 边界

1. 两类别只做限定域辨识；class1 永不映射 central tower ID；非开放集。
2. 标注 AGENT_PROXY/SELF_CHECKED，final conditions + 目视抽查，非独立人工 GT。
3. v6.2 DEVELOPMENT；val_main 用于阈值/选模，val_identity 分层报告；不得当 sealed/final。
4. discarded pilot/旧标签未登记；T25/T26 仍排除；holdout v3 SPEC_FROZEN_NOT_TRIGGERED。
5. 不提升 Gate；未接控制/PPO/板端/导航；未 commit/push。

## 6. 复现与验证

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py scripts/verify_landmark_dataset.py --freeze configs/perception/landmark_split_freeze_v6_2.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v6_2_20261105.json
& $py scripts/verify_landmark_dataset.py --audit-near-duplicates --audit-freezes configs/perception/landmark_split_freeze_v6_2.json --audit-seal none --audit-output docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v6_2_20261105.json
& $py scripts/verify_landmark_dataset.py --external-index --index-freezes configs/perception/landmark_split_freeze_v6_2.json --index-seal none --index-output docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v6_2_20261105.json
& $py scripts/landmark_run_snapshot.py --create --config configs/perception/landmark_run_snapshot_v7b.json --run-id <run> --out <ignored outputs>
```

| 证据 | 结果 |
| --- | --- |
| v6.2 冻结校验 | PASS，0 error，178 warning |
| 泄漏审计 v6.2 | PASS（0 泄漏 / 0 近重复） |
| 外部索引 v6.2 | PASS（4509/4509 帧） |
| snapshot v7b dry create/verify | VALID（34 artifacts，0 mismatch） |
| dataset 专项 pytest | 见最终验证 |

## 7. 剩余缺口

- T25/T26 mutual/far-MS1 未纳入；holdout v3 未触发。
- identity 认证 INCOMPLETE（MS1 证伪 U1/U2）；two-class 训练/评测未开始（R2 由 train 执行）。
- registry v2 仍为 v5 revision；T30/T38/T39/T40 事件待登记（需 lead 授权写域）。
