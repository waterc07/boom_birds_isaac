# Two-class 语义/掩码/GT 审查与数据风险（task-35，2026-11-05）

> **状态：** PRE_DATA_REVIEW / PROPOSED（预注册协议与标签规范的独立审查；T30 采集 in_progress，v6 two-class 标签尚未产出；**不是**训练结果、**不是**能力/认证结论、**不是**对旧包的修改）
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §7.4/§7.5/§7.6/§7.7/§9.1/§11.1/§20.2；configs/perception/landmark_two_class_protocol_v1.json（PRE_REGISTERED，sha b3701461…）与 landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05，sha 8e544efc…）；T31 标注 prep（sha 33c09af5…）
> **证据域：** 离线文档/代码审查 + 安装版 ultralytics 8.2.0 loss 的 CPU tiny-tensor 独立复算 + dev-only 位姿投影估计（无图像/无推理/无训练/无 Isaac）
> **最后核对：** 2026-11-05（HEAD 47d1063；two-class 文件尚未 commit，审查按现场 sha）

---

## 0. 结论先行

| 项 | 结论 | 证据域 |
| --- | --- | --- |
| 标签规范/GT 语义 | **基本对齐但存在 3 个 HIGH 缺口**：class1 语义范围（地图原生 MS1 vs 合成注入）、未验证/其他相似结构无显式记录、同框完整性无法仅靠标签自证 | 文档审查 §1 |
| loss mask | **PASS**：class1 v=0 对 keypoint 坐标 loss 贡献严格为 0；class0 v=1 正常监督；visibility 对 class1 监督为 0；v=2 会被当 visible，builder/QA 必须只允许 {0,1} | CPU 复算 §2 |
| 推理无 GT | **PASS_WITH_ONE_FINDING**：model.predict 仅传图像、decoder 只用预测 class/score/bbox/kpt；但 two-class decoder API 当前接收整行 truth_row（仅读 frame_id），存在架构耦合，须在 P2 前重构并加 poison/rename 测试 | 静态审查 §3 |
| v4.1 未标注 MS1 风险 | **实际训练输入 436 帧中 69 帧（15.8%）投影可见 MS1**；其中 38 帧有塔标签但 MS1 未标（同框遗漏）、31 帧空标签但 MS1 可见（当背景）→ 若原样复用会直接抑制 class1/同框选择率 | 位姿投影 §4 |
| 两类分母/认证边界 | 分母已定义（塔 95 / MS1 35 对象 / 同框 26 / MS1-only 9 / GT_UNOBS 9）；two-class 只做限定域“塔 vs 已验证 MS1”，不是开放集；dev 不得认证，过门才采 holdout | §5 |

一句话：**协议方向与掩码实现正确；当前最大风险是“class1 语义被扩大”和“v4.1 单类标签里 15.8% 的实际训练帧把可见 MS1 当背景/遗漏”，必须在标注与训练前用预注册规则解决。**

---

## 1. 标签规范与 GT 语义审查（①）

### 1.1 已满足的要求

- 协议明确 class1 **永不**映射中央塔 landmark_id，且 class1 不是开放集 catch-all。
- 标签规范要求 class1 keypoint 恒不可用（v=0）、禁止 bbox 中心替代、同框两类可见实例必须全部标注、MS1 不得当背景、难例不删除、TINY 单列。
- T31 schema 明确了坐标域（bbox=source pixels XYXY；keypoint=normalized [0,1]）、GT_UNOBSERVABLE 表示（tower_present=true + occlusion=FULL + 无 class0 instance）、QA fail-loud 框架，与协议不冲突。
- two-class 评测模块（evaltool，任务 34）已按协议实现：class0-only claim、class1 永不映射、class conflict→UNKNOWN、同框选择率、MS1-only 错误塔声明、reference/bearing/consumer 四域；单类冻结 v2 基线同口径 class1 recall 0/35 是结构性（无 class1 通道）。

### 1.2 发现（详见 TWO_CLASS_SEMANTICS_REVIEW_20261105.json）

| ID | 严重度 | 发现 | 必须的解决 |
| --- | --- | --- | --- |
| S1 | HIGH | 规范定义 class1=已验证地图原生 MS1；T31 允许 EXTERNAL_EVIDENCE（合成注入）也标 class1 → 合成 HN1 与 map-native MS1 混类，违反“class1 非开放集/非任何相似结构” | class1 仅限 map-native MS1（verified_source=WORLD_POSE_OR_MAP_DB + map-DB 记录）；合成 HN1 进 other_structures/confusers，单列评测；若要合并类，先升 spec v1.1 并声明语义 |
| S2 | HIGH | 未验证绿色/塔状结构（MS2、未知绿灯、机器人/gantry、合成 confuser）没有显式记录字段；不标=背景，但模型仍可能输出 class0/class1 → 错误身份声明必须被计数 | 增加 other_structures[]/confusers（verified=false）；永不赋 class1；评测单列“未验证/其他结构”分母并计塔 claim 为错误 |
| S3 | HIGH | 同框完整性无法仅由标签自证；标签 QA 只能查“已写的是否合法”，不能查“有没有漏” | v6 QA 加位姿投影完整性 gate：投影 MS1 高度>=8px 的帧必须有 class1 instance 或 gt_uncertainty=INSTANCE_UNRESOLVED（塔同理）；否则 FAIL。方法见 §4，脚本 scripts/v41_ms1_risk.py（投影标定中位 0.04px） |
| S4 | MEDIUM | class1 无最小可判定尺寸/遮挡规则，远景 MS1 可能被猜框 | 定义 bbox 高度>=8px（保守 10px）且非全遮挡才建 instance；否则 INSTANCE_UNRESOLVED；class0 同规则 |
| S5 | MEDIUM | identity_ambiguity/gt_uncertainty 枚举由 T31 提议但未进入 FROZEN spec；训练/评测处理未预注册 | 在标注前冻结为 spec v1.1/协议 addendum；明确 GT_UNCERTAIN 不评定位、单列 improper claim；训练是否排除需写清 |
| S6 | MEDIUM | class1 keypoint 必须“永不参考”，但 YOLO txt 仍需 x,y；若写 bbox 中心不会改变 loss（masked）却留下隐患 | builder 写 0,0,v=0（禁止 bbox 中心）；round-trip 测试 |
| S7 | MEDIUM | ultralytics 8.2.0 loader 只校验坐标/非负，**v=2 会被 loss 当 visible**（复算已证）；typo 可静默恢复监督 | builder/QA 只允许 v∈{0,1}；加 v=2 拒绝测试 |
| S8 | MEDIUM | class1 的 verified_source 未被规范强制 | 强制 WORLD_POSE_OR_MAP_DB + map-DB 交叉链接；缺则 FAIL |
| S9 | LOW | T31 QA 无 class0/class1 跨类 bbox 重叠检查 | 跨类 IoU<0.3（除非显式 ambiguity 记录） |
| S10 | LOW | 截断（贴边）与遮挡（物体遮挡）规则需分开；T31 的贴边 QA 不能误用于遮挡框 | 分开 truncated/occluded 字段与 QA |
| S11 | LOW | GT_UNOBSERVABLE 表示与协议一致（正向确认），但 loader 必须写空标签而非负例 | 加 FULL occlusion loader/eval 测试 |
| S12 | INFO | 坐标域虽已明确，但正是上次 label bug 的根源 | loader 内 /W,/H 转换 + round-trip <=0.001px + coordinate_space 字段 |

---

## 2. Loss mask 独立复核（②）

来源：安装版 ultralytics 8.2.0 .venv/landmark-train/Lib/site-packages/ultralytics/utils/loss.py（sha 7a35e73c…）：

- 行 581：kpt_mask = gt_kpt[..., 2] != 0；行 582：kpts_loss = keypoint_loss(pred_kpt, gt_kpt, kpt_mask, area)；行 585：kpts_obj_loss = bce_pose(pred_kpt[..., 2], kpt_mask.float())。
- KeypointLoss.forward（行 139-145）：kpt_loss_factor = kpt_mask.shape[1]/(sum(kpt_mask)+1e-9)，(kpt_loss_factor * ((1-exp(-e)) * kpt_mask)).mean() → v=0 严格乘 0。

独立复算（CPU，2 instance：row0=class0 v=1，row1=class1 v=0；结果 JSON TWO_CLASS_LOSS_MASK_AUDIT_20261105.json，verdict **PASS**）：

| 实验 | 结果 |
| --- | --- |
| 基础 location loss | 0.500000 |
| 扰动 class1 xy（v=0） | 0.500000（**完全不变** → 不贡献） |
| 扰动 class0 xy（v=1） | 0.478032（变化 → 正常监督） |
| class1 v=0 的 visibility loss | kobj=0.791（target=0，监督“无 kpt”） |
| class1 v=2（错误写法） | mask=visible，扰动坐标 loss 变化 → **v=2 会恢复监督** |
| class0 v=1 | mask=visible，正常 |

注意点（必须写进 train 实现/QA）：
1. class1 的 **bbox/cls 仍正常监督**（这是期望的：要检出 MS1），只有 keypoint 坐标被 mask；visibility 目标为 0 是期望行为，不是泄漏。
2. mask 是 class-agnostic 的，two-class 语义完全由标签决定；标签写错类别/ v 会直接反映为 loss 语义错误。
3. 1-keypoint 场景 kpt_loss_factor 对 v=0 为 1e9 但乘 0，数值安全（复算无 NaN/inf）；不要因此省略 mask。
4. 必须用真实 v6 标签做一次 mask 回归：取一条 class1 v=0 行与一条 class0 v=1 行，经 loader 后复算 mask 与贡献（P2 engineering smoke 必做）。

---

## 3. 推理无 GT 输入检查（③）

静态审查（HEAD 47d1063 现场，相关文件 sha 见 JSON）：

| 检查 | 证据 | 结论 |
| --- | --- | --- |
| 模型只接收图像 | evaluate_landmark_yolo.py:151-152（source=image path）；evaluate_landmark_two_class.py:136-138（source=image_path） | PASS |
| decoder 不用 GT 几何/位置/类别 | landmark_yolo.decode_ultralytics_result 参数 = results/尺寸/内参/阈值/frame_id/image；decode_candidates 只吃 candidates | PASS |
| 部署路径只吃 v2 observation payload | landmark_consumer.py:123-128；landmark_detector.py:3-5,42-43 | PASS |
| 身份 claim 只用预测 class/score/bbox/kpt | landmark_two_class_eval.decode_detections：class0-only claim、class1 不映射塔、conflict/margin 拒绝 | PASS |
| 无 oracle/GT position/文件名解析进入推理决策 | decode 函数不解析文件名、不读 oracle/position；image 字符串仅记录 | PASS |
| GT 行未进入推理 decode API | evaluate_landmark_two_class.py:140-141 传 truth_row；module decode_detections 签名含 truth_row，内部仅用 frame_id（:438） | **RISK（API 耦合，当前无值泄漏）** |
| 评测的图像定位/配对 | _resolve_image(images_dir, truth_row) 用 truth 的 image/frame_id 定位文件（评测面）；部署用 payload.ref（G3） | PASS_WITH_DOCUMENTATION |
| 标签只在推理后计分 | 评测脚本先加载标签用于配对，后跑 predict/decode；evaluate_frame 在预测之后 | PASS_WITH_DOCUMENTATION |

**必须修复/验证（P2 前）**：
1. 把 decode_detections(detections, truth_row, ...) 改成 decode_detections(detections, frame_id, ...)，truth_row 只留在 evaluate_frame；这是把“无 GT”从行为变成结构约束。
2. GT-poison 测试：改乱标签里所有 bbox/kpt/class/position（保留 frame_id），同模型推理 → observations 必须逐字节一致（只有计分行可变）。
3. 文件名独立性测试：把图像重命名成带 tower/ms1 误导 token，observations 必须一致。
4. 静态护栏测试：decode/predict 函数源码不得出现 oracle/ground_truth/target_world/position 访问。
5. class1 即使预测 keypoint 置信度很高也不得输出 landmark_id 或参考点；class conflict→UNKNOWN。

### 3.1 复审：R1 修复后（2026-11-05，evaltool 修复；P2 冻结前复核）

evaltool 按 T35 R1 修复并补测（module sha db8ca0e8…、CLI 006c5e09…、tests febb847d…保持；report 复审时 ddbfc588…，后续仅报告内容更新为 36c25aff…，代码 sha 不变；本审计复跑 tests/evaluation/test_landmark_two_class_eval.py → 21 passed）：

- decode_detections(detections, frame_id, protocol) 只收 frame_id；传 truth dict 直接抛 TwoClassEvalError（:425、:433-435），结构性隔离。
- 推理走 infer_observations(model, truth_rows, images_dir, protocol)：只使用 frame_id + 图像路径；truth_row 只在 evaluate_frame 计分（:1056-1080）。
- 新测试：GT-poison（改乱 GT bbox/kpt/class/position → observations 逐字节一致，:487-516）、rename 独立性 + 传 GT 拒绝（:475-484）、静态 guard（decode/adapter/infer 源码无 gt_*/ground_truth/oracle/target_world，:528-533）。
- class1 范围一致：_route_confuser 只把 map-native 非合成 confuser 归 class1（:289-301）；合成/未验证/其他进 other_structures（:590-651，塔 claim 计 OTHER_STRUCTURE），与 T35 S1/S2 建议一致。
- 复审结论：**R1 PASS（已修复）**，G1-G11 全部 PASS；剩余为文档性（评测图像定位仍用 truth 的 image/frame_id 配对，部署用 payload.ref）与 P2 动态 poison 回归（真实 v6 标签 + 冻结模型）。
- 证据：docs/reports/perception/posteval_20261104/TWO_CLASS_GT_ISOLATION_AUDIT_20261105_V2.json（V1 sha a5267429… 保留为决策记录）。

---

## 4. v4.1 单类训练帧未标注 MS1 的风险估计（④）

方法（只读，无图像/无推理）：对 v4.1 训练池 1697 accepted 帧，用 sensor observation 的 world 相机位姿（position + quat_w_world）把 MS1 柱（map-native (3.0,4.0)，top z=1.78、lamp z=1.71、base z=0）与中央塔灯投影到图像；标定用 dev capture 的 tower_projection 对照 327 帧：中位误差 **0.04px**、max **0.07px**。可见判据：MS1 投影高度>=8px（可判定）/>=20px（清晰）；无遮挡测试 → 结果为投影可见上界。

**分母 1：v4.1 训练池** 1697 accepted 帧 → MS1 可见 443（26.1%），>=20px 432（25.5%）。
**分母 2（关键，实际训练输入）** v4.1 实际 image<->label 1:1 输入 **436 帧**（labels_train_v4_1_merged 439 帧、excluded 3；dataset_build train label_files 436）→ **MS1 投影可见 69 帧 = 15.8%**（>=20px 65=14.9%），投影高度 19.5–79.9px。

| 分组（实际输入 436） | 帧数 | 说明 |
| --- | ---: | --- |
| 塔标签正例但 MS1 可见未标（同框遗漏） | **38** (8.7%) | 正是 pilot 门要考的同框消歧场景，却被教成“MS1 不在” |
| 空标签负例但 MS1 可见（当背景） | **31** (7.1%) | 直接把 MS1 学成背景 |
| 合计受影响 | **69** (15.8%) | 若 v4.1 单类标签原样复用 |
| 家族分布 | fam_south_A 41、lmf_similar_negative 15、fam_dev_static_negative 8、static_E_test 2、static_W_start 2、static_E_dev 1 | 集中在 dev_south_new 航线与 static negative |

**后果**：class1 recall、同框目标选择率（pilot 门>=0.60）最受打击；class0 不受直接影响。**这不是 two-class 模型的结果**，是复用单类 v4.1 标签的训练数据风险。

**缓解（预注册，二选一）**：
- A. 排除：从 two-class train pass 中排除投影 MS1>=8px（或 20px）的 69（65）帧；损失 15.8%（14.9%）v4.1 输入，无矛盾监督。
- B. 补标：给这 69 帧补 class1 instance（同框完整性）；最高价值是 38 个同框帧；成本 69 帧标注+QA。
- C. 忽略区/loss mask：ultralytics 8.2.0 无 per-region ignore，不建议。
- **建议**：预算允许时 B（38 同框帧优先），否则 A；无论哪种，在 v6 标签上重跑本投影检查，若受影响帧缺 class1 且未被显式排除 → 标签 gate FAIL。

**限制**：无遮挡/地形/动态物测试，投影可见是上界；MS1 宽度用轴近似；v6 two-class 标签尚不存在（T30 采集中）；若 v6 对 v4.1 全量重标则风险消除。

---

## 5. 两类评测分母与认证边界（⑤）

| 维度 | 分母/口径 | 备注 |
| --- | --- | --- |
| 塔类混淆 | val_main 可观测塔正例 95 + 负例；每类 TP/FP/FN/precision/recall | val_main 的 MS1 附加标注 PENDING（T32） |
| 身份 precision | class0 claims（经 conflict/margin 拒绝后的塔 claim） | class1 永不进 claim 分子 |
| 身份 recall | identity 池可观测塔实例 44 | 与 claims 分母分开 |
| 同框消歧 | 同框 26 帧：tower_selected / ms1_selected / not_selected；选 MS1=错误，拒绝=UNKNOWN 单列 | pilot 门>=0.60、holdout 门>=0.70 |
| MS1-only 错误塔声明 | 9 帧（帧级）/35 MS1 对象（对象级） | pilot 门<=1 帧；holdout 门<=0.05 |
| false match | 负例分母（含 MS1-only 9 与其他负例） | 单类基线 0/9 只是 dev 上界 |
| reference availability | N_avail=18（identity 池塔参考可见）；N_unavail=26；coverage=correct/N_avail；correct refusal/false reference 单列 | class1 keypoint emissions 必须 0 且单列 |
| bearing | GT 塔参考可见且发射 kpt：median/P90/max、<=3° 计数 | 3° 为 PROPOSED；2D px 仅诊断 |
| consumer 四域 | all-positive 121、observable-positive、reference-available、negatives；UNKNOWN/REJECTED/无输出留在适用分母 | GT_UNOBS/GT_UNCERTAIN 单列，不删难例；TINY 留 all-domain 单列 |
| GT_UNOBSERVABLE | identity 池 9 帧；保持 all-domain，单列 improper claim / correct abstention | 不是负例，不评定位 |

**认证边界（不声明）**：
1. two-class 只解决“中央塔 vs 已验证 map-native MS1”的限定域辨识，**不是开放集身份识别**；class1 不覆盖 MS2/未知绿灯/机器人/合成注入（按 S1/S2 处理）。
2. class1 永不得映射中央塔 ID；class conflict/多候选/低置信/参考不可用 → 显式 UNKNOWN/REJECTED。
3. dev 结论不认证；只有过 development→holdout 门后才允许新 untouched holdout v3（>=3 新族/200–400 帧，采样先冻结，一次性评价，process-isolated 非第三方 sealed）。
4. 无板端/RKNN/真实相机/真实赛场；延迟/热行为 UNKNOWN。
5. T25/T26 provisional diagnostic 帧不进任何分母；旧包/旧模型/旧协议保持封闭、不改。
6. 单类 v2 基线 class1 recall=0 是结构性（无 class1 通道），是参照点不是退化。
7. 不自动恢复“认证级路线”：two-class 身份 precision 必须自己过门；class0 claim 仍受 score/conflict/appearance/reference 规则约束。

---

## 6. 证据与复现

| 内容 | 路径/sha |
| --- | --- |
| 协议（PRE_REGISTERED） | configs/perception/landmark_two_class_protocol_v1.json（sha b3701461…） |
| 标签规范（FROZEN） | configs/perception/landmark_two_class_label_spec_v1.json（sha 8e544efc…） |
| T31 标注准备（PROPOSED schema/QA） | docs/reports/perception/annotation_verify_20261104/T31_TWO_CLASS_ANNOTATION_PREP_20261105.md（sha 33c09af5…） |
| 语义/GT 发现 JSON | docs/reports/perception/posteval_20261104/TWO_CLASS_SEMANTICS_REVIEW_20261105.json |
| loss mask 复算 JSON | docs/reports/perception/posteval_20261104/TWO_CLASS_LOSS_MASK_AUDIT_20261105.json（PASS） |
| GT isolation 审查 JSON（V1 决策记录 + V2 修复后复审 PASS） | docs/reports/perception/posteval_20261104/TWO_CLASS_GT_ISOLATION_AUDIT_20261105.json、TWO_CLASS_GT_ISOLATION_AUDIT_20261105_V2.json |
| v4.1 池级风险 JSON | docs/reports/perception/posteval_20261104/V41_UNLABELED_MS1_RISK_20261105.json |
| v4.1 实际输入风险 JSON | docs/reports/perception/posteval_20261104/V41_MS1_RISK_ACTUAL_INPUTS_20261105.json |
| 投影风险脚本 | docs/reports/perception/posteval_20261104/scripts/v41_ms1_risk.py |
| mask 复算脚本 | docs/reports/perception/posteval_20261104/scripts/two_class_mask_check.py |
| two-class 评测（evaltool，基线） | docs/reports/perception/TWO_CLASS_EVAL_20261105.md；src/boom_birds/evaluation/landmark_two_class_eval.py（sha 8ba54cfb…，审查时点） |

复现：
    E:\isaac\env_isaaclab\Scripts\python.exe docs/reports/perception/posteval_20261104/scripts/v41_ms1_risk.py
    .venv/landmark-train/Scripts/python.exe docs/reports/perception/posteval_20261104/scripts/two_class_mask_check.py

---

## 7. 限制与不声明

- 本审查是 **pre-data**：T30 采集 in_progress（审查时 sensor 目录 279 张、无 run.complete/episodes）、v6 two-class 标签不存在；标注/训练时必须以 v6 实际产物重新跑 S3/S6/S7/S12 与 mask 回归。
- 投影风险是位姿投影上界（无遮挡/动态物），且只针对“复用单类 v4.1 标签”的场景。
- loss mask 复算是 CPU tiny-tensor + 安装版源码，不是训练运行；真实 v6 loader 断言仍须 P2 执行。
- GT isolation 是静态审查；two-class 模型尚不存在，动态 poison/rename 测试待 P2。
- 不声明 two-class 能力、身份认证、开放集识别、板端/实机/导航；不修改旧结果/模型/协议/hash；不接控制/PPO/不提升 Gate。
