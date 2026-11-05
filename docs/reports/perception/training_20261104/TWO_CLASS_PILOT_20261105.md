# Two-class 身份通道 R1 pilot（15ep seed0，dev 验证域）2026-11-05

> **状态：** BASELINE（dev 验证集有界实验；不是认证/板端/导航证据）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json（PRE-REGISTERED）、landmark_two_class_label_spec_v1.json（FROZEN）、v6.1 freeze（B-lite）
> **证据域：** 仿真 dev val_main 163 帧 + identity 62 帧；训练 800 图（v4.1 427 + T30 pool 373 + addendum 60）；无 Isaac 运行、无 holdout、无板端
> **最后核对：** 2026-11-05

## 0. 结论（训练侧提供，pilot 门判定由 lead 汇总）

- R1（从冻结单类 v5 权重 6b86ef1f 直接微调，nc=2）15ep seed0 训练完成：wall 159.42 s、峰值显存 1968.4 MiB、无早停（patience 20 > 15）。
- 不可变快照 v7：snapshot sha a9388f9b…，pre_train / pre_selection / post_train 三阶段全部 **VALID**（22 artifacts、0 mismatch）。
- 训练侧指标（本报告 §4，筛选口径）显示：val tower 78/95=0.821、identity MS1 10/35=0.286、MS1-only 错误塔声明 0/9、同框选择 10/26=0.385、identity P 1.000。
- evaltool 正式 consumer 指标（§5，以它的口径为准，已用最终预测 sha 重算）：**pilot_to_three_seed gate FAIL**，**唯一硬失败是 MS1 recall** —— identity 10/35=0.286（last）/7/35=0.200（best）、val_main 20/47=0.426/14/47=0.298，均 < 0.50；其余 7 条条件 PASS（tower recall、MS1-only 错误塔 claim 0、同框选择、identity precision、consumer confirmed success、bearing median、相对基线回退）。按协议 on_fail 拒绝该 recipe，不增加 epochs/seeds/candidates，**未进入 3 seed**。
- 亮点：two-class 把 identity 塔召回 0.977（last；单类冻结基线 0.659）和 val 同框选择 0.787（基线 0.766）拉高；MS1 通道仍不合格。

## 1. 数据与训练配置（v6.1 B-lite，A 方案不用）

| 项 | 值 |
| --- | --- |
| freeze | configs/perception/landmark_split_freeze_v6_1.json file sha 424642d4…，canonical fe3fa426…，train 24 组/2288 帧，val 14 组/1006 帧 |
| train 标签 | v4.1 427（436 实际输入排除 9 帧未覆盖投影风险；排除清单在 freeze.two_class.train_v41_exclusion）+ addendum class1 60 帧（annot 38 + annot2 22，同框 38）+ T30 pool 373（A 181 + B 192；class0 232、class1 123；同框 39） |
| 合并后标签 | labels_train_v6_merged.json sha 86b36772…；T30 merged sha 4beac2f8…；v4.1+addendum 文档 sha 440cd37c… |
| dataset | dev_v6：train **800 图/800 标签**（class0 575、class1 183、同框 77；空负例保留、GT_UNOBS 3 排除）；val **134/134**（95 pos + 39 负例，GT_UNOBS 29 排除）；data.yaml sha f20d33d2；dataset_build sha 36174618 |
| 模型 yaml | outputs/landmark_train/dataset/landmark_yolov8n-pose-2class-1kpt.yaml（nc=2，names central_tower/similar_structure_ms1，kpt_shape [1,3]）sha d6e6a46d |
| 初始化 | stage_verify_v5/seed2/seed2/weights/last.pt sha 6b86ef1f（单类）→ nc=2 head 重建；batch16、imgsz640、AMP、warmup 15、patience 20、≤15ep |
| 选模 | tower recall（val_main）→ MS1 recall（identity）→ class0 claim precision；选中 **last**（权重 sha 508a0430…） |

## 2. 不可变运行快照（v7）

- run_snapshot.json sha **a9388f9b…**；22 tracked artifacts；pre_train VALID（12:09 前后）、pre_selection VALID（12:19:53）、post_train VALID（12:19:55）。
- 快照 manifest：configs/perception/landmark_run_snapshot_v7.json sha b6575568…；20+2 artifacts（含 v6.1 freeze、两份 addendum、shard A/B、val MS1、exclusion、base weights、model yaml、dataset_build/data.yaml）。

## 3. pilot 门（训练侧筛选口径，非最终判定）

| 条件（protocol） | 训练侧值 | 训练侧判定 | evaltool 正式值 | 正式判定 |
| --- | --- | --- | --- | --- |
| tower recall val_main ≥0.70 | 78/95=0.821 | PASS | 78/95=0.821（last） | PASS |
| MS1 recall identity ≥0.50 | 10/35=0.286 | FAIL | 10/35=0.286（last）/7/35=0.200（best） | FAIL |
| MS1-only 错误 tower 声明 ≤1 | 0/9 | PASS | 0/9（last 与 best） | PASS |
| 同框选择 ≥0.60 | 10/26=0.385（训练侧双匹配口径） | FAIL | 37/47=0.787（val last）、26/26=1.000（identity last） | PASS |
| two-class identity precision ≥0.95 | 1.000（48 claims） | PASS | 76/76=1.000（val last）、43/43=1.000（identity last） | PASS |
| bearing median ≤3° | 0.822°（val）/1.194°（identity，raw kpt） | PASS | 0.822°/1.901°（val last）、1.194°/4.178°（identity last） | PASS（中位） |
| tower recall 不比单类基线差 >0.08 | 0.821 ≥ 0.821−0.08 | PASS | 0.821 ≥ 0.741 | PASS |
| consumer confirmed success ≥0.30 | PENDING（evaltool） | — | all-positive 72/121=0.595（val last）、37/53=0.698（identity last） | PASS |

**综合：pilot_to_three_seed gate FAIL，唯一硬失败为 MS1 recall（identity 0.286/0.200、val 0.426/0.298 均 <0.50）；其余 7 条 PASS。** 按协议 on_fail 拒绝该 recipe、停止，不进入 3 seed/holdout；R2 仅在书面失败原因下启用（lead 已批准一次 R2 pilot，见 §9）。

## 4. 训练侧指标（筛选口径：tau_det 0.25、tau_iou 0.3、tau_px 3px；分母显式）

| 集合 | 指标 | 值 |
| --- | --- | --- |
| val_main 163 | tower recall | 78/95 = 0.821 |
| val_main 163 | tower claim precision | 79 TP / 11 FP = 0.878 |
| val_main 163 | reference coverage（kpt 3px） | 8/41 = 0.195 |
| val_main 163 | false reference（raw kpt 计数） | 44/54 |
| val_main 163 | bearing median / P90 | 0.822° / 1.963°（n=34） |
| identity 62 | MS1 recall | 10/35 = 0.286 |
| identity 62 | MS1-only 错误 tower 声明 | 0/9 |
| identity 62 | 同框选择 | 10/26 = 0.385 |
| identity 62 | identity claim precision | 1.000（48 claims） |
| identity 62 | reference coverage（3px） | 6/18 = 0.333 |
| identity 62 | bearing median / P90 | 1.194° / 3.411°（n=17） |

注：训练侧与 evaltool 的 tower/MS1 计数差异来自匹配口径（IoU 阈值/匹配策略）与 reference 无效坐标过滤；**pilot 门以 evaltool 正式数字为准**，训练侧数字仅作筛选与交叉核对。

## 5. evaltool 正式 consumer 指标（三口径，confirmed_only 主表）

| 集合 | 候选 | tower | MS1 | claims（correct/wrong） | 同框 | ref cov | bearing median/P90 | all-positive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| val_main 163 | last | 78/95=0.821 | 20/47=0.426 | 76 / 76 / 0（P1.000） | 37/47=0.787 | 33/41 | 0.822° / 1.901° | 72/121=0.595 |
| val_main 163 | best | 73/95=0.768 | 14/47=0.298 | 73 / 73 / 0（P1.000） | 32/47=0.681 | 35/41 | 0.751° / 1.911° | 70/121=0.579 |
| identity 62 | last | 43/44=0.977 | 10/35=0.286 | 43 / 43 / 0（P1.000，FMR 0） | 26/26=1.000 | 17/18 | 1.194° / 4.178° | 37/53=0.698 |
| identity 62 | best | 38/44=0.864 | 7/35=0.200 | 38 / 38 / 0（P1.000，FMR 0） | 20/26=0.769 | 18/18 | 1.892° / 3.476° | 35/53=0.660 |

注：以上为 evaltool 用最终预测 sha 重算的 confirmed 口径（pilot_v61_current，evidence shas 2f1b493f…）；同口径单类冻结基线：val tower 0.821 / MS1 0 / claims 80 wrong4 / 同框 0.766 / all 0.612；identity tower 0.659 / MS1 0 / claims 29 wrong0 / 同框 0.423 / all 0.509。

## 6. keypoint (0,0) 语义（已用 raw 推理复核）

- 对最终权重 last.pt 的 raw 推理：keypoints.data = [x, y, kobj_conf]，观测样本为 [0, 0, 0.0025]、[0, 0, 0.239]、[0, 0, 0.0002] —— **坐标恰为 0、kobj 为非零低值**；不是保存/解码 sentinel（ultralytics Results.xy 直接返回解码坐标，无清零逻辑）。
- GT ref-visible 帧上 zero-kpt 仅 val 1/41、identity 0/18（与 evaltool 观测一致），zero 集中在 GT unavailable 帧 → 模型学到“不可用 → 0,0 + 低 kobj”的退化输出。
- 导出接口缺口：predictions.jsonl 原先只存 keypoint_px、没有 keypoint_confidence，无法区分 sentinel 与有效角点。R2 已改为导出 keypoint_confidence（不改变 R1 文件）；正式评测继续用 **GT-free 有效性过滤**（越界/不在 bbox 0.5 扩展内=未发射）并在协议预注册（evaltool 主口径；literal 不滤波仅作敏感性：val false-ref 44/54、identity 26/26、all-positive 0.273/0.245）。

## 7. 失败分析与下一版建议（不在本包自动执行）

- **MS1 recall 是唯一硬失败**（identity 0.286/0.200、val 0.426/0.298 <0.50）。按 identity family（last）：ms1_alone **0/9**、both_mid **1/9**、both_scale_lateral **0/8**、both_same_bearing **9/9** → 只有与塔同方位/重叠的 MS1 被检出；MS1 单独与横向尺度完全失败。
- **尺度/覆盖不匹配**：class1 训练仅 183（f5 45@h 中位 102px、f6 39@44px、f7 39@56px、addendum 60@h 22–63px）；eval identity 35 个 MS1 实例 **h 中位 120.9px（52–217）**、val_main 47 个@中位 39px；大尺度 MS1（identity 最近/最大）训练样本只有 f5 一类。
- **class1 head/训练动态**：transfer log “Overriding model.yaml nc=1 with nc=2; Transferred 391/397 items” → class1 分类头 6 项随机初始化；warmup_epochs=15 == 总 15ep（全程 warmup，LR 未到 lr0）；dataset val 只有 tower 标签（MS1 addendum 未进 dataset val）→ class1 在训练中从未被验证/选模，best.pt 按 tower pose fitness 选。
- **best vs last**：best 的 tower fitness 更高但召回更低（val claim P1.0/R0.768、identity tower 27/44），last 召回更高（P0.878/R0.821、identity tower 40/44）→ same-frame 10/26 vs 22/26（evaltool 口径分别为 best 0.769、last 1.000）差异来自**选模目标对 class1/同框盲**，不是训练不稳定。
- 限制：agent-proxy 标签（非独立人工 GT）、v6.1 B-lite 9 帧排除 + 60 addendum 非全覆盖、MS1 远景小目标（12 帧 scale_note）、identity 62 帧样本量小；T25 PROVISIONAL 未纳入；无 holdout。
- **R2 假设（lead 已批准一次 pilot，≤15ep，不换大模型，唯一变量=数据）**：v6.2 加近距 MS1 族 → 重建 dev_v7 → 训练前冻结 val-only 选模规则（tower recall + MS1 recall 等权，tie same-frame）→ 15ep seed0，base weights/warmup/超参同 R1。预期：修复 ms1_alone 0/9 与 mid 1/9 的近距样本缺失；若仍<0.5 则 MS1 通道在 15ep/该模型容量下不可达，需更强证据再议。选模规则草案见 docs/reports/perception/training_20261104/R2_SELECTION_RULE_20261105.md（rule json sha 4d486b3e…，待 lead 冻结）。

## 8. 证据路径（sha 见括号）

| 内容 | 路径 |
| --- | --- |
| 训练证据 | outputs/landmark_train/runs/two_class_pilot_v61/seed0/two_class_pilot_seed0.json（8f45536a…） |
| 快照 | 同目录 run_snapshot.json（e240e90e…，二进内容 sha a9388f9b…）+ snapshot_checks.jsonl |
| 预测 val_main last / best | predictions_val_main_last.jsonl（96587369…）/ predictions_val_main_best.jsonl（a77eac9e…） |
| 预测 identity last / best | predictions_identity_last.jsonl（81fac15e…）/ predictions_identity_best.jsonl（5daad2c7…） |
| 权重 last / best | train_seed0/weights/last.pt（508a0430…）/ best.pt（6877e37b…） |
| 训练曲线 | train_seed0/results.csv（0665d36b…） |
| evaltool 正式指标 | outputs/perception/two_class_eval_20261105/pilot_v61_current/（每口径 two_class_metrics.json + rows.jsonl；evidence shas 2f1b493f…；报告 sha 5fb3ddc7…） |
| 数据 | labels_train_v6_merged.json（86b36772…）、dev_v6/dataset_build.json（36174618…）、data.yaml（f20d33d2…） |
| 冻结 | configs/perception/landmark_split_freeze_v6_1.json（424642d4…）、configs/perception/landmark_run_snapshot_v7.json（b6575568…） |
