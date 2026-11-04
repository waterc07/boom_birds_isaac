# T6 final 候选池分层试点标注与语义 QA（2026-11-04）

> **状态：** PROVISIONAL（试点完成；**不是完整 test 标签**、不是人工/专家审查、不是模型效果或导航验收；不提升任何 Gate）
> **来源章节：** `SYSTEM_ARCHITECTURE_V2_2.md` §7.5/§7.6/§7.7/§7.8；标注语义依据 `configs/perception/landmark_annotation_spec_v2.json`（lead 2026-11-04 批准用于本试点，PILOT 冻结）；封存清单 `configs/perception/landmark_final_pool_seal_v1.json`
> **证据域：** 离线标注 QA（T1 final 候选池 sealed test-only 的 34 帧 Isaac 合成 RGB 320×240；agent 代理标注；无模型训练/推理、无板端、无 SITL/实飞、无导航验收）
> **最后核对：** 2026-11-04（仓库 `E:\isaac\proj_boom_birds`，分支 `feat/v2.2-simulation-perception`，起始 HEAD `43fee3e`）

## 0. 结论先行

1. **试点规模**：按固定、非分数规则从 T5 seal 的 6 个测试族中分层抽取 **34 帧**（lmf_sweep 8 / lmf_backoff 6 / lmf_near 5 / lmf_edge 6 / lmf_similar_negative 6 / lmf_side_negative 3），覆盖 normal/近中距、远景（≥7 m）、近距、右缘截断、目标缺席、目标出视场；**未构造遮挡，也没有完全遮挡/undecidable 帧，未虚构**。
2. **标注结果**：25 正 / 9 负；参考点可用 **21**、不可用 **4**（全部为 green_pixels ≤2 的远景帧，`REFERENCE_TOO_SMALL`）；截断 **10**（near 底部 5 + edge 右缘 5）；undecidable **0**、ambiguous **0**、occluded **0**、GT_UNOBSERVABLE **0**。
3. **校验**：`scripts/validate_landmark_annotations.py` 对 v2 标签文档运行 → **PASS 34/34，0 error / 0 warning**；标签文件位于 **gitignored** 的 `outputs/perception/landmark_final_annotations_20261104/labels_v1.json`（sha256 `fe8d47d0…c8942`），仓库只保留 manifest/统计/hash。
4. **规范执行**：v2 字段足以完成本试点（bbox 口径、visibility/truncated 优先级、reference 不可用原因、negative_type、pixel_basis、provenance 均被实际使用）；仍暴露 6 条可执行性问题/缺口（§7），建议 T6 反馈后出 v2.1，不改写本次记录。
5. **耗时**：选帧落盘（18:29:58）→ 首次标签落盘（18:32:43）wall clock ≈ **2 分 45 秒 / 34 帧**（≈4.9 s/帧，agent 读图与判定；不是人工工时）；6 个查看批次；校验即时通过。
6. **HN1 口径（重要）**：本池 `lmf_similar_negative` 实际是"**目标缺席（相机朝后）+ 中央场地结构**"，仅有 0–2 px 亚阈值绿色假线索，**未验证存在带绿灯的相似塔**；HN1 的已有证据是旧数据 static_c 的约 **6×25 px 绿色顶端相似结构**（本报告继承，见 §9），不得把本池 negative 写成已验证相似结构。
7. **边界**：试点标签 ≠ 完整 test 标签（本次仅 34/279 帧；完整标签仍 NOT_PRODUCED）；同一 agent 既标注又可能参与后续模型开发 → 仅**流程隔离 + hash 承诺**，无统计独立性；**不得**用本试点标签训练、调阈值或作为模型/板端/导航结论。

## 1. 选帧：固定规则与族分布

### 1.1 上游封存

| 项目 | 值 |
| --- | --- |
| seal 路径 | `configs/perception/landmark_final_pool_seal_v1.json` |
| seal freeze_sha256 | `cedbbc7e1cd455f022d5f7c5f7f7925f046d9eebeb2581ca789ee25f7ce81007` |
| 状态 | SEALED_TEST_POOL_FROZEN_LABELS_PENDING（279 accepted / 297 RGB，6 族，test-only） |
| source run | `outputs/sensor_shadow/lm_final_candidate_20261104_sensor` |

### 1.2 固定抽样规则（在查看任何图像前写定，非模型/检测器分数选择）

- **R1** roster：只取 seal 各组 `accepted=true` 帧，按整数 sequence 升序。
- **R2** 基础抽样：midpoint systematic，`idx_i = floor((i+0.5)*n/k)`，i=0..k-1，去重。
- **R3** `lmf_backoff` 覆盖极值：强制加入**距离最大**与**距离最小**帧（远景要求）。
- **R4** `lmf_edge` 边界：若存在 `truncated=false` 帧，强制加入其中 1 帧（边界对照）。
- **R5** `lmf_side_negative`：3 帧全取。
- k：sweep 8 / backoff 6 / near 5 / edge 6 / similar_negative 6 / side_negative 3 = **34**。
- 选择只使用 seal sequence + capture 派生的位姿/距离/截断元数据（`docs/reports/perception/capture_20261104/frame_conditions.json`），**不使用任何模型或检测器输出**。选择文件：`pilot/selection.json`（sha256 `7c144e16…5229c`）。

### 1.3 选中帧（34）

```text
sweep:  g1_9  g1_23  g1_37  g1_51  g1_65  g1_79  g1_93  g1_107
backoff:g2_3  g2_22  g2_34  g2_47  g2_60  g2_67
near:   g3_5  g3_9  g3_14  g3_19  g3_23
edge:   g4_5  g4_10  g4_14  g4_19  g4_24  g4_29
similar_negative: g5_6  g5_12  g5_18  g5_25  g5_31  g5_37
side_negative:    g6_3  g6_4  g6_5
```

（完整 frame_id 见 `pilot/selection.json` 与标签文件的 `frame_id` 字段；帧顺序即上表。）

## 2. 条件覆盖矩阵（预期 vs 本轮实到）

| 条件 | seal 记录 | 本轮选取 | 本轮标注观测 |
| --- | --- | ---: | --- |
| normal / 近中距 | lmf_sweep 111 | 8 | 8 正，bbox 可见，参考点 7 可用/1 不可用 |
| 尺度/距离：远景 | lmf_backoff ≤8.37 m | 3（7.00/7.98/8.37 m） | 3 正，green 1–2 px → **参考点全部 UNAVAILABLE/TOO_SMALL** |
| 尺度/距离：中距 | backoff + sweep | 11 | 11 正，green 2–13 px |
| 近距 | lmf_near 1.458–1.783 m | 5（1.46–1.72 m） | 5 正，green 29–40 px，参考点全部可用；底座在下缘被切 → truncated=5 |
| 右缘截断 | lmf_edge 26/28 truncated | 5 truncated + 1 非截断（g4_29） | 与预期一致：5 帧 PARTIAL+truncated，1 帧 FULL |
| 目标缺席（相似结构族） | lmf_similar_negative 38 | 6 | 6 负，present=false，negative_type=TARGET_ABSENT；0–2 px 亚阈值绿线索 3 帧（1/2/2 px）；**无已验证相似塔** |
| 目标出视场 | lmf_side_negative 3 | 3 | 3 负，present=false，yaw+π/2，画面无塔、无绿灯 |
| 场景结构遮挡 | 无（NOT CONSTRUCTED） | 0 | **0，未虚构** |
| 完全遮挡 / undecidable | 无 | 0 | **0，未虚构；GT_UNOBSERVABLE=0** |
| 相似结构（HN1 已验证） | seal 记录 0 verified | 0 | **0**；HN1 证据沿用旧数据 static_c（§9） |

> **未捕获条件**：场景遮挡、完全遮挡、多候选歧义。上述 0 是"本池没有这些帧"，不是"标注规范已验证这些条件"。

## 3. 标注规范执行（spec v2）

- **执行规范**：`configs/perception/landmark_annotation_spec_v2.json`，sha256 `b0b7dae6300086fbcdc6bdf08033f8abd47381695e3d12a900f313a93372f749`；状态 **PILOT_FROZEN_LEAD_APPROVED_2026-11-04_NOT_FINAL_PRODUCTION**。
- **lead 评审**：lead 2026-11-04 已批准用于本试点；4 个 open items 的裁定与 GT_UNOBSERVABLE 分母规则写在 v2 文件 `lead_review` / `quality_gate.denominator_rules` 字段中。
- **seal 记录不一致（按要求不改 seal）**：T5 seal 的 `annotation_status.annotation_spec` 仍写 v1。**T6 实际执行用 v2（v2 是 v1 的向后兼容超集）**，seal 记录以本报告与标签文件中的 **v2 sha256 补充说明**，未修改 seal 文件。
- 实际使用的 v2 字段：`bbox_scope` 口径、`target.present/undecidable/visibility/truncated/occluded/ambiguous`、`geometry.keypoint/reference_status/reference_unavailable_reason/reference_source`、`candidates`（本轮为空）、`negative_type`、`annotator.*`、`pixel_basis`、`source.group_id`。
- 标注执行规则（本试点预声明）：参考点仅当 `green_pixels >= 3` 且目视确认时标注；否则 `keypoint=null + UNAVAILABLE + REFERENCE_TOO_SMALL`。参考点坐标取 capture 派生的绿色像素质心并目视核对 → `reference_source=COLOR_CUE_ASSISTED`、`annotator.independent_of_detector_cue=false`（如实披露与绿色 cue 同源，非独立参考）。
- bbox 口径（冻结）：可见目标结构本身（塔头/灯架 + 收分塔体 + 与塔体相连的阶梯底座），不含场地平台/地面/画线/阴影；截断帧只框图像内可见部分并在帧边裁剪。
- 标注者来源：`annotator_type=AGENT_PROXY`、`review_status=SELF_CHECKED`、`independent_of_model_dev=true`；**无人类标注者，因此没有任何 HUMAN_REVIEWED/ADJUDICATED**。

## 4. 标注统计

| 族 | 选取 | 正 | 负 | 参考点可用 | 参考点不可用 | 截断 | 主要条件 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| lmf_sweep | 8 | 8 | 0 | 7 | 1 | 0 | normal/中距 |
| lmf_backoff | 6 | 6 | 0 | 3 | 3 | 0 | 尺度/远景 |
| lmf_near | 5 | 5 | 0 | 5 | 0 | 5 | 近距 + 底部截断 |
| lmf_edge | 6 | 6 | 0 | 6 | 0 | 5 | 右缘截断/边界 |
| lmf_similar_negative | 6 | 0 | 6 | 0 | 0 | 0 | 目标缺席（无已验证相似塔） |
| lmf_side_negative | 3 | 0 | 3 | 0 | 0 | 0 | 目标出视场 |
| **合计** | **34** | **25** | **9** | **21** | **4** | **10** | — |

- **不可判定 / 歧义 / 遮挡 / GT_UNOBSERVABLE：0 / 0 / 0 / 0**（本池无此类帧；不虚构）。
- bbox 面积范围 **540–31,350 px²**（最小 20×27 px @8.37 m；最大 190×165 px @1.66 m）；bbox 均为源图像素坐标、帧边裁剪。
- 负例全部 `present=false, visibility=ABSENT, negative_type=TARGET_ABSENT`，不带几何；不存在 ambiguous/candidates 实例。
- 参考点不可用 4 帧：`sweep_g1_37`（green=2）、`backoff_g2_47`（2）、`backoff_g2_60`（1）、`backoff_g2_67`（2），原因均为 `REFERENCE_TOO_SMALL`。

## 5. 校验结果（v2 文档）

```powershell
& E:\isaac\env_isaaclab\Scripts\python.exe scripts/validate_landmark_annotations.py `
  --annotations outputs/perception/landmark_final_annotations_20261104/labels_v1.json `
  --root . `
  --overlay-dir docs/reports/perception/annotation_verify_20261104/pilot/label_overlays `
  --output docs/reports/perception/annotation_verify_20261104/pilot/label_qa_report.json
```

| 项目 | 结果 |
| --- | --- |
| 状态 | **PASS** |
| 记录数 | 34（25 正 / 9 负） |
| errors / warnings | **0 / 0** |
| 文档 schema | `dsh.tower_annotation.v2` |
| 标签文件（gitignored） | `outputs/perception/landmark_final_annotations_20261104/labels_v1.json` |
| 标签 sha256 | `fe8d47d03e6de8740099822830621edd76f97cb14633a6cb3e44ef08c12c8942` |
| 标签 manifest | `outputs/perception/landmark_final_annotations_20261104/labels_manifest.json`（repo 副本 `pilot/labels_manifest.json`，sha256 `e31ac902…bfa5a5`） |
| QA report | `pilot/label_qa_report.json`（sha256 `ab8cafb0…f697173`） |
| 标注 overlay | `pilot/label_overlays/`（34 张，由校验器生成） |

校验覆盖：image sha/尺寸、pixel_basis 一致、bbox 界内、truncated/visibility/occluded 组合、reference 枚举与不可用原因、present/undecidable 三态、negative_type、annotator provenance、group/split、重复帧。**格式 PASS 只证明标签文件自洽合法，不证明标注语义是专家真值。**

## 6. 批次与耗时

| 阶段 | wall clock | 说明 |
| --- | --- | --- |
| 选帧脚本 → selection.json | 18:29:58 | 固定规则，非分数选择 |
| 分 6 批查看 34 帧（3× 网格放大） | 18:30–18:32 | 每批 4–6 帧 |
| 首次标签落盘 | 18:32:43 | 选择→标签 ≈ **2 分 45 秒 / 34 帧（≈4.9 s/帧）** |
| 修正与重校验 | 18:32:51–18:32:58 | 1 个 keypoint-outside-bbox warning 修正后重验 0 warning |

> 上述为 **agent 读图判定**的实际 wall clock，不代表人工标注工时；正式人工标注需另立流程与工时记录。

## 7. 规范可执行性反馈（v2 是否够用、仍缺什么）

**够用的部分**：bbox 口径与截断裁剪规则使 25 个正例的框边界可判定；visibility/truncated 组合规则给出确定性标签（FULL 15、PARTIAL 10、ABSENT 9）；`reference_unavailable_reason` 让 4 个远景帧不再"猜 keypoint"；`negative_type` 与 `pixel_basis`、`annotator.*`、`group_id` 均被实际使用；v2 校验器可直接跑通 v2 文档。

**仍缺 / 建议 v2.1（本轮不改写 v2 记录）**：

| # | 问题 | 证据（本轮） | 建议 |
| --- | --- | --- | --- |
| P1 | 采集元数据只记录左右截断，未记录上下缘 | near 5 帧底座在下缘被切（标注 truncated=true），但 seal `truncated_frames` 对 near 记 0、条件矩阵把截断只归到 edge | capture/condition 元数据增加上/下/左/右四边截断标记；报告分层同时按"标注截断"与"采集元数据截断"两口径列出 |
| P2 | 参考点可用的像素判据未规范化 | 远景 1–2 px 绿点：若按"可见"逐帧主观判断会产生不一致；本轮预声明 `green_pixels>=3` | v2.1 写入参考点可用性判据（含 green_pixel 下限、模糊/过曝例外）并要求记录 `green_pixels` 或等价证据 |
| P3 | "目标确认缺席 + 可见但未验证的相似结构"没有干净状态 | similar_negative 6 帧画面有中央场地结构，但无已验证相似塔；v2 只能在 TARGET_ABSENT 与 SIMILAR_STRUCTURE 间二选一，且 candidates 只允许后两者/ambiguous | 允许 `negative_type=TARGET_ABSENT` 同时携带 `candidates[]` + `confuser_verified=false`，或增加第三态；否则"未验证相似结构"无法被记录 |
| P4 | GT_UNOBSERVABLE / 完全遮挡分母规则未实测 | 本池无遮挡帧 | 保持 PROPOSED/TBD；待有遮挡帧后验证（不得虚构） |
| P5 | seal 的 annotation_spec 仍写 v1 | seal `annotation_status` | 不改 seal；在 T5/T6 报告与标签里以 v2 sha 补充说明（本报告已做） |
| P6 | 参考点与检测器共用绿色 cue（循环性） | 21 个可用参考点全部 `reference_source=COLOR_CUE_ASSISTED`、`independent_of_detector_cue=false` | 不得用本试点标签验证绿色 seed 检测器的 anchor 精度；需要独立人工/物理标定参考点才能做精度声明 |
| P7 | candidates[] 字段未被本池实际使用 | 无 ambiguous/verified-similar 帧 | 字段保留；用旧数据 static_c 的 v2 示例文档与单测覆盖，待新池有 HN1 帧后再实测 |

**结论**：v2 对"正常/远景/近距/右缘截断/目标缺席/出视场"六类条件**可执行**；新增字段中最关键的是 `reference_unavailable_reason`（4 帧直接受益）与 bbox 截断口径（10 帧）。若要做 HN1/遮挡/多候选的完整覆盖，需先补采并升 v2.1。

## 8. 边界声明

1. **试点 ≠ 完整 test 标签**：本报告只覆盖 34/279 accepted 帧；seal 的 `annotation_status.full_semantic_labels` 仍为 NOT_PRODUCED，完整 final test 标签尚未产出。
2. **代理标注**：单 agent 代理标注（AGENT_PROXY + SELF_CHECKED），不是人类/专家独立审查；同一执行者未来可能参与模型开发 → 只能声明**流程隔离 + hash 承诺**，不能声明盲法或统计独立性。
3. **不得用于模型/阈值开发**：本试点标签不得用于训练、选阈值或调参；若使用即违反 seal 的 test-only 边界。
4. **证据域**：Isaac 合成 320×240 单分辨率、6 个新轨迹族；无真实 OV9782、无板端、无 SITL/HIL、无实飞、无导航；不提升 BB22 Gate。
5. **不改原始数据**：未修改 `outputs/sensor_shadow/` 原始帧；标签只写入 ignored 的 `outputs/perception/landmark_final_annotations_20261104/`；未 commit/push。
6. **未捕获条件不虚构**：遮挡/完全遮挡/多候选 0 帧；HN1 在本池 verified=0。

## 9. HN1 继承与 similar_negative 澄清

- **HN1 已有证据（旧数据，继承）**：盲复标报告 `ANNOTATION_VERIFICATION_20261104.md` §8.1 记录的 `geo_test_static_c` 远端约 **6×25 px、顶端带暗绿色（RGB≈137,166,135，仅 1–2 px 达颜色阈值）的锥形结构**，以及右侧约 20×40 px 深灰柱状结构；对应证据图 `blind_pass/evidence/sc_obj1.png`、`sc_obj2.png`。这是当前唯一"疑似相似结构"的实帧证据，但**身份仍未裁定**（仅图像不可判定），只能作为 HN1 候选证据，不是已验证相似塔。
- **本池 similar_negative 的真实含义**：6 个选中帧均为"相机朝后（bearing≈±179°）、目标确认缺席 + 中央场地结构在画面内"，绿像素仅 **0–2 px（3 帧为 1/2/2 px，全部低于 3 px 标注阈值）**；seal 的 `similar_structure_verified_frames=0` 与本轮标注一致。
- **禁止合并**：不得把本池 similar_negative 写成"已验证相似结构/HN1 覆盖"；HN1 覆盖仍为 **0 帧 verified**，直到有独立证据（世界位姿/地图结构复核或人工裁定）。

## 10. 证据清单

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| `outputs/perception/landmark_final_annotations_20261104/labels_v1.json`（ignored） | T6 试点 v2 标签（34 帧） | `fe8d47d03e6de8740099822830621edd76f97cb14633a6cb3e44ef08c12c8942` |
| `outputs/perception/landmark_final_annotations_20261104/labels_manifest.json`（ignored） | 标签 manifest（seal/spec/selection/hash/边界） | 见 repo 副本 |
| [pilot/labels_manifest.json](pilot/labels_manifest.json) | 仓库内 manifest 副本（不含标签内容） | `e31ac902526e6eb582a61ae5102279473c5207a4067f4da91b3496b351dbf5a5` |
| [pilot/selection.json](pilot/selection.json) | 34 帧选择清单 + 规则 + 条件元数据 | `7c144e162bd1d9ba718f2b307af29c542d88d5e02e647ae3ef6c19903405229c` |
| [pilot/decisions_partial.json](pilot/decisions_partial.json) | 逐帧盲标决策（bbox/kp/notes） | 见文件 |
| [pilot/build_labels.py](pilot/build_labels.py) | 标签构建脚本（可复现） | `7911892a89376dcbf3c3ac7edccb350969f7b26059c547cefa06c87cc0f6ae1b` |
| [pilot/label_qa_report.json](pilot/label_qa_report.json) | v2 校验结果（PASS 34/34，0/0） | `ab8cafb0933f633d2302598105b0e19799c02025715bb22d392f661c0f697173` |
| [pilot/label_overlays/](pilot/label_overlays/) | 校验器生成的 34 张标注 overlay | 见 QA report |
| [pilot/select_frames.py](pilot/select_frames.py) | 固定抽样规则实现 | 见文件 |
| [pilot/zoom/](pilot/zoom/) | 近距/backoff 底座边界放大证据（截断判定） | 见文件 |
| `configs/perception/landmark_annotation_spec_v2.json` | 执行规范（lead 批准的 PILOT 冻结） | `b0b7dae6300086fbcdc6bdf08033f8abd47381695e3d12a900f313a93372f749` |
| `configs/perception/landmark_final_pool_seal_v1.json` | T5 封存清单（未修改） | canonical `cedbbc7e1cd455f022d5f7c5f7f7925f046d9eebeb2581ca789ee25f7ce81007` |

> 标签内容按 seal 约定不入 git；仓库只保留 frame_id、统计与 hash。

## 11. 待决事项与后续

1. **完整 final test 标签**（279 帧）仍未产出；本试点只验证 v2 在 6 类条件上的可执行性，不能当作完整标签或评估结果。
2. **v2.1**：P1–P3 建议在完整标注前处理（四边截断元数据、参考点可用判据、TARGET_ABSENT+未验证 confuser 的表达）；是否升 v2.1 由 lead 决定。
3. **人类独立标注**：若要用该 test 池做精度验收，需要 ≥2 名独立人工标注 + 仲裁（用户事项）；本轮 0 人类标注，`independent_of_detector_cue=false`。
4. **HN1 复核**：static_c 远端绿色顶端结构的身份需世界位姿/地图结构复核后才能升级为"已验证相似结构"；本池不提供 HN1 覆盖。
5. **seal 记录补充**：seal 中 annotation_spec=v1 的字段不在本轮修改范围；建议在 T5/T6 交付说明中以 v2 sha 作附录，不改写 seal 字节。

---

**证据域汇总：** 本报告全部数字为**离线标注 QA** 证据（sealed test-only final 池的 34 帧 Isaac 合成 320×240、agent 代理标注、v2 校验 PASS）；不含模型训练/推理、板端、SITL/HIL/实飞或导航验收；试点 ≠ 完整 test 标签，不提升任何 BB22 Gate。
