# T31 two-class 标注：shard A（T30 pool 181 帧，2026-11-05）

> **状态：** PROVISIONAL（数据准备/标注；agent 代理 + capture 几何条件辅助 + 目视抽查；非独立人工 GT、非模型效果、不提升 Gate）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json（PRE_REGISTERED）、configs/perception/landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05）、T30/T31 任务书、lead 2026-11-05 确认（schema/分片/pool）
> **证据域：** 离线标注 QA（T30 8 新族中的 shard A 4 族；in-pool accepted 181 帧；Isaac 合成 320×240；无训练/推理/Isaac 运行）
> **最后核对：** 2026-11-05（HEAD 47d1063）

## 0. 结论先行

1. **shard A 完成**：条件 ①③⑤⑦（f1 塔近 / f3 塔远 / f5 MS1 近 / f7 同框）共 **181 个 in-pool 帧**（pool 373 中的 A 半），全部标注；另 57 个 accepted 非 pool 帧保留诊断、训练忽略。
2. 统计（分母 181）：tower_present **136**、ms1_present **84**、**同框 39**；class0 实例 136（v=1 **51**、v=0 85）、class1 实例 84（全部 v=0/无 keypoint）；GT_UNOBSERVABLE **0**、REFERENCE_UNRESOLVED 85（塔在视场但绿顶灯不可分辨）；截断实例 0；other_structures 全空（class1 仅 map-native MS1）。
3. 格式/规则 QA **PASS**（0 error / 0 warning）：1:1、类实例、同框、v 分布、坐标域（bbox pixels XYXY / class0 keypoint 归一化）、class0≤1、class1 恒 v=0 无 keypoint、truncated 触边；diag HIGH 投影 gate 满足（MS1 投影≥8px 的 84 帧均有 class1）。
4. 方法披露：bbox 来自 **capture 逐帧几何条件**（tower u/v span；class1 由 MS1 世界位姿投影），再做 contact sheet 目视抽查（各 family 首页 + f1 全页）；**投影/几何辅助 + agent 目视抽查，非独立人工 GT**；bbox 误差约 ±3–8 px，未做逐帧像素级人工修正。
5. pool 口径：capture 冻结 pool=373（raw 492 的 3/4 规则）；本 shard accepted 238，其中 **181 in-pool 已标**；train/datafreeze 用 pool ∩ labels。

## 1. 分片、pool 与选择

| 项 | 值 |
| --- | --- |
| run | outputs/sensor_shadow/lm_two_class_train_20261105{,_sensor} |
| 条件 | docs/reports/perception/capture_dev_20261104/two_class_train_20261105/t30_frame_conditions.json（492 行，373 in_pool） |
| pool 图像 | outputs/sensor_shadow/lm_two_class_train_20261105_pool/images/ |
| 族（in-pool） | f1 50；f3 47；f5 45；f7 39 |
| 选择 | 全量 in-pool（181）；59 非 pool accepted 未标（诊断保留） |

## 2. 标签统计（分母 181）

| 指标 | 值 |
| --- | ---: |
| frames | **181** |
| tower_present / ms1_present | 136 / 84 |
| 同框 | **39** |
| class0 实例 / v=1 / v=0 | 136 / **51** / 85 |
| class1 实例（v=0 恒） | 84 |
| GT_UNOBSERVABLE | 0 |
| gt_uncertainty NONE / REFERENCE_UNRESOLVED | 96 / 85 |
| 截断实例 | 0 |
| other_structures | 空 |

## 3. QA（fail-loud）

- 工具：pilot/two_class_tools.py qa；结果 **PASS**（0 error / 0 warning），见 qa_v1.json。
- 检查覆盖：1:1 image↔label、sha/320×240、类实例、同框、class0≤1、同类 bbox 不重复、v 分布、class1 keypoint=null、坐标域、truncated 边触边、MS1 投影≥8px gate、完全遮挡规则。

## 4. 方法、披露与边界

- class0 bbox：capture 逐帧 tower u/v span；class1 bbox：MS1 世界位姿 (3.0,4.0)+0.5m 截面投影；overlay sheets 目视抽查，整体对齐（未逐帧修正）。
- keypoint：严格绿光（g≥90、g-r≥25、g-b≥25，最大 4 连通块）质心，与检测器 cue 同源（independent_of_detector_cue=false）；代理参考、非独立物理真值。
- class1 仅 map-native MS1（WORLD_POSE_OR_MAP_DB；map_native_structures.json），不得映射 central-tower ID；loader 写 0 0 0 占位并被 keypoint loss mask 排除。
- 训练用途：two-class development 训练输入（shard A）；不代表真实分布，不得作认证/独立测试/holdout。
- 未改动旧包标签/模型/协议/hash；未 commit/push。

## 5. 证据与 sha

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| outputs/perception/dev_annotations_20261105/two_class/shard_a/labels_v1.json（ignored） | 181 帧 | 8874eb79398d4bc8add169938401906dcb43f57937bfbee4e0faf91566dc42c6 |
| .../selection.json（ignored） | in-pool 全量 | a0a248d1c0371315cfb46d11f129b7028b342a707da24dcc4ce3ffa3b7438590 |
| .../qa_v1.json（ignored） | QA PASS | 80394578c60195159a97d55a0c78dd1743d62a6f421fccae807c29787f40cdf7 |
| docs/reports/perception/annotation_verify_20261104/pilot/two_class_shard_a_v2/ | overlay sheets（17 张） | 见目录 |

## 6. 待办

- annot2 shard B；train 合并 A/B 与 loader 校验（不改分片字节）。
- v4.1 训练输入 MS1 addendum（diag 裁定 B）：独立文件、不改旧 v4.1 标签；ETA 5–8 分钟；若超时按 lead A 方案（投影排除 69 帧）不阻塞训练。
