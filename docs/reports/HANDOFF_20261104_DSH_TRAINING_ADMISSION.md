# 交接：地标学习训练前闭环与数据准备（2026-11-04）

## 状态

- 现场：分支 `feat/v2.2-simulation-perception`；本轮开工基线 HEAD `43fee3e`；工作树开工时干净，保留所有既有修改。
- **结论：训练准入 INCOMPLETE；训练启动 BLOCKED（A1 许可需用户决策）。** 本轮未安装训练依赖、未下载模型、未启动训练、未修改 Isaac 环境；所有 Isaac 运行均为可见前台 GUI。
- 详细判定：[训练准入结论](perception/TRAINING_ADMISSION_20261104.md) + [机器可读判定](perception/dsh_landmark_training_admission_20261104.json)。

## 1. 任务与实验定义（已修正）

- 文件：[LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md](perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md)；协议：[landmark_training_plan_v2.json](../../configs/perception/landmark_training_plan_v2.json)（取代 v1 训练协议）。
- 类别检测 ≠ 身份：单类 tower 只是类别证据；landmark_id 需唯一性假设 U1–U3 + 单候选 + 有效参考点；多候选拒绝 M1–M6；困难负例 HN1–HN6。
- 指标分母：presence（N_pos/N_neg，GT 不可观测帧单列不计失败）、reference（N_avail/N_unavail 分开）、identity（claims/N_pos/N_neg，无相似结构负例不可评测）、joint（窄口径 N_joint_eval + 全正例下界 + 覆盖率，未标注参考点不算失败）。
- 训练协议：warmup 15 epochs 不早停不因 joint<0.60 中止；patience 20；诊断触发为书面审查；三 seed 仅用验证集比较/选模/冻结阈值；随后对预选方案在 sealed final 池执行一次 final，不回调、不重跑。
- 可执行定义：`src/boom_birds/evaluation/landmark_metrics.py` + `tests/evaluation/test_landmark_metrics.py`（9 条）。

## 2. 数据分组与封存

- 实况核查：13 个 `*_sensor` 目录 / 3002 RGB / 2909 accepted；旧 inventory 漏列 9 目录 / 1300 帧；仅 2 条物理走廊；旧 split v1 存在同走廊 family 泄漏。
- dev 冻结：[v1](../../configs/perception/landmark_split_freeze_v1.json)（19 组/6 family）与 [v2 保守版](../../configs/perception/landmark_split_freeze_v2.json)（推荐训练前采用；train 7 组 1320 帧、val 3 组 575 帧、excluded 9 组 1107 帧；val 仅北走廊 → held-out INCOMPLETE）。
- final 池：[landmark_final_pool_seal_v1.json](../../configs/perception/landmark_final_pool_seal_v1.json)（6 新族、297 RGB / 279 accepted、抽样 N=1、与既有数据 0 sha 重叠、0 family/group 重叠、GUI provenance 完整）；**完整语义标签 PENDING**。
- 采集：[CAPTURE_20261104.md](perception/capture_20261104/CAPTURE_20261104.md)：可见前台 GUI（D3D12/RTX 5080/驱动 581.80），6/6 SUCCESS，覆盖近距/远景/侧向/右缘截断/目标缺席/出视场；未构造场景结构遮挡；HN1 仅有旧 `static_c` 约 6×25 px 绿色顶端相似结构证据。
- 访问边界：标注者可看 test 图，但 test 内容/结果不得用于模型/阈值开发；hash ≠ sealed；同一执行者标注+开发只能声称流程隔离 + hash 承诺。
- 工具：[landmark_dataset.py](../../src/boom_birds/evaluation/landmark_dataset.py)、[verify_landmark_dataset.py](../../scripts/verify_landmark_dataset.py)；报告：[DATASET_SPLIT_AND_LEAKAGE_20261104.md](perception/dataset_freeze_20261104/DATASET_SPLIT_AND_LEAKAGE_20261104.md)。

## 3. 标注可用性

- 报告：[ANNOTATION_VERIFICATION_20261104.md](perception/annotation_verify_20261104/ANNOTATION_VERIFICATION_20261104.md)；盲标 21 帧/33 旧记录（代理、非专家）。
- 数值：bbox IoU 0.649（0.415–0.897）；绿灯 keypoint 差 1.155 px = 0.414°（max 2.236 px）；bearing 差 0.180°；present 21/21、reference_status 21/21、visibility 16/21；不可判定率 19.0%；旧框系统性高约 37 px（含场地平台）。
- 循环性：旧参考点≈绿色质心（中位 0.43 px）→ 旧 0.036° anchor 残差是同源循环证据，不能当独立精度。
- 表达力：“目标存在但参考点不可见”可表达（真实帧 g3_181 QA PASS）；旧 schema 无法表达不可用原因/候选列表/三态 → 已升级 [spec v2](../../configs/perception/landmark_annotation_spec_v2.json)（Lead 已批准用于试点；v1 保留）。
- 训练标签口径：bbox 只框可见塔体+灯架（含相连阶梯底座），不含场地平台/地面/阴影；截断只框图像内可见部分；YOLO 1-keypoint v∈{0,1}，参考点不可见→bbox+占位+v=0 且不进 anchor/coverage 分母；absent 空标签显式列清单；ambiguous 默认不进正例；sidecar 记录截断/遮挡/歧义/参考状态。
- final 池试点（T6）：[FINAL_POOL_PILOT_ANNOTATION_20261104.md](perception/annotation_verify_20261104/FINAL_POOL_PILOT_ANNOTATION_20261104.md)：固定 midpoint systematic 规则抽 34 帧（25 正/9 负），参考点可用 21/不可用 4（远景 green≤2px→REFERENCE_TOO_SMALL），截断 10，undecidable/ambiguous/occluded 均 0（未虚构），v2 校验 **PASS 34/34**；标签在 ignored `outputs/perception/landmark_final_annotations_20261104/`，仓库只存清单/hash/overlay。试点暴露 P1 四边截断元数据、P2 参考点可用像素判据、P3 “TARGET_ABSENT+未验证 confuser”表达缺口 → **完整 279 帧标签前应先出 spec v2.1**。

## 4. 许可/版本/部署证据（只读核查）

- 报告：[LICENSE_AND_EXPORT_EVIDENCE_20261104.md](perception/license_evidence_20261104/LICENSE_AND_EXPORT_EVIDENCE_20261104.md) + JSON（37 evidence / 12 pending）。
- Ultralytics v8.2.0 LICENSE = AGPL-3.0 逐字节一致；AGPL §13/权重衍生/闭源分发为未决解释；不擅自认定接受 AGPL、不自动切备选。
- YOLOX-Nano 代码 Apache-2.0；权重/COCO 条款 UNKNOWN。RKNN Model Zoo Apache-2.0 且有 `yolov8_pose` RK3576 示例；**RKNN-Toolkit2 为 Rockchip 专有许可**；自定义 1-keypoint ONNX/RKNN = UNKNOWN。
- 本机：RTX 5080 sm_120、驱动 581.80、torch 2.7.0+cu128 arch list 含 sm_120、官方 cu128 Win cp311 wheel 存在；无 ultralytics/onnxruntime/rknn；8.2.0×torch2.7 组合 UNKNOWN（需隔离 venv smoke，未授权未做）。
- 对旧证据包登记 4 条更正（“model_artifacts_found none”不准确等）。

## 5. 需用户决定的最少事项

1. 许可路线：AGPL-3.0（含未决期间是否允许内部有界训练）/ 商业许可 / 切 Apache-2.0 备选（不自动切）。
2. final 标注与开发的独立性：是否允许同一执行者；是否投入 ≥2 独立人工标注 + 仲裁；是否接受 hash+流程记录作为封存证据。
3. 原始数据（279 final + 3002 dev）是否需要在仓库外/远端做带 hash 备份；9 个未登记 debug/evidence 目录处置。

## 6. 验证命令与结果

```powershell
& $py -m pytest -q                       # 最终 <FINAL_PYTEST>
& $py scripts/planning/audit_documents.py  # PASS
& $py scripts/verify_landmark_dataset.py   # PASS, frame_total 3002, 0 error
& $py scripts/verify_landmark_dataset.py --seal configs/perception/landmark_final_pool_seal_v1.json  # PASS, 0 error
```

采集运行：冒烟 1/1 + 正式 6/6 SUCCESS/ROUTE_COMPLETE，0 collision/timeout/invalid，`run.complete.json` PASS。

## 7. 未完成 / 下一步

- spec v2.1（P1/P2/P3）→ final 池完整语义标签（当前 34/279）+ 独立审查/仲裁；HN1/HN2 覆盖补充；
- 隔离 venv 8.2.0×torch2.7 smoke、自定义 1-keypoint ONNX 导出与 RKNN 转换（板卡缺失 → UNKNOWN）；
- A6 最终预注册与训练执行（必须 A1–A8 闭合后另行开工）；
- 模型效果、板端、导航和 Gate 均 NOT RUN；官方示例指标不是我们的结果。
