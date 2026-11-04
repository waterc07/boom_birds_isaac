# 地标 dev 划分冻结 v4、暴露登记 v2 与条件 holdout 占位（2026-11-04）

> **状态：** PASS（v4 清单 / 暴露登记 v2 / 泄漏审计 / 外部产物索引的 QA）；holdout **NOT_TRIGGERED**；identity 案例 **PENDING（v4.1）**；模型效果、板端、导航均 NOT RUN
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §20.11.1/§20.11.3/Phase 6；configs/perception/landmark_improvement_gate_v1.json 的 development-to-holdout 门；configs/perception/landmark_training_plan_v2.json A2/A3/A8
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真采集产物索引（离线只读；本 T17 未运行 Isaac、未训练、未安装依赖、未上传数据）
> **最后核对：** 2026-11-04

本报告回答：HN val 补齐后如何冻结 v4、旧 exploratory 池如何登记为 development、train/val 与旧池是否仍有泄漏、identity 案例与 holdout 的当前状态。所有 PASS 均为数据/清单/格式 QA，不是模型效果、板端、导航或 final 认证。

## 0. 结论摘要

- **v4 已冻结**：`configs/perception/landmark_split_freeze_v4.json`
  - canonical sha256 `afa5caa45f76d4be70245b27be59bf05945574380be4c22fc2102e6f3ef442a4`
  - file sha256 `591a8b113caa2864fe04f9f7f463904a77b177f75785afda90bc9e18aee8afef`
  - **train 10 组 / 1475 帧（1418 accepted）**；**val 7 组 / 816 帧（795 accepted）**；test 0；excluded 9 组 / 1107 帧（1071）；26 组 / 3398 帧 / 15 数据集 / 13 family。
  - v4 校验：**PASS，0 error，155 warning**（115 历史 label split 声称 + 38 组内 warmup 重复 + 1 空采集 + 1 静态视点簇跨 split）。
- **v3→v4 delta**：组结构不变（`new_groups=[]`、`new_frames=0`，base v3 canonical `bc037e30…`）；变化是 **HN val 补齐**与 label lists 更新；v4 的 `annotation_frame_lists` 记录 323 帧逐帧校验（160 train + 163 val）、0 mismatch。
- **labels（v4 引用）**：train `01977b9fea97c58bcdda2c6c301763ac52113bcc411a23094924b917ec08d2df`（160 帧，未变）；val `8c2155979b517626299fd85c61759b73ceb1bfc369be839d4453caa3b3ed33ac`（163 帧）；lists config `0c1c75aed2fdddd6de3773180f93dc643192d2c119eeccbbaea39f2bd23d6488`（status `DEV_VAL_HN_COMPLETE_PENDING_FREEZE_V4`）；spec v2.1 `010255d9…`。
- **HN 口径（val 163 帧）**：HN1 27 帧 `SIMILAR_STRUCTURE`（合成注入 confuser，verified=EXTERNAL_EVIDENCE，非真实分布）；HN2 26 帧 `GT_UNOBSERVABLE`（present/occluded、bbox/keypoint=null、reference UNAVAILABLE，**不是负例**）。val 统计：present 121 / absent 39 / undecidable 3 / GT_UNOBSERVABLE 29 / negative TARGET_ABSENT 12 + SIMILAR_STRUCTURE 27。
- **identity 案例：PENDING（`identity_cases_pending=true`）**。T15 采集 run 已于 20:15:13 完成（run.complete PASS），但 **T19 标注尚未开始**；v4 不含 identity 数据集，默认 v4.1 追加、全部进 val，不阻塞 train baseline。
- **暴露登记 v2**：`configs/perception/landmark_exposure_registry_v2.json`（file sha `11f355ce6cf619476404dd42c19fa0c7d2958f0d347d9babb017b0a93b05fafa`）：32 组全部 **exposed_development**、**0 exploratory / 0 untouched**；旧 final/exploratory 6 组正式降级为 development，**不再称 final/sealed**；10 条事件（含 diag post-eval 查看、one-shot exploratory 评价、HN 补齐、MS1 identity 冲突）；357 帧级 override（34 试点 + 323 dev 标注）；校验 PASS 0 error/0 warning。
- **泄漏/近重复审计**：v4 sha 跨 split 0、像素近重复 0、同轨迹跨 split 0、family/group/连续帧泄漏 0；同轨迹相邻 3651 对为预期。**PASS**。
- **外部产物索引**：16 数据集 / 3695 帧 PNG 可读、逐帧 sha 与清单一致、obs sha 一致；0 缺失/0 不匹配。**PASS**。
- **holdout：NOT_TRIGGERED**（`configs/perception/landmark_holdout_freeze_v1.json`，file sha `958ebf4888808904b608034b98c98ac157ee25d3c6a902b1514f58cb0af0cb76`）：improvement gate 尚未评估（T18 候选在本 freeze 之后才跑），无 holdout 数据采集；采样/覆盖规则已预注册但未触发。

## 1. 现场与输入

| 项 | 值 |
| --- | --- |
| 仓库 / 分支 / HEAD | `E:\isaac\proj_boom_birds` / `feat/v2.2-simulation-perception` / `0c27525` |
| HN 补齐（T16-A） | `labels_hn_val 87ba533d…`（53/53），`labels_val 8c215597…`（163 帧），QA PASS；来源 `docs/reports/perception/annotation_verify_20261104/HN_REMAINING_ANNOTATION_20261104.md` |
| dev lists | `configs/perception/landmark_dev_label_lists_v1.json` sha `0c1c75ae…`（status `DEV_VAL_HN_COMPLETE_PENDING_FREEZE_V4`） |
| identity 采集（T15） | case manifest `configs/scenarios/landmark_dev_identity_cases_v1.json`（目标单独/MS1 单独/同框×3/近距截断/完全遮挡 7 case）；run `outputs/sensor_shadow/lm_dev_identity_capture_20261104` 于 20:15:13 完成（run.complete PASS），但 **T19 标注未开始**，故未并入 v4（v4.1） |
| identity 标注（T19） | 依赖 T15，未完成 → identity_cases_pending |
| improvement gate | `configs/perception/landmark_improvement_gate_v1.json` sha `7c81ae51c003d4a0271fcb8284a6edbedd3267d103cbb923c87d2ab4c0bddd38` |
| 旧 exploratory 池 | seal `configs/perception/landmark_final_pool_seal_v1.json` canonical `cedbbc7e…`；279 帧 labels `7115ee04…`；**已降级 development** |
| 许可/研究边界 | 用户 2026-11-04 授权主候选仅内部有界研究；分发另行决策（项目决定，非许可已解决） |

## 2. v4 划分与 v3→v4 delta

| split | v3 组/帧(accepted) | v4 组/帧(accepted) | 说明 |
| --- | ---: | ---: | --- |
| train | 10 / 1475（1418） | 10 / 1475（1418） | 不变 |
| val | 7 / 816（795） | 7 / 816（795） | 结构不变；标签 110→163（HN 24→53） |
| test | 0 | 0 | 无 sealed/final |
| excluded | 9 / 1107（1071） | 9 / 1107（1071） | 不变 |
| 合计 | 26 / 3398（3284） | 26 / 3398（3284） | 组结构完全一致 |

- val 组/家族（不变）：fam_north（lm_ind_north/geo_north/lm_pilot_north）+ fam_inner_north + fam_static_low_oblique + fam_HN1_confuser + fam_HN2_occluder。
- **v3→v4 的唯一实质变化是标注**：HN val 从 24/53 补齐到 53/53；lists config 更新并刷新 sha；v4 `annotation_frame_lists` 逐帧校验 323 帧、0 mismatch、`hn_val_pending=false`。
- **身份案例不并入 v4**：T15 采集未完成、T19 未开始；v4 记 `identity_cases_pending=true`，计划 v4.1 追加并全部进 val（困难评估案例）。

## 3. HN 分母与 GT_UNOBSERVABLE 口径（对 train 的关键说明）

- val labels 163 帧统计（annot2 v2.1）：present 121、absent 39、undecidable 3、**GT_UNOBSERVABLE 29**、reference 可用 41 / 不可用 80、四边截断 17、negative_type = TARGET_ABSENT 12 + SIMILAR_STRUCTURE 27。
- **HN1（27 帧，SIMILAR_STRUCTURE）**：`present=false + negative_type=SIMILAR_STRUCTURE + confusers[1] verified=true（EXTERNAL_EVIDENCE；合成注入 hn1_confuser_v1；非 arena 资产、不代表真实分布）`。作为相似结构负例使用，但必须标注合成来源。
- **HN2（26 帧，GT_UNOBSERVABLE）**：`present=true + occluded=true + visibility=OCCLUDED + bbox=null + keypoint=null + reference UNAVAILABLE/REFERENCE_OCCLUDED`。
  - **不评定位、不进 presence 四格**（GT 不可观测），**必须单列报告**；**不是负样本**，训练损失必须排除，不能当 background。
- **undecidable 3 帧（val）+ 3 帧（train）**：同样从训练损失/分母排除。
- 因此 val 的可用 presence 分母 = 121 present − 29 GT_UNOBSERVABLE = 92（仅为示例口径，实际分层报告必须给分母），**不能把 29 个 GT_UNOBSERVABLE 算成 29 个漏检或 29 个负例**。

## 4. 暴露登记 v2（谁看过什么/用途/时点）

证据：`configs/perception/landmark_exposure_registry_v2.json`（sha `11f355ce…`）+ `docs/reports/perception/dataset_freeze_20261104/landmark_exposure_registry_v2_verify_20261104.json`（PASS）。

| 数据池 | 状态 | 事件/依据 |
| --- | --- | --- |
| v4 dev 26 组（legacy + T9 + HN） | **exposed_development** | dev 模板/几何/independent 开发（2026-11-03）、annot2/annot 标注选择（2026-11-04）、T9 采集、HN 补齐、MS1 审查 |
| 旧 final/exploratory 6 组（297 帧） | **exposed_development（正式降级）** | 34 帧试点（annotation calibration）、279 帧 exploratory 标签（`7115ee04…`）、一次性 exploratory 评价（train，279 帧）、diag post-eval 查看（predictions/labels/images） |
| untouched | **0 组** | 没有任何未触碰数据 |

- 事件列表（10 条）：dev 检测历史、dev 标注选择（含 HN 53/53）、T9 dev 采集、MS1 identity 冲突、final 34 帧试点、final 279 exploratory 标签、**one-shot exploratory 评价**、**diag post-eval 查看**、HN/TINY 标注、identity case 采集（PENDING_V4_1）。
- 帧级 override 357 条：34 帧 final 试点 + 323 帧 dev 标注（160 train + 163 val）。
- **旧池不得再称 final/sealed**：seal 文件保留原字节与历史名字；registry v2 是权威暴露状态；`certification.can_claim_sealed=false`、`untouched_final_groups=0`、`conclusion=INCOMPLETE`。
- identity：`identity_certification` 记录 U1/U2 **FALSIFIED**（map-native 绿灯柱 MS1≈(3.0,4.0) 在 inner_north 可见）；final 池无已验证 HN1 帧 → identity 认证 INCOMPLETE。
- 历史 registry v1 的 evidence hash 因 T16 lists 更新而变旧（annot 已提示）；v1 保留为历史字节，只做结构复核；**v2 为当前权威登记**。

## 5. 泄漏 / 近重复审计

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v4_20261104.json`（**PASS**）。

- 集合：v4 train 1475 帧、v4 val 816 帧、旧 exploratory 297 帧（18 warmup accepted=false）。
- 阈值：16×12 灰度缩略图 mean abs diff ≤ 2.0 预筛；全分辨率 mean abs ≤ 3.0 且 max ≤ 40 确认；sha256 相等单独检查（启发式，不替代人工视觉复核）。
- 结果：
  - sha 跨 split：train-val **0**；exploratory-dev **0**。
  - 像素近重复对：**0**（train_val 0、dev_exploratory 0）。
  - 同轨迹相邻帧 3651 对（同一 episode 相邻 sequence，预期非泄漏）；同轨迹跨 split **0**。
  - 结构审计（v4）：group/family/sha/连续帧跨 split 均 **0**。
- 已知邻接：final 旧池 vs dev 最接近起点 0.30 m/yaw 0.60 rad（edge vs pilot_east_center）、0.54 m/同 yaw（similar_negative vs pilot_east_away）；最接近图像对 mean abs ≥7.69/255，高于阈值；旧池已降级 development，不构成 v4 dev split 泄漏。

## 6. 外部产物索引

证据：`docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v4_20261104.json`（**PASS**）。

- 16 数据集 / **3695 帧**（v4 3398 + 旧 exploratory 297）：逐帧 PNG 可解码、320×240、字节 sha256 与清单一致；observations sha 一致。
- 结果：png_readable 3695 / missing 0 / sha_mismatch 0 / observations_sha_mismatch 0；16/16 数据集 PASS。
- 原始数据仍为 ignored `outputs/`；仓库只存 freeze/registry/清单/hash/报告。备份建议：外部磁盘/NAS 保留原始包 + freeze/registry/index（**不阻塞、未上传**）。

## 7. holdout 状态（条件门）

证据：`configs/perception/landmark_holdout_freeze_v1.json`（file sha `958ebf48…`），status **NOT_TRIGGERED**。

- 触发条件（`landmark_improvement_gate_v1.json` sha `7c81ae51…`，development_to_holdout_gate）：胜出候选（3 seeds、val 选模）需同时满足 val joint≥0.60、相对匹配 baseline 提升≥+0.08、identity 高置信误匹配不差于 baseline、reference coverage≥0.50、worst-group joint 不差于 baseline +0.05。
- 当前**未评估**：improvement 候选（T18）在本 freeze 之后才运行，尚无 3-seed 结果；因此 holdout 无数据、无采样、**captured=false**。
- 已预注册（不因触发而重定）：≥3 新族、200–400 帧、small target / close-range truncation / target absent / real map confuser / same-frame ambiguity；固定抽样规则（按 family accepted 帧序 midpoint systematic，端点/极值条件强制，不用预测质量挑选）；标注 spec v2.1+；一次性评价、不回调。
- 触发后必须新建 holdout 数据并重新冻结（不能复用本 placeholder 的 hash）；未触发则本路由版本停止，不做新 holdout capture。

## 8. 复现命令与证据

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py scripts/verify_landmark_dataset.py --build --profile v4 --freeze configs/perception/landmark_split_freeze_v4.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v4_20261104.json
& $py scripts/verify_landmark_dataset.py --build-exposure-registry-v2
& $py scripts/verify_landmark_dataset.py --build-holdout
& $py scripts/verify_landmark_dataset.py --audit-near-duplicates --audit-freezes configs/perception/landmark_split_freeze_v4.json --audit-seal configs/perception/landmark_final_pool_seal_v1.json --audit-output docs/reports/perception/dataset_freeze_20261104/landmark_leakage_audit_v4_20261104.json
& $py scripts/verify_landmark_dataset.py --external-index --index-freezes configs/perception/landmark_split_freeze_v4.json --index-seal configs/perception/landmark_final_pool_seal_v1.json --index-output docs/reports/perception/dataset_freeze_20261104/landmark_external_index_v4_20261104.json
& $py -m pytest -q
```

| 证据 | 结果 |
| --- | --- |
| v4 冻结校验 | PASS，0 error，155 warning |
| 暴露登记 v2 校验 | PASS，0 error / 0 warning（32 组、10 事件、357 override） |
| 泄漏/近重复审计 v4 | PASS，0 泄漏 / 0 近重复 |
| 外部产物索引 v4 | PASS，3695/3695 帧 |
| holdout | NOT_TRIGGERED（无数据、未触发） |
| dataset 专项 pytest | `tests/evaluation/test_landmark_dataset.py` → **48 passed**（含 v1/v2/v3/v4/registry v1-v2/holdout 集成测试） |
| 全量 pytest | 当前仓库其他进行中模块导致 2 failures（`test_landmark_posteval` import 未完成、`test_landmark_onnx/test_landmark_train_cli` 在改）；与 T17 文件无关，待对应 teammate 完成后复跑 |

## 9. 遗留缺口与认证结论

| 项 | 结论 | 说明 |
| --- | --- | --- |
| A2 dev 机制隔离 | **PASS（机制）/ held-out INCOMPLETE** | v4 0 泄漏；val 5 family + HN1/HN2；仍单仿真资产/单相机 |
| A3 final 封存 | **INCOMPLETE** | 无 untouched final；旧池已降级 development；identity 案例 pending |
| identity（U1/U2） | **INCOMPLETE** | map-native MS1 证伪 U1/U2；final 池无已验证 HN1 帧 |
| v4 标注覆盖 | **INCOMPLETE** | 3398 帧中仅 323 帧有人工标签（train 160/val 163）；HN 53/53 已补齐；identity 案例待 v4.1 |
| holdout | **NOT_TRIGGERED** | improvement gate 未评估；无 holdout 数据 |
| v4 可用性 | **dev train/val 可用** | train 10 组 1475 帧 / val 7 组 816 帧；不可作 final/sealed 认证 |

- **没有真正未触碰 final**：旧 279 帧已被完整标注 + 一次性评价 + post-eval 查看；只能作为 development/exploratory 证据，不能当 sealed final。
- 对真实赛场、HN1 真实分布、合成注入域差异、单代理标注一致性仍是 UNKNOWN；v4 不提升 BB22 Gate。
