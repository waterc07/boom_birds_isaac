# T26 身份案例标注：T25 补充采集就绪度与预注册规则（2026-11-04）

> **状态：** BLOCKED（WAITING_ON_T25_CAPTURE；T25 尚未采集，见 `team_task_list` task-25=pending）
> **来源章节：** `LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md` §1.4；`configs/perception/landmark_annotation_spec_v2_1.json`（FROZEN_FOR_DATA）；T25/T26 任务书
> **证据域：** 文档/流程准备（无新图像、无新标注、无模型）；当前 identity 数据仍为 T19 批 7 case/169 accepted/62 代表帧
> **最后核对：** 2026-11-04（HEAD `3491cde`）

## 1. 为什么 BLOCKED

- T26 依赖 T25（identity 补充采集：①MS1 与中央塔相互遮挡/前后景重叠；②远景 MS1 8–12 m，60–120 accepted RGB）。
- 现场核对：`outputs/sensor_shadow` 最新 identity run 仍是 `lm_dev_identity_capture_20261104`（T19 批，20:15 生成，已标注 62 帧）；`configs/scenarios/landmark_dev_identity_cases_v1.json` 仍只有 T19 的 7 个 case，没有 T25 的相互遮挡/远景 MS1 增量。
- 因此没有可用帧可标注。**不伪造标注、不把 T19 旧帧冒充 T25 新帧**。已把 task-26 的 blocked_by 设为 task-25。

## 2. 已预注册的规则（在见到 T25 图像之前冻结）

### 2.1 代表帧选择

- 规则 `identity_midpoint_systematic_v1`：每个新 case 的 accepted front_rgb 帧按 sequence 排序，midpoint systematic `floor((i+0.5)*n/k)`；总预算 24–32 帧（2 case 各 12–16），prior 不看模型分数、不看标签。脚本：`pilot/prepare_identity_t25.py`（--total 28 默认）。
- 选择清单与图像 sha 校验后才开始目视标注；选择规则写入 selection JSON（含 run、cases、每 case accepted/selected）。

### 2.2 标注规则（spec v2.1）

| 场景 | 标注 |
| --- | --- |
| 相互遮挡：目标部分被 MS1 遮挡 | present=true、occluded=true、visibility=PARTIAL、bbox 取目标可见部分（四边真实裁剪）、reference 按绿顶灯可见性（可见→MANUAL_APPROX/COLOR_CUE_ASSISTED；不可见→UNAVAILABLE + REFERENCE_OCCLUDED） |
| 相互遮挡：目标被 MS1 **完全挡住** | present=true、occluded=true、visibility=OCCLUDED、bbox=null、keypoint=null、reference UNAVAILABLE/REFERENCE_OCCLUDED = **GT_UNOBSERVABLE（非负例）** |
| 同框且 MS1 与目标**外观/尺度同等可信**（无法唯一判定） | ambiguous=true + candidates[]（两个候选，各含 bbox/green_cue/identity_hypothesis），**不写唯一 negative_type、不评定位**；不得猜 keypoint |
| 远景 MS1（8–12 m）单独 | target present=false + negative_type=SIMILAR_STRUCTURE + confusers[MS1 verified=true, verification_source=WORLD_POSE_OR_MAP_DB]（依据 `map_native_structures.json` 世界位姿 + 外观：细长平顶柱/侧挂绿灯/蓝侧条）；远景参考点过小 → REFERENCE_TOO_SMALL（green<3 或不可辨） |
| 远景中央塔（若出现） | 按 green_pixels 规则；green<3 → UNAVAILABLE/REFERENCE_TOO_SMALL，不猜 keypoint |
| 其他 | 四边截断逐边记录（ANNOTATOR_VISUAL）；bbox_source 按实际（视觉=ANNOTATOR_VISUAL；若使用投影=PROJECTION_AID_CALIBRATED 必须披露） |

- confuser 验证口径沿用 T19：`verification_source=WORLD_POSE_OR_MAP_DB`，note 引用 `docs/reports/perception/capture_dev_20261104/map_native_structures.json`（MS1 world (3.0,4.0)、顶 z≈1.78 m、绿灯 z≈1.71 m、map-native 非注入）+ 该帧外观；`verified` 仅表示"结构与地图/世界位姿可核验"，不表示真实场地分布已覆盖。
- 输出：标签 ignored（`outputs/perception/dev_annotations_20261104/identity_t25/labels_v1.json`）；仓库只留 selection/hash/统计/报告/少量 overlay。

## 3. 落地步骤（T25 采集完成后）

1. 运行 `prepare_identity_t25.py` 生成 selection（sha 记录）；2×放大 contact sheet 目视；
2. 逐帧 v2.1 标注（mutual occlusion / ambiguity / far MS1 / REFERENCE_TOO_SMALL）；
3. `scripts/validate_landmark_annotations.py` → PASS（0 error/0 warning）；
4. 更新 `labels_identity_dev.json` 增量（或新文件，按 datafreeze 要求）+ manifest/lists 记新 sha；
5. 报告 `T26_IDENTITY_T25_ANNOTATION_20261104.md`（帧数、case 分布、ambiguous/GT_UNOBSERVABLE/confuser verified 统计、QA、边界）；
6. send_message：lead / datafreeze / evaltool；不 commit/push。

## 4. 边界

- 单 agent 代理标注、SELF_CHECKED；不是人工独立审查，无标注员间一致性。
- MS1 verified 来自世界位姿/地图 DB + 外观，不是"真实分布已覆盖"；合成注入（若有）必须标 SYNTHETIC_INJECTED 且不冒充真实分布。
- 本准备文档不含任何新标注；未 commit/push；未跑 Isaac。
