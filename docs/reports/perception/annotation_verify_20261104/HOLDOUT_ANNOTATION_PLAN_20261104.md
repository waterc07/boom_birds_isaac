# Holdout 标注准备：规范、工具与工时预估（2026-11-04）

> **状态：** PREPARED_NOT_TRIGGERED（holdout 当前 NOT_TRIGGERED；等 lead 按 improvement gate 触发；本文件不预标注、不采集）
> **来源章节：** `configs/perception/landmark_improvement_gate_v1.json`（development_to_holdout_gate / holdout_rules）；`LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md` §1.4/§2.1；`configs/perception/landmark_annotation_spec_v2_1.json`（FROZEN_FOR_DATA）
> **证据域：** 文档/工具准备（无 holdout 图像、无新标注、无模型）；TINY/T25/T16 的经验用于工时预估
> **最后核对：** 2026-11-04（HEAD `3491cde`）

## 0. 结论先行

- holdout 触发条件（gate）目前 **未满足/未触发**：improvement gate 要求 val joint ≥0.60 且 Δ≥+0.08、identity 不恶化、reference coverage ≥0.50、worst-group 不差于 baseline +0.05；当前 STOP（两个候选未过 pilot gate，不 3 seed、不 holdout）。
- 一旦触发，标注侧需要 **≥3 新族 / 200–400 帧**、覆盖 small target、close-range truncation、target absent、real map confuser、same-frame ambiguity；采样规则**先冻结后采集**，标注用 frozen spec v2.1+，QA PASS，并登记 exposure（谁何时看过哪些图）。
- 本文件已备好：样本选择/校验/统计工具（`pilot/holdout_annotation_pipeline.py`）、标注协议（§2）、分母/QA 规则（§3）、**工时预估**（§4：200 帧约 7–15 h，400 帧约 14–30 h，agent 执行、非承诺工期）。
- 关键前置：lead 触发 + 数据冻结方给出先冻结抽样规则 + capture 完成 + 是否投入独立人工标注（用户决定）；在此之前**不预标注**。

## 1. 样本与抽样（先冻结后采集）

| 项 | 规则 |
| --- | --- |
| 规模 | 200–400 accepted RGB；≥3 新轨迹族（family），与旧 dev/exploratory 无同族/同轨迹/sha 重叠 |
| 条件覆盖（必含） | small target（且尽量含 9–14px 与 15–22px 两档）、close-range truncation（左/右/下缘）、target absent、real map confuser（map-native MS1/其他绿顶柱）、same-frame ambiguity（MS1+目标同框且外观/尺度接近） |
| 抽样 | **capture 前冻结**：按 family 分层；每层 systematic/midpoint；不看模型 predictions/score；不用旧 final 结果；条件配额表先写入 holdout sampling JSON |
| 暴露登记 | 记录谁（agent/user）、何时、看了哪些帧、用途；holdout 用后不得再作训练/调参/final 重用 |
| 选择工具 | `holdout_annotation_pipeline.py selection`（family 分层 + midpoint systematic + 每帧 image sha 校验 + 条件配额统计）；输出 selection JSON（含规则、分母、sha） |

## 2. 标注协议（绑 spec v2.1，不新增 v2.2 字段）

- **盲/隔离**：holdout 标注者不读模型预测、旧 final 指标、训练标签；同 agent 执行按 gate 定义称 **PROCESS-ISOLATED HOLDOUT**，不是第三方 sealed/认证真值。
- **bbox**：spec v2.1 塔体口径（head/light-rack + 收分塔体 + 相连阶梯底座，四边真实裁剪）；有投影时若使用必须标 `bbox_source=PROJECTION_AID_CALIBRATED` 并披露；纯目视则 `ANNOTATOR_VISUAL`。
- **参考点**：严格绿光规则（g≥90、g-r≥25、g-b≥25，最大 4 连通块）；green_pixels≥3 且目视确认绿顶灯在标注位置才给 keypoint；否则 UNAVAILABLE + reason（REFERENCE_TOO_SMALL / REFERENCE_OCCLUDED / REFERENCE_NOT_PRESENT）；`reference_source=COLOR_CUE_ASSISTED`、`independent_of_detector_cue=false`（同源披露）。
- **目标状态**：present/undecidable/absent 三态；完全遮挡 → present+OCCLUDED+无 bbox = GT_UNOBSERVABLE（不是负例）；同框歧义 → ambiguous=true + candidates[]（不评定位、不猜 keypoint）；无 negative_type 于 undecidable/ambiguous。
- **confuser**：verified=true 需非图像证据（`WORLD_POSE_OR_MAP_DB` 或构造记录 `EXTERNAL_EVIDENCE`）；合成注入标 SYNTHETIC_INJECTED 且不冒充真实分布；仅图像证据 verified=false。
- **截断**：逐边 + truncation_source（ANNOTATOR_VISUAL；有采集元数据可 BOTH）；truncated=any(edge)。
- **置信度**：每帧 HIGH/MEDIUM/LOW（可放 notes/扩展字段），用于可标注性分层；TINY 结论要求"不可标注"不得用猜 bbox 掩盖。

## 3. 分母与 QA

- 分母规则（spec v2.1 quality_gate）：GT_UNOBSERVABLE **单列**、不进 TP/FP/FN/TN；ambiguous 默认不进正/负分母；undecidable 不是负例；keypoint 分母=present 且 reference 可用（v=1）；coverage 分母=present 且 MANUAL_APPROX。
- QA：①每帧 `scripts/validate_landmark_annotations.py` **PASS 0 error/0 warning**；②每 10 帧抽 1 帧独立复核对 bbox/keypoint/截断（第二遍目视，记录不一致）；③统计（present/undecidable/absent/GT_UNOBSERVABLE/ambiguous/reference 可用性/截断/confuser/尺度分桶）落 JSON+报告；④标签 ignored，仓库只留 selection/清单/hash/统计/少量 overlay/报告。
- 失败/不可标注处理：分辨率不足或目标 <可靠阈值 → undecidable + reason（并作为可标注域证据），不得为了覆盖而猜；小样本类别给分母与缺口。

## 4. 工时预估（agent 执行，经验值，非承诺）

| 帧类型 | 单帧时间（含 notes） | 说明 |
| --- | ---: | --- |
| 标准正例/负例（绿≥3、目标可辨） | 1.5–3 min | bbox+keypoint+文字 |
| 困难帧（ambiguous/遮挡/远景/9–14px） | 3–6 min | 多假设/放大/不确定记录 |
| contact sheet 复核+QA+validator | ~0.3 min/帧 | 12 帧/张，2× |
| 独立复核抽样 10% | +0.5 min/帧 | 第二遍 |

估算（按 60% 标准 + 40% 困难）：
- **200 帧**：200×(0.6×2.25+0.4×4.5)=200×3.15 ≈ 630 min ≈ **10.5 h** + setup 1 h + 复核 1 h ≈ **12.5 h（范围 8–17 h）**。
- **400 帧**：≈ **25 h（范围 16–32 h）**。
- 分 6–8 个批次（每批 ≤2 h）执行，避免长会话误标；含 holdout 暴露登记与报告撰写约 +2 h。
- 风险：9–14px 目标可能大面积 undecidable（TINY 证据 12/12），会降低有效标注覆盖但**不得降低标准**；若要求独立人工双标+仲裁，工时按人工另算（用户决定）。

## 5. 工具与落点

| 工具/文件 | 用途 |
| --- | --- |
| `pilot/holdout_annotation_pipeline.py` | selection（family 分层 + 规则冻结 + sha 校验）、stats（分母/条件/尺度）、report 骨架 |
| `pilot/validate_landmark_annotations 间接` | 每批 `scripts/validate_landmark_annotations.py` |
| 标签落点（ignored） | `outputs/perception/holdout_annotation_20261104/labels_v1.json`（触发后创建） |
| 仓库留档 | `docs/reports/perception/annotation_verify_20261104/HOLDOUT_ANNOTATION_20261104.md`（触发后）+ selection/hash/统计/overlay 样例 |

## 6. 触发清单（lead 打勾后开工）

- [ ] improvement gate PASS（或 lead 明确 waiver 并记录原因）
- [ ] holdout sampling 规则先冻结（datafreeze/capture 提供）
- [ ] capture 完成、图像 sha 可读、exposure 登记表就绪
- [ ] 标注者隔离确认（不读 predictions/旧 final/训练标签）
- [ ] 预算批准（200–400 帧、工时范围、是否人工双标）
