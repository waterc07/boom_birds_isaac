# val_main 163 帧 MS1 附加标注（class1 presence+bbox，2026-11-05）

> **状态：** PROVISIONAL（开发用附加标注；不是模型效果、板端或导航验收；不修改既有 tower 标签、不提升 Gate）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json（PRE_REGISTERED）与 landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05_BEFORE_LABELLING）；task-32 任务书②
> **证据域：** 离线标注 QA（Isaac 合成 320×240 RGB；val_main 163 帧 = labels_val_validation163 帧集合；agent 代理 + 全量原生接触表视觉复核；无模型训练/推理、无板端/SITL/实飞、无 Isaac 运行）
> **最后核对：** 2026-11-05（仓库 E:\isaac\proj_boom_birds，分支 feat/v2.2-simulation-perception，开工 HEAD 47d1063；本任务未 commit/push）

## 0. 结论先行

1. **范围**：对 val_main 的 **163 帧**做 class1（map-native similar structure MS1）附加 presence+bbox 标注，输出独立文件 `outputs/perception/dev_annotations_20261104/labels_val_main_ms1.json`；**未修改** `labels_val_validation163.json`（sha256 前后均为 a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144）。
2. **计数（分母=163 帧）**：MS1 可见并标注 **47 帧**（28.8%），MS1 不可见 **116 帧**（71.2%）；其中 MS1 与 tower 同框 **47 帧**（全部 47 个 MS1 实例所在帧同时也是 tower_present=true）；MS1 截断 **3 帧**（left 1/right 1/top 1/bottom 3）；远景小 MS1（宽 6–8 px，标记 gt_uncertainty 但保留）**9 帧**。
3. **tower 上下文（未改）**：163 帧中 tower_present 121、可观测 present 95、GT_UNOBSERVABLE 26；class0 keypoint v=1 41、present 但 v=0 80（含 GT_UNOBSERVABLE 26）。本文件只增 class1，不改任何 class0 字段。
4. **class1 关键点规则**：47 个实例全部 keypoint_x/y=null、v=0、reference_available=false；**未使用 bbox 中心或插值替代**（防止 class1 参与 keypoint loss 的伪监督）。
5. **QA**：labels_val_main_ms1.json **PASS**（1:1 帧集 163/163、bbox 在图像域内、class1 v 全 0、无 class1 keypoint、旧 tower 标签 sha 未变；0 problems）。qa 文件 sha256 2190907ff9a69a2ab754e8c20a7e6f73aeef0a1423e6ad7ca7d41efa902f5fa2。
6. **边界**：MS1 bbox 来自 map-native world 投影 draft（(3.0,4.0)、z_top≈1.78、半宽 0.25）+ 14 张原生 4×3 QA 表逐帧目视复核；这是投影 aid+视觉复核，不是独立人工逐像素真值；单代理 AGENT_PROXY+SELF_CHECKED，非人工独立审查。

## 1. 方法

1. **帧集合**：直接取 `labels_val_validation163.json` 的 163 个 frame_id（不增删），因此与 train 固定读取的 validation 子集严格 1:1。
2. **MS1 几何 draft**：用每帧相机外参（从各自 sensor run 的 observations.jsonl 读取 front_rgb）把 map-native MS1（world (3.0,4.0)、z_top 1.78、green lamp z≈1.71、半宽 0.25 m）投影为 12 点圆柱 bbox；clipped bbox 作为 draft，raw 投影判定四边截断；green cue（strict v2.1）用于 QA/归属记录。
3. **视觉复核**：生成 14 张原生 4×3 接触表（20 px 网格；绿框=既有 tower bbox 上下文、品红框=MS1 draft、青点=strict green 质心），逐帧检查：MS1 draft 是否落在细长平顶柱（侧绿灯/蓝侧条）上、是否可见、是否截断、是否与 tower 同框；对不可见帧确认画面中无 MS1。
4. **决策**：MS1 可见→class1 实例（bbox=clipped draft+目视确认，truncated_edges=raw 投影边）；不可见→ms1_present=false；远小（min side<8 px）→保留并标 gt_uncertainty=FAR_SMALL_MS1_WIDTH_6_8PX_APPEARANCE_LOW_INFORMATION；无同框歧义帧（tower 与 MS1 外观/位置可区分）→identity_ambiguity=NONE。
5. **同框规则**：所有同框帧均含 class1 实例（MS1 不当背景）；class0 实例保持旧文件原样，不在本文件重复。

## 2. 逐 family 覆盖

| family | frames | tower_present | ms1_present | same-frame(both) | ms1 truncated | far-small flagged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fam_dev_hn1_confuser | 27 | 0 | 0 | 0 | 0 | 0 |
| fam_dev_hn2_occluder | 26 | 26 | 0 | 0 | 0 | 0 |
| fam_dev_inner_north | 30 | 30 | 20 | 20 | 2 | 4 |
| fam_dev_static_low | 15 | 15 | 0 | 0 | 0 | 0 |
| fam_north | 65 | 50 | 27 | 27 | 1 | 5 |

- MS1 可见集中在 fam_north（27/65）与 fam_dev_inner_north（20/30）；fam_dev_static_low/fam_dev_hn1_confuser/fam_dev_hn2_occluder 中 MS1 不在视野（0）。
- 116 个 ms1_absent 帧经几何投影+接触表确认不见 MS1；其中 HN1 可见的是**合成注入 confuser**（非 map-native MS1），HN2 为合成墙遮挡，均不标 class1；static_low 为塔东侧视角，MS1 在背后。

## 3. 字段与格式

- schema `dsh.landmark_val_main_ms1_annotation.v1`；coordinate space 与 T31/T32 约定一致：**bbox = source image pixels XYXY**；class1 keypoint 恒 null/v=0。
- 每帧字段：frame_id/image/image_sha256/family/group_id/run/split(val_main)/tower_present/tower_undecidable/tower_visibility/tower_gt_unobservable/tower_reference_status/ms1_present/ms1_undecidable/ms1_bbox_xyxy/ms1_truncated_edges/ms1_occluded/identity_ambiguity/gt_uncertainty/occlusion/green 元数据/instances(class1)/notes。
- 实例字段：class=1、bbox_xyxy、truncated_edges、truncated、occluded、keypoint_x=null、keypoint_y=null、v=0、reference_available=false、verified_source=WORLD_POSE_OR_MAP_DB、verification_note（MS1 map probe 证据；class1 永不映射 central tower ID）。

## 4. QA 明细（fail-loud）

| 检查 | 结果 |
| --- | --- |
| 帧集 1:1（vs labels_val_validation163） | PASS 163/163 |
| 旧 tower 标签 sha 未变 | PASS（a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144 → a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144） |
| bbox 坐标域（0≤x1<x2≤320、0≤y1<y2≤240） | PASS（47/47） |
| class1 v 全 0 / keypoint 全 null | PASS（47/47） |
| 同框帧含 class1 实例 | PASS（47/47；MS1 未当背景） |
| 截断边记录 | 3 帧（left1/right1/top1/bottom3，按边计） |
| problems | [] |

## 5. 边界与不声明

1. AGENT_PROXY+SELF_CHECKED，非人类/专家独立审查；MS1 verified 依据 map probe（WORLD_POSE_OR_MAP_DB），不是人工 GT。
2. bbox 为投影 aid+视觉复核，不是逐像素人工框；MS1 在边缘/远景的 bbox 有像素级不确定性（min side 6–8 px 已标注 gt_uncertainty）。
3. 本文件只服务 two-class 训练/评测的 class1 presence+bbox 通道；**未改**旧 tower 标签、train 固定读取的 validation163、lists/manifest，也未并入任何 train 文件。
4. 不改写旧包协议/hash；不 commit/push；未启动 Isaac/训练/控制/PPO；未提升 Gate。
5. 同框 identity_ambiguity=NONE 是**本 val_main 帧集合**的外观判断；不等于真实开放集身份能力；MS1 之外未知相似结构仍会 UNKNOWN。

## 6. 证据清单（sha256）

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| outputs/perception/dev_annotations_20261104/labels_val_main_ms1.json | MS1 附加标注（163 帧，ignored） | 05670eaedfeea5c91186be83bc08b5563375a72993a904c0deac3631a2ece3b0 |
| outputs/perception/dev_annotations_20261104/val_main_ms1/qa_val_main_ms1.json | MS1 附加标注 QA（PASS） | 2190907ff9a69a2ab754e8c20a7e6f73aeef0a1423e6ad7ca7d41efa902f5fa2 |
| outputs/perception/dev_annotations_20261104/val_main_ms1/val_main_ms1_frame_geometry.json | 逐帧 MS1 几何投影 draft | 6df6c4ea14a25f871b70502203743a1777f72647d84111e2450fc29dbc2b8aa5 |
| outputs/perception/dev_annotations_20261104/labels_val_validation163.json | tower 标签基线（未被修改） | a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144 |
| configs/perception/landmark_two_class_label_spec_v1.json | two-class 标签规范（FROZEN） | 8e544efca0e8feb22ab193479a52d4f0131f6556a1144a41f559f65a0f7c7f57 |
| docs/reports/perception/capture_dev_20261104/map_native_structures.json | MS1 map-native 证据 | cb0deffa787050b1b13694a406ed62e4a10f14ddc4c80e063a3cc681628678b4 |
| outputs/perception/dev_annotations_20261104/labels_val_main_ms1.json | MS1 附加标注（163 帧） | 05670eaedfeea5c91186be83bc08b5563375a72993a904c0deac3631a2ece3b0 |
| outputs/perception/dev_annotations_20261104/val_main_ms1/qa_val_main_ms1.json | QA（PASS） | 2190907ff9a69a2ab754e8c20a7e6f73aeef0a1423e6ad7ca7d41efa902f5fa2 |
| outputs/perception/dev_annotations_20261104/val_main_ms1/val_main_ms1_frame_geometry.json | 逐帧几何 draft | 6df6c4ea14a25f871b70502203743a1777f72647d84111e2450fc29dbc2b8aa5 |
| outputs/perception/dev_annotations_20261104/val_main_ms1/qa/ (14 sheets) | 逐帧视觉复核接触表（目录） | （目录，无单一 sha） |

## 7. 验证命令

~~~
# 1) 几何 draft + 14 张 QA 接触表
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/prepare_val_main_ms1.py
# 2) 决策/标签 + QA（PASS/FAIL fail-loud）
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/build_val_main_ms1_labels.py
~~~
