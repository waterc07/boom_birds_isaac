# T39 近距 MS1 训练族标注（annot2 shard B，final，2026-11-05）

> **状态：** PROVISIONAL（开发用标注；不是模型效果/板端/导航验收；不提升 Gate）
> **来源章节：** configs/perception/landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05_BEFORE_LABELLING）；task-38/task-39；lead 2026-11-05 分片与 final 重标指示
> **证据域：** 离线标注 QA（Isaac 合成 320×240 RGB；T38 **final** pool 102 accepted 帧，shard B 50 帧）；agent 代理 + 投影 draft + 5 张原生 4×3 接触表逐帧目视复核；无模型训练/推理、无板端/SITL/实飞、无 Isaac 运行
> **最后核对：** 2026-11-05（仓库 E:\isaac\proj_boom_birds，开工 HEAD 47d1063；本任务未 commit/push）

## 0. 结论先行

1. **final shard B（T38 近距 MS1 后半族）50 帧已标完并 QA PASS**：final pool 102 = f1_north 49 + f2_se 53；每族前 ceil(n/2) 帧 = annot shard A（52：f1 25 + f2 27），B = full − A = **f1 后 24 + f2 后 26 = 50 帧**；A+B=102=全部 final pool。
2. **计数（分母 50 帧）**：ms1_present **50/50**（class1 50 instances，全部 map-native MS1）；tower_present 0（capture final 条件证实两族塔均不在 FOV；投影复核 tower_candidate=0）；same_frame 0；negatives 0；GT_UNOBSERVABLE 0；class1 v=1 0 / v=0 50（keypoint JSON null，YOLO 导出 0 0 0）；identity_ambiguity/gt_uncertainty/occlusion 全 NONE。
3. **MS1 尺度**：bbox 宽 47.7–79.6 px、高 193.1–226.7 px（near 1.56–1.89 m / 1.54–1.75 m，符合 capture 目标 140–220 px；bottom 截断 39 帧，其余边 0）。
4. **QA**（annot 的 two_class_tools.py qa，fail-loud）：**PASS**（errors=[], warnings=[]；1:1 帧集、class1 v=0/无 keypoint、bbox 坐标域、截断触边、GT 规则全过）。投影 gate：50/50 帧 MS1 投影≥8px 且均有 class1，无 INSTANCE_UNRESOLVED。
5. **HIGH 修正落实**：class1 仅 map-native MS1；f1 视角可见的红色灯臂结构记入 other_structures（不标 class1、不虚构 bbox）；背景小灯柱不标；每帧 other_structures 字段存在。class1 keypoint 恒 null/v=0。
6. **数据源修正**：首版 53 帧基于 discarded pilotA_discarded pool，已按 lead/annot 要求**作废**；final 版基于 final run/pool/conditions 重标。旧 discarded 文件归档于同目录 `discarded_pilot_shard_b/`（README 标明不得使用，仅作诊断）。

## 1. 分片与数据源

| 项 | 值 |
| --- | --- |
| rule id | near_ms1_family_halves_v1 |
| 规则 | final pool 102 帧按 (family, sequence) 排序；每族前 ceil(n/2) 帧=shard A（annot），其余=shard B（annot2）；规则由 pool 元数据冻结，不按模型分数选帧 |
| final pool | docs/reports/perception/capture_dev_20261104/two_class_near_ms1_20261105/t38_pool_selection.json（102 帧；f1 49 + f2 53；N=1 全 accepted） |
| final conditions | .../t38_frame_conditions.json（102 行：pose、MS1 距离/方位/FOV、MS1 bbox uv/宽高、四边截断、塔状态、strict green/clusters） |
| 图像 | outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images/ |
| observations | outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor/observations.jsonl（run.complete PASS） |
| selection B | outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_b/selection_b.json，sha256 6f3d9af03b48473f768f1594f242750d487e67acd91cb08a7e28d33785e568dd，50 帧 |
| 旧 discarded | lm_two_class_near_ms1_20261105_pilotA_discarded{,_pool,_sensor}（西南视角过近），不得使用 |

## 2. 文件与 sha（ignored）

| 文件 | sha256 |
| --- | --- |
| near_ms1/shard_b/labels_v1.json（50 帧） | bfb73d6828c1d3711376ea304a348e77200e4d73c9ad8b3acbd84b3449f00f49 |
| near_ms1/shard_b/selection_b.json（50） | 6f3d9af03b48473f768f1594f242750d487e67acd91cb08a7e28d33785e568dd |
| near_ms1/shard_b/qa_v1.json（PASS） | 7926090c4427d90d1a5284cc611c116d331dd0afe8ec365579915b3843ab7665 |
| near_ms1/shard_b/manifest.json | c3b68fcf6a56da36808176130d1700ccf1dc8d8e823a6bed6cb6ce80f7752363 |
| annotation spec | 8e544efca0e8feb22ab193479a52d4f0131f6556a1144a41f559f65a0f7c7f57 |

## 3. 方法

1. **selection**：final pool in_pool 帧；每族排序后切半（前 ceil(n/2) 属 A，其余 B）；selection 记录 parent pool/conditions sha 与 split 规则。
2. **投影 draft**：final 相机外参把 map-native MS1（world (3.0,4.0)，半宽 0.25，z 0–1.78）投影为 12 点圆柱 bbox；raw 投影判定四边截断；同时投影 central tower（50/50 帧不在 FOV → 无 class0 候选）；strict v2.1 green cue 记录（final 族 f1 仅 4/49、f2 0/53 帧可见，不改变 class1 标注）。
3. **目视复核**：5 张原生 4×3 接触表（20 px 网格；品红=MS1 候选框，青点=green 质心）；逐帧确认 MS1 柱体、bbox 紧致、截断边、无塔/无其他 class1 结构。
4. **labels/QA**：class1-only 实例（bbox source px XYXY、truncated_edges、occluded=false、keypoint null、v=0、reference_available=false、verified_source=WORLD_POSE_OR_MAP_DB）；annot 的 two_class_tools.py qa fail-loud 校验。

## 4. 边界与不声明

1. AGENT_PROXY+SELF_CHECKED（annot2），非人类独立审查；投影 draft 仅辅助定位，最终实例以目视复核为准。
2. 本 shard 无 class0/同框/负例帧（near-MS1 族为 MS1 单独）；class1 召回/近距定位指标需 A+B 合并后由 train/evaltool 计算。
3. 不改旧包协议/hash；不写 train/val 既有文件；不 commit/push；未接控制/PPO；未提升 Gate。
4. 旧 discarded pilot shard B 已作废并归档；final 版以本文件 sha 为准。
