# 交接：地标失败诊断、工程修复与有界改进实验（2026-11-04 三阶段）

## 状态

- 分支 feat/v2.2-simulation-perception；开工 HEAD 0c27525；以现场提交为准。
- **结论：STOP（负结果）**。两候选均未过预注册 development gate；不推进 3 seed、不触发 holdout、不读新 final；旧结果只增不改。
- 未接控制/未启动 PPO/未提升 Gate/未推送；权重/大图/日志留 ignored。

## 1. 诊断（post-evaluation 只读）

- 报告：docs/reports/perception/posteval_20261104/POSTEVAL_DIAGNOSIS_20261104.md；模块 src/boom_birds/evaluation/landmark_posteval.py（20 测试）。
- reference 失败（分母 218）：3px 内 62（28.4%）、错误锚点 119（54.6%，88/119 纵向主导，dy 中位 +2.67px）、kpt 置信度抑制 28（12.8%）、可用参考漏检 9（4.1%）。
- 3px 2D vs bearing：181 已发射中 87 帧 2D>3px 但 bearing≤1.074°（3° 时 119）；下游消费 bearing，旧 3px 偏严（旧结果保留，新口径单列）。
- TINY 盲复标（22 帧）：presence 严格 8/22=0.364 FAIL；TINY 正例 12/12 undecidable；bbox IoU 中位 0.434 FAIL；同源 kpt 0.823px PASS → 9–14px 不可标注。
- MS1（map-native 带绿灯柱）证伪 U1/U2；单类 tower 无身份通道；identity 只能 UNKNOWN/appearance-gated。

## 2. 评价定义审计

- 报告 docs/reports/perception/EVAL_DEFINITION_AUDIT_20261104.md；代码 src/boom_birds/evaluation/landmark_eval_definitions.py + scripts/recompute_landmark_metrics.py（45 测试）。
- 四项分离：presence / identity / reference-availability / localization；joint 拆 LOCALIZED 62/218 + CORRECT_REFUSAL 9/20 + FAIL_PRESENCE 20 + FAIL_REFERENCE 147；UNKNOWN/漏检/错误身份不消失；GT 不可观测不评定位但单列错误声明。

## 3. ONNX 三路径

- 报告/JSON docs/reports/perception/onnx_parity_20261104.json；代码 scripts/landmark_export_onnx.py、scripts/landmark_onnx_parity.py、src/boom_birds/evaluation/landmark_onnx.py。
- 共享预处理 126 帧 0 决策翻转；旧 4.67px 差异=legacy .pt 与 ONNX predict letterbox 模式不同（17 observation/18 joint 翻转），不是导出错误；近阈值 7 帧翻转 0；RKNN/板端 UNKNOWN。

## 4. 工程链入库

- scripts/landmark_train_cli.py（预注册 PatienceStopper、数据集准备、协议 hash 守卫、候选评估）、scripts/landmark_freeze_thresholds.py、scripts/evaluate_landmark_yolo.py、scripts/recompute_landmark_metrics.py；configs/perception/landmark_train_cli_v1.json；CLI/配置移除私有绝对路径。
- 标签漂移处置：训练期间 labels_val 被并行标注更新为 231 帧，首轮 eval 判 INVALID；改用稳定文件 labels_val_validation163.json（sha a9bfda8f…），记录在 IMPROVEMENT §1。

## 5. 数据与身份案例

- dev freeze v4（HN 53/53）、v4.1（旧 exploratory 279 帧入 train，DEVELOPMENT_TRAIN）、v4.2（identity 7 组 190 帧进 val_identity）；泄漏审计 v4/v4.1/v4.2 均 PASS；外部产物 3885 帧可读/hash 一致。
- 暴露登记 v2：39 组全部 exposed_development、0 untouched；旧 exploratory 已降级 development。
- identity 采集 7 case/169 accepted/62 帧代表标注；HN1 27 合成注入、HN2 26 GT_UNOBSERVABLE；MS1 map-native verified。

## 6. 改进实验与 STOP

- 预注册：configs/perception/landmark_improvement_gate_v1.json（先于结果冻结）+ landmark_improvement_protocol_v1.json（status CLOSED_STOP_GATE_NOT_MET）。
- baseline pilot15 joint 0.379（36/95）；候选 A pilot15 0.453（43/95，Δ+0.074）；候选 B tau_kpt 无改善且 false_reference 0.093→0.130 变差。
- gate（Δ≥+0.08 且 joint≥0.60 且 identity 不恶化）→ FAIL → STOP；完整训练用 1/4；holdout NOT_TRIGGERED。
- 报告 docs/reports/perception/training_20261104/IMPROVEMENT_20261104.md；证据 outputs/landmark_train/runs/improvement_v4/。

## 7. 路线建议与需用户决定

- 建议：停止“单类 pose+3px 2D+单类别身份”认证级路线；若要继续，收窄为 bearing-primary + 可标注域（排除 TINY/<3px 绿光）+ identity=UNKNOWN/appearance-gated，并补近距大目标严格绿光数据与 ≥2 人独立标注。
- 用户决定：①是否接受 bearing-primary 开发口径；②是否投入独立人工标注与新未触碰 holdout；③许可分发路线；④板卡/真实相机（可选）。

## 8. 验证与证据

- 收尾：python -m pytest -q、python scripts/planning/audit_documents.py、python scripts/verify_landmark_dataset.py --freeze configs/perception/landmark_split_freeze_v4_2.json。
- 汇总报告：docs/reports/perception/LANDMARK_DIAGNOSIS_AND_IMPROVEMENT_RESULTS_20261104.md。
- 旧结果：docs/reports/perception/LANDMARK_EXPLORATORY_RESULTS_20261104.md、configs/perception/landmark_model_freeze_v1.json（保留）。
