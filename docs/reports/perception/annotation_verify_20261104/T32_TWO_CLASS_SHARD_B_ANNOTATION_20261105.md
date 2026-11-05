# T32 two-class shard B 标注 + val_main MS1 附加标注（annot2，2026-11-05）

> **状态：** PROVISIONAL（开发用标注；不是模型效果/板端/导航验收；不提升 Gate）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json（PRE_REGISTERED）、landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05_BEFORE_LABELLING）；task-32 任务书
> **证据域：** 离线标注 QA（Isaac 合成 320×240 RGB；T30 pool 373 帧、shard B 192 帧；val_main 163 帧）；agent 代理 + 投影 draft + 全量原生接触表目视复核；无模型训练/推理、无板端/SITL/实飞、无 Isaac 运行
> **最后核对：** 2026-11-05（仓库 E:\isaac\proj_boom_birds，开工 HEAD 47d1063；本任务未 commit/push）

## 0. 结论先行

1. **shard B（f2/f4/f6/f8）192 帧已标完并 QA PASS**：selection rule = 全部 in_pool 帧（capture t30_pool_selection.json 373 帧；shard B = f2 48 + f4 48 + f6 50 + f8 46 = 192；shard A f1/f3/f5/f7 = 181 属 annot；A+B=373 全覆盖）。
2. **统计（分母 192 帧）**：tower_present 96、ms1_present 39、negatives 57（f6 11 + f8 46）、same_frame 0（f7 同框属 shard A）、GT_UNOBSERVABLE 0。class0 instances 96（v=1 85 / v=0 11）；class1 instances 39（v=0 全部；keypoint JSON null，YOLO 导出 0 0 0）。identity_ambiguity 全 NONE；occlusion 全 NONE。
3. **QA（annot 的 two_class_tools.py qa，fail-loud）**：full/batch1/batch2 三种视图均 **PASS**（errors=[], warnings=[]；1:1 帧集、类计数、v 分布、坐标域、截断触边、GT 规则全过）。
4. **两处过程修正（已记录）**：
   - 最初 selection 用 raw accepted（226 帧，含 51 帧不在 pool）；capture 发布 pool 后，**重冻结为 pool 全部 in_pool 帧（192）**；旧 batch1（sha 994ff844…）**作废**，train 暂不用（已 send_message 通知）。
   - 首版 gt_uncertainty 自定义枚举被 annot QA 判 invalid；改为 **gt_uncertainty=NONE + scale_note 记录远景小 MS1**（12 帧 min side<8px），QA PASS。
5. **HIGH 修正落实**：class1 仅 map-native MS1（合成/其他结构不进 class1；每帧 other_structures: []）；同框投影 gate 在本 shard 不触发（无同框帧；f6 MS1 投影可见帧均有 class1，11 帧投影<8px 记负例）；class1 keypoint 恒 v=0、JSON null、导出 0 0 0。
6. **val_main 163 帧 MS1 附加标注**（独立文件，未改旧 tower 标签）已完成：47/163 可见、同框 47、截断 3、远景小 9；见 VAL_MAIN_MS1_ADDENDUM_20261105.md。
7. **v4.1 空标签 MS1 可见帧补充标注**：交付 22/31 帧（本地投影口径差异），独立 addendum，旧 v4.1 标签未改；QA PASS；见 V41_MS1_ADDENDUM_ANNOT2_20261105.md。

## 1. shard B selection（冻结规则）

| 项 | 值 |
| --- | --- |
| rule id | two_class_pool_all_frames_v1 |
| 规则 | shard B = capture pool（t30_pool_selection.json）中全部 in_pool 帧的 f2/f4/f6/f8；不按模型分数选帧、不 post-hoc 重采样 |
| 池 | docs/reports/perception/capture_dev_20261104/two_class_train_20261105/t30_pool_selection.json（373 帧），sha256 d5f2066af7900928bdddec7471ec2ff35deb9d65f7ece40c0595a07ec0ae3a06 |
| 逐帧条件 | .../t30_frame_conditions.json，sha256 d2fbfb50beead5a03bfb84e37b77425f661964b0594375346d5f5f59e4c4b8f3 |
| selection | outputs/perception/dev_annotations_20261105/two_class/shard_b/selection_v1.json，sha256 c24bef210b6ddc67b0fce8d85f67cd55a59668e9cb2c70839c236a068749a902，192 帧 |
| batch1/batch2 | batch1 = f2+f4（96 帧，selection sha fc1421c07d6b06847bfa30122f459c59b9fd73d9dd3505e981c4c929eadcdb9c）；batch2 = f6+f8（96 帧，selection sha fbe712eb278641718ffe089199601c40168a5337f6b8d7eac70c9c6ce92d0d9d） |

## 2. shard B 逐族统计（QA PASS）

| family | frames | tower_present | ms1_present | negatives | notes |
| --- | ---: | ---: | ---: | ---: | --- |
| f2 tower_mid_alone | 48 | 48 | 0 | 0 | class0 box+light kpt; no MS1 in FOV |
| f4 tower_edge_trunc | 48 | 48 | 0 | 0 | class0 box touches left/top edge; truncated_edges recorded |
| f6 ms1_far_trunc | 50 | 0 | 39 | 11 | class1 bbox far/truncated; 11 frames both targets out of FOV -> negatives |
| f8 target_absent_neg | 46 | 0 | 0 | 46 | both absent -> negatives (0 green) |

- class0：96 instances，v=1 85 / v=0 11（绿顶灯不可定位时 v=0，keypoint null，reference_available=false；f2/f4 塔单独，无 MS1 可见）。
- class1：39 instances，全部 map-native MS1（verified_source=WORLD_POSE_OR_MAP_DB），keypoint 不可用；f6 远景 MS1 bbox 宽 6–8px 的 12 帧在 scale_note 记录低信息量但保留，不删帧。
- 截断：f4 左/上缘、f6 右缘截断按投影+目视记录（bbox 触边容差内，QA 通过）。

## 3. 其他交付

- val_main 163 帧 MS1 附加标注：labels_val_main_ms1.json sha256 05670eaedfeea5c91186be83bc08b5563375a72993a904c0deac3631a2ece3b0；QA PASS sha256 2190907ff9a69a2ab754e8c20a7e6f73aeef0a1423e6ad7ca7d41efa902f5fa2；未修改 labels_val_validation163.json（sha a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144）。
- v4.1 空标签 MS1 addendum（22/31）：labels sha256 6b59f3c71fc916b8fe0f7d54aab5780b356b382c911a70d1d65bdb5eebd887c8；QA PASS sha256 d30f5eb892cce6d073db52cb334879266f6d4781d32a78e0238b8a2e2bb13e2a；旧 merged labels sha c936da6bfb126cb668825e3091117dc752311c9207fcc66b32691c608e61f187 未改。

## 4. 证据清单（ignored）

| 文件 | sha256 |
| --- | --- |
| shard_b/labels_v1.json（192 帧） | fe38e4a35702e199e447752ebf5a77636f6446ec0eb9bfb7460362ff0304b4cc |
| shard_b/labels_batch1.json（96 帧） | f4f847f27e40652ea83cd1e241dd0b3bae9dcb2d3d965973f26959a532635753 |
| shard_b/labels_batch2.json（96 帧） | 418d94cd2a3c5a5ee2d77a54321c5279e62556e759ce0eb6694a627bdf7d2fe8 |
| shard_b/selection_v1.json（192） | c24bef210b6ddc67b0fce8d85f67cd55a59668e9cb2c70839c236a068749a902 |
| shard_b/qa_full.json（PASS） | 2b168bc5e91849e8f49a07b1edc6754a3a81cd6440ffd7b2b79f158cc8b61e22 |
| shard_b/qa_batch1.json（PASS） | 9d5d26ae78600da2e3d9a9e6e459c96211d3859c3ae8ef224351c3c4ec21bbb4 |
| shard_b/qa_batch2.json（PASS） | 638614c190b4a9e9d4aad116b99f23afa9c7d00f3c350eb804fc3d6d65ea8fed |
| shard_b/manifest.json | d5c888cda15c84cf9d07452f6340d895c5e3d8ecfd0eec2db81fa0fa7fdca557 |
| labels_val_main_ms1.json | 05670eaedfeea5c91186be83bc08b5563375a72993a904c0deac3631a2ece3b0 |
| val_main_ms1/qa_val_main_ms1.json（PASS） | 2190907ff9a69a2ab754e8c20a7e6f73aeef0a1423e6ad7ca7d41efa902f5fa2 |
| v41_ms1_addendum/labels_v41_ms1_addendum.json | 6b59f3c71fc916b8fe0f7d54aab5780b356b382c911a70d1d65bdb5eebd887c8 |
| v41_ms1_addendum/qa_v41_ms1_addendum.json（PASS） | d30f5eb892cce6d073db52cb334879266f6d4781d32a78e0238b8a2e2bb13e2a |
| annotation spec | 8e544efca0e8feb22ab193479a52d4f0131f6556a1144a41f559f65a0f7c7f57 |

## 5. 边界与不声明

1. AGENT_PROXY+SELF_CHECKED（annot2），非人类独立审查；投影 draft 仅辅助定位，最终实例以目视复核为准（f6 远景小目标信息量有限已在 scale_note 标注）。
2. 本 shard 无同框帧（f7 属 annot shard A）；class1 召回/同框指标需 A+B 合并后由 train/evaltool 计算。
3. 不改旧包协议/hash；不写 train/val 既有文件；不 commit/push；未接控制/PPO；未提升 Gate。
4. 旧 batch1（raw selection，226 帧版本）作废，train 请只用本报告 §4 的新 sha。
5. v4.1 addendum 为 22/31 非全覆盖；本包若需 31 帧严格覆盖请用 diag 逐帧列表重映射，否则按 A 方案（排除 69 帧）继续。

## 6. 命令

~~~
# 1) pool-based selection
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261105/two_class/shard_b/tools/make_shard_b_selection_pool.py
# 2) 投影 draft + 16 张原生 QA 接触表
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261105/two_class/shard_b/tools/prepare_shard_b_draft.py --selection outputs/perception/dev_annotations_20261105/two_class/shard_b/selection_v1.json --sensor outputs/sensor_shadow/lm_two_class_train_20261105_pool --observations outputs/sensor_shadow/lm_two_class_train_20261105_sensor --images outputs/sensor_shadow/lm_two_class_train_20261105_pool/images --no-zoom
# 3) labels + QA（annot two_class_tools.py）
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261105/two_class/shard_b/tools/build_final_labels_pool.py
~~~
