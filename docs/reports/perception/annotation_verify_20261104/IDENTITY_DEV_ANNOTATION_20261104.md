# identity/confuser development 案例标注与 QA（2026-11-04）

> **状态：** PROVISIONAL / DEVELOPMENT（内部开发标注；不是 sealed final、不是模型效果、板端或导航验收；不提升任何 Gate）
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §7.5/§7.6/§7.7；标注规范 configs/perception/landmark_annotation_spec_v2_1.json（FROZEN_FOR_DATA，sha256 010255d9…）
> **证据域：** 离线标注 QA（Isaac 合成 320×240 RGB；T15 identity 7 case/169 accepted，取 capture 固定规则 62 代表帧；agent 代理标注 + 接触表/zoom 视觉复核；无模型训练/推理、无板端/SITL/实飞）
> **最后核对：** 2026-11-04（仓库 E:\isaac\proj_boom_birds，分支 feat/v2.2-simulation-perception，HEAD 0c27525；本任务未 commit/push）

## 0. 结论先行

1. **标注范围**：采用 capture 固定代表帧规则（identity_representative_frames.json，sha256 c59f88e7062b2886fc6c77e165adc3a485b6c52e107c7d671a9053930433c80f；规则：每 case 前 2 + 后 2 个 accepted 帧 + 中间等步长，每 case ≤10，共 **62 帧** ≤72）。7 case 覆盖 target alone / MS1 confuser alone / 三者同框 3 构图 / 近距四边截断 / 完全遮挡。
2. **逐案判定**：TARGET_ONLY 18、CONFUSER_ONLY 9（全部 negative_type=SIMILAR_STRUCTURE + verified MS1 confuser）、BOTH_TARGET_IDENTIFIED 26、GT_UNOBSERVABLE 9；**AMBIGUOUS 0**（本批所有同框帧在 320×240 + zoom 下均可凭外观区分塔与 MS1；未强行制造 ambiguous，candidates 字段保留未用）。
3. **统计**：present 53（含 9 GT_UNOBSERVABLE 全遮挡）/ absent 9；keypoint 18（仅 target-alone 与 near-trunc 帧，参考点可用）；confusers 35（全部 verified）；截断 16 帧（right 16、bottom 9）；ambiguous/candidates 0/0。
4. **格式 QA**：scripts/validate_landmark_annotations.py → labels_identity_dev.json **PASS 62/62，0 error / 0 warning**；labels_val.json（已恢复为 163 帧系统样本+HN，不含 identity 行）**PASS 163/163**。另导出 train 稳定读取的 **labels_val_validation163.json**（163 帧，原 8c215597 帧集合；identity 行排除；sha256 a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144，PASS 163/163）。
5. **合并口径**（按 Lead 2026-11-04 指示）：identity 批次作为**独立文件** labels_identity_dev.json + lists identity_dev_batch 段交付；**不并入** labels_val.json，由 datafreeze v4.2 合并。dataset_role=DEVELOPMENT，每 case 一个 group，整 case 分配 split（不拆帧），本批不参与 final/sealed。
6. **身份判定边界**：只用外观（中央塔：对称顶部灯架 + 宽收分塔体 + R 标记 + 白色阶梯底座；MS1：细长柱体、单侧/非对称平顶模块、侧向绿灯、蓝色饰条）；几何候选 bbox 仅作 bbox draft 并按图像 x 顺序标 A/B，**未用 GT 位置/oracle 区域/标签判定身份**。MS1 verified 依据 map probe + map_native_structures.json（WORLD_POSE_OR_MAP_DB）；唯一合成注入 hn2_occluder_v1 标 EXTERNAL_EVIDENCE + SYNTHETIC_INJECTED（非真实赛场分布）。

## 1. 数据与 provenance

| 项目 | 值 |
| --- | --- |
| 采集 run | outputs/sensor_shadow/lm_dev_identity_capture_20261104（run.complete.json PASS，可见前台 GUI；sensor run 同名前缀 + _sensor） |
| 逐帧条件 | docs/reports/perception/capture_dev_20261104/identity_frame_conditions.json（sha256 d8cc9d37a085079ee81384f5d79c7088bbfdf8046a2f9492aff12383e5292d69；169 帧：相机位姿、target/MS1 距离/方位/FOV、四边截断、strict v2.1 green、target/MS1 归属 green、confusers[]） |
| 代表帧规则 | docs/reports/perception/capture_dev_20261104/identity_representative_frames.json（sha256 c59f88e7062b2886fc6c77e165adc3a485b6c52e107c7d671a9053930433c80f；62 帧） |
| case 定义 | configs/scenarios/landmark_dev_identity_cases_v1.json（sha256 e73350802a400cb1836cce14ec0c5cc278f888b6ff5e726b4692e9ac39b7a0c7） |
| MS1 证据 | identity_ms1_confuser_record.json（sha256 c95f13c5d633e679d10bc665df2835265d22baff8de3493522450021e240b952）：map-native MAP_NATIVE_GREEN_LAMP_PILLAR_MS1，map probe down-ray (3.0,4.0) 顶 z=1.78、绿灯 z~1.71；**非注入** |
| 注入证据 | identity_injection_record.json（sha256 3645177aafca5a2364c4996344ebd9f46e6fed6da977f8af2931566e2a0c577d）：唯一合成注入 hn2_occluder_v1（visual-only 墙，0.4×2.4×1.9 m @ (10.6,0,0.95)） |
| capture 报告 | docs/reports/perception/capture_dev_20261104/IDENTITY_CAPTURE_20261104.md（sha256 04e77c98f33bb279ee87fdde96f15b987185d9fa79be303bce965f79ee35b6ad） |

## 2. 选帧（固定规则，非检测器分数）

- 采用 capture 代表帧规则（见 §1），**62 帧**：target_alone 9、ms1_alone 9、both_scale_lateral 8、both_mid_similar_scale 9、both_same_bearing 9、target_near_trunc 9、full_occlusion 9。
- 我另做过一次独立近重复簇+medoid 抽样（68 帧）做交叉检查；最终交付按 lead 要求改用 capture 的 62 代表帧，selection_identity.json（sha256 944872c8a0929bb11f8ccf7e3cc64d17d9752e068821744b6fed4362669aa6af）记录 roster 来源与规则，未使用检测器/模型分数。
- 每 case 为一个 group（不拆帧）；本批 dataset_role=DEVELOPMENT、split 待 datafreeze v4.2 按整 case 分配。

## 3. 标注口径（spec v2.1）

- **target alone / near-trunc**：present=true + bbox + keypoint（strict green≥3 且在目标 bbox 内且目视确认）；四边截断按 capture 塔几何投影 + zoom 目视核对。
- **MS1 alone**：present=false（中央塔不在视野）+ negative_type=SIMILAR_STRUCTURE + confusers[verified=true, verification_source=WORLD_POSE_OR_MAP_DB]，confuser bbox=几何 draft+目视、green_cue=可见绿灯；不把 MS1 写成目标。
- **both-in-frame（3 构图）**：present=true（目标）+ confusers[MS1 verified]；目标由外观判定（对称顶部灯架/宽收分塔体/R 标记/白阶梯底座 vs 细长柱+非对称平顶+侧向绿灯+蓝饰条）。同框帧**不给 keypoint**：dominant strict green 可能来自 MS1 灯（scale_lateral/same_bearing）或目标灯仅 ≤4 px（mid_similar_scale），无法在无歧义下归属 → reference_status=UNAVAILABLE/REFERENCE_TOO_SMALL，不猜坐标。
- **same_bearing 近距 MS1 与远目标（12 m）**：目标 green<3 px → REFERENCE_TOO_SMALL；两对象在该视角并排可见（非完全遮挡），目标 bbox 取 capture 塔几何投影 + 目视。
- **full occlusion**：present=true + occluded=true + visibility=OCCLUDED + bbox=null + keypoint=null + reference_status=UNAVAILABLE + REFERENCE_OCCLUDED = **GT_UNOBSERVABLE**，不进四格/正负分母，不是负样本。
- **四边截断**：true 边来自 capture tower_four_side_truncation_geometric（投影 aid），并在 zoom 接触表目视核对；labels 内 truncation_source 标 CAPTURE_METADATA。与 capture 元数据无冲突（见 §5 QA 记录：早期 draft 与 capture 的 14 帧差异已按 capture 几何修正）。
- **身份歧义**：同框帧若外观无法区分应标 ambiguous+candidates(MULTIPLE_SIMILAR_STRUCTURES)；本批 62 帧经视觉复核均可区分（目标 35–42 px 及以上；same_bearing 目标约 22–24 px 但顶灯架轮廓可辨），故 **ambiguous=0**，不虚构歧义。

## 4. 逐案矩阵

| group | condition | frames | present(可观测) | absent | GT_UNOBSERVABLE | keypoints | confusers | truncated(right/bottom) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| g_lmf_devid_both_mid_similar_scale_0 |  | 9 | 9 | 0 | 0 | 0 | 9 | 0 (right 0/bottom 0) |
| g_lmf_devid_both_same_bearing_0 |  | 9 | 9 | 0 | 0 | 0 | 9 | 0 (right 0/bottom 0) |
| g_lmf_devid_both_scale_lateral_0 |  | 8 | 8 | 0 | 0 | 0 | 8 | 7 (right 7/bottom 0) |
| g_lmf_devid_full_occlusion_0 |  | 9 | 0 | 0 | 9 | 0 | 0 | 0 (right 0/bottom 0) |
| g_lmf_devid_ms1_alone_0 |  | 9 | 0 | 9 | 0 | 0 | 9 | 0 (right 0/bottom 0) |
| g_lmf_devid_target_alone_0 |  | 9 | 9 | 0 | 0 | 9 | 0 | 0 (right 0/bottom 0) |
| g_lmf_devid_target_near_trunc_0 |  | 9 | 9 | 0 | 0 | 9 | 0 | 9 (right 9/bottom 9) |

## 5. QA 过程与修正

- 原生 4×3（20 px 网格）+ 2× zoom（10 px 网格）接触表覆盖 62 帧；另用 labels 校验器生成的 62 张 overlay 抽查目标 bbox/keypoint 与身份选择。
- **发现的错误并修正**：初版同 bearing 构图把“近处大对象（MS1）”误当目标（overlay 显示 bbox 落在 MS1 上）；复核外观后改为目标=远处小塔（A），MS1=近处大柱（B），并同步修正 confuser 记录。
- **截断口径修正**：我最初的宽度/高度 draft 与 capture 的四边几何预测在 14 帧上不一致（7 帧 scale_lateral 目标贴右缘未标 right；6 帧 target_alone 在我的 draft 上误判 bottom；1 帧 near_trunc top）。按“标注以目视+几何证据为准”采用 capture 塔几何投影的 bbox 与四边 flags 后重新生成，labels 的 truncation_source=CAPTURE_METADATA；这 14 帧记为本轮 QA 修正（不写 truncation_conflicts，因为最终标注与 capture 一致）。
- **keypoint 规则修正**：同框帧最初有 1 帧把绿 cue 当目标 keypoint；复核后统一取消同框帧 keypoint（无法无歧义归属），仅保留 target-alone/near-trunc 的 18 个 keypoint。
- **格式 QA**：labels_identity_dev.json PASS 62/62（0 error/0 warning，qa_identity.json sha256 4a8e0e574428d2adfd7665a49272d8def7f52580a61659c577e59ac3c83eea49）；labels_val.json 恢复为 163 帧后 PASS 163/163。
- **全量 pytest**：本轮运行在收集阶段被并行 teammate 的进行中测试 tests/evaluation/test_landmark_posteval.py（import landmark_posteval 尚未落盘）阻断；该文件非本任务产物，本任务未改 src/ 或 tests/。历史完整套件为 979 passed（TRAINING_20261104.md）。此状态如实记录，不写成通过。

## 6. 边界与不声明

1. 单代理 AGENT_PROXY + SELF_CHECKED，不是人类/专家独立审查；MS1 的 map probe 证据也不是人工独立审查。
2. 身份判定只用外观；目标 bbox 使用 capture 塔几何投影 + 目视核对（投影 aid），不是逐像素人工框；参考点与绿色 cue 同源（independent_of_detector_cue=false）。
3. 本批为 **DEVELOPMENT**，不 sealed、不 final、不进任何模型阈值/能力认证；合成注入（HN2 墙）不代表真实赛场分布；MS1 是 map-native 结构但不是规则保证的通用相似结构分布。
4. 62 代表帧 ≠ 169 accepted 全量；未选中帧未标注（如需全覆盖另行扩展）。full_occlusion 只标代表帧，但类型全部为 GT_UNOBSERVABLE。
5. 未用 GT 位置/oracle 区域/标签判身份；未查看 final 池标签用于本批；未 commit/push。
6. 合并由 datafreeze v4.2 执行：labels_identity_dev.json（sha256 79fd17459538aaeabf89ebe10c170eaf8f1277cfc05399300362667c0a4204b2）+ lists identity_dev_batch 段；本批不并入 labels_val.json（已恢复为 annot 完成 HN 后的 163 帧系统+HN 标签（标注行未改，仅顶层 status/note 更新，故 sha 由 8c2155… 变为 4e8e87…），sha256 4e8e877e09a8dd1c559556b87c5ae52751bce9dbf325c0238327dc8fe670f29f）。

## 7. 证据清单（sha256）

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| outputs/perception/dev_annotations_20261104/labels_identity_dev.json | identity/confuser development 标签（ignored） | 79fd17459538aaeabf89ebe10c170eaf8f1277cfc05399300362667c0a4204b2 |
| outputs/perception/dev_annotations_20261104/identity/selection_identity.json | 62 代表帧选择清单 | 944872c8a0929bb11f8ccf7e3cc64d17d9752e068821744b6fed4362669aa6af |
| outputs/perception/dev_annotations_20261104/identity/identity_decisions.json | 逐帧身份判定与 bbox/边标记 | 2fe3de0691c96360b45d01f365f6008e599989d7edc55f26c6ef51e8de5d060b |
| outputs/perception/dev_annotations_20261104/identity/identity_candidates.json | 几何候选 bbox draft（仅 bbox aid） | 084d1a16ca102a6f1fb89e33ca74d2b554579ba23648e3560305110ae160c564 |
| outputs/perception/dev_annotations_20261104/identity/identity_frame_conditions.json | 逐帧采集条件缓存 | 0ab58db4a59b78b1f75e461300b729253f3355d4ef0e3cb289b1636eec653149 |
| outputs/perception/dev_annotations_20261104/identity/qa_identity.json | v2.1 格式 QA（identity 62 帧） | 4a8e0e574428d2adfd7665a49272d8def7f52580a61659c577e59ac3c83eea49 |
| configs/perception/landmark_dev_label_lists_v1.json | 清单（identity_dev_batch 段，入 Git） | 2dceb5fca84b2e77220460b27537c6bfa99386530b985ba5fe2d7ac93e7794ca |
| outputs/perception/dev_annotations_20261104/labels_manifest.json | manifest（identity 独立文件引用） | 197f94a91b99c4a2aa9f07d3139db94f2ed0169c69d8f746d2a6857496dd9d8a |
| docs/reports/perception/capture_dev_20261104/identity_representative_frames.json | capture 62 代表帧固定规则 | c59f88e7062b2886fc6c77e165adc3a485b6c52e107c7d671a9053930433c80f |
| docs/reports/perception/capture_dev_20261104/identity_frame_conditions.json | capture 逐帧条件（四边截断/green/归属） | d8cc9d37a085079ee81384f5d79c7088bbfdf8046a2f9492aff12383e5292d69 |
| docs/reports/perception/capture_dev_20261104/identity_ms1_confuser_record.json | MS1 map-native 证据（map probe） | c95f13c5d633e679d10bc665df2835265d22baff8de3493522450021e240b952 |
| docs/reports/perception/capture_dev_20261104/identity_injection_record.json | hn2_occluder_v1 合成注入记录 | 3645177aafca5a2364c4996344ebd9f46e6fed6da977f8af2931566e2a0c577d |
| configs/scenarios/landmark_dev_identity_cases_v1.json | T15 case 定义 | e73350802a400cb1836cce14ec0c5cc278f888b6ff5e726b4692e9ac39b7a0c7 |
| outputs/perception/dev_annotations_20261104/labels_val.json | val 系统+HN 标签（163 帧，identity 未并入） | 4e8e877e09a8dd1c559556b87c5ae52751bce9dbf325c0238327dc8fe670f29f |
| outputs/perception/dev_annotations_20261104/labels_manifest.json | manifest（identity 独立文件引用） | 197f94a91b99c4a2aa9f07d3139db94f2ed0169c69d8f746d2a6857496dd9d8a |
| configs/perception/landmark_dev_label_lists_v1.json | 清单（identity_dev_batch 段） | 2dceb5fca84b2e77220460b27537c6bfa99386530b985ba5fe2d7ac93e7794ca |

## 8. 验证命令

~~~
# 选择（capture 62 代表帧）
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/rebuild_identity_selection_capture.py
# QA 表 + 判定 + 标签
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/render_identity_qa.py --cases configs/scenarios/landmark_dev_identity_cases_v1.json --out outputs/perception/dev_annotations_20261104/identity
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/make_identity_decisions.py
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/build_identity_labels.py
& E:\isaac\env_isaaclab\Scripts\python.exe scripts/validate_landmark_annotations.py --annotations outputs/perception/dev_annotations_20261104/labels_identity_dev.json --root . --overlay-dir outputs/perception/dev_annotations_20261104/identity/overlays --output outputs/perception/dev_annotations_20261104/identity/qa_identity.json
# 独立发布：恢复 labels_val 163 帧、刷新 manifest、patch lists
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/publish_identity_dev.py
~~~
