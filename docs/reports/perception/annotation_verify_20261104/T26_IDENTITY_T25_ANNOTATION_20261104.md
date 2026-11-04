# T25 身份补充采集标注（相互遮挡 / 远景 MS1，2026-11-04）

> **状态：** PROVISIONAL（数据准备/标注增量；agent 代理标注；非模型效果、非导航/板端验收；不提升 Gate）
> **来源章节：** `LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md` §1.4/§2.1；`configs/perception/landmark_annotation_spec_v2_1.json`（FROZEN_FOR_DATA）；T25/T26 任务书
> **证据域：** 离线标注 QA（T25 identity 补充采集 2 case / 91 accepted RGB 中的 28 代表帧；Isaac 合成 320×240；无训练/推理/Isaac 运行）
> **最后核对：** 2026-11-04（HEAD `3491cde`）

## 0. 结论先行

1. T25 两个新 case 的**代表帧 28 帧已按 spec v2.1 标注完成**（相互遮挡 14 + 远景 MS1 14），格式 QA **PASS 28/28（0 error / 0 warning）**；标签在 ignored `outputs/perception/dev_annotations_20261104/identity_t25/labels_v1.json`（sha256 `a3f3109d475e4912fa4ba23ed5c0ee029ecdc0b0e0c5702aec122ea797ed0050`）。
2. **相互遮挡（14 帧）**：目标塔 present=true + **OCCLUDED + visibility=PARTIAL**；bbox 只覆盖 MS1 右侧可见目标部分；MS1 为前景 map-native 结构，部分遮挡远处塔（11.5–13.5 m）。target 绿顶灯 <3 px / 被近景 MS1 遮挡 → `UNAVAILABLE + REFERENCE_TOO_SMALL`，无 keypoint（不猜）。
3. **远景 MS1（14 帧）**：MS1 10.2–11.2 m，绿色灯严格像素 0–4 px（低于 3 px 锚点阈）→ target 不在视场（present=false、TARGET_ABSENT、`negative_type=SIMILAR_STRUCTURE`），MS1 记 `confusers[1], verified=true, verification_source=WORLD_POSE_OR_MAP_DB`；无 keypoint。
4. **同框不可判/歧义**：按任务要求逐帧检查"MS1 与目标同框且外观/尺度同等可信"的条件；本 28 帧中近景 MS1（细长平顶+侧挂绿灯+蓝侧条）与远景塔（对称顶灯架/R/白阶梯底座）在所选帧中均可区分 → **ambiguous=0**（不虚构歧义）；若后续更大重叠帧出现再按 ambiguous+candidates 处理。
5. **GT_UNOBSERVABLE**：本批 mutual 帧目标均有可见部分（无完全被 MS1 遮挡帧）→ **0**；T19 full_occlusion case 的 GT_UNOBSERVABLE 逻辑仍由既有 62 帧承载。
6. 计数口径：T25 sensor 记录 accepted 125（valid 69/56），实际 RGB 图像 91 帧（47 mutual + 44 far）；本批代表帧 28 = 每 case midpoint systematic 14，选择规则在见图像前预注册（`identity_midpoint_systematic_v1`，selection sha `1ddb093146e24afe0157b75dcbf0e8758a8b54a520f74d7211ee2e2da58b1683`）。

## 1. 数据与选择

| 项 | 值 |
| --- | --- |
| 采集 run | `outputs/sensor_shadow/lm_dev_identity_capture_t25_20261104` / `..._sensor`（run.complete PASS，21:23） |
| case | `lmf_devid_mutual_overlap_0`（47 imgs）/ `lmf_devid_ms1_far_0`（44 imgs） |
| 选择规则 | `identity_midpoint_systematic_v1`：每 case accepted 帧按 sequence midpoint systematic floor((i+0.5)*n/k)，k=14；总 28（24–32 预算内）；预注册、不看模型分数/标签 |
| 图像完整性 | 28/28 帧 image sha256 与文件一致（构建时逐帧重算） |
| 标签 | ignored；仓库只留 selection/hash/统计/报告/overlay 样例 |

## 2. 标注统计（分母=28）

| 指标 | 值 |
| --- | ---: |
| frames | **28** |
| mutual_overlap / ms1_far | 14 / 14 |
| present（PARTIAL） | **14** |
| absent（TARGET_ABSENT, SIMILAR_STRUCTURE） | **14** |
| ambiguous | **0**（条件已检查，未虚构） |
| GT_UNOBSERVABLE | 0 |
| reference UNAVAILABLE/REFERENCE_TOO_SMALL | **14**（全部 mutual 帧） |
| truncated | 0 |
| confusers / verified | **28 / 28**（MS1，WORLD_POSE_OR_MAP_DB） |
| green_pixels mutual | 8–16 px（属近景 MS1 灯，非目标） |
| green_pixels far | 0–4 px（远景 MS1 灯，低于 3 px 锚点阈） |

## 3. 标注口径与几何来源（披露）

- **MS1 验证**：`verified=true`、`verification_source=WORLD_POSE_OR_MAP_DB`，note 引用 `docs/reports/perception/capture_dev_20261104/map_native_structures.json`（MS1 world (3.0,4.0)、顶 z≈1.78 m、绿灯 z≈1.71 m、map-native 非注入）+ T25 case provenance + 外观（细长平顶/单侧绿灯/蓝侧条 vs 塔的对称灯架/R/白阶梯底座）。`verified` 仅指"结构与地图/世界位姿可核验"，不代表真实场地分布已覆盖。
- **几何来源**：bbox_source=`ANNOTATOR_VISUAL`；在 4 张 4× 放大 crop（mutual 帧 0/3/7/11、far 帧 14/18/22/26）实测模板后，对全部 28 帧按 2× contact sheet 估计/插值；**未使用** capture 投影/模型输出。该 bbox 是代理估计，不是像素级人工 GT，下游若用于 appearance-gate 特征需注意此误差。
- **参考点**：严格绿光规则（g≥90、g-r≥25、g-b≥25，最大 4 连通块）；mutual 帧目标绿顶灯不可分辨/被遮挡 → `REFERENCE_TOO_SMALL`；far 帧目标不在视场 → NOT_APPLICABLE。全部 `reference_source=COLOR_CUE_ASSISTED`（如给 keypoint）或 NOT_APPLICABLE；`independent_of_detector_cue=false`。
- **工作模式**：`FRAME_BY_FRAME_VISUAL`、AGENT_PROXY、SELF_CHECKED；非人工独立审查，无标注员间一致性。

## 4. QA

| 项目 | 结果 |
| --- | --- |
| 校验器 | `scripts/validate_landmark_annotations.py`（v2.1） |
| labels_identity_t25 | **PASS 28/28**，0 error / 0 warning |
| QA report | `outputs/perception/dev_annotations_20261104/identity_t25/qa_v1.json` sha `0c85d5edcfdee3d487eb6bd5d6b198dd7ada6b937660b0167c000132d842dfde` |
| overlays | `docs/reports/perception/annotation_verify_20261104/pilot/identity_t25/overlays`（28 张，q82） |
| 语义自检 | 3 张 2× contact sheet + 7 张 4× crop：mutual 帧目标在 MS1 右侧可见部分/头臂可辨；far 帧无中央塔、MS1 远景绿灯 0–4 px |

## 5. 证据与其 sha

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| `outputs/perception/dev_annotations_20261104/identity_t25/labels_v1.json`（ignored） | 28 帧 v2.1 标签 | `a3f3109d475e4912fa4ba23ed5c0ee029ecdc0b0e0c5702aec122ea797ed0050` |
| `outputs/perception/dev_annotations_20261104/identity_t25/selection.json`（ignored） | 代表帧选择（预注册规则） | `1ddb093146e24afe0157b75dcbf0e8758a8b54a520f74d7211ee2e2da58b1683` |
| `outputs/perception/dev_annotations_20261104/identity_t25/qa_v1.json`（ignored） | 格式 QA（PASS 28/28） | `0c85d5edcfdee3d487eb6bd5d6b198dd7ada6b937660b0167c000132d842dfde` |
| T25 采集 | run dir + GUI 证据（capture 报告 pending/另出） | 见 capture 产物 |
| 地图原生结构 | MS1 世界位姿/外观依据 | `map_native_structures.json`（capture 目录） |

## 6. 边界与待决

1. **代理标注**：bbox 为视觉估计（4×/2× 目视模板 + 插值），非像素级人工 GT；不是认证/第三方真值；不得用于认证精度声明。
2. **合成/地图原生**：MS1 是 map-native（非注入）；T25 两 case 为 development 数据；不得当作真实赛场分布证明。
3. **未并入 labels_val**：本批为独立文件，待 datafreeze 决定 freeze v4.3 的 val_identity 增量（evaltool 的 consumer 评估可直接消费该文件）。
4. 本批 **ambiguous=0 / GT_UNOBSERVABLE=0** 是逐帧检查结果，不是遗漏；若 lead 需要"强制困难案例"可另采，不虚构。
5. 未 commit/push；未跑 Isaac；未改原始帧。

## 7. 来源核实与状态降级（2026-11-04，lead 质疑后追加；只追加，不改标签坐标/overlay）

**结论：本批 28 帧来自 T25 的 PILOT run，不是 formal run → 整批标 `PROVISIONAL_DIAGNOSTIC_ONLY`，不得并入 v5 / 不得作 val_identity GT。**

### 7.1 来源（实测）

| 项 | 值 |
| --- | --- |
| 本批图像 run | `outputs/sensor_shadow/lm_dev_identity_capture_t25_20261104_sensor`（= pilot run 的 sensor 侧） |
| pilot run 元数据 | `..._t25_20261104/manifest.json`：started_at `2026-11-04T21:22:35+08:00`、HEAD `3491cde`、cases = mutual_overlap + ms1_far、run.complete **PASS（仅 pilot）** |
| pilot 机位问题 | lead 指出 case A（mutual_overlap）目标被**完全挡住**；因此本批 mutual 帧"目标部分可见/PARTIAL + bbox"是在错误机位下的**暂定判断**，不得当 GT |
| formal run | `..._t25_20261104_formal`：**无 run.complete**，`summary.error.txt` 为 Isaac Sim reset/rigid-object buffer 初始化失败（CUDA/Isaac 运行时），GUI exit=0 但 formal 未完成 |
| formal sensor 残留 | `..._formal_sensor`：仅 mutual_overlap case 37 张 RGB，无 run.complete，不能作为 formal 数据 |
| 两 run 图像对比 | 看了 pilot/formal 的 `lmf_devid_mutual_overlap_0-follow_only_g1_11.png`：两者机位/画面基本一致（同一 case 几何），不能据此判定 target 可见性；需 capture 重跑后以合格机位图像复核 |

> 更正 §0/§1 的表述：此前写"T25 run 21:23 PASS / accepted 125"实际是 **pilot run**；formal run 失败，未完成。pilot 91 RGB（47 mutual + 44 far），formal 仅残留 37 张（mutual）。

### 7.2 状态与使用限制

- 标签顶层 status 改为 **`PROVISIONAL_DIAGNOSTIC_ONLY`**，并加 `provenance_clarification` 块（source_run / formal_run / use_restriction / unchanged）；**annotation 行与坐标未改**（annotations 内容 sha `82b5c392…` 与降级前一致；文件 sha 因顶层元数据变化：`a3f3109d…` → `7164a5d6…`）。
- **不得**：并入 dev freeze v5、作为 val_identity GT、进入 consumer identity false-match 分母、作为"MS1 相互遮挡"能力的正式证据。
- **可以**：作为标注流程演练/诊断性检查；等 capture 用合格机位重跑 T25 formal（两 case、60–120 accepted、run.complete PASS）后，我按同一预注册选择规则重新选帧、复核/重标，并在报告 7.3 记录新的 sha 与来源。
- QA 仍为格式 PASS（28/28，0 error/0 warning）；格式 PASS 不代表语义/来源合格。

### 7.3 待办

- [ ] capture 重跑 T25 formal（修复 CUDA/机位；case A 目标可见性需逐帧记录；run.complete PASS）
- [ ] 重跑后 → 重新选择代表帧 → 复核/重标 → 新标签文件（新 sha）+ 报告更新（只增不改旧诊断批）
- [ ] 若 formal 重跑仍失败，lead 决定是否降级为"仅 far MS1 可用"或以 T19 identity 62 帧为准

## 8. 最终收尾：T25 INCOMPLETE，本批诊断标签定稿（2026-11-04，capture 确认后追加）

capture 已确认 T25 来源与结论（见 `docs/reports/perception/capture_dev_20261104/T25_CAPTURE_INCOMPLETE_20261104.md`，sha256 `440f528d9862520563d715a834034ee27d8a00a0d40144605786647f6167b29f`；provenance `t25_provenance_20261104.json`，sha256 `b513d82ce729f9aec4e962c1e4c837774766a3ee44efe761b8abebe7eee021a5`）：

| 项 | 结论 |
| --- | --- |
| 本批 28 帧 | 来自 **T25 pilot run**（`lm_dev_identity_capture_t25_20261104_sensor`；pilot run.complete PASS、accepted RGB 85、RGB 图像 91）；**不是 formal run** |
| pilot 机位 | 图像复核为**不合格**：① mutual_overlap 近景 MS1 把远景中央塔基本挡住，不能确认"两者可辨"；② 远景 MS1 视角被场地中央结构在前景占满。→ pilot 只作诊断 |
| formal | 两次失败（attempt1 torch 扩展 import 异常；attempt2 第二案 CUDA OOM），无 run.complete；**按 lead 决定不再重跑** |
| T25 池 | **INCOMPLETE**：未交付合格 60–120 accepted RGB 池；v5 不依赖 T25 |
| 本批标签 | 维持 `PROVISIONAL_DIAGNOSTIC_ONLY`；**不并入 v5、不作 val_identity GT、不用于模型/阈值决策、不进 consumer 误匹配分母**；capture 确认**无需重新选帧/重标** |
| 与 §7.3 的关系 | §7.3 的"等 capture 重跑后重选/重标"**已被 capture 的"不再重跑"决定取代**；不再有重标计划 |

- capture 在 pilot 复核后已把两个新 case 的机位调好（A：重叠约 10–25%、目标灯在 MS1 轮廓外；B：正西 ~10 m、MS1 居中），但**未再采集验证**，只记待办、不作证据。
- **identity 缺口说明**：v5/consumer 评测的 identity 覆盖继续以 T19 `labels_identity_dev.json`（62 帧，sha `79fd1745…`）为准；T25 缺口可直接引用 capture 报告 §1/§5/§6。
- **holdout**：T25 失败不改变 holdout 准备（`HOLDOUT_ANNOTATION_PLAN_20261104.md` + `pilot/holdout_annotation_pipeline.py`）；当前 holdout 仍 NOT_TRIGGERED，等 lead GO；holdout 需覆盖 real map confuser / same-frame ambiguity 时不能假设 T25 已提供，需在新采集中重新设计机位。
- 本批标签文件现状：sha `7164a5d6…`（status=PROVISIONAL_DIAGNOSTIC_ONLY；annotations 内容 sha `82b5c392…`，坐标未改）；QA 格式 PASS 28/28（不代表语义/来源合格）。
- 结论：T26 以"诊断性批次"收尾，不再占用标注资源；后续 identity 补充需 lead 决定是否另采（独立新批次，重新预注册机位与选择规则）。
