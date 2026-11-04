# TINY / 4–10 px 盲复标（T16-B，2026-11-04）

> **状态：** PROVISIONAL（盲标完成；agent 代理标注，非人工独立审查；比较由 diag 独立计算）
> **来源章节：** `LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md` §1.4/§2.1；`configs/perception/landmark_annotation_spec_v2_1.json`（FROZEN_FOR_DATA）；T13/T16-B 任务书
> **证据域：** 离线盲标 QA（22 帧 Isaac 合成 320×240 development 帧；agent 代理标注；无模型训练/推理、无导航/板端）
> **最后核对：** 2026-11-04（HEAD `0c27525`）

## 0. 结论先行

1. 按 diag 盲版清单（sha256 `fc3508de…`，22 帧，逐帧 image sha 22/22 一致）完成**独立盲标**，产出 `labels_tiny_blind.json`（v2.1，22 条），**未**读取原标注坐标、模型 predictions、旧 final 结果，**未**自行对比原标签。
2. 盲标结果：present **6**、undecidable **14**、absent **2**；带 keypoint **6**（全部 green_pixels≥3 且目视确认绿顶灯）；truncated 2（right 1、bottom 1）；confusers **10**（全部 `verified=false`，未验证绿色/灰色结构）。
3. **可标注性信号**：14/22（63.6%）在 TINY 尺度下无法从图像可靠判定"目标存在/身份"（主要因 ~9–20 px 目标与中央场地 gantry/机器人混杂、绿光仅 1–3 px 或落在非目标结构上）；这些按 `undecidable=true + IDENTITY_UNRESOLVED` 处理，**未为了对齐而猜**。该比例本身即为 TINY annotatability 证据（diag 负责与旧标比较并计算预注册门）。
4. 格式 QA：v2.1 校验器 **PASS 22/22，0 error / 0 warning**；文件 sha256 `be08ca8baa0948d919de921d0f7ffac85bd6379c872e5a546d2a072812fa730a`。
5. 同源性披露：所有参考点 `reference_source=COLOR_CUE_ASSISTED`、`annotator.independent_of_detector_cue=false`；green_pixels 采用预注册严格规则（g≥90、g-r≥25、g-b≥25，最大 4 连通块）并记录，分歧将主要反映**同源可复现性**而非独立物理精度。

## 1. 盲标协议与判据

- 输入：只读 diag 盲版帧清单（frame_id/image/sha/宽高）与图像；**未读** `TINY_BLIND_REANNOTATION_KEY_20261104.json`、`labels_train/labels_val`、模型 predictions、旧 final 结果。
- bbox：spec v2.1 口径（head/light-rack + 收分塔体 + 相连阶梯底座，四边真实裁剪），纯目视；不使用采集投影先验。
- 参考点：严格绿光规则；仅 green_pixels≥3 且目视确认绿顶灯位于标注位置时给 keypoint；否则 null + UNAVAILABLE + reason。
- 不可判定/歧义：present 无法判定 → undecidable=true（无 bbox/keypoint、无 negative_type）；多候选 → ambiguous；不猜 keypoint。
- 截断：逐边记录，truncation_source=ANNOTATOR_VISUAL；truncated=any(edge)。
- confuser：可见非目标绿色/灰色结构记 confusers[]，verified=false（无图像外证据）。
- 主观置信度：每帧 HIGH/MEDIUM/LOW（写 `confidence` 字段，便于 diag 分层）。

## 2. 结果统计（分母 22）

| 指标 | 值 |
| --- | ---: |
| frames | **22** |
| present | **6** |
| undecidable | **14**（63.6%） |
| absent | **2** |
| keypoint 可用 | **6**（全部 green_pixels≥3） |
| truncated | **2**（right 1、bottom 1） |
| confusers | **10**（verified=false 10） |
| confidence HIGH / MEDIUM / LOW | {"LOW":14,"HIGH":6,"MEDIUM":2} |

- present 6 帧：目标塔可清晰辨认（head/arms + tapered body + 绿顶灯），bbox 与 keypoint 见文件；截断 1 右缘、1 下缘。
- undecidable 14 帧：远景/小目标（约 9–20 px）与中央场地 gantry/机器人、地图原生绿顶柱混杂，绿光 1–3 px 或落在非塔结构上；无法在盲标条件下可靠判定目标存在/身份。
- absent 2 帧：static_negative 位姿与 pilot_east_away 位姿，画面无中央塔；附未验证灰色柱/结构 confuser。

## 3. QA 与证据

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| `docs/reports/perception/annotation_verify_20261104/labels_tiny_blind.json` | 22 帧 v2.1 盲标 | `be08ca8baa0948d919de921d0f7ffac85bd6379c872e5a546d2a072812fa730a` |
| `docs/reports/perception/annotation_verify_20261104/pilot/tiny_blind_qa_report.json` | 格式 QA（PASS 22/22，0/0） | `9d001f1d7f8c7bee007195d617701263a7ba18a544a44d61c895779f387ad44b` |
| `docs/reports/perception/annotation_verify_20261104/pilot/tiny_blind/` | grid/band/zoom 查看证据 + cues.json | 见目录 |
| diag 盲版清单 | 22 帧清单（未含原标注坐标） | `fc3508de23b8d16c593d0e2bad27889de89d3e4ed68a1704e01ba50b37364941` |

## 4. 边界

- agent 代理盲标（AGENT_PROXY + SELF_CHECKED），非人工/专家；无标注员间一致性。
- 参考点与检测器绿色 cue 同源；不得把本次一致性当作独立物理精度。
- 本标签仅用于 TINY 可标注性分析；不并入 train/val（落点为独立文件）。
- 比较（presence/ref-availability/IoU/kpt/bearing/截断一致率与预注册门）由 diag 独立计算，本报告不做自我比较。
- 未 commit/push；未跑 Isaac；未改原始帧。

## 5. diag 独立比较结果（2026-11-04，diag 计算；本文件仅引用，不改盲标）

- 比较明细：`docs/reports/perception/posteval_20261104/TINY_BLIND_DISAGREEMENT_20261104.json`（sha256 `9049547f…`）；结论落在 `POSTEVAL_DIAGNOSIS_20261104.md` §4（TINY annotatability **INCOMPLETE/FAIL**）。
- 口径：undecidable **不剔除**（严格 presence 分母 = 22），另报"仅可判定帧"作参考。

| 指标 | 结果 | 预注册门 | 判定 |
| --- | --- | --- | --- |
| presence 严格一致 | 8/22 = **0.364** | ≥0.90 | **FAIL** |
| presence（仅可判定帧） | 8/8 = 1.000（覆盖 36.4%） | — | 参考 |
| reference availability 一致（可判定帧） | 8/8 = 1.000 | ≥0.90 | PASS（覆盖同 36.4%） |
| keypoint 欧氏距离（n=6，同源绿光） | 中位 **0.823 px** / P90 2.159 px / max 2.159 px | 中位≤2、P90≤4 | **PASS** |
| bbox IoU（n=6） | 中位 **0.4341** / P90 0.6677 | 中位≥0.50 | **FAIL** |
| 截断一致（可判定帧） | 6/8 = 0.750 | — | 记录 |

- 分层：**tiny_positive 12/12 全部 undecidable（LOW）**；small_green_cue 6/6 可判定（HIGH，presence 一致、kpt 0.82 px）；control_absent 4 帧中 2 帧可判定且均正确、2 帧 undecidable。
- 结论（引用 diag，不改写）：TINY 9.3–14 px 在盲标下**不能可靠判定 presence**（严格 0.364、bbox IoU 0.434）；既有 TINY 标签的 bbox 依赖 capture 投影先验（`bbox_source=PROJECTION_AID_CALIBRATED`），**不是独立视觉 GT**；小绿 cue 参考点可复现（0.82 px，同源）但 bbox 未达 0.5 IoU；TINY annotatability = **INCOMPLETE/FAIL**。
- 本盲标的 14 帧 undecidable + LOW confidence 被 diag 认定为真实可标注性证据，未作为本项目失败归因；**无需返工**，盲标文件未改（sha 仍 `be08ca8b…`）。
