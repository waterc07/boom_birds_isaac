# T39 近距 MS1 训练族标注：shard A（T38 final，2026-11-05）

> **状态：** PROVISIONAL（数据准备/标注；final capture conditions（ms1_bbox_uv）+ 目视抽查；agent 代理，非独立人工 GT；不提升 Gate）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json、landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05）、T38/T39 任务书、lead 2026-11-05 指示（final run，旧 discarded 作废）
> **证据域：** 离线标注 QA（T38 final run accepted RGB 102 帧中的 shard A 52 帧；Isaac 合成 320×240；无训练/推理）
> **最后核对：** 2026-11-05（HEAD 47d1063）

## 0. 结论先行

1. **shard A 完成**：final run 的 2 个近距 MS1 族（f1 49 + f2 53 = 102 accepted）按每族前 ceil(n/2) 取 **52 帧**（f1 25 + f2 27）标注 class1；QA **PASS 52/52**。
2. 全部 52 帧：\`tower_present=false\`（final observations 逐帧检查 tower 投影不在画面内）、\`ms1_present=true\`、class1 实例 52、v=0、keypoint null、bbox 由 map-native MS1 (3.0,4.0, z0.05–1.78) 用 final run 相机位姿投影 + 2× contact sheet 目视抽查。
3. 口径澄清：capture 先前 108 帧 pool/conditions 属于 **pilotA_discarded**（已作废）；final run accepted=**102**、sensor images 108（含非 accepted），f1 名改为 \`lmf_t38_f1_ms1_near_north_0\`。旧 discarded 标签不得用于 v6.2/训练。
4. 分片：A=52（本文件）；B=50（annot2 按同一 final pool 重标：f1 后 24 + f2 后 26）；A+B=102。
5. QA warning 25 条均为 tower 投影全跨度≥8px 但 \`tower_present=false\`（fov 判定在画面外，非实际可见），记录不阻塞。

## 1. 数据与分片

| 项 | 值 |
| --- | --- |
| run | outputs/sensor_shadow/lm_two_class_near_ms1_20261105（run.complete PASS；sensor 108 images） |
| accepted | 102（gate.accepted RGB） |
| 族 | f1 lmf_t38_f1_ms1_near_north_0 49；f2 lmf_t38_f2_ms1_near_se_0 53 |
| 分片规则 | 每族前 ceil(n/2)=A；其余=B；A+B=102 |
| A | 52（f1 25 + f2 27） |
| B（annot2） | 50（f1 24 + f2 26） |

## 2. 标签统计（分母 52）

| 指标 | 值 |
| --- | ---: |
| frames | **52** |
| tower_present / ms1_present | 0 / 52 |
| class0 实例 | 0 |
| class1 实例（v=0） | 52 |
| keypoint | 0（class1 恒 v=0） |
| 截断实例 | 见标签（bottom 截断帧按 capture/几何记录） |
| other_structures | 空（class1 仅 map-native MS1） |

## 3. QA

- 工具：pilot/two_class_tools.py qa → **PASS 52/52，0 error**；25 warning（tower 投影全跨度≥8px 但 tower_present=false，fov 画面外）。
- 检查：1:1、image sha/320×240、class1 v=0/keypoint null/reference false、bbox 界内/有序、投影 gate（MS1 投影≥8px 必有 class1）、class0=0。

## 4. 方法、披露、边界

- bbox：map-native MS1 世界位姿 + final run observations 相机位姿投影；2× contact sheet 目视抽查；**投影辅助 + agent 目视，非独立人工 GT**；bbox 约 ±3–8px。
- class1 仅 map-native MS1；不得映射 central-tower ID；keypoint 恒 null/v=0（loader 写 0 0 0 占位且被 loss mask 排除）。
- final conditions 尚未补发；capture 条件到位后我会做 diff 复核（若有差异以 capture 条件为准重出）。
- 旧 discarded 数据/标签作废；本批为 development 训练输入；不认证/不作独立测试/holdout；未 commit/push；未跑 Isaac/训练。

## 5. 证据与 sha

| 文件 | sha256 |
| --- | --- |
| shard_a/labels_v1.json（ignored） | deef8284f46384c218b77bc6f90a9a7c7cfa77781b3e4950b4bee9b9817bf504 |
| shard_a/selection.json（ignored） | cc35eb2ee7d2c62b5e02dc81b1b6c87c7033f6ad903b6adb2568e3793b86a702 |
| shard_a/qa_v1.json（ignored；PASS 0/0） | f6b0b7f14538426490da6bf8367ecb572bf883903f887cdcefbcbc32614018fc |
| full/labels_v1.json（ignored，102 帧 provisional） | db08d47b73f47ca371a33d2f754e55cd4508f7f7afb6312aa180641b21b0854c |
| full/selection.json（ignored） | 4344f91ed6fc04185dae133a4af9675b2f795da56b9aa7ba9b2b982ed4dc036a |

> 注：本表为 final capture conditions 重建后的 sha；先前基于 final observations 纯投影的版本（labels a2da4339…）已被取代。A(52)+B(50)=102；与 annot2 final shard B（bfb73d68…）互补校验：交集 0、并集 102=pool、无 missing/extra。

## 6. 待办

- annot2 重标 B（50 帧，final pool），完成后 A+B 合并=102。
- final conditions 补发后 diff 复核（本批用 final observations 位姿，若条件不同则重出）。
- 报告/证据供 v6.2 冻结与 train/datafreeze 消费。
