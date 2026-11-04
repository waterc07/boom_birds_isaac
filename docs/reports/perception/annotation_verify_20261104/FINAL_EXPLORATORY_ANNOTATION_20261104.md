# final 探索池 279 帧完整标注与语义 QA（2026-11-04）

> **状态：** PROVISIONAL（数据准备/标注产出；exploratory/development 标签；**不是** human 独立标注、**不是** sealed final、**不是**模型效果/板端/导航证据，不提升任何 Gate）
> **来源章节：** `SYSTEM_ARCHITECTURE_V2_2.md` §7.5/§7.6/§7.7/§7.8（地标接力、歧义多假设、可见地标输出、目标相对定位）；`LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md` §1.4/§2（HN1–HN6、presence/reference/identity/joint 分母）；标注规范 `configs/perception/landmark_annotation_spec_v2_1.json`
> **证据域：** 离线标注 QA（T1 final 候选池 6 族 279 accepted 帧，Isaac 合成 RGB 320×240；agent 代理 BULK_CALIBRATED_WITH_FULL_VISUAL_QA；无模型训练/推理、无 Isaac 运行、无板端/SITL/实飞/导航）
> **最后核对：** 2026-11-04（仓库 `E:\isaac\proj_boom_birds`，分支 `feat/v2.2-simulation-perception`，HEAD `800c53b`；以现场为准）

## 0. 结论先行

1. **规模**：T5 seal 的 279 个 accepted 帧（6 族）**全部完成标注**；24 个 QA contact sheet 覆盖全部 279 帧的视觉复核，1 帧（`lmf_backoff g2_69`，无绿光锚点）在复核中人工修正 bbox，其余 278 帧按校准先验通过复核。
2. **标注统计（分母=279）**：present **238** / absent **41**；参考点可用 **218** / 不可用 **20**（全部为 backoff 远景帧，`green_pixels` 0–2 → `REFERENCE_TOO_SMALL`）；截断 **48**（右缘 24、下缘 42，其中 edge 族 18 帧同时右+下）；visible 分布 FULL 190 / PARTIAL 48 / ABSENT 41；undecidable **0**、ambiguous **0**、occluded **0**、GT_UNOBSERVABLE **0**；negative_type 全部 `TARGET_ABSENT` 41（SIMILAR_STRUCTURE/OTHER_LANDMARK 0）。
3. **格式 QA**：`validate_landmark_annotations.py` 对 v2.1 标签文档运行 → **PASS 279/279，0 error / 0 warning**；标签在 ignored 目录，仓库仅保留清单/hash/统计/12 张 overlay 样例/报告。
4. **关键状态变更**：34 帧试点已使整个 6 族池**降级为 development/exploratory**（6/6 族都看过代表帧，只删除 34 帧不能恢复独立性）；本报告标签**不得**再称 sealed final、不得用于 sealed-final 一次性评测或对接认证（C3 INCOMPLETE）。试点状态转移记录：[pilot/PILOT_STATUS_UPDATE_20261104.md](pilot/PILOT_STATUS_UPDATE_20261104.md)。
5. **与 34 帧试点一致性**：34 帧全部命中；present 34/34、truncated 34/34；bbox IoU 均值 0.669（中位 0.682，n=25）；keypoint 差均值 0.164 px（max 0.316 px，n=21）。
6. **方法边界**：bbox 由 capture 塔体跨度 + 试点 25 帧标定的先验生成（`bbox_source=PROJECTION_AID_CALIBRATED`），再对全部帧做视觉复核；参考点取绿光颜色质心（`reference_source=COLOR_CUE_ASSISTED`，`independent_of_detector_cue=false`）。这是**代理标注 + 投影助记**，不是人工像素标注；不得用于证书级精度声明。
7. **HN 覆盖**：HN3（边缘截断）24 帧、HN4（远景小目标/无参考）20 帧、HN5（目标不存在）41 帧有覆盖；**HN1（带绿灯相似结构）0 帧 verified、HN2（完全遮挡）0 帧**（本池未构造，未虚构）；HN1 的已有候选证据仍是旧数据 `static_c` 的 ~6×25 px 绿色顶端结构（T2/T6 报告继承）。

## 1. 数据、状态降级与同组污染

| 项目 | 值 |
| --- | --- |
| seal | `configs/perception/landmark_final_pool_seal_v1.json`，canonical `cedbbc7e1cd455f022d5f7c5f7f7925f046d9eebeb2581ca789ee25f7ce81007` |
| seal 原始状态 | SEALED_TEST_POOL_FROZEN_LABELS_PENDING（279 accepted / 297 RGB，6 族 test-only） |
| 本报告有效状态 | **DOWNGRADED_TO_DEVELOPMENT_EXPLORATORY_AFTER_34_FRAME_PILOT** |
| source run | `outputs/sensor_shadow/lm_final_candidate_20261104_sensor`（320×240，fx=160，cx=160，cy=120） |
| 标注数据角色 | 34 帧 `ANNOTATION_CALIBRATION` + 245 帧 `EXPLORATORY_EVAL` = 279 |
| 图像完整性 | 279/279 帧 sha 与 seal/conditions 记录一致（校验器逐帧重算） |

**降级理由（同组污染，不可只删 34 帧）**：

- T6 试点按中点系统抽样在 **6 个族全部**取了代表帧（sweep 8 / backoff 6 / near 5 / edge 6 / similar 6 / side 3），标注者已看到每族画面；
- 同族帧来自同一轨迹/同一 session，连续帧高度相关；删掉 34 帧后剩余帧仍与已看帧同组；
- 因此 **6/6 族受影响**，不存在"未被查看的 sealed final 残留"；任何"final 一次性评测"都失去独立性（`landmark_training_plan_v2.json` 的 `certification_conditions.C3` = INCOMPLETE）。
- 未来认证级评测需要**新的、未查看过的**数据池 + 重新预注册（用户/组织决策）。

## 2. 标注方法与视觉复核

### 2.1 规范

- 执行规范：`configs/perception/landmark_annotation_spec_v2_1.json`，sha256 **`010255d931936457ded48db9b3691b69a31d6015f1f84fbbc6a659f10f766eac`**，status **FROZEN_FOR_DATA**（lead 2026-11-04 批准；v1/v2 仍向后兼容）。
- 使用字段：`target.present/undecidable/visibility/truncated/truncated_edges/truncation_source/truncation_conflicts/occluded/ambiguous`、`geometry.bbox_xywh/bbox_source/keypoint/green_pixels/reference_status/reference_unavailable_reason/reference_source`、`confusers`（本轮为空）、`negative_type`、`annotator.{annotator_type,annotation_mode,independent_of_model_dev,independent_of_detector_cue,review_status}`、`dataset_role`、`pixel_basis`。

### 2.2 标注模式与生成方式

- `annotator.annotation_mode = BULK_CALIBRATED_WITH_FULL_VISUAL_QA`；`geometry.bbox_source = PROJECTION_AID_CALIBRATED`；`annotator_type = AGENT_PROXY`、`review_status = SELF_CHECKED`、`independent_of_model_dev = true`、`independent_of_detector_cue = false`。
- **bbox 先验**：capture 的 `predicted_tower_span_u_px`（位姿/几何投影，属投影助记）作为横向跨度；在 25 个试点正例上网格搜索标定得到 **宽度 = 0.85×span、高度 = 1.0×span、顶边 = 绿光质心 y − 6 px**（试点 bbox IoU 均值 0.669 / 中位 0.682）。先验强制在四边裁剪，溢出边置 `truncated_edges`。
- **参考点**：严格绿光阈值（`g≥90, g-r≥25, g-b≥25`，最大 4 连通域）像素数 ≥3 且目视确认时标注；否则 `keypoint=null + UNAVAILABLE + REFERENCE_TOO_SMALL`。坐标取该绿光质心（`reference_source=COLOR_CUE_ASSISTED`，与检测器绿色 cue 同源，已披露）。
- **视觉复核（全量，不抽样）**：279 帧渲染为 24 张 contact sheet（每张 12 帧、原生分辨率、bbox+keypoint 叠加、帧序号/族/sequence/green_pixels/截断标记），逐张检查：目标存在性、bbox 对齐、四边截断、keypoint 落点、负例画面。复核索引：`pilot/qa_sheets_index.json`（sha256 `f8e602f7…c1407`），图片在 `pilot/qa_sheets/`（JPEG q82，1.67 MB）。
- **逐帧修正**：1 帧（`lmf_backoff_0-follow_only_g2_69`：green_pixels=0、无绿光锚点、插值锚点导致 bbox 偏移）在复核中改为目视 bbox `[129,115,47,46]`。其余 278 帧接受先验。
- **QA 标记**：锚点来源统计 strict green 227 / relaxed green 43 / 邻居插值 6 / 帧中心回退 3；其中 5 个插值帧与 3 个回退帧都是 **absent 负例**（无需 bbox），唯一受影响的 present 帧 g2_69 已修正。
- **序列一致性自检**：19 处中心/尺寸跳变全部对应 sweep/backoff 轨迹 waypoint 的高度/偏航变化（相邻帧绿光 y、跨度的同步变化），复核后接受；0 处 bbox 越界、0 处 keypoint 在框外、0 处 truncated 与 edges 不一致。

## 3. 279 帧统计

### 3.1 总体（分母=279）

| 指标 | 数值 |
| --- | --- |
| frames | **279** |
| present / absent | **238 / 41** |
| reference_status：MANUAL_APPROX / UNAVAILABLE | **218 / 20**（不可用全部在 backoff 远景，green_pixels 0–2） |
| visibility：FULL / PARTIAL / ABSENT | **190 / 48 / 41** |
| truncated（任一四边） | **48**：right **24**、bottom **42**、left 0、top 0；right+bottom 同时 18（全部 edge 族） |
| truncation_source | right: BOTH 24；bottom: ANNOTATOR_VISUAL 42（采集元数据未记录上下缘，见 §7） |
| undecidable / ambiguous / occluded / GT_UNOBSERVABLE | **0 / 0 / 0 / 0** |
| negative_type | TARGET_ABSENT **41**；SIMILAR_STRUCTURE 0；OTHER_LANDMARK 0 |
| green_pixels 分布 | 0–2：**52**；3–9：**114**；10+：**113** |
| bbox 尺寸范围（238 正例） | 最小 **27.8×32.7 px**（909 px²，backoff g2_66）～最大 **168×144.6 px**（24,293 px²，near g3_18） |
| dataset_role | ANNOTATION_CALIBRATION **34** / EXPLORATORY_EVAL **245** |

### 3.2 逐族

| 族 | 帧 | 正 | 负 | 参考可用 | 参考不可用 | 截断 | 右缘 | 下缘 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lmf_sweep | 111 | 111 | 0 | 111 | 0 | 0 | 0 | 0 |
| lmf_backoff | 76 | 76 | 0 | 56 | 20 | 1 | 0 | 1 |
| lmf_near | 23 | 23 | 0 | 23 | 0 | 23 | 0 | 23 |
| lmf_edge | 28 | 28 | 0 | 28 | 0 | 24 | 24 | 18 |
| lmf_similar_negative | 38 | 0 | 38 | 0 | 0 | 0 | 0 | 0 |
| lmf_side_negative | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0 |
| **合计** | **279** | **238** | **41** | **218** | **20** | **48** | **24** | **42** |

> 注：near 族 23 帧全部因**塔体连接底座在下缘被裁**记 bottom 截断；edge 族 18 帧同时右缘+下缘；这与采集时只记录左右截断的元数据不一致，属 §7 的 P1 事实，已按标注优先记录。

## 4. 条件覆盖与困难负例映射

| 条件 | 本池帧数 | 对应 HN | 本轮标注观测 |
| --- | ---: | --- | --- |
| normal / 中距 | 111 sweep + 56 backoff（参考可用） | — | 全正例、参考点可用 |
| 尺度/距离（远景，≥7 m） | backoff 20 帧（green_pixels 0–2） | HN4 | 参考点全部 UNAVAILABLE/TOO_SMALL，不猜 keypoint |
| 近距 | 23 near（1.46–1.78 m） | — | 23/23 正例，底座下缘裁切 |
| 右缘截断 | 24 edge | HN3 | 24 帧 right=true，其中 18 帧同时 bottom |
| 目标不存在（相机朝后） | 38 similar_negative | HN5 | 全负例；画面为中央场地结构/机器人，无塔；green 0–2 px 亚阈值 |
| 目标出视场 | 3 side_negative | HN5 | 全负例；无塔、无绿光 |
| 相似结构（带绿灯、已验证） | **0** | HN1 | **未构造**；HN1 仍以旧 static_c 证据为候选（未验证） |
| 完全遮挡 | **0** | HN2 | **未构造，未虚构** |
| 场景结构遮挡 / 多候选 / undecidable | **0** | — | **未构造，未虚构** |

## 5. 格式 QA（与语义自检分开）

### 5.1 格式 QA（机器校验）

```powershell
& E:\isaac\env_isaaclab\Scripts\python.exe scripts/validate_landmark_annotations.py `
  --annotations outputs/perception/final_exploratory_20261104/labels_v1.json `
  --root . `
  --overlay-dir outputs/perception/final_exploratory_20261104/label_overlays `
  --output docs/reports/perception/annotation_verify_20261104/pilot/exploratory_label_qa_report.json
```

| 项目 | 结果 |
| --- | --- |
| 状态 | **PASS** |
| 记录数 | **279** |
| errors / warnings | **0 / 0** |
| 标签 sha256 | `7115ee04cd2db33381047e6952541ee2bb5214df994a35df8f55ec24d7d79504` |
| QA report sha256 | `220928047282c2cffdf6828f57c852eb8ac193d3d468ea8029087bcd22883bc3` |
| 全量 overlay（ignored） | `outputs/perception/final_exploratory_20261104/label_overlays/`（279 张） |
| 仓库 overlay 样例 | `pilot/exploratory_overlays_sample/`（12 张：normal/远景/近距/edge/负例） |

校验覆盖：image sha/尺寸与 pixel_basis 一致、bbox 界内与四边裁剪、truncated 与 truncated_edges 一致、每个 true 边有 truncation_source、keypoint 界内/框内、green_pixels 记录且 keypoint 仅在 green≥3 时存在、present/undecidable 三态、negative_type、annotator provenance、dataset_role、group/split、重复帧、candidate/confuser 约束。**格式 PASS 只证明文件自洽合法，不证明语义正确。**

### 5.2 语义自检（人工/目视口径，非机器证明）

- **存在性**：238 正例逐帧确认画面内有中央塔；41 负例逐帧确认画面内**无**中央塔（similar_negative 画面为中央场地结构/机器人；side_negative 为空场地/矮墙）。
- **参考点**：218 个可用参考点均落在头部绿灯位置；20 个不可用帧确认绿光不可辨（green_pixels 0–2）；0 个"参考点不可见却输出 keypoint"。
- **四边截断**：48 个截断帧逐帧确认目标结构在对应图像边界继续延伸；near/edge 的下缘截断经放大图复核（底座被裁）。
- **bbox/框内**：0 处 bbox 越界、0 处 keypoint 在框外、0 处退化框。
- **局限**：这是**单代理目视自检**，不是第三方/人工独立复核，也不是与独立真值的比对。

## 6. 与 34 帧试点重叠与一致性

| 项目 | 结果 |
| --- | --- |
| 试点帧命中 | 34/34 |
| presence 一致 | **34/34** |
| truncated（布尔）一致 | **34/34** |
| bbox IoU（试点 vs 本轮，n=25 正例） | 均值 **0.669** / 中位 0.682 / 最小 0.284 / 最大 0.956 |
| keypoint 像素差（n=21） | 均值 **0.164 px** / 中位 0.2 / 最大 0.316 px |

解释：本轮 bbox 是"投影先验 + 全量视觉复核"，试点 bbox 是"人工目视近似"；0.669 的 IoU 差异主要来自口径/画框习惯（试点框更宽松），而非目标身份差异。34 帧在标签中统一标 `dataset_role=ANNOTATION_CALIBRATION`，其余 245 帧 `EXPLORATORY_EVAL`；试点原件（`outputs/perception/landmark_final_annotations_20261104/`，sha `fe8d47d0…c8942`）未删除、未改写。

## 7. 争议帧 / 特殊处理（单列）

| 类别 | 帧/数量 | 处理 |
| --- | --- | --- |
| 无绿光锚点、bbox 需目视修正 | `lmf_backoff g2_69`（1 帧） | 改为目视 bbox `[129,115,47,46]`；其余同情况帧为 absent 负例（无需 bbox） |
| 参考点不可用（远景） | backoff 20 帧（green 0–2） | `keypoint=null + UNAVAILABLE + REFERENCE_TOO_SMALL`；不猜 |
| 目标缺席 | similar_negative 38 + side_negative 3 = 41 帧 | `present=false, visibility=ABSENT, negative_type=TARGET_ABSENT`，无几何；未把中央场地结构写成已验证相似结构 |
| 非截断边界样本 | `lmf_edge g4_29` 等 4 帧 edge | 逐帧确认在画内，truncated=false |
| 下缘截断（采集元数据未记录） | near 23 帧、edge 18 帧、backoff 1 帧 | 标注优先记 bottom=true / `ANNOTATOR_VISUAL`；采集元数据只记录左右，未产生"冲突"（无 bottom 字段） |
| 序列跳变 | 19 处中心/尺寸跳变 | 均对应 waypoint 高度/偏航变化，复核接受 |
| ambiguous / undecidable / occluded | 0 帧 | 本池无此类帧，未虚构 |

## 8. v2.1 规范可执行性反馈

- **够用**：四边截断 + truncation_source 让 near 底部、edge 右+下缘可以如实记录；green_pixels 判据让 20 个远景帧不再猜参考点；dataset_role 支持 34 帧→calibration 转移；bbox_source/annotation_mode 支持"投影先验+视觉复核"的诚实标注；格式校验器可直接跑通 279 帧、0 error/0 warning。
- **未使用/待补**：`confusers[]` 本池**未使用**（similar_negative 未验证相似塔；不写 verified=false 之外的断言、也不冒充实证）；HN1/HN2 仍缺实帧；无 human reviewer。
- **建议**：后续补采 HN1（带绿灯相似结构）/HN2（完全遮挡）时，必须用 `confusers[]` 记录候选并以 `verified=true/false` 区分；采集元数据补四边截断；若要证书级，需要 ≥2 名独立人工标注 + 仲裁（用户事项）。

## 9. 边界与不可声称

1. **不是 human 标注**：单 agent 代理标注（AGENT_PROXY + SELF_CHECKED）；bbox 为投影先验校准 + 全量目视复核，reference 为颜色 cue 质心且 `independent_of_detector_cue=false`。不是专家/人工独立审查，无标注员间一致性统计。
2. **不是 sealed final**：全池已降级 development/exploratory（6/6 族污染）；不得用于 sealed-final 一次性评测、认证或对外精度声明。
3. **不是模型证据**：本轮无训练、无推理、无 ONNX/RKNN、无板端、无 SITL/实飞/导航；不提升 BB22 Gate；模型效果、板端与导航均 NOT RUN/UNKNOWN。
4. **标签不得用于调阈值/训练后再回测本池**：按 training plan 的 exposure policy，本池只能作为 exploratory 评测；任何训练/阈值冻结需用新的、未查看数据。
5. **数据写入边界**：未改 `outputs/sensor_shadow/` 原始帧；标签写入 ignored 的 `outputs/perception/final_exploratory_20261104/`；仓库只保留清单/hash/统计/12 张 overlay 样例/24 张 QA contact sheet（JPEG）/报告；未 commit/push。

## 10. 证据清单

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| `outputs/perception/final_exploratory_20261104/labels_v1.json`（ignored） | 279 帧 v2.1 exploratory 标签 | `7115ee04cd2db33381047e6952541ee2bb5214df994a35df8f55ec24d7d79504` |
| `outputs/perception/final_exploratory_20261104/labels_manifest.json`（ignored） | 标签 manifest | 见 repo 副本 |
| [pilot/final_exploratory_labels_manifest.json](pilot/final_exploratory_labels_manifest.json) | 仓库 manifest 副本（不含量标签内容） | `8f06e1560265e8d82b669f6308280ec5fd182ebf0e93efb39bfcfae7540dc7ae` |
| `configs/perception/landmark_annotation_spec_v2_1.json` | 执行规范（FROZEN_FOR_DATA） | `010255d931936457ded48db9b3691b69a31d6015f1f84fbbc6a659f10f766eac` |
| [pilot/exploratory_label_qa_report.json](pilot/exploratory_label_qa_report.json) | 格式 QA（PASS 279/279，0/0） | `220928047282c2cffdf6828f57c852eb8ac193d3d468ea8029087bcd22883bc3` |
| [pilot/qa_sheets/](pilot/qa_sheets/) | 24 张全帧视觉复核 contact sheet（JPEG q82） | 逐文件 |
| [pilot/qa_sheets_index.json](pilot/qa_sheets_index.json) | sheet→frame_id 映射 | `f8e602f73485fb012b2b469eeef3c7fb1182a03afb2abe4b59a3ac8afcfc1407` |
| [pilot/exploratory_overlays_sample/](pilot/exploratory_overlays_sample/) | 12 张标注 overlay 样例 | 逐文件 |
| [pilot/build_bulk_draft.py](pilot/build_bulk_draft.py) | 先验 draft 构建（含标定参数） | 见文件 |
| [pilot/finalize_exploratory_labels.py](pilot/finalize_exploratory_labels.py) | 修正/统计/manifest 生成 | 见文件 |
| [pilot/PILOT_STATUS_UPDATE_20261104.md](pilot/PILOT_STATUS_UPDATE_20261104.md) | 34 帧试点→development/annotation calibration 状态转移 | `1c2a2b168bba36dcb5b5232436e0a98c343836db695e6167375e708ade579d87` |
| `configs/perception/landmark_final_pool_seal_v1.json` | T5 seal（未修改） | canonical `cedbbc7e1cd455f022d5f7c5f7f7925f046d9eebeb2581ca789ee25f7ce81007` |

## 11. 复现命令（离线，无需 Isaac）

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
cd E:\isaac\proj_boom_birds

# 1) draft（capture span 先验 + 绿光 cue；会写 ignored outputs 目录）
& $py docs/reports/perception/annotation_verify_20261104/pilot/build_bulk_draft.py
# 2) 最终标签（1 帧修正 + 统计 + manifest）
& $py docs/reports/perception/annotation_verify_20261104/pilot/finalize_exploratory_labels.py
# 3) 格式 QA
& $py scripts/validate_landmark_annotations.py `
  --annotations outputs/perception/final_exploratory_20261104/labels_v1.json `
  --root . --overlay-dir outputs/perception/final_exploratory_20261104/label_overlays `
  --output docs/reports/perception/annotation_verify_20261104/pilot/exploratory_label_qa_report.json
# 4) 全量单元测试
& $py -m pytest -q
```

## 12. 待决与下一步

1. **新 sealed final 池**：现有 279 帧已降级；认证/一次性 final 需要新的、未被查看的数据池（HN1/HN2 覆盖）+ 重新预注册（C3）。
2. **独立人工标注**：≥2 名人工标注 + 仲裁仍是用户事项；在此之前不得声称标注精度或认证级 identity/false-match 指标。
3. **HN1/HN2 补采**：带绿灯相似结构、完全遮挡视角；采集元数据补齐四边截断；新池必须用 `confusers[]` 记录未验证候选。
4. **训练/评测消费**：本标签可作为 exploratory 训练/分层评价输入，但必须标注来源（`bbox_source=PROJECTION_AID_CALIBRATED`、`annotation_mode=BULK_CALIBRATED_WITH_FULL_VISUAL_QA`），且不得再把本池当 sealed final；阈值与 final 协议仍按 `landmark_training_plan_v2.json`，不得用本池结果回调。
5. **T12 冻结更新**：建议由数据冻结任务把 34 帧 calibration、279 帧 exploratory、同组污染写入暴露登记/冻结更新（本报告可作为输入证据）。

---

**证据域汇总：** 本报告全部数字为**离线标注 QA** 证据（279 帧 exploratory Isaac 合成 320×240、agent 代理 BULK_CALIBRATED_WITH_FULL_VISUAL_QA、v2.1 校验 PASS 279/279）；不含模型训练/推理、板端、SITL/HIL/实飞或导航验收；exploratory ≠ sealed final，不提升任何 BB22 Gate。
