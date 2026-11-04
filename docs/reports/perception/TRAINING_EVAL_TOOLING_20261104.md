# 训练/评测工具链与分母审计修正（2026-11-04）

> **状态：** BASELINE（工具链已实现并通过单元测试；不表示模型效果、板端或导航验收）
> **来源章节：** docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §1–§2；configs/perception/landmark_training_plan_v2.json（metrics_definition / annotation_and_label_policy）；configs/perception/landmark_annotation_spec_v2.json 与 v2_1（derived_model_format / D1–D7）；V2.2 §7.4–§7.8（经任务定义文档引用，本文件不重新定义合同）
> **证据域：** 单元测试（Isaac venv 纯 Python，无 Isaac/GUI 依赖）+ 只读标注数据转换 smoke；无模型推理、无仿真、无板端
> **最后核对：** 2026-11-04

本文件记录 task-10 的交付：可执行训练/评测工具链（标签转换、letterbox 正/逆变换、推理解码、分层评价入口）与**分母审计修正**。本轮未安装训练依赖、未下载模型、未启动训练、未修改 Isaac 环境、未提升任何 Gate；训练依赖只允许在独立 .venv/landmark-train 内安装（由 train 负责）。许可口径不变：主候选 YOLOv8n-pose/ultralytics 仅内部有界研究/评测，对外分发另行决策；本文件不构成许可结论，也不自动切换备选模型。

---

## 0. 结论摘要（带证据域）

| 结论 | 证据 | 边界 |
| --- | --- | --- |
| 工具链代码已落地：landmark_yolo.py（标签转换 + letterbox + 解码 + GT 抽取）、landmark_metrics.py（分母审计）、scripts/evaluate_landmark_yolo.py（分层评价） | 单元测试 89 条（61 + 28），全部 PASS | 单元测试证据域；不是模型效果 |
| 标签转换对真实 pilot 标注（v2，34 帧）可执行 | 只读 smoke：34 帧 → 25 正标签 + 9 空标签负例；参考点可用 21 / 不可用 4；截断 10；0 排除 | 数据准备/格式 QA，**不是**模型效果 |
| 标签转换对 annot 的 v2.1 示例文档可执行（四边截断对象、confusers、green_pixels） | 只读 smoke：5 帧 → 4 正 + 1 空标签负例；参考点 3/1；截断 2；0 排除 | 数据准备/格式 QA；v2.1 文档由 annot 生产，本轮只读 |
| 分母审计修正已落到可执行代码与回归测试 | 28 条 metrics 测试（含旧口径回归被改写的原因） | 定义/软件证据；尚未在任何真实模型输出上产生 final 指标 |
| 推理后端（ultralytics / onnxruntime）未在本 venv 实测 | 依赖缺失时脚本明确退出码 2；解码器用 fake Results / ONNX 张量数组做单元测试 | 真实模型输出的数值一致性 = **UNKNOWN**（待 train 在隔离 venv 验证） |
| 未做 | 训练、模型评测、final 读取、ONNX 导出验证、RKNN 转换、板端、Gate | 全部 NOT RUN / UNKNOWN |

---

## 1. 交付文件与接口

### 1.1 src/boom_birds/evaluation/landmark_yolo.py

| 接口 | 用途 |
| --- | --- |
| Letterbox / letterbox_params(src_w, src_h, model_w=640, model_h=640) | 中心 padding 的 letterbox 参数（scale/pad_x/pad_y + 源/目标尺寸） |
| point_to_model / point_from_model / bbox_to_model / bbox_from_model | 正/逆变换；bbox 用 xywh，keypoint 用 (x, y) |
| format_yolo_pose_line(target) | 把 **source_normalized_target()** 处理后的 target 渲染成确定性 8 字段 line（class cx cy w h kx ky v，6 位小数） |
| source_normalized_target(target, annotation, ...) | 把 yolo_pose_target() 的**模型画布归一化**值反变换成 **YOLO txt 要求的源图归一化**（px/src_w, px/src_h）；letterbox 只用于模型映射，不参与标签归一化（2026-11-04 缺陷修复，见 §10） |
| yolo_pose_label(annotation, model_width=640, model_height=640, green_pixels_threshold=3) | 单帧 →（label_text, sidecar）；返回 '' 表示确认缺席（空标签），None 表示排除 |
| convert_annotation_document(document, root=None, split=None, ...) | v2 / v2.1 文档 → labels + negatives + absent_frames + excluded + sidecars + counts |
| write_yolo_dataset(result, labels_dir) | 写 labels/*.txt（缺席写空文件）与 labels_manifest.json（逐帧 sha256） |
| write_sidecar(result, path) | 每帧一行 sidecar JSONL |
| merge_thresholds(overrides) | 解码阈值合并（未知键报错，避免静默拼写错误） |
| image_bearing_deg(x, fx_px, cx_px) | 图像 bearing = atan2(x - cx_px, fx_px)，单位度；**图像角，不是世界方位/距离** |
| unknown_observation(frame_id, reason) | 模型侧 UNKNOWN 记录（检测器失败），永不当作负例 |
| decode_candidates(candidates, ...) | 源图像像素候选 → landmark observation record（含拒绝规则） |
| decode_ultralytics_result(result, ...) | ultralytics Results 适配（默认坐标已在源图坐标系；coordinates='model' 时用 letterbox 逆变换） |
| decode_onnx_pose_output(output, ...) | YOLOv8-pose ONNX 输出（(B, 4+nc+3k, N)，模型输入像素 cx/cy/w/h + class scores + kpt x/y/conf）→ record |
| observation_to_metric_prediction(record) | observation → landmark_metrics 的 pred 契约（status/landmark_id/bbox_xywh/score/keypoint_px/reject_reason） |
| ground_truth_from_annotation(annotation) | 评测侧 GT 抽取：gt + reference_px + strata（family/group_id/visibility/scale/truncation/negative_type） |
| pixel_basis_from_annotation(annotation) | 读取 pixel_basis 作为解码 intrinsics |
| scale_bucket(bbox_xywh) | 尺度分桶：TINY < 1500 px²，SMALL < 5000，MEDIUM < 15000，LARGE 其余；无框 = NO_BBOX（PROPOSED 分桶） |

标签转换**委托** landmark_annotations.yolo_pose_target 做核心映射（保证只有一份 YOLO 标签实现），本模块只增加文档级导出与 v2.1 规则。train 若也用 yolo_pose_target + format_yolo_pose_line，两边 label 应逐字节一致（见 §7 的说明与限制）。

### 1.2 src/boom_birds/evaluation/landmark_metrics.py

| 接口 | 用途 |
| --- | --- |
| evaluate_frame(gt, pred, *, tau_iou, reference_px, tau_px, tau_conf, fx_px=None, cx_px=None, strata=None) | 单帧分类：presence/reference/identity/joint + 每个判定所需中间量 |
| summarize(rows) | 分子/分母 + 四格 + UNKNOWN/REJECTED 分桶 + 误差统计 + 分母快照 |
| stratified_summary(rows, dimensions) | 按维度分层 + 每维度最差条件（带分子/分母；分母为 0 标 INSUFFICIENT_DENOMINATOR） |
| error_stats(values, unit) | median/P90/max + count（样本量即分母） |
| image_bearing_deg(x, fx_px, cx_px) | 一致的 bearing 公式 |

### 1.3 scripts/evaluate_landmark_yolo.py

支持的调用（两种模式）：

    # A. 预计算预测（无 ML 依赖；可在 Isaac venv / CI 内跑指标回归）
    python scripts/evaluate_landmark_yolo.py --predictions preds.jsonl --labels annotations.json --split val --output-dir out/val

    # B. 模型推理（需 train 的隔离 venv；.pt 用 ultralytics，.onnx 用 onnxruntime）
    python scripts/evaluate_landmark_yolo.py --model best.pt --images <img_dir> --labels annotations.json --split val --output-dir out/val

    # C. 语义标签 → YOLO 数据集（纯 Python，不推理）
    PYTHONPATH=src python -m boom_birds.evaluation.landmark_yolo export --annotations annotations.json --root . --output-dir out/dataset --split train

输出：

- predictions.jsonl：每帧 frame_id / gt_frame_id / image / observation / prediction / strata / presence_class / reference_class / joint_evaluable / joint_ok / joint_fail_reason；
- metrics.json：schema_version、status（COMPUTED/INCOMPLETE）、inputs（labels/model/predictions 路径与 sha256）、counts（frame 分母、缺失图/缺失预测/无 GT 预测计数）、thresholds（**PROPOSED_NOT_FROZEN** + 冻结规则）、overall（完整 summarize 结果）、strata（family/group_id/visibility/scale/negative_type/truncation 六个维度）、worst_conditions、limitations、denominator_audit（预测 UNKNOWN/REJECTED 与 GT_UNOBSERVABLE 分桶摘要）。

防误用：

- 输出目录已有 metrics.json 时默认**拒绝覆盖**（exit 3），需显式 --overwrite —— 防止 final 之后回调重跑；
- 缺 ultralytics / onnxruntime 时**明确报错**（exit 2），不静默降级、不改标签、不改阈值；
- 缺预测的 GT 帧不会消失：用 UNKNOWN/MISSING_PREDICTION 记录并留在分母；缺图同理计数。

---

## 2. 标签转换规则（v2 / v2.1）

| 输入状态 | 输出 | sidecar 记录 |
| --- | --- | --- |
| present + 参考点可见且 green_pixels ≥ 3（或 v2 文档未记录 green_pixels） | class 0 + bbox（**按源图宽高归一化**的 cx/cy/w/h）+ keypoint（**按源图宽高归一化**）(x, y, v=1) | label_kind=POSITIVE_KEYPOINT；reference_usable=true；included_in_anchor_denominator=true |
| present + 参考点不可见（keypoint=null / reference_status=UNAVAILABLE） | 同 bbox + **bbox 中心占位坐标** + v=0；占位永远不是参考估计 | label_kind=POSITIVE_NO_REFERENCE；reference_usable=false；reference_unavailable_reason |
| present + 可见但 green_pixels < 3（v2.1 判据） | 若标注者仍写了 keypoint，则降级为 bbox + 占位 + v=0 | reference_downgraded=REFERENCE_TOO_SMALL；green_pixels；reference_usable=false |
| 确认缺席（present=false, undecidable=false, ambiguous=false） | 空标签（显式写空 txt） | label_kind=EMPTY_NEGATIVE；negative_type；confusers（含 v2.1 未验证 confuser） |
| ambiguous=true | 不写正例标签 | label_kind=EXCLUDED；exclusion_reason=AMBIGUOUS；candidates/confusers 保留 |
| undecidable=true | 不写正例标签 | exclusion_reason=UNDECIDABLE；gt_unobservable=true；gt_unobservable_reason=UNDECIDABLE |
| present + 完全遮挡且无可见 bbox | 不写正例标签（无法训练不可见目标的框） | exclusion_reason=GT_UNOBSERVABLE；gt_unobservable_reason=FULL_OCCLUSION / NO_VISIBLE_GT_BBOX |

v2.1 字段落地：

- **四边截断 P1**：target.truncated_edges 支持 v2.1 的**四布尔对象**（{left, right, top, bottom}），sidecar 的 truncated_edges 规范化为“为真的边名的排序列表”，原始对象保留在 truncated_edges_flags；另记录 truncation_source 与 truncation_conflicts。v2 无该字段时用 bbox 贴边做**回退推断**（并明确这是推断）。
- **参考点像素判据 P2**：green_pixels 依次从 geometry / target / 帧根读取；v2 文档未记录时按“标注可见即 v=1”向后兼容，但 sidecar 会显示 green_pixels=null（不声称已按像素判据核验）。
- **未验证 confuser P3**：v2.1 的 confusers[]（confuser_id/description/verified/verification_source/...）与 v2 的 ambiguous candidates[] 都进入 sidecar 的 confusers；TARGET_ABSENT + verified=false 的 confuser 仍是合法空标签负例，不会被提升为 SIMILAR_STRUCTURE。confuser_verified 由显式字段或 confusers[] 的 verified 汇总得到。
- 数据集角色/来源标注不参与标签几何，只进 sidecar（dataset_role、bbox_source、annotation_mode、annotator_*），供分层与独立性披露使用。

仍然保留的规则（不变）：不产生 v=2；截断只框图像内可见部分、不跨边外推；bbox 只框可见塔体+灯架，不含地面/平台/阴影（spec v2 bbox_scope）。

---

## 3. letterbox 正/逆变换

- 公式：scale = min(model_w/src_w, model_h/src_h)；pad_x = (model_w − src_w·scale)/2；pad_y 同理；均为**中心 padding**。
- 正变换：x_m = x_s·scale + pad_x；w_m = w_s·scale（bbox）；逆变换为其解析逆。
- 回归测试覆盖：320×240→640×640（scale 2、pad_y 80）、1280×720→640（scale 0.5、pad_y 140）、640×480→960×544、奇数尺寸 97×61→640；bbox 与 keypoint 往返误差 < 1e-9；退化尺寸（0）明确报错。
- 记录规则：**YOLO txt label 用源图宽高归一化坐标（px/源图宽高），letterbox 不参与标签归一化**（训练 loader 自己 denormalize 到源图像素再 letterbox）；sidecar 逐帧记录 scale/pad_x/pad_y 供**解码**时反变换；ONNX 解码用同一 Letterbox 反变换回源图像素后再算 bearing —— 标签空间、模型输入空间、指标空间三者不得混用。

---

## 4. 推理解码与拒绝规则（可测部分）

observation record 关键字段：frame_id、status（DETECTED / NOT_DETECTED / UNKNOWN / REJECTED）、landmark_class（仅类别证据）、landmark_id（身份证据，条件满足才写）、identity_claimed、bbox_xywh（源图像素）、score、keypoint_px、keypoint_confidence、reference_status（VISIBLE/UNAVAILABLE）、image_bearing_deg、visibility（FULL/PARTIAL/UNKNOWN）、truncated/truncated_edges、candidate_count/candidates、reject_reason + reject_reasons、appearance_check、valid、thresholds、letterbox、uniqueness_assumption。

实现的部分：

| 规则 | 触发 | 结果 |
| --- | --- | --- |
| M1 多候选 | ≥2 个 ≥tau_det 的 tower 候选且 top1−top2 < tau_margin | status=DETECTED（类别证据保留），landmark_id=null，reject_reason=MULTIPLE_CANDIDATES |
| M2 目标歧义 | green_pixels 已提供且 < tau_green_pixels；或 appearance_prior 的纵横比越界 | status=DETECTED，landmark_id=null，reject_reason=TARGET_AMBIGUOUS，appearance_check 记录原因 |
| M3 参考点不可用 | 无 keypoint 或 kpt conf < tau_kpt | reference_status=UNAVAILABLE、keypoint_px=null、bearing=null、reject_reason=REFERENCE_UNAVAILABLE；**身份 claim 仍允许**（spec v2 §1.5：正确声明 UNAVAILABLE 时仍可计 claim） |
| M4 截断 | bbox 贴图像边 → truncated_edges/visibility=PARTIAL、reject_reason=TRUNCATED；若可见边小于 tau_trunc_min_side_px 则同时**不写身份**（无足够外观证据） | 记录四个贴边；identity_allowed 视可见面积 |
| M6 无效观测 | intrinsics 缺失 → MISSING_CALIBRATION；图像尺寸非法 → INVALID_IMAGE | status=REJECTED、valid=false |
| 低于检测阈 | 无 ≥tau_det 候选 | status=NOT_DETECTED、valid=true（不是负例断言，只是“本帧未检出”） |
| 检测器失败 | 后端异常/无输出/缺预测 | status=UNKNOWN、valid=false、reason 记录（DETECTOR_ERROR / MISSING_IMAGE / MISSING_PREDICTION） |

未实现/不可仅凭离线输出判定的部分（UNKNOWN）：

- M2 的“外观/几何先验与中央塔一致”需要 green-cue 探针或资产先验；解码器只在**调用方提供 green_pixels / appearance_prior** 时评估，否则 appearance_check=NOT_EVALUATED，并在报告中如实记录（不把未评估写成通过）。
- M4 的“截断面积超限”没有离线的真实外延信息；实现采用可测代理规则（贴边 + 可见边过小 → 不写身份），属于 PROPOSED 工程约定，不是规范原文。
- M5（STALE/DUPLICATE/GENERATION_MISMATCH）属于在线观测时效/代际问题，离线批处理不产生；词汇与 valid 映射已保留。
- kpt 置信度的语义：训练标签 v∈{0,1}，推理输出是连续置信；tau_kpt=0.5 是 PROPOSED，未在任何真实权重上实测。

---

## 5. 分母审计：旧口径 vs 新口径（本轮修正核心）

旧实现（本轮修改前）把预测 UNKNOWN/REJECTED 一律记为 UNOBSERVABLE，**从四格与 recall/coverage/joint 分母中消失**；这会系统性高估召回。新口径：

| # | 场景 | 旧口径 | 新口径（本轮） | 测试 |
| --- | --- | --- | --- | --- |
| 1 | GT 可观测正例 + 预测 UNKNOWN/REJECTED | 不计 FP/FN/TN/TP；recall 分母缩小 | presence_class=FN，**留在 N_pos 与 recall 分母**；同时进 presence.unknown_rejected（on_positive、by_status、by_reason） | test_unknown_prediction_on_observable_positive_is_counted_as_a_miss；rejected 版本 |
| 2 | GT 可观测负例 + 预测 UNKNOWN/REJECTED | 不计 TN（也不计 FP） | 新类 NEGATIVE_UNOBSERVABLE：不记 TN，但**留在 N_neg**，negative_coverage=TN/N_neg 不被虚高 | test_unknown_prediction_on_absent_negative_is_not_credited_as_tn |
| 3 | GT 不可判定 / 完全遮挡无框 / ambiguous | 与预测 UNKNOWN 混在同一 UNOBSERVABLE 计数 | 单列 GT_UNOBSERVABLE（presence_class=GT_UNOBSERVABLE），**不进四格/任何分母**；gt_unobservable_by_reason 分 UNDECIDABLE / FULL_OCCLUSION / NO_VISIBLE_GT_BBOX / AMBIGUOUS；与预测 UNKNOWN **分桶、不合并** | test_gt_undecidable_frame_is_excluded_and_kept_separate_from_pred_unknown 等 |
| 4 | GT 参考点不可见的正例 | 已有：不算参考失败 | 保留：presence/recall 照评；**不进 anchor/bearing 误差分母**；若预测仍输出 keypoint 记为 false_reference（语义错误，单列） | test_unavailable_reference_positive_stays_in_recall_but_not_in_anchor_denominator |
| 5 | joint 分母 | present 且有 bbox+reference 标签 | **GT 可观测**且标签完整的正例；预测拒绝/UNKNOWN 计 joint 失败并**进分母**；未标注参考点只降低 coverage | test_unavailable_reference...；test_unknown... |
| 6 | 分层 | 无 | stratified_summary 六维度 + 每维度最差条件（分子/分母；分母 0 标 INSUFFICIENT_DENOMINATOR，不参与排名；并列取分母更大者） | test_stratified_summary_reports_worst_condition_with_denominators 等 |
| 7 | 会计一致性 | 无显式对账 | tp+fp+fn+tn+GT_UNOBSERVABLE+NEGATIVE_UNOBSERVABLE 必须等于帧数，否则 MetricDefinitionError | test_accounting_is_complete_across_all_presence_classes |

其它口径保持：presence precision=TP/(TP+FP)；recall=TP/(TP+FN)；identity precision=正确 claim/claims；identity recall=正确 claim/N_pos；高置信错误匹配 = 分数≥tau_conf 的错误 landmark_id 帧 / N_neg；joint 三口径同时报告（窄口径主判定、全正例下界、覆盖率）；bbox IoU 仅辅助诊断（分母=有 GT bbox 的正例）。

新增输出（metrics.json / summarize）：

- denominators 快照：frames / positives / negatives / gt_unobservable / negative_unobservable / reference_available / reference_unavailable / reference_not_labelled / joint_evaluable / positive_frames_with_gt_bbox / identity_claims；
- presence.unknown_rejected：total / on_positive / on_negative / on_gt_unobservable / by_status / by_reason；
- presence.fn_by_pred_status（FN 是 NOT_DETECTED 还是 UNKNOWN/REJECTED 一目了然）；
- reference.anchor_error_px 与 anchor_error_px_correct_only、bearing_error_deg 与 bearing_error_deg_correct_only（median/P90/max，count 即分母）；两个子集口径都给出，避免“只报正确子集”掩盖大误差；
- identity.claims_on_gt_unobservable（GT 不可观测帧上的 claim 不进精度/召回分母，单列）；
- gt_unobservable_by_reason（顶层）。

**旧测试相应改写**：原 test_unknown_observation_is_never_tn_or_fn 断言 UNKNOWN 不进 FN，正是本轮要修正的旧口径；已替换为 test_unknown_prediction_on_observable_positive_is_counted_as_a_miss（并保留 “UNKNOWN 永不记 TN” 的约束）。旧测试的其他语义（GT 参考点不可见不算定位失败、未标注参考点不算 joint 失败、单地标 identity 需负例才可评）全部保留。

---

## 6. 测试命令与结果（2026-11-04 本轮）

    cd E:\isaac\proj_boom_birds
    & 'E:\isaac\env_isaaclab\Scripts\python.exe' -m pytest -q
    # 本轮修复后最终全量：979 passed（2026-11-04；含 annot 并行改动；其他 teammate 并行改动可能使数字随后变化）
    & 'E:\isaac\env_isaaclab\Scripts\python.exe' -m pytest -q tests/evaluation/test_landmark_yolo.py tests/evaluation/test_landmark_metrics.py
    # 89 passed（61 + 28）

- 测试均为纯 Python（stdlib + PIL），**不导入 torch / ultralytics / onnxruntime / Isaac**；Isaac venv 未安装任何训练依赖，未修改。
- tests/evaluation/test_landmark_yolo.py（61 条）：letterbox 往返（参数化 4 组尺寸）、标签转换（可见/不可见/green_pixels 降级/缺席空标签/v2.1 confusers/四边截断对象/排除清单/文档计数/split 过滤/写盘 manifest/sha256）、推理解码（单候选/多候选 margin/低 kpt conf/贴边截断/小残片/绿色先验/裁剪/缺标定/非法图像/UNKNOWN）、ultralytics 与 ONNX 适配（源坐标与模型坐标两种）、GT 抽取与尺度分桶、脚本端到端（预计算 predictions → metrics.json；覆盖保护；缺后端明确报错）。
- tests/evaluation/test_landmark_metrics.py（28 条）：第 5 节表格中的每一行都有对应回归。

只读数据 smoke（不训练、不改数据）：

| smoke | 输入 | 结果 | 证据域 |
| --- | --- | --- | --- |
| pilot 标注 v2 转换 | outputs/perception/landmark_final_annotations_20261104/labels_v1.json（sha256 fe8d47d0…c8942，34 帧） | 25 正标签 / 9 空标签负例 / 排除 0；参考点可用 21、不可用 4；截断 10；occluded 0；undecidable/ambiguous 0；schema 校验通过（--root .） | 数据准备/格式 QA，不是模型效果 |
| v2.1 示例转换 | docs/reports/perception/annotation_verify_20261104/pilot/v2_1_example_annotations.json（sha256 90a0663c…f902，5 帧，annot 产物，只读） | 4 正 / 1 空标签负例；参考点 3/1；截断 2；排除 0 | 数据准备/格式 QA；v2.1 由 annot 生产 |

以上 smoke 的输出写在系统临时目录（不入库、不覆盖任何 teammate 的 outputs），仅用于证明转换器在真实标注上可执行。

---

## 7. 给 train（task-11）的运行命令

前提：在独立 .venv/landmark-train 内执行；PYTHONPATH 指向仓库 src；不写 final、不调阈值。

    cd E:\isaac\proj_boom_birds
    $py = '.venv\landmark-train\Scripts\python.exe'
    $env:PYTHONPATH = 'src'

    # 1) 语义标签 → YOLO 文本标签（按 split 分目录；空标签=确认缺席，excluded 只进 sidecar）
    & $py -m boom_birds.evaluation.landmark_yolo export --annotations outputs/perception/dev_annotations_20261104/labels.json --root . --split train --output-dir outputs/landmark_train/dataset/dev_train
    & $py -m boom_birds.evaluation.landmark_yolo export --annotations outputs/perception/dev_annotations_20261104/labels.json --root . --split val --output-dir outputs/landmark_train/dataset/dev_val

    # 2) 训练（数据 yaml 指向上面导出的 labels 与对应 images 目录；本任务不提供训练器）
    #    yolo pose train model=yolov8n-pose.pt data=<your yaml> imgsz=640 batch=16 seed=0 ...
    #    训练只读 val 选模/冻结阈值；不要看 final。

    # 3) 验证集评价（点估计 + 分层 + 最差条件）
    & $py scripts/evaluate_landmark_yolo.py --model outputs/landmark_train/train/seed0/weights/best.pt --images <val_images_dir> --labels <val_annotations.json> --split val --output-dir outputs/landmark_train/eval_val_seed0 --tau-iou 0.3 --tau-px 3.0 --tau-conf <frozen_tau_conf> --tau-det <frozen> --tau-margin <frozen>

    # 4) ONNX（若该阶段在范围内；需 onnxruntime）
    & $py scripts/evaluate_landmark_yolo.py --model best.onnx --images <dir> --labels <labels.json> --split val --output-dir outputs/landmark_train/eval_val_onnx

    # 5) final：预注册后仅一次；脚本默认拒绝覆盖已有 metrics.json
    & $py scripts/evaluate_landmark_yolo.py --model <frozen.pt> --images <final_images> --labels <final_annotations.json> --split test --output-dir outputs/landmark_train/eval_final_<date>

标签一致性约定（2026-11-04 修复后更新）：**不要**直接用 yolo_pose_target 的结果格式化 txt（它是模型画布归一化，只适合导出前的中间表示）；请用 landmark_yolo.convert_annotation_document / yolo_pose_label 得到 labels，或显式调用 format_yolo_pose_line(source_normalized_target(target, annotation))。逐字节比对请在“你的 builder 反变换后”与“我的 labels”之间做，格式为 8 字段、6 位小数；有 green_pixels 的 v2.1 子集按 sidecar 的 reference_downgraded 解释差异（标注语义差异，不是随机不一致）。

阈值提示：脚本里 tau_iou/tau_px/tau_conf 默认值只是占位（0.3/3.0/0.5，PROPOSED_NOT_FROZEN）。final 前必须用验证集冻结并把冻结来源写进预注册记录；final 后不得回调。

---

## 8. 未实现 / UNKNOWN / 需要后续处理

1. **真实模型推理未实测**：本 venv 无 ultralytics / onnxruntime；解码器只用 fake Results 对象与合成 ONNX 张量验证。真实 8.2.0 + torch 2.7.0 输出与解码器的数值一致性 = UNKNOWN（由 train 的隔离 venv smoke 承担）。
2. **ONNX 输出布局**：按 YOLOv8-pose 约定 (B, 4+nc+3k, N) 实现，并兼容 (N, C) 转置；未用真实导出模型核对 opset 18 / simplify=True 的实际布局 → UNKNOWN。
3. **kpt 置信度语义**：训练用 v∈{0,1}，推理连续 conf 与 tau_kpt 的关系未在真实权重上校准 → 阈值 PROPOSED。
4. **多候选 / TARGET_AMBIGUOUS / 遮挡**：拒绝逻辑有单元测试，但现有数据中无多候选、无 occluded 帧（pilot 34 帧 occluded=0）→ 相关分支**无真实数据证据**。
5. **identity 指标可评性**：单地标 + 现有数据缺 HN1/HN2 覆盖；没有相似结构负例时 identity 不可评（工具会标 evaluable=false / INCOMPLETE）。
6. **final 未执行**：本任务不读 final、不产生 final 指标；final 需预注册 + 一次性读取。
7. **v2.1 四边截断的采集侧元数据**：转换器支持并对冲突（capture vs annotator）记录 truncation_source/conflicts，但采集侧四边元数据由 capture 的 T9 提供；本轮未核对采集元数据是否齐全 → UNKNOWN。
8. **board/RKNN/部署**：完全未涉及（NOT RUN），不得由本工具链推导。
9. **数据准备 ≠ 模型效果**：pilot 34 帧与 v2.1 示例 5 帧的转换成功只证明格式/语义可执行，不构成任何精度、板端或导航结论。

---

## 9. 变更与引用

| 文件 | 关系 |
| --- | --- |
| src/boom_birds/evaluation/landmark_yolo.py（新增） | 标签转换 / letterbox / 解码 / GT 抽取 / export CLI |
| src/boom_birds/evaluation/landmark_metrics.py（修改） | 分母审计修正 + 分层最差条件 |
| scripts/evaluate_landmark_yolo.py（新增） | 分层评价入口（predictions.jsonl + metrics.json） |
| tests/evaluation/test_landmark_yolo.py（新增） | 54 条工具链回归 |
| tests/evaluation/test_landmark_metrics.py（修改） | 28 条分母口径回归（含旧口径改写） |
| src/boom_birds/evaluation/landmark_annotations.py（其他 teammate） | 本模块委托其 yolo_pose_target 与 validate_document；v2.1 侧车字段由 annot 并行补齐，本模块只读复用 |
| configs/perception/landmark_annotation_spec_v2.json / v2_1（annot） | 转换规则的规范来源（只读） |
| configs/perception/landmark_training_plan_v2.json | 指标分母与标注标签策略的机器可读版本（本任务未修改） |
| docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md | 任务/实验定义与分母口径（本任务未修改） |

本文件不修改合同、不更新 Gate、不改变许可状态；若后续任务定义或阈值冻结规则变化，需新编号并说明是否作废既有评价计划。

---

## 10. 勘误（2026-11-04 紧急修复）：YOLO 标签归一化坐标域缺陷

> **状态：** FIXED（含真实 ultralytics loader 复现证据）；旧导出结果作废，须重新导出
> **证据域：** 单元测试 + 真实 ultralytics 8.2.0 YOLODataset 标签读取（train 的隔离 venv，只读数据 smoke）+ train 独立复现

### 10.1 缺陷

export 路径（本模块委托的 landmark_annotations.yolo_pose_target）把 bbox/keypoint 按 **640 模型画布**归一化后直接写 txt。YOLO 要求 txt 按**源图尺寸**归一化：ultralytics 8.2.0 `LetterBox._update_labels` 先 `denormalize(*img.shape[:2][::-1])`（源图/加载图尺寸）再 `scale(ratio)`+`add_padding`，训练目标最后由 `Format` 再按 imgsz 归一化。因此模型画布归一化会被 loader 二次 letterbox：

- keypoint y 误差（源图像素） = 60 − 0.5·ky（本 320×240→640、pad_y=80 情形），ky∈[4,236] 时最大 ±58 px；
- bbox h 被压成 0.75·h（偏小 25%；一般情形为 src_h/src_w 因子）；
- x/cx/w 因 pad_x=0 且 scale=2 恰好与源图归一化同值，掩盖了缺陷。

train 的独立复现（用它自己的 loader 诊断）：旧标签读回 keypoint=(97.0, 310.25) px，而正确应为 (97.0, 307.0) px（ky=113.5），delta_y=+3.25 px —— 与公式 60−0.5·113.5=+3.25 完全一致。

### 10.2 修复

- 新增 `source_normalized_target(target, annotation, model_width, model_height)`：用 `target['letterbox']` 的 scale/pad 做逆变换：
  - bbox：model 归一化 → model 像素 → `bbox_from_model` → 源图像素 → 除以源图宽高（cx/cy 用中心）；
  - keypoint/占位点：model 归一化 → model 像素 → `point_from_model` → 源图像素 → 除以源图宽高；
  - 标注 `label_normalization=SOURCE_IMAGE_PX_OVER_SOURCE_SIZE`。
- `yolo_pose_label` 在格式化前调用该函数；sidecar 增加 `label_normalization` 与 `label_space_note`。
- 坐标域自查（lead 要求）：
  - **标签空间**：源图归一化（本修复）；
  - **模型输入/损失空间**：loader 自己 letterbox，不做任何手工预归一化；
  - **解码/指标空间**：decoder 输出**源图像素**（ultralytics 结果默认已回源图坐标；ONNX 经 Letterbox 逆变换），GT 从 annotation 取**源图像素**，bearing 用源图像素 + pixel_basis 的 fx/cx。评测入口未使用模型画布归一化，故 `ground_truth_from_annotation`/decoder/metrics 不受该缺陷影响（已逐项自查）。

### 10.3 验证证据（不把“测试通过”当修复证据）

1. **真实 loader 复现**：在 `.venv/landmark-train`（ultralytics 8.2.0）用 `YOLODataset(task='pose', imgsz=640, augment=False)` 读取修复后的 8 字段 txt（源图 320×240，bbox=[97,106,83,74]，keypoint 源图 (48.5,113.5)）：

   | 量 | loader 输出（按 640 画布归一化） | 期望 | delta |
   | --- | --- | --- | --- |
   | bbox cx,cy,w,h | 0.432812, 0.571875, 0.259375, 0.231250 | 0.432812, 0.571875, 0.259375, 0.231250 | 0.0 |
   | keypoint x,y | 0.151562, 0.479687 | 0.151562, 0.479687 | 0.0 |
   | keypoint 模型像素 | (97.0, 307.0) | (97.0, 307.0) | 0.0 |

   导出的 txt 为 `0 0.432812 0.595833 0.259375 0.308333 0.151562 0.472916 1.000000`（源图归一化）。
2. **单元回归（新增 7 条：4 条坐标域 + 1 条幂等 + 2 条上游坐标空间声明/校验，在 61 条 test_landmark_yolo 内）**：
   - `test_label_normalization_is_source_relative_not_model_canvas`：断言 cy=143/240 且 ≠ 旧错误值 366/640；
   - `test_exported_labels_survive_the_loader_letterbox_roundtrip`：模拟 loader（源图归一化→源图像素→letterbox）得到模型像素 bbox 中心 (277,366)、wh (166,148)、keypoint (199.8,299.8)；
   - `test_exported_label_roundtrips_back_to_source_pixel_geometry`：txt 反归一化回源图像素 = 标注像素；
   - `test_non_square_letterbox_padding_keeps_bbox_and_keypoint_source_relative`：160×120 源图（scale 4、pad_y 80）验证非方形 padding 下仍源图归一化；
   - `test_source_normalized_target_never_transforms_twice`：带 label_normalization 标记的 target 不会被二次变换（防 annot 改语义后 double conversion）；
   - `test_upstream_declared_model_canvas_space_is_converted_and_recorded` / `test_unknown_upstream_coordinate_space_fails_loud`：上游 coordinate_space=MODEL_CANVAS_NORMALIZED 时正常反变换并记录；声明未知坐标空间时 fail-loud 而非静默错标。
   原有 3 条标签数值断言同步改为源图归一化期望（旧断言本身固化了缺陷，已改写）。
3. **全量回归**：Isaac venv `-m pytest -q` 结果见 §6（本轮修复后重跑，其他 teammate 并行改动可能使数字随后变化）。

### 10.4 影响与后续

- 本轮之前由该转换器导出的任何 YOLO 标签**全部作废**，必须重新导出；train 之前 30 epoch 的过拟合实验使用错误标签，判定**无效**，不能作为方法/数据/模型能力的任何结论。
- `landmark_annotations.yolo_pose_target` 仍返回**模型画布归一化**，export 在 `landmark_yolo` 侧转换。**annot 已于 2026-11-04 完成语义澄清**：docstring 写明 model-canvas≠YOLO txt，返回 dict 增加 `coordinate_space=MODEL_CANVAS_NORMALIZED`，故意不设 `label_normalization`（不触发幂等旁路），未改数值/未改标签数据，并加单测锁定该声明。export 侧已配合加入 fail-loud 校验（未知 coordinate_space 直接报错）与 sidecar 字段 `source_target_coordinate_space`，后续 dataset 导出仍以 `convert_annotation_document/yolo_pose_label` 为唯一出口。
- 该缺陷只影响标签落盘；不影响 `evaluate_landmark_yolo.py` 的 GT/解码/metrics 坐标域。
- 不提升任何 Gate；不改变许可状态；final 仍未读取。