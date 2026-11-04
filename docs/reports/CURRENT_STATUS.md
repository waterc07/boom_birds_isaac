# 当前进度与接手续查（2026-11-04）

本页汇总仓库内已交付能力与证据边界。设计正文仍为 [V2.2 架构](../design/RMUC2027_UAV_V2_2.md)，本页不修改其合同或放行任何 Gate。正文中的开工时实现状态、早期计划和历史交接应按日期阅读，不能代替当前源码和后续修订。

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

## 当前能力限制

- 几何/绿灯独立测试 presence TP/FP/FN/TN 为 13/0/5/12；18 个正例中有 9 个定位标注，定位子集联合达标 3/9。3/18 表示全部正例中已确认达标的比例，不能把未标注帧一律解释为定位失败。成功检测样本上的低 anchor 误差不代表全部正例的整体精度。
- 旧 route/reset 数据属于同轨迹重复采集；旧 presence TP 未验证目标框，bbox 中心方位不能直接当作绿灯参考点方位。旧指标仅按对应勘误使用。
- 地标学习：现有 dev 数据 val 仅北走廊 1 条 family，静态视点每 pose 仅 3 accepted 帧；final 池只有试点标注、HN1（带绿灯相似结构）与 HN2（完全遮挡）覆盖不足；单代理标注不是独立人工审查；只凭 hash 不构成 sealed。
- 原生 contact event/impulse、负接触覆盖、多环境 reset/训练及完整实机外廓未验证。旧 CONTACT_INFERRED 的两个历史案例仍不具备确认物理真值的证据。
- 官方 Vulkan GUI、USD 克隆的 100 步短例有历史 PASS 记录，见 [核验摘要](official_gui_smoke/vulkan_current_verification.json)；并不证明默认 Fabric 路径、地图长时稳定性或驱动根因。后续地图正式实验使用 D3D12 的原证据保持原边界。
- 项目 PPO、真实感知设备、PX4 Sender、板端 Student、SITL/HIL 与实机均未完成本项目验收；旧官方 PPO 兼容短例不能替代项目训练。规则、BOM、准确固件/参数来源仍为 UNKNOWN/RULE-CHECK，不提升任何 BB22 Gate。

## 下一项

1. 用户决策许可路线（AGPL/商业/备选）与标注独立性安排；在此之前**不得**启动训练。
2. 先出 spec v2.1（P1 四边截断元数据、P2 参考点可用像素判据、P3 TARGET_ABSENT+未验证 confuser 状态），再生产 final 池完整语义标签（当前 34/279）+ 独立标注/仲裁，补 HN1/HN2 覆盖，冻结阈值推导与最终预注册。
3. 隔离环境 8.2.0×torch 2.7 兼容性 smoke、自定义 1-keypoint ONNX 导出（需用户授权安装），再做有界训练；不得跳过准入项。
4. 实物输入针对具体迁移目标收集，不笼统阻塞离线软件准备；感知仍保持 shadow，不接控制、不提升 Gate。

## 运行与历史复现

- 所有 Isaac 采集、仿真、诊断、重放及训练必须前台可视 GUI；离线分析、单元测试和文档审计不要求 GUI。本次地标 final 池采集为可见前台 GUI（D3D12），窗口截图与日志见 [采集报告](perception/capture_20261104/CAPTURE_20261104.md)。
- 当前单环境动态评价默认：`--geometry-policy reference_origin_v2 --contact-mode measured_hard_reset`。显式历史模式：`--geometry-policy legacy --contact-mode legacy_inference`。不能混用，不能将旧冻结直接套到新默认。
- 旧冻结、失败、pilot、无效标签轮次和历史验证文件保留原路径及字节，不因入库而变成当前正式验收证据。原始大图、逐步日志、权重、地图资产及本机配置继续留在忽略目录或外部存储。
- 冻结匹配原源码/配置与当时工作树；当前 HEAD 前进并不使历史冻结适用于新源码。复现时按对应报告选择源码，不重写历史 commit/hash。
