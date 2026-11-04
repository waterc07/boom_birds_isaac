# 交接：地标探索实验执行（2026-11-04 二阶段）

## 状态

- 分支 `feat/v2.2-simulation-perception`；本阶段开工 HEAD `800c53b`；按现场以实际提交为准。
- **结论：探索实验链路全部跑通并产出实际数字；模型效果未达计划门限；能力认证 INCOMPLETE。**
- 未推送、未刷固件、未启动 PPO/控制、未提升 Gate；模型/权重/训练日志/大图不入 Git（只留清单、hash、版本化结论）。

## 1. 许可与判定

- 用户 2026-11-04 授权主候选 YOLOv8n-pose（AGPL-3.0）**仅内部有界研究**，分发另行决策；记录为项目决定，不是法律结论。
- 判定拆分为 E1–E5（探索启动，本轮全部满足并执行）与 C1–C8（能力认证，本轮多数 INCOMPLETE/UNKNOWN）。定义见 [任务与实验定义 §4](perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md)。

## 2. 数据与标注

- dev v3：[landmark_split_freeze_v3.json](../../configs/perception/landmark_split_freeze_v3.json)（canonical `bc037e30…`）：train 10 组/1475 帧、val 7 组/816 帧（795 accepted，5 family + HN1/HN2）、excluded 9 组/1107；泄漏审计 0；外部产物 16 数据集/3695 帧可读、hash 一致。
- 暴露登记：[landmark_exposure_registry_v1.json](../../configs/perception/landmark_exposure_registry_v1.json)：26 exposed / 6 exploratory / **0 untouched**；34 帧试点→annotation calibration，final 6 族整体降级 exploratory（不称 sealed）。
- 标注：spec v2.1 `010255d9…`（FROZEN_FOR_DATA）；train 160 帧 `01977b9f…`、val 134 帧 `c3944e08…`（HN 24 帧）、final exploratory 279 帧 `7115ee04…`；均为单代理 AGENT_PROXY+SELF_CHECKED，bbox 为投影 aid+全帧目视复核，参考点与绿色 cue 同源——**不是人工独立审查**。
- 新采集：375 accepted RGB（batch1 322 + HN 53）；HN1 合成 confuser 27、HN2 合成遮挡 26（GT_UNOBSERVABLE，非负例）；GUI 全程可见前台、无 headless；HN 仍 29 accepted 帧未标（INCOMPLETE）。
- 重要更正：采集发现 map-native 带绿灯相似结构 MS1（≈(3.0,4.0)）→ **U1/U2 唯一性假设证伪**；final 池无已验证 HN1 帧 → identity 结论不可认证。

## 3. 工具链与环境

- 工具：[landmark_yolo.py](../../src/boom_birds/evaluation/landmark_yolo.py)（标签转换/letterbox 逆变换/推理解码/多候选拒绝）、[evaluate_landmark_yolo.py](../../scripts/evaluate_landmark_yolo.py)（分层评价、一次性 final 拒绝覆盖）、[landmark_metrics.py](../../src/boom_birds/evaluation/landmark_metrics.py)（分母审计：预测 UNKNOWN/REJECTED 留在召回/覆盖/joint 分母；GT_UNOBSERVABLE 单列；GT 参考不可见不评定位误差）；测试 979+。
- 环境：隔离 `.venv/landmark-train`（torch 2.7.0+cu128、ultralytics 8.2.0、onnx 1.22.0、onnxruntime 1.31.1）；Isaac venv 未改。
- 工程发现：YOLO 标签坐标域 bug（模型画布归一化误写 txt）→ 用 ultralytics loader 复现（delta_y=+3.25 px）、evaltool 修复为源图归一化 + 幂等 marker + fail-loud、重建数据集与 canonical 导出逐字节一致；bug 期间 30 epoch 运行判 INVALID。

## 4. 训练与一次性 exploratory final

- 有界训练：3 seed × 60 epoch（协议上限 100，固定 60 为时间盒 delta）；val joint：seed0 0.484 / **seed1 0.579** / seed2 0.442（最差已报）；选模仅 val。
- 冻结：[landmark_model_freeze_v1.json](../../configs/perception/landmark_model_freeze_v1.json)（sha 以文件为准）：seed1/last.pt `d4ffe49a…`、tau_det=tau_conf=0.605476（val P 0.9508=58/61）、tau_px 3.0、tau_iou 0.3、tau_margin 0.1 PROPOSED（val 无多候选帧）。
- ONNX：opset18、`ca28a5c9…`；torch vs ORT raw max_abs_diff 1.22e-4；.pt vs .onnx 原生 predict 一致。
- final：**只执行一次**（279 帧，标签 `7115ee04…`）：presence TP218/FP0/FN20/TN41（P1.000/R0.916）、reference coverage 62/218=0.284、false-reference 0/20、identity P1.000（无已验证 HN1，不作认证）、joint 71/238=0.298（失败 presence 20 + reference 147）；anchor 正确子集中位 1.95 px、bearing 0.30°；最差 lmf_near joint 3/23。计划效果门未达 → 按不回调规则停止。
- 首次 final 调用因 torch 2.7 weights_only 在推理前失败、未产生指标；加 trusted-load 环境变量后成功，是唯一一次成功读取。
- RKNN：UNKNOWN / NOT RUN（无板卡、RKNN-Toolkit2 专有未安装）。

## 5. 认证缺口与用户决策

- C1 许可分发未决；C2 无独立人工标注；C3 无未触碰 sealed final；C4 false-match 分母仅 41；C5 无 RK3576；C6 合成域；C7 单次；C8 合同对齐未完成。
- 需要用户决定的最少事项：①许可分发路线（AGPL/商业/切换）；②是否为认证投入 ≥2 独立人工标注+仲裁与全新 sealed 采集；③是否投入 RK3576 板卡与真实相机标定；④原始数据仓库外备份（建议项）。

## 6. 验证与证据

- 命令：`pytest -q`（Isaac venv）979+；`scripts/planning/audit_documents.py` PASS；数据集校验 `scripts/verify_landmark_dataset.py` PASS；final 评价命令见 [结果报告](perception/LANDMARK_EXPLORATORY_RESULTS_20261104.md) §7。
- 证据索引：[探索实验结果](perception/LANDMARK_EXPLORATORY_RESULTS_20261104.md)、[训练执行](perception/training_20261104/TRAINING_20261104.md)、[环境](perception/training_20261104/ENV_20261104.md)、[阈值冻结](perception/training_20261104/threshold_freeze_val_20261104.json)、[数据冻结 v3](perception/dataset_freeze_20261104/DATASET_FREEZE_V3_20261104.md)、[采集与 HN](perception/capture_dev_20261104/CAPTURE_DEV_20261104.md)、[标注](perception/annotation_verify_20261104/)、[工具链](perception/TRAINING_EVAL_TOOLING_20261104.md)。
- final 输出（ignored）：`outputs/perception/final_exploratory_eval_20261104/{metrics.json,predictions.jsonl}`（sha `a01c08ec…`/`8cdfe558…`）。
