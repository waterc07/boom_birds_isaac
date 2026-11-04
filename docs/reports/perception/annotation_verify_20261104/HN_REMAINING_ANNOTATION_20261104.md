# HN val 标注补齐：剩余 29 帧与 53 帧完整覆盖（2026-11-04）

> **状态：** PROVISIONAL（数据准备/标注增量；非模型效果、非导航/板端验收；不提升 Gate；TINY 盲复标 WAITING_ON_DIAG）
> **来源章节：** `LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md` §1.4（HN1–HN6）、§2.1（GT_UNOBSERVABLE 规则）；`configs/perception/landmark_annotation_spec_v2_1.json`（FROZEN_FOR_DATA）；T16 任务书
> **证据域：** 离线标注 QA（T9 HN 批次 2 集 53 accepted RGB，Isaac 合成 320×240；agent 代理标注；无训练/推理/Isaac 运行）
> **最后核对：** 2026-11-04（仓库 `E:\isaac\proj_boom_birds`，分支 `feat/v2.2-simulation-perception`，HEAD `0c27525`）

## 0. 结论先行

1. **HN 剩余 29 帧已补齐**（HN1 14 + HN2 15），HN val 由 24 帧扩展为 **53/53 accepted 全覆盖**（27 HN1 + 26 HN2）；`labels_hn_val.json` 与合并后的 `labels_val.json`（134→**163** 帧）格式 QA **PASS**（0 error / 0 warning）。
2. **HN1**：27 帧全部 `present=false + negative_type=SIMILAR_STRUCTURE + confusers[1 verified]`；confuser 为采集时**合成注入**的塔状结构（柱体+顶板+绿色自发光球），构造记录 `scene_injections.hn1_confuser_v1`；**非场地资产、不代表真实赛场相似结构分布**。confuser bbox 由构造 prims 投影生成，先对已有 24 帧 HN1 验证 **IoU=1.000**（逐帧），再做 4 张原生 contact sheet 目视复核。
3. **HN2**：26 帧全部 `present=true + visibility=OCCLUDED + occluded=true + bbox=null + reference UNAVAILABLE/REFERENCE_OCCLUDED` = **GT_UNOBSERVABLE，不是负例**；逐帧条件记录 `injected_wall_fully_occludes_tower_geometric=true`，contact sheet 目视确认墙体完全挡住塔、画面无塔像素。
4. **QA**：v2.1 校验器对 `labels_hn_val.json`（53）与 `labels_val.json`（163）均 **PASS，0 error / 0 warning**；`labels_train.json` 未改动（sha 不变）。
5. **隔离与保留**：原 24 帧 HN 标注（annot2 产出）**字节未改**；旧 `labels_hn_val.json`/`labels_val.json`/清单/manifest 已备份为 `*_before_hn53_20261104.json`（ignored 目录），manifest 记录旧 sha。
6. **B（TINY 盲复标）**：diag 的 T13 帧清单/预注册判据**尚未落盘**（`docs/reports/perception/posteval_20261104/` 目前只有脚本），故 **WAITING_ON_DIAG**，本轮未做、未虚构 TINY 结论。

## 1. 数据来源与计数口径

| 项 | 值 |
| --- | --- |
| 采集 run | `outputs/sensor_shadow/lm_dev_hn_capture_20261104` / `..._sensor` |
| 采集报告 | `docs/reports/perception/capture_dev_20261104/CAPTURE_DEV_20261104.md` |
| 帧条件 | `docs/reports/perception/capture_dev_20261104/frame_conditions.json`（batch2_hn，53 行） |
| HN1 集 | `lmf_dev_hn1_confuser_0-follow_only`，27 accepted |
| HN2 集 | `lmf_dev_hn2_occluder_0-follow_only`，26 accepted |
| 注入构造 | `configs/scenarios/landmark_dev_cases_v2.json#scene_injections`（sha256 `10b55544…`） |
| 原已标 | 24 帧（13 HN1 + 11 HN2，`labels_hn_val.json` sha `3dff20b6…`，annot2） |
| 本轮新增 | **29 帧**（14 HN1 + 15 HN2，annot） |
| 合并后 | `labels_hn_val.json` 53 帧；`labels_val.json` 163 帧（= 原非 HN 110 + HN 53） |

> 计数口径：HN 批 raw RGB 59（含 6 warmup），**gate.accepted 53**；本报告分母均为 53/163/27/26。

## 2. 标注内容与方法

### 2.1 HN1（合成 confuser 负例，27 帧）

| 字段 | 值 |
| --- | --- |
| `target.present` / `visibility` / `negative_type` | false / ABSENT / **SIMILAR_STRUCTURE** |
| `geometry` | bbox=null、keypoint=null、reference_status=NOT_APPLICABLE；`green_pixels`=`injected_confuser_green_pixels` |
| `confusers[0]` | `confuser_id=injected_green_light_confuser`；bbox=构造 prims 投影；green_cue=capture green cluster 质心；`verified=true`、`verification_source=EXTERNAL_EVIDENCE`、verification_note 引用构造记录 sha 并声明 **SYNTHETIC_INJECTED / NOT arena asset / NOT real distribution** |
| 生成方法 | confuser bbox：按构造 prims（pedestal cuboid 0.9×0.9×0.2 z0.18、body cylinder r0.3 h1.5 z1.03、top bar 1.5×0.18×0.12 z1.84；**不含** green sphere 外凸）投影到图像（320×240、fx=fy=160、cx=160、cy=120；相机外参取 frame_conditions 的 position/quat）；与已有 24 帧 HN1 框比对 **IoU=1.000（mean=min=1.000）**后用于新增 14 帧 |
| 边界 | 合成注入仅用于流程/负例覆盖，**不得冒充真实分布**；`verified` 指"构造记录可核验该结构为注入 confuser"，不是"真实场地相似塔已存在" |

### 2.2 HN2（完全遮挡 GT_UNOBSERVABLE，26 帧）

| 字段 | 值 |
| --- | --- |
| `target.present` / `visibility` / `occluded` | **true** / **OCCLUDED** / true |
| `geometry` | bbox=null（无目标像素）、keypoint=null、reference_status=**UNAVAILABLE**、`reference_unavailable_reason=REFERENCE_OCCLUDED`、green_pixels=0 |
| `negative_type` | null（**不得当负例**） |
| GT 分类 | **GT_UNOBSERVABLE**（present 且完全遮挡）→ 检测四格/分母之外单列，presence/joint 必须显示该计数 |
| 证据 | 每帧 `injected_wall_fully_occludes_tower_geometric=true`、`injected_wall_projection_px` u/v span；contact sheet 目视确认墙体完全遮挡、画面无塔 |

## 3. 合并后统计

### 3.1 HN val（53 帧）

| 指标 | 值 |
| --- | --- |
| frames | 53 |
| present / absent | 26 / 27 |
| **GT_UNOBSERVABLE** | **26**（全部 HN2） |
| reference 可用 / 不可用 | 0 / 26（全部 REFERENCE_OCCLUDED） |
| truncated | 0（HN 两集无截断） |
| confusers / verified | **27 / 27** |
| negative_type | TARGET_ABSENT 0、**SIMILAR_STRUCTURE 27**、OTHER_LANDMARK 0 |
| by group | `g_lmf_dev_hn1_confuser_0` 27（全负例）；`g_lmf_dev_hn2_occluder_0` 26（全 GT_UNOBSERVABLE） |

### 3.2 合并后 val（163 帧，= 原 110 + HN 53）

| 指标 | 原 134 帧 | 合并后 163 帧 |
| --- | ---: | ---: |
| frames | 134 | **163** |
| present | 106 | **121** |
| absent | 25 | **39** |
| undecidable | 3 | 3 |
| GT_UNOBSERVABLE | 11 | **29**（11 旧 + 26 HN2） |
| reference 可用 / 不可用 | 41 / 65 | 41 / **80** |
| truncated | 17 | 17 |
| edge（left/right/top/bottom） | 0/10/0/7 | 0/10/0/7 |
| confusers / verified | 43 / 13 | **57 / 27** |
| negative_type TARGET_ABSENT / SIMILAR_STRUCTURE | 12 / 13 | 12 / **27** |

## 4. QA（格式 QA 与语义自检分开）

### 4.1 格式 QA（v2.1 机器校验）

```powershell
& E:\isaac\env_isaaclab\Scripts\python.exe scripts/validate_landmark_annotations.py `
  --annotations outputs/perception/dev_annotations_20261104/labels_hn_val.json `
  --root . --overlay-dir docs/reports/perception/annotation_verify_20261104/pilot/hn_val_overlays `
  --output outputs/perception/dev_annotations_20261104/qa_hn_val.json
# 同样对 labels_val.json（overlay-dir outputs/perception/dev_annotations_20261104/overlays_val）
```

| 文件 | 结果 | 记录数 | errors/warnings |
| --- | --- | ---: | --- |
| `labels_hn_val.json` | **PASS** | 53 | **0 / 0** |
| `labels_val.json` | **PASS** | 163 | **0 / 0** |

### 4.2 语义自检（目视，4 张 contact sheet × 9 帧）

- HN1（sheet 00–01）：27 帧合成 confuser 均可见、绿色灯在顶部、bbox 与结构对齐、green_cue 落在灯上；中央塔不在画面（相机 yaw +π/2）。
- HN2（sheet 01–03）：26 帧墙体完全占据视线、无塔像素可见；与构造记录的"8 个塔体采样点射线全遮挡"一致。
- 未覆盖：真实场地相似结构（MS1 等）不在本批；HN1 合成注入不代表真实分布（已披露）。

## 5. 证据与文件

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| `outputs/perception/dev_annotations_20261104/labels_hn_val.json`（ignored） | HN val 53 帧 | `87ba533de8feef0cf4399650d477c071b66aa4586b74e07af10d7ccc3c1189af` |
| `outputs/perception/dev_annotations_20261104/labels_val.json`（ignored） | 合并后 val 163 帧 | `8c2155979b517626299fd85c61759b73ceb1bfc369be839d4453caa3b3ed33ac` |
| `outputs/perception/dev_annotations_20261104/labels_train.json`（ignored，未改） | train 160 帧 | `01977b9fea97c58bcdda2c6c301763ac52113bcc411a23094924b917ec08d2df` |
| `outputs/perception/dev_annotations_20261104/qa_hn_val.json` | HN QA（PASS 53/53） | `b53599787762870cb979bbf173247397384557e7920d9d554b04ecb712ff17eb` |
| `outputs/perception/dev_annotations_20261104/qa_val.json` | val QA（PASS 163/163） | `93f5545bc28e37ecf0c8cca9e2afce861a97b938cd5f3bbaea87c8fc673121c2` |
| `outputs/perception/dev_annotations_20261104/labels_manifest.json` | dev 标签 manifest（更新） | `ad02329acc945388751bca778e9d0eea7f6775c0a0eda65d5eb41d5db93fe2fc` |
| `configs/perception/landmark_dev_label_lists_v1.json` | dev 帧清单（更新 val/HN 段） | `0c1c75aed2fdddd6de3773180f93dc643192d2c119eeccbbaea39f2bd23d6488` |
| `docs/reports/perception/annotation_verify_20261104/pilot/hn_completion_sheets/` | 29 帧 QA contact sheet（4 张 + index） | 见目录 |
| 旧字节备份（ignored） | `labels_hn_val_before_hn53_20261104.json`、`labels_val_before_hn53_20261104.json`、`qa_val_before_hn53_20261104.json`、`labels_manifest_before_hn53_20261104.json` | 旧 HN sha `3dff20b6…`、旧 val sha `c3944e08…` |

## 6. 边界与不声明

1. **agent 代理标注**（AGENT_PROXY + SELF_CHECKED；bbox 为构造记录投影 + 目视复核；参考点与绿色 cue 同源 `independent_of_detector_cue=false`），不是人工独立标注，无标注员间一致性。
2. **合成分布 ≠ 真实分布**：HN1 为仅本次采集存在的合成注入 confuser，HN2 为合成视觉遮挡墙；不能据此声称真实赛场相似结构/遮挡分布已覆盖。
3. **GT_UNOBSERVABLE ≠ 负例**：HN2 不得计入 TN/FN；presence/joint 报告必须单列 26 帧（合并后 val 共 29）。
4. 不声明模型效果、板端、导航、Gate；未训练、未跑 Isaac、未改原始帧、未 commit/push。
5. `labels_val.json` 已变更（134→163），旧 sha `c3944e08…` 不再对应当前文件；datafreeze 需在新 freeze v4 中记录新 sha（本报告与 manifest 已提供）。

## 6.1 后续状态更新（2026-11-04，annot2 T19 元数据合并后）

- annot2 在 T19 中更新了 `labels_val.json` 的顶层 status/note（**标注行未改**，仍 163 帧；HN1 27 + HN2 26 经复核保留），并把 identity 组放入独立 `labels_identity_dev.json`（未并入 val）。
- 因此本报告 §5 中的 `labels_val.json` sha `8c215597…` 与 lists sha `0c1c75ae…` 已被后续元数据更新取代，**当前现场 shas**（复核：163 帧、HN 27/26 行未变）：
  - `labels_val.json` = `4e8e877e09a8dd1c559556b87c5ae52751bce9dbf325c0238327dc8fe670f29f`
  - `configs/perception/landmark_dev_label_lists_v1.json` = `2dceb5fca84b2e77220460b27537c6bfa99386530b985ba5fe2d7ac93e7794ca`
  - `labels_manifest.json` = `197f94a91b99c4a2aa9f07d3139db94f2ed0169c69d8f746d2a6857496dd9d8a`
  - `labels_hn_val.json` 未变 = `87ba533de8feef0cf4399650d477c071b66aa4586b74e07af10d7ccc3c1189af`；`labels_train.json` 未变 = `01977b9f…`
  - identity 独立文件 = `79fd17459538aaeabf89ebe10c170eaf8f1277cfc05399300362667c0a4204b2`（不并入 val；datafreeze v4.2 消费）
- 本条只记录状态，不改写本报告前文的统计与结论。

## 7. 待决 / 下一步

- **TINY 盲复标（T16-B）**：WAITING_ON_DIAG——需 diag（T13）提供 4–10px/TINY 帧清单与预注册判据（盲标规则、分歧表口径、`green_pixels`/质心同源记录方式）；到货后独立盲标、输出分歧表交 diag。落点计划：独立 `labels_tiny_blind.json`（ignored）+ 报告，不直接混入 train/val，除非 lead/datafreeze 明确要求并入某 split（届时按 dataset_role 区分）。
- **dev freeze v4（T17）**：消费新 `labels_val.json`（sha `8c21559…`）与 `labels_hn_val.json`（`87ba533d…`）；HN 组 27/26 帧进入 val。
- **identity 组（annot2/T16b）**：按并行写域协调，等本 base 就绪后在 `labels_val.json` 仅 append identity 组、刷新 manifest/lists；本报告 base sha 已给出。
