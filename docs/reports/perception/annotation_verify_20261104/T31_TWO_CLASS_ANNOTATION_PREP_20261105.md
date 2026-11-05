# T31 two-class 标注准备：schema、分片、QA 与工时（2026-11-05，BLOCKED_ON_T30）

> **状态：** PREPARED_BLOCKED（T30 采集 in_progress，尚无可用帧；本文件不预标注、不伪造标签）
> **来源章节：** `configs/perception/landmark_two_class_protocol_v1.json`（PRE-REGISTERED）、`configs/perception/landmark_two_class_label_spec_v1.json`（FROZEN_2026_11_05）、T30/T31 任务书
> **证据域：** 文档/工具准备（无新图像、无新标签、无模型）；前一包 T25/T26 结论不变
> **最后核对：** 2026-11-05（HEAD `47d1063`）

## 0. 结论先行

- T31 已 claim，**blocked on T30**（capture in_progress，8 新族 ~360 accepted 尚未落盘）；本文件把不依赖 T30 的部分做完：标签 schema、坐标域、QA fail-loud 规则、分片建议、工时预估、工具。
- 分片建议（需 lead/annot2 确认）：annot A = 条件 **①③⑤⑦**（塔近距/塔远景/MS1 单独近中距/同框近中距），annot2 B = **②④⑥⑧**（塔中距/塔边缘截断/MS1 远景+截断/同框远景+负例），各约一半帧（~180）。理由：两边都覆盖"塔、MS1、同框/负例"三类证据，避免一方只标塔、一方只标 MS1。
- 待确认问题（见 §7）：① bbox 坐标域（建议 source pixels XYXY；spec 只显式规定 keypoint 归一化 0–1）；②`identity_ambiguity`/`gt_uncertainty` 取值表（建议 NONE/UNCERTAIN/AMBIGUOUS + NONE/FULLY_OCCLUDED/REFERENCE_UNRESOLVED/INSTANCE_UNRESOLVED）；③GT_UNOBSERVABLE 表示（tower_present=true + occlusion=FULL + 无 class0 instance）；④T30 家族名称/分片归属以 capture 产出为准。

## 1. 标签文件 schema（PROPOSED，供 train data loader 对齐）

```json
{
  "schema_version": "dsh.landmark_two_class_annotations.v1",
  "status": "T30_TWO_CLASS_SHARD_A_AGENT_PROXY",
  "annotation_spec": {"path": "configs/perception/landmark_two_class_label_spec_v1.json", "sha256": "..."},
  "coordinate_space": {
    "bbox": "SOURCE_IMAGE_PIXELS_XYXY",
    "keypoint": "SOURCE_IMAGE_PIXELS_NORMALIZED_01"
  },
  "frames": [
    {
      "frame_id": "...", "image": "...", "image_sha256": "...",
      "image_width": 320, "image_height": 240,
      "family": "...", "shard": "A", "sequence": 12,
      "tower_present": true, "ms1_present": true,
      "identity_ambiguity": "NONE|UNCERTAIN|AMBIGUOUS",
      "gt_uncertainty": "NONE|FULLY_OCCLUDED|REFERENCE_UNRESOLVED|INSTANCE_UNRESOLVED",
      "occlusion": "NONE|PARTIAL|FULL",
      "notes": "agent proxy; green-light centroid is same-cue proxy, not independent truth",
      "instances": [
        {"class": 0, "bbox_xyxy": [x1, y1, x2, y2], "truncated_edges": {"left": false, "right": false, "top": false, "bottom": false},
         "occluded": false, "keypoint_x": 0.5, "keypoint_y": 0.42, "v": 1,
         "reference_available": true, "verified_source": "VISUAL"},
        {"class": 1, "bbox_xyxy": [x1, y1, x2, y2], "truncated_edges": {"left": false, "right": false, "top": false, "bottom": false},
         "occluded": false, "keypoint_x": null, "keypoint_y": null, "v": 0,
         "reference_available": false, "verified_source": "WORLD_POSE_OR_MAP_DB"}
      ]
    }
  ]
}
```

- **class0**：bbox 紧致（塔可见轮廓含顶灯罩）；keypoint=绿顶灯中心，v=1 仅当可见且可定位，v=0 时 `keypoint_x/y=null`（禁止 bbox 中心/插值代替）；`reference_available` 与 v 一致。
- **class1**：bbox 紧致（细长平顶柱+侧绿灯+蓝侧条）；**keypoint 恒 null、v=0、reference_available=false**；`verified_source=WORLD_POSE_OR_MAP_DB`（或 `EXTERNAL_EVIDENCE` 若合成注入）；禁止 bbox 中心当 keypoint。
- **同框**：两类所有可见可判定实例都必须列入 instances；MS1 不得当背景。
- **完全遮挡**：`tower_present=true + occlusion="FULL" + gt_uncertainty="FULLY_OCCLUDED"`，**无 class0 instance/bbox** = GT_UNOBSERVABLE（不是负例）。
- **负例**：`tower_present=false, ms1_present=false, instances=[]`。
- 坐标域：bbox 用 **source image 像素 XYXY**（0≤x1<x2≤W、0≤y1<y2≤H，浮点）；keypoint 用 **归一化 [0,1]**（spec 明文）；文件内 `coordinate_space` 显式声明，避免像 yolo 那次坐标域混淆。

## 2. QA（fail-loud；工具在 `pilot/two_class_tools.py`）

| 检查 | 规则 |
| --- | --- |
| 1:1 image↔label | selection 帧集合 == labels 帧集合；每帧 image 存在、sha 一致、宽高 320×240 |
| 类实例计数 | 每帧 class∈{0,1}；无重复同类同 bbox；class0/class1 instance 数与 tower_present/ms1_present 一致（除 FULL occlusion 允许 tower_present=true 且无 class0） |
| 同框计数 | 报告 frames with class0+class1 同时可见的数量（分母=全部 shard A 帧） |
| v 分布 | 报告 class0 v=1/v=0 计数；**class1 全部 v=0**；class0 v=0 时 keypoint 必须 null |
| 坐标域 | bbox 在图像范围内、x1<x2/y1<y2；若检测到 bbox 全 ≤1.0（疑似归一化）→ 报错；keypoint 若存在必须在 [0,1] |
| 截断 | truncated=any(edges)；true 边对应 bbox 触及相应图像边界（容差 1.5 px）；false 边不应明显触边 |
| GT 规则 | FULL occlusion 帧不得有 class0 bbox；负例不得有 instance；同框帧 ms1_present=true 时必须有 class1 instance |
| 失败处理 | 任一 fail → 该批 FAIL，不写"通过"；修数据后重跑 |

## 3. 分片与流程（T30 完成后）

1. capture 产出 8 族 + 条件/位姿/四边截断/green_pixels 后，按 §0 分片；A 由 annot 标，B 由 annot2 标。
2. 选择：每族 accepted 帧按 sequence midpoint systematic，总 A ≈180（约半数）；规则与 selection JSON 先冻结（`two_class_tools.py selection`）。
3. 2× contact sheet 目视 + 4× zoom（同框/远景/截断/遮挡帧）；逐帧按 §1 写标签。
4. `two_class_tools.py qa --labels ... --selection ...` → PASS；失败即修。
5. 输出：ignored `outputs/perception/dev_annotations_20261105/two_class/shard_a/labels_v1.json` + selection/qa/manifest shas；仓库留报告/统计/少量 overlay。
6. 报告：`T31_TWO_CLASS_SHARD_A_ANNOTATION_20261105.md`（帧数、类实例、同框、v 分布、截断/遮挡、边界、工时）。
7. send_message lead/datafreeze/train；不 commit/push。

## 4. 工时预估（agent 执行，经验值）

- 单类帧 ~2–3 min；同框双实例 ~3–4 min；完全遮挡/歧义 ~2–3 min；contact sheet/QA ~0.3 min/帧。
- shard A ~180 帧（含 ~40 同框）：约 **9–13 h**（含 QA/报告），分 4–6 批；若 T30 帧数降至 ~150，则 7.5–11 h。
- 风险：远景 MS1 9–14 px 可能不可判定 → 按规则记录（present 但 v=0/identity_uncertainty），不猜；不得为覆盖虚构实例。

## 5. 前置与阻塞

- T30 尚未落盘（capture in_progress；最新 sensor 目录仍为 T25）。T30 完成后需 capture send_message 我（或 dir 出现 run.complete + summary）。
- 依赖确认：①train 对接 label schema（§1）；②lead/annot2 确认 §0 分片；③capture 家族命名/条件映射。
- 在 T30 落地前**不预标注、不伪造**；本轮只写工具/文档，不跑 Isaac/训练/大批量图像处理。

## 6. 工具

- `pilot/two_class_tools.py`：
  - `selection --run <sensor_run> --families A,B,C,D --per-family N --out selection.json`（midpoint systematic + image sha 校验 + 分片标记）；
  - `template --selection selection.json --out labels_draft.json`（生成待填骨架，tower_present/ms1_present 先 null，禁止直接当标签）；
  - `qa --labels labels.json --selection selection.json --out qa.json`（§2 全部 fail-loud 检查 + 统计）；
  - `stats --labels ... --out stats.json`。

## 6.1 已确认（lead + train，2026-11-05）

- bbox = SOURCE_IMAGE_PIXELS_XYXY（loader 内 /W、/H；标签不预归一化）；class0 keypoint 归一化 [0,1]，v=0 时 null；class1 keypoint 恒 null/v=0/reference_available=false（YOLO 8 字段占位由 loader 生成且被 keypoint loss mask 排除）。
- identity_ambiguity / gt_uncertainty 枚举按 §7 建议采用；完全遮挡 = tower_present=true + occlusion=FULL + 无 class0 instance（GT_UNOBSERVABLE，非负例；loader 训练空标签、eval 单列）。
- 分片 A=①③⑤⑦（f1/f3/f5/f7）、B=②④⑥⑧（f2/f4/f6/f8）已确认（lead + annot2）。
- train 追加 fail-loud（工具已实现）：frame_id 唯一、image repo-relative、class0≤1、同类同 bbox 不重复、truncated 边必须触边（容差 1.5px）、class1 可多实例、A/B 不得含 val_main/identity 帧。
- 输出路径：shard A = outputs/perception/dev_annotations_20261105/two_class/shard_a/labels_v1.json（+ selection/qa/manifest shas）；train 合并为 labels_train_v6_merged.json（不改分片字节）。

## 7. 待确认问题（lead/train/annot2）

1. **bbox 坐标域**：确认为 source pixels XYXY（与 spec 的 keypoint 归一化分开）？若 train loader 需要归一化 bbox，请明确在 loader 内转换而不是标签里混存。
2. `identity_ambiguity` 取值：建议 `NONE|UNCERTAIN|AMBIGUOUS`；`gt_uncertainty`：建议 `NONE|FULLY_OCCLUDED|REFERENCE_UNRESOLVED|INSTANCE_UNRESOLVED`。
3. 分片：A=①③⑤⑦、B=②④⑥⑧ 是否同意（annot2 同步）。
4. 完全遮挡帧表示（tower_present=true + occlusion=FULL + 无 class0 instance）是否与 train loader 一致。
5. T30 完成后以 capture 的 family 命名/条件表重新映射 ①–⑧；若实际族数≠8，以实际为准并重报预算。
