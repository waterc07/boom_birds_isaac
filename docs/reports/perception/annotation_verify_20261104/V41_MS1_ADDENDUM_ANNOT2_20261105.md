# v4.1 空标签 MS1 可见帧补充标注（annot2，2026-11-05）

> **状态：** PARTIAL_22_OF_31 / PROVISIONAL（agent 代理标注；不改旧标签；不是模型效果或验收）
> **来源章节：** two-class 标签规范 v1（FROZEN_2026_11_05）+ diag 裁定 B（补标 69 帧 v4.1 同框）
> **证据域：** 离线标注（Isaac 合成 320x240 RGB；v4.1 dev_v4_1 436 included frames 中空标签且 MS1 投影可见帧）；投影 draft + 2 张原生接触表目视复核
> **最后核对：** 2026-11-05

## 0. 结论

- annot 负责 38 个“已有塔标签+MS1 可见”帧；annot2 负责 31 个“空标签但 MS1 可见”帧。
- 本 addendum 交付其中 **22 帧**（本地投影口径：MS1 lamp 入画 + 投影高度>=8px + 空/负标签；2 张原生接触表逐帧复核）；与 diag 的 31 帧口径差 9 帧（diag 使用其自身投影/可见阈值）。
- 若需要严格 31 帧覆盖，建议用 diag 的逐帧列表重映射后再补 9 帧；否则本包按 A 方案（排除 69 帧）继续，本文件作为补充证据不影响 A。

## 1. 计数与文件（ignored）

| 项 | 值 |
| --- | --- |
| 补充标注帧 | 22 帧（class1 instances 22） |
| 截断帧 | 0 |
| labels | outputs/perception/dev_annotations_20261105/two_class/v41_ms1_addendum/labels_v41_ms1_addendum.json，sha256 6b59f3c71fc916b8fe0f7d54aab5780b356b382c911a70d1d65bdb5eebd887c8 |
| QA | .../qa_v41_ms1_addendum.json（PASS），sha256 d30f5eb892cce6d073db52cb334879266f6d4781d32a78e0238b8a2e2bb13e2a |
| 旧标签未改 | labels_train_v4_1_merged.json sha256 c936da6bfb126cb668825e3091117dc752311c9207fcc66b32691c608e61f187 |

## 2. 规则

- 只加 class1（map-native MS1）presence+bbox；`tower_present=false` 保持旧空/负标签语义不变。
- class1 keypoint 恒 null、v=0、reference_available=false；JSON null，YOLO 导出 0 0 0。
- 合成/其他结构不进 class1；本批无 other_structures。
- agent proxy + 投影 draft（map-native MS1 world (3.0,4.0)）+ 2 张原生 4x3 目视复核；非人工独立。

## 3. 边界

- 本 addendum 不改旧 train 标签、不并入任何 train 文件；由 train 决定是否 merge。
- 22/31 非全覆盖；如要 31 帧需 diag 精确 frame list。
