# T39 近距 MS1 训练族（T38）标注准备：分片、schema、QA（2026-11-05，BLOCKED_ON_T38）

> **状态：** PREPARED_BLOCKED（T38 in_progress=尚未开始/无采集产物；本文件不预标注、不伪造标签）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json、landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05）、T38/T39 任务书
> **证据域：** 文档/工具准备（无新图像、无新标签、无模型）；T30/T31 经验用于分片与 QA
> **最后核对：** 2026-11-05（HEAD 以现场为准）

## 0. 现状与阻塞

- T38（近距 MS1 1.3–2.2m，2 新族，90–120 accepted，目标 bbox 高 140–220px）**pending**；预期目录 `outputs/sensor_shadow/lm_two_class_near_ms1_20261105{,_sensor}`，条件/证据在 capture_dev 下新目录。
- T39 已 claim，`blocked_by=[task-38]`；无帧可标，不预标注。

## 1. 分片建议（与 annot2，需确认）

- 2 个新族；annot 与 annot2 各标一半：**annot = 族 A（按 capture 命名第 1 族）全部 pool 帧；annot2 = 族 B 全部 pool 帧**。
- 若两族帧数偏差 >20%，按 sequence 互补：帧数多的一族的偶数 sequence 归 annot、奇数归 annot2（先冻结再执行，写入 selection 并记录）。
- 每片选择规则先冻结：pool 内全部帧（不抽样；若单族 >60 帧则 midpoint systematic 至 60，规则同 T30）；两片并集 = 全部 pool 帧，交集空。

## 1.1 已冻结分片规则（与 annot2 一致，2026-11-05）

- T38 pool 全部帧按 (family, integer sequence) 排序；**每个族内前 ceil(n/2) 帧 = annot（shard A）**，其余 = annot2（shard B）；两族各半、B 约 pool 一半（45–60 帧）。
- 规则在 T38 run.complete/pool 落盘后冻结（selection sha 记录）；builder 用 --split-mode first_half。
- 落点：annot = outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a/；annot2 = .../shard_b/；互不覆盖。

## 2. 标签内容与 schema（同 T30/T31）

- 每帧：`tower_present=false`（T38 设计塔不可见；如个别帧塔入镜，需按 two-class spec 补 class0 并记录，不默认 false）、`ms1_present=true`；`identity_ambiguity=NONE`、`gt_uncertainty=NONE`、`occlusion=NONE/PARTIAL`。
- class1 实例：bbox=SOURCE_IMAGE_PIXELS_XYXY（紧致包住 MS1 可见轮廓，近距 140–220px 高）、truncated_edges 按可见边缘、occluded 记录、`keypoint_x/y=null`、`v=0`、`reference_available=false`、`verified_source=WORLD_POSE_OR_MAP_DB`。
- 不标 class0（除非塔可见）；`other_structures=[]`（其他结构不得标 class1）。
- 坐标域声明 `coordinate_space` 同 T31；bbox 不归一化，loader 负责 /W /H。

## 3. QA（fail-loud）

| 检查 | 规则 |
| --- | --- |
| 1:1 | selection 帧集合 == labels 帧集合；image sha/宽高 320×240 |
| class1 v=0 | 全部 class1：v=0、keypoint null、reference_available=false |
| bbox 触边 | truncated_edges=true 的边必须触边（容差 1.5px）；bbox 界内/有序 |
| 投影 gate | MS1 投影 max side ≥8px 的帧必须有 class1（本任务全部应有）；tower 投影 ≥8px 而 tower_present=false → warning/查 FOV |
| 类实例 | class∈{0,1}；class1 可多实例但本族预期 1；class0≤1 |
| 帧层 | 负例不允许 instance；同框必须含两类 |

工具：`pilot/two_class_tools.py qa`（已含上述 gate）+ 本任务 builder `pilot/t39_near_ms1_build.py`。

## 4. 方法与披露

- bbox 优先用 T38 capture 逐帧记录（MS1 bbox 高/宽、四边截断、green 可见性）；若只给 u/v span 或位姿，则用世界位姿 (3.0,4.0) 投影 + 目视复核。
- disclosed：投影/几何辅助 + contact sheet 目视抽查（非独立人工 GT）；class1 仅 map-native MS1；agent 代理。

## 5. 输出与流程（T38 落地后）

1. 读 capture conditions/pool；按 §1 分片；生成 selection（含 shard 标记）。
2. builder 生成 labels draft（class1 bbox）→ 2× contact sheet 目视 → 修正异常帧。
3. `two_class_tools.py qa` → PASS；输出 `outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a/labels_v1.json` + selection/qa/manifest shas。
4. 报告 `T39_NEAR_MS1_SHARD_A_ANNOTATION_20261105.md`；send_message lead/datafreeze/train；complete。

## 6. 边界

- 未采集/未预标注；不改旧包；不 commit/push；不跑 Isaac/训练。
- class1 仅 map-native MS1，合成注入/其他结构不得标 class1。
