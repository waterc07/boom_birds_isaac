# 当前进度与接手续查（2026-11-05）

本页汇总仓库内已交付能力与证据边界。设计正文仍为 [V2.2 架构](../design/RMUC2027_UAV_V2_2.md)，本页不修改其合同或放行任何 Gate。正文中的开工时实现状态、早期计划和历史交接应按日期阅读，不能代替当前源码和后续修订。

## 当前结论与下一步（2026-11-05）

地标单类有界训练、阶段门勘误及 two-class 身份通道实验已完成归档。旧 3px 协议候选 A 三 seed 的 holdout 门通过，但消费者协议身份通道未通过；随后 two-class R1/R2 两次 pilot 均未通过 pilot→3seed 门，two-class 本版 STOP，未进入三 seed 完整训练，未触发新 holdout。R2 pilot ONNX 三路径对齐仅为诊断性工程证据（NOT_SELECTED_VALIDATED_PILOT_ONLY / DIAGNOSTIC_ONLY_NOT_GATE），不是效果、身份或板端验收。

当前工作包已封闭。如继续 two-class，须另立工作包，重新预注册 same-frame 联合监督、reference availability guard、负例/不可观测 claim 约束及新预算与不可变快照；不自动追加训练。内部有界研究授权有效，对外分发另行决策。感知保持 shadow；PX4 Sender、板端 Student、项目 PPO、真实相机及各 BB22 Gate 均未完成验收。

最新依据：[two-class 结果](perception/LANDMARK_TWO_CLASS_RESULTS_20261105.md)、[交接](HANDOFF_20261105_TWO_CLASS.md)。下方日期化实验记录保留其当时状态，不能替代本节当前结论。

## 已实现与证据入口

| 层次 | 已交付范围 | 主要证据与适用边界 |
| --- | --- | --- |
| 软件合同 | 四级上下文、时钟/模拟飞控身份、消息溯源、不可续期 TTL、动作接纳及所有权合同 | [G2.6 报告](g2_6/G2_6_CONTRACTS_REPORT.md)；不是实际 PX4 Sender，G2.6 整体仍 INCOMPLETE |
| 仿真执行与评价 | 速度外环至 PhysX、到点、传统制导比较、episode 边界修复及历史污染审计 | [干净基线](eval_audit/CLEAN_BASELINE_REPORT.md)、[分层评价修订](c_diagnosis/C_DIAGNOSIS_REPORT.md)；不等于训练或实机能力 |
| 地图与动态监督 | RMUC2027 配置引用、局部路线、停止/等待/恢复、v2 执行与故障后物理观测 | [路线](map_eval/MAP_ROUTES_REPORT.md)、[v2 执行](map_eval/MAP_V2_EXEC_REPORT.md)、[制动](map_eval/MAP_BRAKE_ENVELOPE_REPORT.md)；ORACLE 状态、运动学障碍、当前仿真模型 |
| 延迟和净空 | 到达队列、模拟双时钟、clearance 字段化、有限制动支持区间 | [延迟](map_eval/MAP_LATENCY_ENVELOPE_REPORT.md)、[边界](map_eval/MAP_CLEARANCE_BOUNDARY_REPORT.md)；旧结果的验收变更和包络修正须一并阅读 |
| 单环境接触评价 | hard reset、分离握手、generation、原始向量 L2 读出、真实碰撞几何包络；新模式已成为单环境动态入口默认 | [自由飞行阳性](map_eval/contact_envelope/DSH_FREE_FLIGHT_POSITIVE_20261103.md)、[默认升级](map_eval/contact_envelope/DSH_DYNAMIC_DEFAULT_UPGRADE_20261103.md)；零测力仍 UNKNOWN，传送后陈旧力未做底层修复 |
| 模拟传感器 | 渲染 RGB/深度、v2 消息溯源和 shadow 消费 | [采集](map_eval/contact_envelope/DSH_SENSOR_SHADOW_20261103.md)、[统计与时间勘误](map_eval/contact_envelope/DSH_SENSOR_SHADOW_ERRATA_20261103.md)；SIM_UPDATE_SAMPLE_TIME 不是真实曝光时间，单像素深度不是 ToF 或目标距离 |
| 自然地标感知 | 模板和几何/绿灯消费者已完成有界实验，均停止作为当前主候选；训练前任务定义、数据准备、标注可用性、许可证据闭环到准入判定；**2026-11-04 二阶段完成有界训练与一次性 exploratory 评价（效果门未达）** | [独立测试](perception/DSH_LANDMARK_INDEPENDENT_20261103.md)、[根因审查](perception/DSH_LANDMARK_ROOT_CAUSE_20261103.md)、[几何方法](perception/DSH_GEOMETRY_GREEN_20261104.md)、**[训练准入结论](perception/TRAINING_ADMISSION_20261104.md)**；软件交付完成，感知/导航能力未达标，不进入地标关联控制 |

## 地标训练前闭环（2026-11-04 工作包）

- 判定：整体 **INCOMPLETE**，训练启动 **BLOCKED**（A1 许可需用户决策；A3/A4/A6/A8 未闭合）。本轮未安装训练依赖、未下载模型、未启动训练、未改 Isaac 环境；所有 Isaac 运行均为可见前台 GUI。
- 任务/实验定义：[训练前任务与实验定义](perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md) + [训练协议 v2](../../configs/perception/landmark_training_plan_v2.json)：类别检测与 landmark_id 分离、唯一性假设、HN1–HN6、M1–M6 拒绝、presence/reference/identity/joint 分母、warmup 15 / patience 20、三 seed 仅验证集选模 + 阈值冻结 + 一次性 final 不回调。分母规则已落到 [landmark_metrics.py](../../src/boom_birds/evaluation/landmark_metrics.py) 与 [测试](../../tests/evaluation/test_landmark_metrics.py)。
- 数据：实际暴露 13 目录/3002 帧/2909 accepted（旧 inventory 漏列 9 目录/1300 帧）；[dev 划分冻结 v2](../../configs/perception/landmark_split_freeze_v2.json) train 7 组 1320 帧 / val 3 组 575 帧 / excluded 9 组 1107 帧，机制互斥但 held-out 仅北走廊一条 family（INCOMPLETE）；[final 池封存](../../configs/perception/landmark_final_pool_seal_v1.json) 6 新族/297 RGB/279 accepted，与既有数据 0 sha 重叠；完整语义标签 PENDING。证据见 [数据冻结报告](perception/dataset_freeze_20261104/DATASET_SPLIT_AND_LEAKAGE_20261104.md)、[final 池封存报告](perception/dataset_freeze_20261104/FINAL_POOL_SEAL_20261104.md)、[采集报告](perception/capture_20261104/CAPTURE_20261104.md)。
- 标注：盲复标 21 帧/33 旧记录，bbox IoU 0.649、绿灯 keypoint 1.155 px（0.414°）、不可判定 19.0%、visibility 5/21 分歧；旧 .036° anchor 被证实为同源绿色质心循环证据；规范缺口升 [spec v2](../../configs/perception/landmark_annotation_spec_v2.json)。final 池试点标注 34/279 帧（25 正/9 负）v2 校验 **PASS 34/34**，暴露 P1–P3 三项可执行性缺口 → 完整标签前先出 spec v2.1。见 [标注可用性报告](perception/annotation_verify_20261104/ANNOTATION_VERIFICATION_20261104.md) 与 [试点标注报告](perception/annotation_verify_20261104/FINAL_POOL_PILOT_ANNOTATION_20261104.md)。
- 许可/部署：[证据清单](perception/license_evidence_20261104/LICENSE_AND_EXPORT_EVIDENCE_20261104.md)：AGPL-3.0 原文确证、AGPL 义务/权重衍生未决、RKNN-Toolkit2 为专有许可、RTX 5080 sm_120 与 torch 2.7.0+cu128 有证据、自定义 1-keypoint ONNX/RKNN 路径 UNKNOWN；不擅自认定接受 AGPL、不自动切备选。
- 需用户决定的最少事项：许可路线；final 标注与开发的独立性/是否投入 ≥2 独立人工标注；原始数据外部备份。详见 [训练准入结论 §8](perception/TRAINING_ADMISSION_20261104.md)。

## 地标探索实验执行（2026-11-04 二阶段）

- 结果：**链路全部跑通、模型效果未达计划门限、认证未完成**。详见 [探索实验结果](perception/LANDMARK_EXPLORATORY_RESULTS_20261104.md) 与 [训练执行报告](perception/training_20261104/TRAINING_20261104.md)。
- 数据：[dev v3](../../configs/perception/landmark_split_freeze_v3.json)（train 10 组/train 1475 帧、val 7 组/816 帧含 HN1/HN2）、[暴露登记](../../configs/perception/landmark_exposure_registry_v1.json)（26 exposed / 6 exploratory / 0 untouched）、final 6 族整体 exploratory；泄漏审计 0；外部产物 3695 帧可读/hash 一致。
- 标注：[spec v2.1](../../configs/perception/landmark_annotation_spec_v2_1.json) FROZEN；dev train 160/val 134 帧、final exploratory 279 帧完整标注（代理标注，非人工独立）；U1/U2 唯一性假设被 map-native 绿灯相似结构 MS1 证伪。
- 训练：隔离 `.venv/landmark-train`（torch 2.7.0+cu128/ultralytics 8.2.0）；3 seed × 60 epoch；val joint 0.484/0.579/0.442 → 选中 seed1；[模型/阈值冻结](../../configs/perception/landmark_model_freeze_v1.json)（tau_conf 0.605476，仅 val）。
- 一次性 exploratory final（279 帧，只读一次）：presence TP218/FP0/FN20/TN41（P1.000/R0.916）、reference coverage 62/218=0.284、joint 71/238=0.298、identity P1.000（池内无已验证 HN1，不作认证）；anchor 正确子集中位 1.95 px / bearing 0.30°；最差 lmf_near joint 3/23。
- 工程发现：YOLO 标签坐标域 bug（模型画布归一化误写 txt）已用 loader 复现并修复，旧 30 epoch 运行判 INVALID；ONNX opset18 主机数值一致；RKNN/板端 UNKNOWN/NOT RUN。
- 认证缺口：许可分发、独立人工标注、未触碰 sealed final、false-match 分母、RK3576 板卡、真实相机/场地、重复性——C1–C8 多数 INCOMPLETE/UNKNOWN。

## 地标失败诊断与有界改进实验（2026-11-04 三阶段）

- 结论：**STOP**（预注册 gate 未过）；旧 exploratory 结果保留、不重跑；旧 3px 口径保留，新 bearing/四项分离口径单列。详见 [诊断与改进结果](perception/LANDMARK_DIAGNOSIS_AND_IMPROVEMENT_RESULTS_20261104.md)。
- 诊断：[post-eval 报告](perception/posteval_20261104/POSTEVAL_DIAGNOSIS_20261104.md)：reference 失败 = 119 错误锚点（88/119 纵向为主）+ 28 kpt 抑制 + 9 漏检；主瓶颈是 2D 定位精度，不是横向 bearing（87 帧 2D>3px 但 bearing≤1.074°）；TINY 9–14px 盲标 presence 0.364、正例 12/12 undecidable；MS1 证伪 U1/U2。
- 评价定义：[EVAL_DEFINITION_AUDIT](perception/EVAL_DEFINITION_AUDIT_20261104.md)：四项分离、joint 双分支（LOCALIZED 62/218 + CORRECT_REFUSAL 9/20 + FAIL_PRESENCE 20 + FAIL_REFERENCE 147）；预测 UNKNOWN/漏检/错误身份不消失；GT 不可观测单列。
- ONNX：三路径共享预处理 0 决策翻转（126 帧）；旧 4.67px 差异=legacy letterbox 模式不同（17 observation/18 joint 翻转），不是导出错误；RKNN/板端 UNKNOWN。
- 改进实验：[IMPROVEMENT](perception/training_20261104/IMPROVEMENT_20261104.md)：候选 A（近距/远景复用帧入 train）pilot joint 0.453 vs baseline 0.379（Δ+0.074<+0.08、joint<0.60）；候选 B（tau_kpt 标定）无改善且 false_reference 变差 → **FAIL/STOP**；完整训练用 1/4，不触发 holdout（[holdout freeze](../../configs/perception/landmark_holdout_freeze_v1.json) NOT_TRIGGERED）。
- 数据：dev v4/v4.1/v4.2（HN 53/53、identity 7 组 62 帧标注、旧 exploratory 登记 DEVELOPMENT_TRAIN）；[暴露登记 v2](../../configs/perception/landmark_exposure_registry_v2.json)：39 组全部 exposed_development、0 untouched；泄漏审计 0。
- 工程：训练/停止器/阈值/导出/parity/重算脚本已入库并有 CLI+配置；标签漂移首轮 eval 判 INVALID 并记录。
- 路线建议：停止“单类 pose+3px 2D+单身份”认证级路线；若要继续，收窄为 bearing-primary + 可标注域 + identity=UNKNOWN/appearance-gated，并补近距大目标严格绿光数据与独立标注。

## 地标阶段门勘误、候选 A 三 seed 与消费者协议（2026-11-04 四阶段）

- **阶段门勘误**：上一包把 holdout 门误用于 pilot→3seed；gate 文件 pilot 门为 +0.05/FMR/coverage-0.02，A pilot 满足 → 补完 3 seed。见 [勘误](perception/GATE_STAGE_ERRATA_20261104.md)。
- **候选 A 3 seed（旧 3px，val_main 163/95）**：seed0 0.516、seed1 0.453、seed2 **0.632（选定）**；baseline 0.400；Δ+0.232；presence P1.0/R0.821、refcov 0.561、identity P1.0/FMR 0。旧协议 holdout 门 **PASS**。见 [阶段验证](perception/training_20261104/STAGE_VERIFICATION_20261104.md) 与 [模型冻结 v2](../../configs/perception/landmark_model_freeze_v2.json)。
- **消费者协议（身份+水平 bearing+可用性+有效）**：strict_unknown 下 consumer 成功=0（单类 detector 无身份确认通道）；raw claim 上界 0.5–0.76 仅诊断。appearance gate 在 annotated box 可分（aspect AUC 1.0）但 pipeline 预测框不可迁移；two-class detector NOT RUN。消费者 holdout 门 **FAIL** → **holdout NOT_TRIGGERED**。见 [消费者评测](perception/CONSUMER_EVAL_20261104.md) 与 [汇总报告](perception/LANDMARK_ROUND4_GATE_AND_CONSUMER_RESULTS_20261104.md)。
- **不可变快照**：13 artifacts 在 pre_train/pre_selection/post_train 校验；3 seed 全部 VALID；标签漂移阻断。v5 freeze（train 19 组/1857、val 11 组/921）泄漏审计/外部索引 PASS。
- **ONNX 三路径（候选 A 选定）**：PARITY_PASS，186 帧/134 metric 帧全部决策层 0 翻转（presence/reference/identity claim/identity gt/false claim/reject reason/bearing/joint）；raw 相对差 1.48e-6；RKNN/板端 UNKNOWN。
- **身份案例缺口**：T25 补采 INCOMPLETE（CUDA OOM、无 run.complete；pilot 机位不合格），T26 28 帧 PROVISIONAL_DIAGNOSTIC_ONLY 不纳入；holdout v2 预注册 SPEC_FROZEN_NOT_TRIGGERED。
- **下一包建议（2026-11-04 记录，已于 2026-11-05 启动）**：实现 two-class 身份通道（tower vs similar structure/MS1）并重新预注册 consumer gate；之后按 holdout v2 补采与一次性评价。

## 当前能力限制

- 几何/绿灯独立测试 presence TP/FP/FN/TN 为 13/0/5/12；18 个正例中有 9 个定位标注，定位子集联合达标 3/9。3/18 表示全部正例中已确认达标的比例，不能把未标注帧一律解释为定位失败。成功检测样本上的低 anchor 误差不代表全部正例的整体精度。
- 旧 route/reset 数据属于同轨迹重复采集；旧 presence TP 未验证目标框，bbox 中心方位不能直接当作绿灯参考点方位。旧指标仅按对应勘误使用。
- 地标学习早期限制（历史，已由后续 v3–v6.2 数据冻结更新）：当时 dev 数据 val 仅北走廊 1 条 family，静态视点每 pose 仅 3 accepted 帧；final 池只有试点标注、HN1（带绿灯相似结构）与 HN2（完全遮挡）覆盖不足；单代理标注不是独立人工审查；只凭 hash 不构成 sealed。
- 原生 contact event/impulse、负接触覆盖、多环境 reset/训练及完整实机外廓未验证。旧 CONTACT_INFERRED 的两个历史案例仍不具备确认物理真值的证据。
- 官方 Vulkan GUI、USD 克隆的 100 步短例有历史 PASS 记录，见 [核验摘要](official_gui_smoke/vulkan_current_verification.json)；并不证明默认 Fabric 路径、地图长时稳定性或驱动根因。后续地图正式实验使用 D3D12 的原证据保持原边界。
- 项目 PPO、真实感知设备、PX4 Sender、板端 Student、SITL/HIL 与实机均未完成本项目验收；旧官方 PPO 兼容短例不能替代项目训练。规则、BOM、准确固件/参数来源仍为 UNKNOWN/RULE-CHECK，不提升任何 BB22 Gate。

## 下一项

当前工作包已封闭。如继续 two-class，须另立工作包，重新预注册 same-frame 联合监督、reference availability guard、负例/不可观测 claim 约束及新预算与不可变快照；不自动追加训练。内部有界研究授权有效，对外分发另行决策。感知保持 shadow；PX4 Sender、板端 Student、项目 PPO、真实相机及各 BB22 Gate 均未完成验收。

## 运行与历史复现

- 所有 Isaac 采集、仿真、诊断、重放及训练必须前台可视 GUI；离线分析、单元测试和文档审计不要求 GUI。本次地标 final 池采集为可见前台 GUI（D3D12），窗口截图与日志见 [采集报告](perception/capture_20261104/CAPTURE_20261104.md)。
- 当前单环境动态评价默认：`--geometry-policy reference_origin_v2 --contact-mode measured_hard_reset`。显式历史模式：`--geometry-policy legacy --contact-mode legacy_inference`。不能混用，不能将旧冻结直接套到新默认。
- 旧冻结、失败、pilot、无效标签轮次和历史验证文件保留原路径及字节，不因入库而变成当前正式验收证据。原始大图、逐步日志、权重、地图资产及本机配置继续留在忽略目录或外部存储。
- 冻结匹配原源码/配置与当时工作树；当前 HEAD 前进并不使历史冻结适用于新源码。复现时按对应报告选择源码，不重写历史 commit/hash。

## 当前状态（2026-11-05 更新；two-class 工作包进行中）

- **当前任务**：two-class 身份通道 + 消费者验证（新预注册 [two-class protocol](../../configs/perception/landmark_two_class_protocol_v1.json)、[标签规范](../../configs/perception/landmark_two_class_label_spec_v1.json)、新预算、新快照 manifest v7）；旧包 47d1063 保持封闭。
- **已过时描述更正（历史保留）**：
  - “训练启动 BLOCKED（A1 许可需用户决策）”只适用于 2026-11-04 训练前闭环包；自 2026-11-04 起已在用户“仅内部有界研究”授权下实际完成多轮训练与评测，当前训练不再 BLOCKED。
  - “停止单类 pose+3px 2D+单身份认证路线”仍是单类路线的结论；two-class 是新的、独立预注册的工作包，不等于该路线重启或认证恢复。
- **当前限制/边界**：two-class 只解决“塔 vs 已验证相似结构 MS1”的限定域辨识，**不是开放集身份识别**；class1 永不映射中央塔 ID；UNKNOWN/REJECTED 必须显式。身份误匹配、bearing 覆盖、消费者成功率仍以实测定论；RKNN/板端/真实相机保持 UNKNOWN；认证级结论仍需独立人工标注与新 holdout。
- **下一项**：two-class 数据冻结 → 工程 smoke/pilot → 3 seed → consumer development→holdout 门判定；门通过才触发 holdout v3（≥3 新族/200–400 帧/覆盖 MS1 单独、塔单独、同框、尺度、截断遮挡、缺席）。
- **历史记录**：2026-11-04 及以前各节按日期阅读，不因本更新而改写。

## Two-class 身份通道与消费者验证（2026-11-05 工作包；STOP）

- 结论：**两套预注册配方 pilot 均未过 pilot→3seed 门 → 停止本版 two-class 实验**；不进入 3 seed，不触发新 holdout（landmark_holdout_freeze_v3 保持 SPEC_FROZEN_NOT_TRIGGERED）。详见 [two-class 结果报告](perception/LANDMARK_TWO_CLASS_RESULTS_20261105.md)。
- 预注册：[two-class protocol](../../configs/perception/landmark_two_class_protocol_v1.json)（class0 中央塔 / class1 map-native MS1；class1 永不映射塔、kpt v=0 mask；工程 smoke / pilot→3seed / consumer holdout 三级门；预算 2 配方×15ep pilot + 最多 4 次完整训练；R2 amendment 与 r2_joint 选模规则先于 R2 冻结）、[标签规范](../../configs/perception/landmark_two_class_label_spec_v1.json)。
- 数据：T30 373（class0 232/class1 123/同框 39）+ v4.1 addendum 60 + T38 近距 MS1 102（class1 102，h 184–227px）；val_main 163（MS1 47）+ identity 62（MS1 35/同框 26/MS1-only 9/GT_UNOBS 9）；v6.1/v6.2 冻结（class1 285、泄漏审计 0）、snapshot v7/v7b（34 artifacts 全 VALID）。
- R1（v6.1，15ep）：MS1 recall identity 0.286 <0.50 → pilot gate FAIL（近距 MS1 OOD；class1 head 重初始化+15ep+warmup）。
- R2（v6.2+近距 MS1，15ep）：MS1 recall 修复到 0.571、tower 0.853，但官方 same-frame 0.319/0.500 <0.60 → pilot gate FAIL；且 identity false-ref 0.077→0.500、consumer all 0.698→0.434、val negative claims 2/39、GT_UNOBS improper 2 → 回退项进一步阻止 promotion。
- 预算：2 次 pilot（≤15ep），**0 次完整训练**；未 3-seed、未 holdout。
- ONNX：对 R2 pilot last（NOT_SELECTED_VALIDATED_PILOT_ONLY）导出并做 two-class 三路径对齐，225 帧 12 决策层 × 3 对 0 翻转（kpt max 9.92e-5 px、ONNX `8bc01a40…`）；仅证明路径等价，不证明效果/身份/板端。
- 可保留正面证据：近距 MS1 数据方向有效（MS1 recall 0.286→0.571）；但 same-frame 消歧与 reference availability/负例/不可观测 claim 是本版失败点。
- 下一版若继续 two-class 需新预注册（same-frame 监督、参考通道 guard、negatives/GT_UNOBS claim、class1 不干扰 kpt 分支），不是本 R2 的延续；当前可交付基线仍是单类 + identity 显式 UNKNOWN + bearing-primary 诊断。
- 旧包 47d1063 封闭、旧模型/协议/hash 不改；`CURRENT_STATUS`/`AGENTS` 中历史“训练 BLOCKED/下一项”表述已在本包开头按日期更正（历史保留）。
