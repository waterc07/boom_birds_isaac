# 试点 34 帧状态转移：final 池标注清单 → development/annotation calibration（2026-11-04）

> **状态：** BASELINE（状态记录；不删除、不改写任何试点标签文件字节）
> **来源章节：** T7 任务书（34 帧试点移出 final 标注清单、整体降级 development/exploratory）；`landmark_training_plan_v2.json` 的 `exposure_policy`
> **证据域：** 文档/清单状态；无模型、无导航、无 Gate 含义
> **最后核对：** 2026-11-04

## 变更记录

1. **34 帧试点（T6）** 原记录为 final 封存池（`configs/perception/landmark_final_pool_seal_v1.json`）的分层试点标注。现将其用途状态改为 **DEVELOPMENT / ANNOTATION_CALIBRATION**，不再作为 final/sealed 标注清单的一部分。
2. **整个 6 族 / 279 帧池**因试点期间已查看过**每个族的代表帧**（不止这 34 帧）而降级为 **development / exploratory**；不存在未被查看的 sealed final 残留（C3 INCOMPLETE）。
3. 本文件只记录状态转移，**不删除、不改写**：
   - `outputs/perception/landmark_final_annotations_20261104/labels_v1.json`（T6 试点标签，sha256 `fe8d47d03e6de8740099822830621edd76f97cb14633a6cb3e44ef08c12c8942`）
   - `pilot/labels_manifest.json`（T6 manifest，sha256 `e31ac902526e6eb582a61ae5102279473c5207a4067f4da91b3496b351dbf5a5`）
   - seal 文件本身（T5 产物，未修改）
4. 新的 279 帧 exploratory 标签中，这 34 帧逐帧标为 `dataset_role=ANNOTATION_CALIBRATION`；其余 245 帧为 `EXPLORATORY_EVAL`。
5. 同组污染：**6/6 族**受影响；不能通过删除这 34 帧来恢复其余帧的独立性（同族相邻帧同轨迹）。
6. 任何未来的 sealed/certification 评测需要**新的、未被查看过的**数据池与重新预注册（用户/组织决策）。
