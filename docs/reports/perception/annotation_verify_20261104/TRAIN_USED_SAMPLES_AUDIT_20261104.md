# 候选 A 训练实际使用标注样本审计 + holdout 标注预置（2026-11-04）

> **状态：** AUDIT_COMPLETED / PROVISIONAL（工程与数据审计；不是模型效果、板端或导航验收；不提升任何 Gate）
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §7.5/§9.1/§20.11；证据口径引 configs/perception/landmark_improvement_gate_v1.json 与 landmark_improvement_protocol_v1.json（status CLOSED_STOP_GATE_NOT_MET，holdout NOT_TRIGGERED）
> **证据域：** 训练数据集文件级审计（outputs/landmark_train/dataset/dev_v4_1，ignored）+ 训练运行参数/证据（ignored）+ 标注规范 v2.1；无模型推理、无板端/SITL/实飞；本任务未启动 Isaac
> **最后核对：** 2026-11-04（仓库 E:\isaac\proj_boom_birds，分支 feat/v2.2-simulation-perception，HEAD 3491cde；本任务未 commit/push）

## 0. 结论先行

1. **候选 A 实际训练输入已核实**：候选 A 为 DATA 候选（把旧 exploratory 279 帧注册为 reuse-development 并入 TRAIN），训练运行 data=outputs/landmark_train/dataset/dev_v4_1/data.yaml、epochs 15、batch 16、imgsz 640、seed 0、pretrained yolov8n-pose.pt、patience 15（bounded_evidence: epochs_completed=15，status BOUNDED_TRAINING_DEV_VALIDATION_ONLY）。该数据集 **436 张图 / 436 个 YOLO 标签文件 / 439 条合并标注**（160 dev + 279 reuse）。
2. **逐图对应与内容核验 0 差异**：436/436 图像均有一一对应的标签文件；0 张"训练用了但无标签"；0 个标签文件无图像；343 个正例标签、93 个空负例标签与注解一致；对全部 436 张导出图逐项比对 YOLO txt（bbox 中心/宽高源图归一化、keypoint、v）与合并注解 → **0 mismatch**；sidecar included_in_training=true 436 / false 3。
3. **"清单有但训练未用" = 3 帧（唯一差异）**：dev_south_new-follow_only_g1_168、dev_south_new-follow_only_g1_170、sensor_reset_1-follow_only_g6_193 —— 均为 T8 阶段判为 presence 不可判定（ANNOTATOR_UNDECIDABLE 边缘 sliver）的帧，sidecar 标 exclusion_reason=UNDECIDABLE、label_kind=EXCLUDED，未导出图像/标签。**"训练用了但无标签" = 0**。
4. **与 dataset_build 计数存在两处口径差异（审计发现，不是数据错误）**：(a) dataset_build 的 reference_available/unavailable=274/69 分母是 343 个正例标签，不是全部 439 条注解；全注解口径为 274 available / 165 unavailable（69 正例无参考点 + 93 空负例 + 3 排除）。(b) dataset_build 的 gt_unobservable=3 实为上述 3 个 undecidable 排除帧在训练 sidecar 里记 gt_unobservable=true(reason=UNDECIDABLE) 的簿记结果，**train 合并标签中 visibility=OCCLUDED 的帧为 0**；不得把这 3 帧引用为 GT_UNOBSERVABLE 覆盖。
5. **尺度分桶**（bbox 面积 px²：TINY≤1500、SMALL≤5000、MEDIUM≤15000、LARGE>15000）：TINY 86、SMALL 120、MEDIUM 110、LARGE 27（另有 96 条非正例/排除）；全部正例 343。**LARGE 27 帧全部来自 reuse-development；dev_train 自身 LARGE=0**（与候选 A 的 DATA 诊断一致）。
6. **近距 LARGE / 边缘截断 / 绿灯参考可用计数（②）**：LARGE 27 帧（占正例 7.9%），其中截断 26、参考可用 27；截断正例共 57 帧（left 9/right 24/bottom 42/top 0），其中参考可用 56（98.2%）。绿灯参考可用正例 274/343=79.9%；**TINY 参考可用仅 21/86=24.4%**，是 bearing-primary 口径的主要缺口。train 中 verified confuser=0、map-native MS1 verified=0、synthetic injected=0（仅 6 个 unverified green-blob confuser）、ambiguous 标注=0、GT_UNOBSERVABLE=0。
7. **holdout 标注预置（③）已就绪但未触发**：holdout_annotation_spec_v1.json 在无任何 holdout 数据前冻结（触发条件、采集要求、分层抽样与配额、v2.1 标注口径、QA 门、边界）；prepare_holdout_batch.py 可做族内近重复→medoid→分层系统抽样+强制覆盖、泄漏检查、覆盖率矩阵与 QA 接触表；audit_holdout_batch.py 为 PASS 门（schema/1:1/配额/分片/访问日志）。按 lead 指示新增冻结分片规则：annot2=shard_A、annot=shard_B，族内按 sequence 交替分配，每族每 7 帧取 1 帧双标做一致性对照（只做一致性检查，lead 仲裁；不称第三方独立）。当前 protocol 结果为 STOP、holdout NOT_TRIGGERED，**未做任何 holdout 预标注**。
8. **基线维护**：labels_val_validation163.json（sha a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144）与 labels_identity_dev.json（sha 79fd17459538aaeabf89ebe10c170eaf8f1277cfc05399300362667c0a4204b2）本轮未改；labels_val.json 仍 163 帧（sha 4e8e877e09a8dd1c559556b87c5ae52751bce9dbf325c0238327dc8fe670f29f）；lists（sha 2dceb5fca84b2e77220460b27537c6bfa99386530b985ba5fe2d7ac93e7794ca）未改。本任务未写 train 正在使用的文件。

## 1. 审计输入与 provenance

| 输入 | 值 |
| --- | --- |
| 候选 A 运行参数 | outputs/landmark_train/runs/improvement_v4/candidateA_pilot15_seed0/seed0/args.yaml（data=dev_v4_1/data.yaml、epochs 15、batch 16、imgsz 640、seed 0、pretrained yolov8n-pose.pt、patience 15），sha256 3091781fc65c1646df7702174c754b75cf6dd4df1b2a4791966badd71df31df5 |
| 候选 A evidence | bounded_evidence_seed0.json：epochs_completed 15、status BOUNDED_TRAINING_DEV_VALIDATION_ONLY，sha256 bee9533add7bcf70ac46d3a2ca3a965f1682839e5fae52bbe8b233e7fc2666e3 |
| 合并标注 | labels_train_v4_1_merged.json（439 帧：dev 160 + reuse 279），sha256 c936da6bfb126cb668825e3091117dc752311c9207fcc66b32691c608e61f187 |
| 数据集构建 | dev_v4_1/dataset_build.json，sha256 2ac8fb387111d9e493a3d1bddfb475fdef581df4d9d9eefa8a7bab3ea8d43a76 |
| data.yaml | dev_v4_1/data.yaml，sha256 c15cb2d2052f7a8a78a18c0877dbe73f494a437428bd41eff3a9b673e823dcf3（train=images/train、val=images/val、kpt_shape=[1,3]） |
| 训练 sidecar | dev_v4_1/sidecars/train_sidecar.jsonl，sha256 b1ce4e49be770f450a28bcc41d0b5c4aef1564d0577481ce540b210f3e38e5ae |
| v4.1 冻结 | configs/perception/landmark_split_freeze_v4_1.json，sha256 531565a25d77d4d1bf3cc3292c55fc9ee4dda23a36280e0ce63ecd01f67f8923 |
| 改进门/协议 | gate sha256 7c81ae51c003d4a0271fcb8284a6edbedd3267d103cbb923c87d2ab4c0bddd38；protocol sha256 1cac7caa3fddf423f60b36cbba014b4b0e53cfaa329f9b1d4d86ef80b9a43164（status CLOSED_STOP_GATE_NOT_MET，outcome STOP，complete_trainings_used=1/4，holdout NOT_TRIGGERED） |

## 2. ① 训练实际使用样本与差异

### 2.1 文件级对应

| 检查 | 结果 |
| --- | --- |
| 训练图像 | 436（images/train/*.png） |
| 标签文件 | 436（labels/train/*.txt） |
| 合并标注 | 439 |
| 图像缺标签 | 0 个 |
| 标签缺图像 | 0 个 |
| 有图像无注解 | 0 个 |
| 有注解无图像（清单有但训练未用） | 3 个：dev_south_new-follow_only_g1_168、dev_south_new-follow_only_g1_170、sensor_reset_1-follow_only_g6_193 |
| sidecar included_in_training | true 436 / false 3（reason: {"UNDECIDABLE":3}） |
| 标签内容逐图核验 | 436/436 检查；正例 mismatch 0；正/空类型 mismatch 0 |

### 2.2 计数核对（合并注解 vs dataset_build）

| 项 | 逐注解重算 | dataset_build | 说明 |
| --- | ---: | ---: | --- |
| frames | 439 | 439 | 一致 |
| positive_labels | 343 | 343 | 一致（bbox 有效且非 GT_UNOBSERVABLE） |
| negative_empty_labels | 93 | 93 | 一致 |
| excluded | 3 | 3 | 一致（3 帧 undecidable） |
| reference_available | 274 | 274 | 一致（274） |
| reference_unavailable | 165 | 69 | **口径差异**：重算=全 439 条（165），dataset_build=正例分母 343（69） |
| gt_unobservable | 0 | 3 | **口径差异**：重算=合并标签 visibility=OCCLUDED（0），dataset_build 把 3 个 undecidable 排除帧的 sidecar 簿记计入 |
| truncated | 57 | 57 | 一致（57） |
| undecidable / ambiguous | 3 / 0 | 3 / 0 | 一致 |

### 2.3 差异结论

- **清单有但训练未用 = 3 帧（全部 expected & explained）**：presence 不可判定（T8 边缘 sliver 判定），sidecar 显式 UNDECIDABLE/EXCLUDED，未导出；属"排除"而非数据丢失。
- **训练用了但无标签 = 0**；**标签与注解不一致 = 0**（bbox 中心/宽高、keypoint、v 全部源图归一化且逐图核验）。
- 训练 sidecar 的 gt_unobservable 字段在这 3 帧上为 true(reason=UNDECIDABLE)，只作排除簿记；报告/下游不得据此声称训练集含 GT_UNOBSERVABLE 覆盖（train 合并标签中 OCCLUDED=0）。

## 3. 数据构成（来源 / 尺度 / 截断 / 参考）

### 3.1 来源（dev vs reuse）

| 来源 | frames | positive | truncated | reference_available |
| --- | ---: | ---: | ---: | ---: |
| dev_train | 160 | 105 | 9 | 56 |
| reuse_development | 279 | 238 | 48 | 218 |

### 3.2 尺度桶 × 来源

| 来源 | TINY | SMALL | MEDIUM | LARGE | NONE |
| --- | ---: | ---: | ---: | ---: | ---: |
| dev_train | 52 | 28 | 25 | 0 | 55 |
| reuse_development | 34 | 92 | 85 | 27 | 41 |

### 3.3 尺度桶 × 正例/截断/参考可用

| bucket | frames | positive | truncated | reference_available |
| --- | ---: | ---: | ---: | ---: |
| TINY | 86 | 86 | 2 | 21 |
| SMALL | 120 | 120 | 7 | 116 |
| MEDIUM | 110 | 110 | 22 | 110 |
| LARGE | 27 | 27 | 26 | 27 |

### 3.4 family 分布（前 13）

| family | fused annotations |
| --- | ---: |
| lmf_sweep | 111 |
| fam_south_A | 110 |
| lmf_backoff | 76 |
| lmf_similar_negative | 38 |
| lmf_edge | 28 |
| lmf_near | 23 |
| fam_dev_inner_south | 20 |
| fam_dev_static_high | 12 |
| fam_dev_static_negative | 8 |
| fam_static_E_test | 5 |
| fam_static_E_dev | 3 |
| lmf_side_negative | 3 |
| fam_static_W_start | 2 |

## 4. ② 近距 LARGE / 边缘截断 / 绿灯参考可用：实际计数与缺口

| 指标 | 分子/分母 | 结果 |
| --- | --- | --- |
| LARGE 正例 | 27/343 正例 | 7.9%（27 帧） |
| LARGE 截断 | 26/27 LARGE | 96.3% |
| LARGE 参考可用 | 27/27 LARGE | 100% |
| 截断正例 | 57/343 正例 | 16.6%；edges left 9/right 24/bottom 42/top 0 |
| 截断+参考可用 | 56/57 截断帧 | 98.2% |
| 参考可用（全正例） | 274/343 正例 | 79.9%（正例无参考点 69） |
| TINY 参考可用 | 21/86 TINY | 24.4% |
| SMALL/MEDIUM 参考可用 | 116/120、110/110 | 96.7% / 100% |

**缺口（如实）**：
1. **dev_train 自身 LARGE=0**：27 个 LARGE 正例全部来自 reuse-development（旧 exploratory 池）；候选 A 的数据改动确实改变了 LARGE 覆盖，但"新采集的近距大目标"仍为 0，近距数据来源单一（同池分布风险）。
2. **TINY 参考可用仅 21/86=24.4%**：TINY 正例大多无 keypoint（REFERENCE_TOO_SMALL），这是 bearing-primary 口径的主要缺口；训练 joint 分母若含 TINY 定位会不可判。
3. **截断覆盖集中在 LARGE/MEDIUM（26/22）而 SMALL/TINY 仅 7/2；top 边截断=0**（当前数据无上缘截断样本）。
4. **verified 真实 map confuser = 0**：train 仅 6 个 unverified green-blob confuser；map-native MS1 verified、synthetic injected 均 0（HN1 27 在 val），没有可用于"真实相似结构"训练/评测的 train 帧。
5. **ambiguous 标注=0、GT_UNOBSERVABLE=0**（train）：无同框歧义与完全遮挡训练样本；这些只在 val/HN、identity val 出现。

## 5. ③ holdout 标注工具与规范预置（未触发）

### 5.1 冻结内容（在任何 holdout 数据之前）

- 权威冻结：configs/perception/landmark_holdout_freeze_v2.json（sha256 6d24e26f0ebfcee7a048a1522d4a181a64f5b971c8101fc81855e9c6c3bcb1ca，status SPEC_FROZEN_NOT_TRIGGERED，datafreeze T28）；本预置规范是其实现 annex（工具契约/分片/访问日志），覆盖配额严格对齐 v2 required_conditions，不重定义覆盖下限。
- 规范：outputs/perception/dev_annotations_20261104/holdout_tools/holdout_annotation_spec_v1.json（sha256 7f9215b0c55fc73d6ab5aaa7f065a7c67bfdc783e0f3760595fc0943f23d6ce7），status PREINSTALLED_PENDING_TRIGGER_NOT_STARTED。
- 触发：仅当预注册 development-to-holdout gate 通过（3 seed 选中候选 + lead 明确触发 + 可见前台 GUI）；当前 protocol 为 STOP/CLOSED_STOP_GATE_NOT_MET、holdout NOT_TRIGGERED，故不采集、不预标注。
- 采集要求：≥3 新族 / 200–400 帧；覆盖 small target、close-range truncation、target absent、real map confuser、same-frame ambiguity；禁用 headless 与检测器分数选帧。
- 抽样：族内近重复聚类（dHash64 Hamming≤6 且 64×48 灰度 MAD≤3.0）→ medoid → midpoint 系统抽样 + 强制分层覆盖；配额严格对齐 v2：near_range_large_target 40、far_small_target 40、edge_truncation 30、ms1_confuser_alone 30、same_frame_ambiguity 30、target_absent 30（sum=200 最小标注帧；条件定义以 v2 为准）。
- 标注：spec v2.1 + bearing-primary keypoint 域（TINY/<3px 无 keypoint）、外观 gated identity、confuser verified（MS1=WORLD_POSE_OR_MAP_DB；synthetic=EXTERNAL_EVIDENCE+SYNTHETIC_INJECTED）、GT_UNOBSERVABLE、undecidable、四边截断、冲突记录。
- QA PASS 门：validator 0 error/0 warning、selection↔label 1:1、冻结配额、分片审计、访问日志完整、泄漏检查 0。

### 5.2 分片与分工（lead 2026-11-04 指示，已冻结进 spec）

- annot2=shard_A、annot=shard_B；规则 holdout_shard_roundrobin_stratified_v1：族内按 sequence 交替分配；每族每 7 帧取 1 帧双标做一致性对照（lead 仲裁），overlap 只做一致性检查、不称第三方独立。
- 访问记录：holdout_access_log_template.json（annotator/frame_id/purpose/viewed_at_utc/spec sha/selection sha/decision sha），交付时冻结并写入审计。
- 声明边界：同代理冻结规范下只能称流程隔离 + hash 承诺，不是第三方封存、不是认证级；认证仍需 ≥2 独立人工标注 + 仲裁。

### 5.3 工具与自测

- prepare_holdout_batch.py（sha256 359c4149dca2ab557f555668db77db14c06afef7e50ad0284f0277407282ac42）：触发检查（无 TRIGGERED 文件拒绝）、分组、近重复聚类、分层抽样、泄漏检查（与全部既有 exposed sha 比）、覆盖率矩阵、原生 4×3 QA 接触表、decisions 模板、分片与访问日志模板。
- audit_holdout_batch.py（sha256 2a0bbb4f04e99aa91730bbc2503ebbc14f06dcc98255dd1c74efd5bbb4a50232）：v2.1 校验、1:1 帧集、四状态计数与分母、冻结配额、分片分割/覆盖/访问日志、PASS/FAIL 门（FAIL 时退出码 1）。
- self-test（仅验证代码路径，SELFTEST_NOT_HOLDOUT）：以 identity 采集为替身 → 68 帧、34/34 分片、14 帧 overlap；泄漏检查正确报出 62 个既有 sha 重叠、配额 gaps 正确报告（工具在真实 holdout 会 fail-loud，而非静默通过）。

## 6. 测试与跨任务状态

- 本轮 pytest（在 lead 暂停重负载要求之前完成）：**1086 passed / 3 failed（398.66s）**，3 个失败均为 HEAD 3491cde 的既有/并行状态，不是本任务新增代码：
  1. tests/evaluation/test_landmark_consumer_eval.py::test_success_requires_presence_identity_reference_and_bearing（identity_correct 期望 False 实为 True）
  2. tests/evaluation/test_landmark_consumer_eval.py::test_summarize_reports_three_domains_and_rates（all_positive success 期望 2 实为 1）
  3. tests/evaluation/test_landmark_dataset.py::test_exposure_registry_v2_downgrades_old_final_to_development（EXPOSURE_EVIDENCE_SHA_MISMATCH: ev_identity_cases_capture_20261104 evidence hash changed: configs/scenarios/landmark_dev_identity_cases_v1.json；registry 期望 e7335080…，现场文件为 861cbec170c4cce22e75da5412f749fd116e2efaabbb4e0131def5d3d36a133d）
- exposure registry 不一致属 datafreeze/capture 的跨任务登记问题（本任务未修改该 config），供 v4.2/v5 刷新 registry 时处理；consumer-eval 两项属并行消费者协议工作，本任务未改 src/tests。

## 7. 边界与不声明

1. 本审计只证明"候选 A 训练实际读取的文件与标签对应关系"，不证明标签正确性、不证明模型效果；标签为 AGENT_PROXY+SELF_CHECKED（非人工独立）。
2. 尺度桶/参考可用性按 bbox 面积与 spec v2.1 字段计算；不是物理距离/ToF 结论。
3. holdout 工具仅为预置；当前未触发、无 holdout 数据、无 holdout 标签；不得引用 self-test 结果作 holdout 证据。
4. 未使用旧 final/exploratory 预测或阈值做本审计选择；未 commit/push；未启动 Isaac/训练/控制/PPO；未提升 Gate。
5. 未修改 train 正在使用的文件（labels_val.json、validation163、identity、lists 的 sha 与本任务开始时一致）。

## 8. 证据清单（sha256）

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| outputs/perception/dev_annotations_20261104/TRAIN_USED_SAMPLES_AUDIT_20261104.json | T27 机器可读审计结果 | ea494a018ad6580502038315bcef94adfa84b36deb3d83e5743cc3bc1552b83a |
| outputs/landmark_train/dataset/labels_train_v4_1_merged.json | v4.1 合并 train 标注（439） | c936da6bfb126cb668825e3091117dc752311c9207fcc66b32691c608e61f187 |
| outputs/landmark_train/dataset/dev_v4_1/dataset_build.json | 训练数据集构建证据 | 2ac8fb387111d9e493a3d1bddfb475fdef581df4d9d9eefa8a7bab3ea8d43a76 |
| outputs/landmark_train/dataset/dev_v4_1/data.yaml | 候选 A 实际 data 配置 | c15cb2d2052f7a8a78a18c0877dbe73f494a437428bd41eff3a9b673e823dcf3 |
| outputs/landmark_train/dataset/dev_v4_1/sidecars/train_sidecar.jsonl | 逐帧训练使用/排除 sidecar | b1ce4e49be770f450a28bcc41d0b5c4aef1564d0577481ce540b210f3e38e5ae |
| outputs/landmark_train/runs/improvement_v4/candidateA_pilot15_seed0/seed0/args.yaml | 候选 A 运行参数 | 3091781fc65c1646df7702174c754b75cf6dd4df1b2a4791966badd71df31df5 |
| outputs/landmark_train/runs/improvement_v4/candidateA_pilot15_seed0/bounded_evidence_seed0.json | 候选 A bounded evidence | bee9533add7bcf70ac46d3a2ca3a965f1682839e5fae52bbe8b233e7fc2666e3 |
| configs/perception/landmark_split_freeze_v4_1.json | v4.1 划分冻结 | 531565a25d77d4d1bf3cc3292c55fc9ee4dda23a36280e0ce63ecd01f67f8923 |
| outputs/perception/dev_annotations_20261104/holdout_tools/holdout_annotation_spec_v1.json | 预置 holdout 规范（含分片规则） | 7f9215b0c55fc73d6ab5aaa7f065a7c67bfdc783e0f3760595fc0943f23d6ce7 |
| outputs/perception/dev_annotations_20261104/holdout_tools/prepare_holdout_batch.py | holdout 批次准备工具 | 359c4149dca2ab557f555668db77db14c06afef7e50ad0284f0277407282ac42 |
| outputs/perception/dev_annotations_20261104/holdout_tools/audit_holdout_batch.py | holdout 标注审计/PASS 门工具 | 2a0bbb4f04e99aa91730bbc2503ebbc14f06dcc98255dd1c74efd5bbb4a50232 |
| outputs/perception/dev_annotations_20261104/holdout_tools/README.md | holdout runbook + 分工/触发规则 | 9018b14cf3c962757dcdce2a804a6ebbb98133d1d07f2f55137f38534014858b |
| outputs/perception/dev_annotations_20261104/holdout_tools/_selftest/holdout_shards.json | 分片工具 self-test 输出（SELFTEST_NOT_HOLDOUT） | 1131682955bda9d0d373b4c7d2c73ade29ba2898af384d54229131a50f4bd271 |
| configs/perception/landmark_holdout_freeze_v2.json | 权威 holdout 冻结规范（datafreeze T28，SPEC_FROZEN_NOT_TRIGGERED） | 6d24e26f0ebfcee7a048a1522d4a181a64f5b971c8101fc81855e9c6c3bcb1ca |
| outputs/perception/dev_annotations_20261104/labels_val_validation163.json | train 稳定读取 VALIDATION 163 基线（未改） | a9bfda8fc39b7f895521b0aafc459648c79a96ad123a82d0e0949c334705d144 |
| outputs/perception/dev_annotations_20261104/labels_identity_dev.json | identity 独立标签（未改） | 79fd17459538aaeabf89ebe10c170eaf8f1277cfc05399300362667c0a4204b2 |
| configs/perception/landmark_dev_label_lists_v1.json | 清单（未改） | 2dceb5fca84b2e77220460b27537c6bfa99386530b985ba5fe2d7ac93e7794ca |
| outputs/perception/dev_annotations_20261104/TRAIN_USED_SAMPLES_AUDIT_20261104.json | T27 机器可读审计（本报告数字来源） | ea494a018ad6580502038315bcef94adfa84b36deb3d83e5743cc3bc1552b83a |

## 9. 验证命令

~~~
# 训练使用样本审计（本报告 §2–§4 数字）
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/audit_train_used_v4_1.py
# holdout 工具自测（不产生 holdout 证据）
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/holdout_tools/prepare_holdout_batch.py --cases configs/scenarios/landmark_dev_identity_cases_v1.json --sensor outputs/sensor_shadow/lm_dev_identity_capture_20261104_sensor --conditions docs/reports/perception/capture_dev_20261104/identity_frame_conditions.json --out outputs/perception/dev_annotations_20261104/holdout_tools/_selftest --self-test --per-case-cap 10 --total-cap 100
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/holdout_tools/audit_holdout_batch.py --annotations outputs/perception/dev_annotations_20261104/labels_identity_dev.json --selection outputs/perception/dev_annotations_20261104/holdout_tools/_selftest/selection_holdout.json --conditions outputs/perception/dev_annotations_20261104/holdout_tools/_selftest/holdout_frame_conditions.json --shards outputs/perception/dev_annotations_20261104/holdout_tools/_selftest/holdout_shards.json --access-log outputs/perception/dev_annotations_20261104/holdout_tools/_selftest/holdout_access_log_template.json --out outputs/perception/dev_annotations_20261104/holdout_tools/_selftest/holdout_audit_selftest.json
# 全量单测（HEAD 3491cde 结果：1086 passed / 3 failed，失败清单见 §6；当前 lead 要求暂停重负载，未在暂停期内重跑）
& E:\isaac\env_isaaclab\Scripts\python.exe -m pytest -q
~~~
