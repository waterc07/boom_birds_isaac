# 地标 dev 划分冻结 v3、暴露登记与泄漏审计（2026-11-04）

> **状态：** PASS（v3 划分 / 暴露登记 / 泄漏审计 / 外部产物索引的 QA）；final 池已降级 development-exploratory；封存与 identity 认证均 INCOMPLETE；模型效果、板端、导航均 NOT RUN
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §20.11.1（测试数据分层，禁止连续视频随机拆帧）、§20.11.3（统计结论边界）、Phase 6（输入泄漏检查报告交付）；configs/perception/landmark_training_plan_v2.json 的 A2/A3/A6/A8
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真采集产物索引（离线只读；本 T12 未运行 Isaac、未训练、未安装依赖、未上传任何数据）
> **最后核对：** 2026-11-04

本报告回答：T9 新 dev 族与 HN1/HN2 能否并入 dev 划分 v3、现有暴露状态如何登记、train/val/exploratory 是否仍有近重复或同族泄漏、ignored 原始产物能否复验。所有 PASS 均为数据/清单/格式 QA，不是模型效果、板端、导航或"封存 final 已就绪"的结论。

## 0. 结论摘要

- **v3 已冻结**：`configs/perception/landmark_split_freeze_v3.json`，canonical sha256 `bc037e301d6370bb3de3232b1cc3573ae29c80a3465055114f5ef2d2ae422ce1`，文件 sha256 `50c064c120effea4fab904853b2970756d95382ed9376ec806f937b8b44feec2`。
  - **train 10 组 / 1475 帧（1418 accepted）**；**val 7 组 / 816 帧（795 accepted）**；test 0；excluded 9 组 / 1107 帧（1071）；合计 26 组 / 3398 帧（3284 accepted），15 个数据集、13 个 family。
  - v2→v3 delta：新增 7 组 / **396 帧**（T9 batch1 337 + batch2 HN 59）；legacy v2 组的帧与 split 不变；base = v2 canonical `269d9a65…`。
- **val 覆盖多 family + HN1/HN2 + 北走廊**：7 组 / 5 个 family = `fam_north`（3 组：lm_ind_north、geo_north、lm_pilot_north）+ `fam_inner_north` + `fam_static_low_oblique` + `fam_HN1_confuser` + `fam_HN2_occluder`。
  - val 负例构成（annot2 v2.1 标签，134 帧）：`TARGET_ABSENT 12`、`SIMILAR_STRUCTURE 13`（HN1，合成 confuser）、**`GT_UNOBSERVABLE 11`（HN2 完全遮挡）**、`undecidable 3`。
  - **HN2 的 11 帧必须作为 GT_UNOBSERVABLE 处理**：`present=true + occluded=true + visibility=OCCLUDED + bbox/keypoint=null + reference UNAVAILABLE`；训练损失/分母中排除，不能当 background 负例。
- **与 annot2 的 train/val 帧清单一致**：label-list config `configs/perception/landmark_dev_label_lists_v1.json` sha256 `befbbea1b587261ed861a081706fe44a8a761aa90b04743fb137ddbd85c27701`（status `DRAFT_FOR_DATAFREEZE_VAL_HN_MINIMAL_MERGED`）；逐帧校验 294 帧、0 mismatch、0 unresolved、`hn_val_pending=false`。
  - labels：train `01977b9f…`（160 帧）、val `c3944e08…`（134 帧，含 HN 最小集 24 帧 = HN1 13 + HN2 11）；annot2 另有 `labels_hn_val 3dff20b6…`（24 帧子集）；spec v2.1 `010255d9…`；annot2 报告 `docs/reports/perception/annotation_verify_20261104/DEV_TRAIN_VAL_ANNOTATION_20261104.md` sha256 `a3395e6d7b069e1bbb4cd06ed214eaaec2c0f34af8e73a2e09dd9f518f10338a`。
  - **HN 仍有 29 个 gate.accepted 帧未标注**（HN accepted 53 = HN1 27 + HN2 26，已标 24）→ HN val 标注覆盖 INCOMPLETE，后续补 val；val labels 的 undecidable 3 帧与 GT_UNOBSERVABLE 11 帧须从训练损失排除（train 另有 undecidable 3，合计 6）。
- **暴露登记**：`configs/perception/landmark_exposure_registry_v1.json`（文件 sha256 `643d27c56a11a5baedcadaa741a1104893923500994601ccbe7a12ea34c52640`）：32 组 = v3 26 + final seal 6；**26 组 exposed_development、6 组 exploratory_eval_candidate、0 组 untouched**；**6 条暴露事件**、328 条帧级 override（34 试点 + 294 dev 标注）。final 6 族整体降级 exploratory（6/6 同组污染），**不能只移除 34 帧就宣称其余独立**。
- **identity 认证 INCOMPLETE（新增关键证据）**：map-native（地图原生、非注入）绿灯柱 MS1 约 (3.0,4.0)，绿灯 z≈1.71，在 inner_north 可见（g1_90 约 55 green px），**证伪唯一性假设 U1/U2**（至多一个塔状实例 / 中央塔是唯一带绿灯的塔）。final 池无已验证 HN1 帧（similar_negative 只是目标缺席 + ≤3px 绿点）→ identity 认证 INCOMPLETE；MS1 与合成 HN1 confuser 是不同证据类，不得混写。
- **泄漏审计 PASS**：v3 sha 跨 split 重合 0；val/train 与 exploratory 的像素近重复对 **0**；同轨迹跨 split 0；family/group/连续帧泄漏 0。同轨迹相邻帧 3651 对（预期内，非泄漏）。
- **外部产物索引 PASS**：3695 帧（v3 3398 + final 297）逐帧 PNG 可读（320×240）、字节 sha 与清单一致、observations sha 一致，0 缺失 / 0 不匹配；仓库外备份仅为建议，未上传。
- **认证结论 INCOMPLETE**：当前**没有任何"未被触碰"的 final 池**；final exploratory 标签不能冒充 sealed final；HN1 依赖合成构造记录、HN2 为 visual-only 合成遮挡；dev 手工标签只覆盖 294/3398 帧；**identity 的唯一性假设 U1/U2 被 map-native MS1 证伪**。v3 只能作为 dev train/val 与阈值冻结数据，identity/最终封存均未认证。

## 1. 现场与输入（本报告只读消费）

| 项 | 值 |
| --- | --- |
| 仓库 / 分支 / HEAD | `E:\isaac\proj_boom_birds` / `feat/v2.2-simulation-perception` / `800c53b0e8c1f075d7492be93c19aab06ef339e7` |
| T9 batch1 | `outputs/sensor_shadow/lm_dev_capture_20261104{,_sensor}`：5 族、337 RGB / **322 accepted**，run.complete PASS |
| T9 batch2 HN | `outputs/sensor_shadow/lm_dev_hn_capture_20261104{,_sensor}`：HN1/HN2、59 RGB / **53 accepted**，run.complete PASS |
| case manifest | `configs/scenarios/landmark_dev_cases_v2.json`（7 cases + `scene_injections`：hn1_confuser_v1 / hn2_occluder_v1，visual-only、非 arena 资产、无碰撞） |
| capture 证据 | `docs/reports/perception/capture_dev_20261104/`（run1/run2 manifest/summary/complete、frame/episode conditions、四边截断确认、HN1/HN2 证据、dedup/overlap、provenance） |
| annot2 dev 标注 | `outputs/perception/dev_annotations_20261104/`（labels_train 160 / labels_val 134 / labels_hn_val 24、labels_manifest、DRAFT label lists）；报告 `docs/reports/perception/annotation_verify_20261104/DEV_TRAIN_VAL_ANNOTATION_20261104.md` sha256 `a3395e6d…` |
| annot final exploratory | `outputs/perception/final_exploratory_20261104/`（labels_v1 `7115ee04…`、labels_manifest、279 帧全量 exploratory） |
| identity 相关证据 | `docs/reports/perception/capture_dev_20261104/map_native_structures.json`（sha256 `cb0deffa787050b1b13694a406ed62e4a10f14ddc4c80e063a3cc681628678b4`）：地图原生绿灯柱 MS1；与合成 HN1 confuser 分开记录 |
| 训练前决策 | 用户 2026-11-04 授权主候选**仅内部有界研究**，分发另行决策；这是**项目决定**，不表示许可问题已解决（AGPL/权重分发仍待用户） |

## 2. v3 划分

### 2.1 规模与 delta

| split | v2 组/帧(accepted) | v3 组/帧(accepted) | v3 变化 |
| --- | ---: | ---: | --- |
| train | 7 / 1320（1272） | **10 / 1475（1418）** | +inner_south、+static_high、+static_negative |
| val | 3 / 575（566） | **7 / 816（795）** | +inner_north、+static_low、+HN1、+HN2 |
| test | 0 | 0 | 无 sealed / 无 final |
| excluded | 9 / 1107（1071） | 9 / 1107（1071） | 不变 |
| 合计 | 19 / 3002（2909） | 26 / 3398（3284） | +7 组 / +396 帧 |

- 新组帧/accept：inner_south 105/102、static_high 26/23、static_negative 24/21（train）；inner_north 158/155、static_low 24/21、HN1 30/27、HN2 29/26（val）。
- family：新增 7 个（fam_inner_south、fam_static_high_far、fam_static_negative_E、fam_inner_north、fam_static_low_oblique、fam_HN1_confuser、fam_HN2_occluder）；共 13 个声明 family（fam_debug_empty 无帧）。
- v3 的 legacy 组保持 v2 conservative 归属：E 静态视点簇仍在 train；北走廊 3 组仍在 val。

### 2.2 val 覆盖核查（要求：多 family + 负例类型 + 北走廊）

| val 组 | family | 帧 / accepted | 覆盖 |
| --- | --- | ---: | --- |
| g_lm_ind_north | fam_north | 193 / 190 | 北走廊（旧） |
| g_geo_north | fam_north | 189 / 186 | 北走廊变体 |
| g_lm_pilot_north | fam_north | 193 / 190 | 北走廊 pilot |
| g_lmf_dev_inner_north | fam_inner_north | 158 / 155 | 新内北走廊（y≈+3.0） |
| g_lmf_dev_static_low | fam_static_low_oblique | 24 / 21 | 新近距低斜视静态 |
| g_lmf_dev_hn1_confuser | fam_HN1_confuser | 30 / 27 | HN1 合成绿顶相似结构（负例） |
| g_lmf_dev_hn2_occluder | fam_HN2_occluder | 29 / 26 | HN2 完全遮挡（GT_UNOBSERVABLE） |

- **结论：满足"多 family + 北走廊 + HN1/HN2"**。val 仍是单一仿真资产、同一相机配置，属"同一环境的不同走廊/视点/困难负例"，不是真实赛场 held-out visual domain。
- 边界：HN1 的 verified 仅来自 capture 的合成构造记录（`EXTERNAL_EVIDENCE`），**不代表真实赛场相似结构分布**；HN2 的墙是 visual-only 合成注入，`present=true` 但不可观测，**不是负样本**；val 的 `TARGET_ABSENT` 纯负例为 12 帧（其余负例为相似结构/不可观测），数量仍小。
- map-native 绿灯柱 MS1 在 inner_north（val）中可见，使"至多一个塔状实例 / 中央塔唯一带绿灯"不成立；它既不是目标也不是合成 HN1，**identity 相关结论必须按多候选/UNKNOWN 处理**。

## 3. 与 annot2 train/val 帧清单和标签 sha 的一致性

- 权威清单：`configs/perception/landmark_dev_label_lists_v1.json`（sha `befbbea1…`，status `DRAFT_FOR_DATAFREEZE_VAL_HN_MINIMAL_MERGED`；此前的 bf93b1d4 是文本差异，标签文件 sha 不变）；其 `splits.train` 160 帧 / 10 组、`splits.val` 134 帧 / 7 组，逐帧带 group 归属。
- v3 逐帧校验：**294 帧 checked，0 mismatch，0 unresolved，hn_val_pending=false**。即 v2 + T9 batch1 + HN 最小集的所有标注帧在 v3 中保持相同 split。
- 标签与规范 sha（写入 v3 `annotation_frame_lists`）：
  - labels_train.json `01977b9fea97c58bcdda2c6c301763ac52113bcc411a23094924b917ec08d2df`（160 帧）
  - labels_val.json `c3944e081d09d8a1d8398a0fb01a854580b116d004d8dcf14dacfa7f9493520d`（134 帧）
  - labels_hn_val.json `3dff20b6d99249a0cf71b7703eddea08ff223c8e2ff3d0466acfefc6ce283dc2`（24 帧子集）
  - annotation spec v2.1 `010255d931936457ded48db9b3691b69a31d6015f1f84fbbc6a659f10f766eac`（`FROZEN_FOR_DATA`）
- **关键缺口（对 train）**：v3 划分覆盖 3398 帧，但**人工标签只覆盖 294 帧**（160 train / 134 val）。训练若用全部帧，需要自动/半自动标签或裁剪到已标注子集；这不是本 T12 的产出，必须由 train 明确记录，不能把未标注帧当有标签数据。
- **HN 标注仍不完整**：HN accepted 53 帧（HN1 27 + HN2 26），已标 24 帧（13 + 11），**29 帧未标注**；"val HN 最小集"已可用，但不是完整 HN val 覆盖，后续补 val（INCOMPLETE）。
- **必须排除的帧**：val 的 GT_UNOBSERVABLE 11 帧（HN2）与 undecidable 3 帧、train 的 undecidable 3 帧（合计 undecidable 6）必须从训练损失/分母排除，不能当 background；HN2 不是负样本。

## 4. 暴露登记（configs/perception/landmark_exposure_registry_v1.json）

### 4.1 状态汇总

| 状态 | 组数 | 说明 |
| --- | ---: | --- |
| exposed_development | 26 | v3 全部 dev 组（legacy + T9 batch1 + HN） |
| exploratory_eval_candidate | 6 | 原 final seal 的 6 族整体降级 |
| untouched | 0 | **没有未触碰组** |
| 合计 | 32 | v3 26 + final seal 6 |

- 事件 **6 条**：dev 检测历史（模板/几何/independent 开发）、annot2 dev 去重标注选择、T9 dev 采集、**map-native MS1 identity 冲突**、final 34 帧试点标注、final 279 帧 exploratory 标注。
- 帧级 override 328 条：34 帧 `ANNOTATION_CALIBRATION`（final 试点）+ 294 帧 dev 标注校准。
- 校验：`landmark_exposure_registry_verify_20261104.json` **PASS，0 error / 0 warning**；registry 与 v3、seal 的 group 集合逐一对齐。

### 4.2 final 池降级依据

- annot 已对 final 池 **279/279 accepted 帧**生产 exploratory 标签（labels sha `7115ee04…`，manifest sha `8f06e156…`）；此前 34 帧试点已覆盖 **6/6 family**（每族至少 1 帧）。
- 依据 `同组近邻污染` 规则：同一 episode/group/family 内帧高度相关，**移除 34 帧不能恢复 sealed**；final 6 族整体记为 `exploratory_eval_candidate`，`dataset_role=DEVELOPMENT_EXPLORATORY`，34 帧 `ANNOTATION_CALIBRATION`，其余 245 帧 exploratory。
- registry `certification`：`can_claim_sealed=false`、`untouched_final_groups=0`、`conclusion=INCOMPLETE`，理由：final 全量已标注、34 帧不能单独移除、T9 是 dev 数据、无第三方独立封存（仅流程隔离 + hash 承诺）。
- **hash 不等于 sealed**：seal 文件保留原字节与历史 `sealed_test` 名字，registry 是权威暴露状态并已降级；不得再用 seal 名字对外称 sealed。

### 4.3 identity 认证（U1/U2 证伪）

- registry `identity_certification`：`U1_at_most_one_tower_like_instance=FALSIFIED`、`U2_central_tower_is_only_green_light_tower=FALSIFIED`、`final_pool_verified_HN1_frames=0`、`identity_status=INCOMPLETE`。
- 证据：map-native 绿灯柱 MS1 约 (3.0,4.0)，顶 z≈1.78、绿灯 z≈1.71，**地图原生非注入**；inner_north g1_90 可见约 55 green px，static_negative 从东侧看绿灯 0 px（灯为单侧/方向性）。它与中央塔 (11.52,-0.01,1.25) 不同，也不属于合成 HN1 confuser。
- 影响：tower 类别检测仍可训练，但**任何 landmark_id/identity 声明必须改为多候选/UNKNOWN 或重新定义唯一性假设**；final 池的 similar_negative 只有目标缺席 + ≤3px 绿点，**没有已验证 HN1 帧**，identity 认证不能写成通过。

## 5. 泄漏 / 近重复审计

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_20261104.json`（status PASS）。

- 审计集合：v3 train 1475 帧、v3 val 816 帧、final exploratory 297 帧（含 18 warmup，accepted=false）。
- 阈值（写入证据 JSON）：16×12 灰度缩略图 **mean abs diff ≤ 2.0/255** 作为候选预筛；全分辨率 **mean abs ≤ 3.0/255 且 max ≤ 40** 确认近重复；sha256 相等单独检查。该启发式不能替代人工视觉复核。
- 结果：
  - sha 跨 split 重合：train-val **0**；exploratory-dev **0**。
  - 像素近重复对：**0**（train_val 0、dev_exploratory 0）。
  - 同轨迹相邻帧：3651 对（同一 episode 相邻 sequence，预期高度相似，**非泄漏**），同轨迹跨 split **0**。
  - 结构审计（v3）：group 跨 split 0、family 跨 split 0、sha 跨 split 0、连续帧跨 split 0。
- 已知最接近的跨集合邻接（final vs dev，T5 已登记）：`lmf_edge` vs `pilot_east_center` 起点 0.30 m/yaw 差 0.60 rad；`lmf_similar_negative` vs `pilot_east_away` 0.54 m/同 yaw；最接近图像对 mean abs ≥ 7.69/255，高于近重复阈值，且 final 已降级 exploratory → 这些是已知邻接，不是 dev split 泄漏。
- 残余风险：像素阈值是启发式；同族不同 session 的重跑（如 debug/gui）靠 family/session 规则排除而非像素；v3 val 的 HN1/HN2 是合成注入，与真实负例分布不同（见 §8）。

## 6. 外部产物索引与可复验性

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_external_index_20261104.json`（status PASS）。

- 实际遍历 16 个数据集目录（v3 的 15 + final seal 的 1），共 **3695 帧**（3398 + 297）：逐帧 PNG 存在、可解码、尺寸 320×240、字节 sha256 与清单一致；observations.jsonl 的 sha256 与 freeze 记录一致。
- 结果：`png_readable 3695 / png_missing 0 / png_sha_mismatch 0 / observations_sha_mismatch 0`；16/16 数据集 PASS。
- 原始数据仍在 ignored 的 `outputs/`，不入 Git；仓库只存 freeze/seal/registry/清单/hash/报告。
- 备份建议（**不阻塞、未上传**）：在至少一块外部磁盘/NAS 保留 `outputs/sensor_shadow` 原始包，并连同 freeze/registry/本报告与 `landmark_external_index_20261104.json` 一起保存；是否上传远端由用户决定（D3）。

## 7. 复现命令与证据

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 重建并校验 v3（canonical hash 不含 generated_at）
& $py scripts/verify_landmark_dataset.py --build --profile v3 --freeze configs/perception/landmark_split_freeze_v3.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v3_20261104.json
# 暴露登记（构建后立即校验）
& $py scripts/verify_landmark_dataset.py --build-exposure-registry --registry configs/perception/landmark_exposure_registry_v1.json --registry-output docs/reports/perception/dataset_freeze_20261104/landmark_exposure_registry_verify_20261104.json
# 近重复 / 泄漏审计
& $py scripts/verify_landmark_dataset.py --audit-near-duplicates --audit-freezes configs/perception/landmark_split_freeze_v3.json --audit-seal configs/perception/landmark_final_pool_seal_v1.json
# 外部产物索引
& $py scripts/verify_landmark_dataset.py --external-index --index-freezes configs/perception/landmark_split_freeze_v3.json --index-seal configs/perception/landmark_final_pool_seal_v1.json
# 回归
& $py -m pytest -q
```

| 证据 | 结果 |
| --- | --- |
| v3 冻结校验 | PASS，0 error，155 warning（115 历史 label split 声称 + 38 组内 warmup 重复 sha + 1 空采集 + 1 新静态视点簇跨 train/val） |
| 暴露登记校验 | PASS，0 error / 0 warning |
| 近重复审计 | PASS，0 泄漏 / 0 近重复 |
| 外部产物索引 | PASS，3695/3695 帧 |
| 全量 pytest | **971 passed**（含 dataset 专项 45 条；v1/v2/v3/registry 集成测试在 raw outputs 缺失时自动 skip） |

- v3 仅 1 条新 `VIEW_CLUSTER_SPLIT` warning：T9 新静态视点簇 `static_E_new_views` 跨 train（static_high/static_negative）与 val（static_low）。三者机位不同（高/远、低斜、yaw+2.2），不是字节重复；按 Lead 批准 split 保留并如实记录。

## 8. 认证结论与剩余缺口

| 项 | 结论 | 说明 |
| --- | --- | --- |
| A2 数据组独立（dev 机制隔离） | **PASS（机制）/ held-out INCOMPLETE** | v3 0 泄漏；val 现覆盖 5 family + HN1/HN2，比 v2 单北走廊明显改善；仍是单仿真资产/单相机，不能当真实 held-out visual domain |
| A3 final 池封存 | **INCOMPLETE** | 无 untouched final；final 6 族整体 exploratory；34 帧试点 + 279 帧 exploratory 标签已暴露 |
| A6 预注册 | **INCOMPLETE** | v3 hash + label shas + spec sha 可作预注册材料；阈值仍需在 v3 val 上冻结，且 final 不存在 |
| A8 样本/统计 | **INCOMPLETE** | dev 人工标签仅 294/3398 帧；HN1 为合成构造（EXTERNAL_EVIDENCE，非真实分布）；HN2 11 帧 GT_UNOBSERVABLE；val 纯目标缺席负例仅 12 帧；HN 仍有 29 accepted 帧未标 |
| identity（U1/U2） | **INCOMPLETE** | map-native 绿灯柱 MS1 证伪唯一性 U1/U2；final 池无已验证 HN1 帧；identity 声明不可通过 |
| v3 可用性 | **dev train/val 可用** | train 10 组 1475 帧 / val 7 组 816 帧；**不可作 final/sealed 结论** |

- **没有真正未触碰 final → 认证条件 INCOMPLETE**。若未来需要 sealed final，必须在新轨迹族上采集并**在采集前冻结**，且标注者/开发者独立性或"流程隔离 + hash 承诺"局限需如实写入 final 记录。
- 对真实赛场的适用性、HN1 真实分布、合成注入的域差异、单代理标注一致性仍是 UNKNOWN；v3 不提升 BB22 Gate。

## 9. 交给 train 的使用边界

1. 只使用 **v3**（canonical `bc037e30…`）的 train/val；不要再用 v2/v1 或 final seal 当训练/验证划分。
2. train 用 `accepted=true` 帧并过滤 38 组 warmup 重复（freeze 中 accepted=false）；标签只覆盖 294 帧（train 160 / val 134），其余 dev 帧无人工标签，必须显式选择"只用已标注子集"或另行生成自动标签并记录。
3. 阈值/early-stop/checkpoint 只用 **val**（816 帧，7 组；有标签子集 134 帧含 HN 最小集）冻结；HN2 的 11 帧 `GT_UNOBSERVABLE` 不进 presence 分母、不参与训练损失；undecidable 6 帧（train 3 + val 3）也排除；HN1 的 13 帧作为 `SIMILAR_STRUCTURE` 负例但注明合成来源；HN 剩余 29 accepted 帧未标，不能当有标签数据。
4. **final sealed 不存在**：不得把 final exploratory 279 帧当 sealed final；final 结果只能标记 exploratory，不能用于阈值回调或"已达标"声明。
5. 预注册材料：v3 canonical `bc037e30…`、label lists `befbbea1…`、labels train/val shas、spec v2.1 `010255d9…`、registry sha `643d27c5…`。
6. **identity 不可作为已认证能力**：map-native MS1 使 U1/U2 不成立；若训练身份输出，必须按多候选/拒绝策略处理并在报告标 INCOMPLETE。
