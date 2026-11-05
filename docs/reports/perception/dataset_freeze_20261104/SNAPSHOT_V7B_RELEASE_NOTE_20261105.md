# snapshot v7b 发布说明（2026-11-05）

> 状态：FROZEN（由 T40 datafreeze 发布）；旧 ec0ea6e9 仅作历史副本保留
> 来源：T40 v6.2 冻结；train R2 pilot 执行 config

## 变更

- 官方 manifest：configs/perception/landmark_run_snapshot_v7b.json
- **当前 sha256：5daef9824dd0a2538f2fd422fc5bf4a2fcefacb1d86df5407bf813030c7b200e**（与 train 执行 config 字节一致）
- 旧版 sha256：ec0ea6e9858fa8a4c96d7c643996a18473446d20a3c354c2a17650c2edfe1221
  - 历史副本：docs/reports/perception/dataset_freeze_20261104/landmark_run_snapshot_v7b_ec0ea6e9_history.json（字节一致，仅归档）
- 变更原因：旧版仍 track v6.1 路径；v6.2 实际数据为 dev_v7 / labels_train_v6_2_merged。

## 仅 3 条路径变化

| id | 旧路径 | 新路径 |
| --- | --- | --- |
| train_merged_labels | outputs/landmark_train/dataset/labels_train_v6_merged.json | outputs/landmark_train/dataset/labels_train_v6_2_merged.json |
| dataset_build_v6 | outputs/landmark_train/dataset/dev_v6/dataset_build.json | outputs/landmark_train/dataset/dev_v7/dataset_build.json |
| dataset_data_yaml | outputs/landmark_train/dataset/dev_v6/data.yaml | outputs/landmark_train/dataset/dev_v7/data.yaml |

- 其余 31 artifacts 路径/kind 未变；34 artifacts 全部存在；dry create + --verify VALID（0 mismatch）。
- train 已按此字节 --create：snapshot sha 93ee18fc…（pre_train 记录）；后续 --verify 以官方 5daef982 字节为准。
- v6.2 freeze canonical d8ad5ca0… / file 71a4eef0…；R2 selection rule 4d486b3e… 仍被 track。
