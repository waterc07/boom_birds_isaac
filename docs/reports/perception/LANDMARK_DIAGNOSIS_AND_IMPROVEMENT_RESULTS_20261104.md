# 地标失败诊断、工程修复与有界改进实验结果（2026-11-04 三阶段）

> **状态：** BASELINE / NEGATIVE-RESULT（内部有界研究；post-evaluation 分析与 dev 有界实验；**不是**认证、sealed final、板端或导航验收）
> **来源章节：** V2.2 §7.4/§7.5/§7.7/§9.1/§11.1/§20.2/§20.11；预注册 configs/perception/landmark_improvement_gate_v1.json
> **证据域：** 离线诊断（旧 final 只读）+ dev 验证集有界实验 + 主机 ONNX 对齐；无板端/实机/SITL/HIL
> **最后核对：** 2026-11-04

旧 exploratory 结果与产物只增不改；新增 post-evaluation 诊断、评价定义审计、ONNX 三路径对齐、脚本入库、identity/TINY 数据补齐与两个诊断驱动候选的有界对比。结论：两个候选均未过预注册 gate → STOP；不进入 3 seed，不触发 holdout 采集。

## 0. 结论先行

| 项 | 结果 |
| --- | --- |
| 主瓶颈（已确认） | reference 2D 定位精度（不是漏检、不是横向 bearing）：参考可用 218 帧中 3px 内 62（28.4%）、错误锚点 119（54.6%）、kpt 置信度抑制 28（12.8%）、可用参考漏检 9（4.1%）；错误锚点 88/119 纵向主导（dy 中位 +2.67px） |
| 3px 2D vs 消费者 bearing | 181 个已发射 kpt 中 87 帧 2D>3px 但 bearing≤1.074°（3° 口径 119）；下游消费图像 bearing，旧 3px 2D 偏严——旧结果保留、新口径单列 |
| TINY 可标注性 | 22 帧盲复标：presence 严格 8/22=0.364 FAIL；TINY 正例 12/12 全 undecidable；bbox IoU 中位 0.434 FAIL；同源 kpt 0.823px PASS → 9–14 px 不可靠标注 |
| identity | MS1（map-native 带绿灯相似结构）证伪 U1/U2；单类 tower 无身份判别通道；identity 只能 UNKNOWN/appearance-gated，不可认证 |
| 候选 A（近距/远景复用帧入 train） | matched baseline pilot joint 0.379（36/95）→ A 0.453（43/95），Δ+0.074；joint<0.60 → gate FAIL |
| 候选 B（tau_kpt 可用性标定） | joint 无改善（0.400），false_reference 0.093→0.130 变差 → gate FAIL |
| 最终决定 | STOP：不追加 3 seed、不触发 holdout、不读新 final；完整训练预算用 1/4，pilot 2 次 |
| ONNX 三路径 | 共享预处理后 0 决策翻转（126 帧）；旧 4.67px 差异归因于 legacy .pt 与 ONNX predict 的 letterbox 模式不同（17 observation/18 joint 翻转），不是导出错误 |
| 工程链 | 训练/停止器/阈值/导出/parity/重算脚本已入库并有 CLI+配置；旧标签坐标域 bug 勘误保留 |

## 1. 旧产物保留与只读边界

- 旧 final 输出、模型、协议、预测、hash 原字节保留；本次只读诊断，没有重跑旧 final，也没有用旧 final 调参。
- 旧 3px 数字（presence P1.000/R0.916、coverage 62/218、joint 71/238、anchor 正确子集 1.95px）保持原口径有效；新口径（四项分离、joint 双分支、bearing）单列，不替换、不用于宣布旧实验通过。
- 旧 exploratory 池在 v4.1 中作为 DEVELOPMENT_TRAIN 复用（登记来源/暴露事件）；用后不得再作 final/sealed/独立测试。见 configs/perception/landmark_exposure_registry_v2.json。

## 2. 评价定义审计（新口径单列）

四项能力分开：presence / identity / reference-availability / localization；joint 拆两分支。代码：src/boom_birds/evaluation/landmark_eval_definitions.py、scripts/recompute_landmark_metrics.py；45 条测试。

| 量（旧 final 279 帧只读重算） | 分子/分母 | 值 |
| --- | --- | --- |
| presence | TP218/FP0/FN20/TN41；N_pos 238 / N_neg 41 | P 1.000、R 0.916 |
| identity | claims 218 / wrong 0 / claims_on_negatives 0 | P 1.000、R 0.916（分母 238）、FMR 0/41；无 verified 相似结构负例 → 不认证 |
| reference availability | N_avail 218 / N_unavail 20 | 正确拒绝 20/20=1.000；false reference 0/20=0.000；已发射 181 / 未发射 37 |
| localization（仅 218） | 3px 内 62 | 62/218=0.284；n=181：2D 中位 3.72/P90 5.96/max 8.44 px；abs dx 1.67/3.74，abs dy 2.84/5.28；bearing 中位 0.546°/P90 1.188° |
| joint（旧复合 71/238） | 分解 | LOCALIZED 62/218 + CORRECT_REFUSAL 9/20；FAIL_PRESENCE 20；FAIL_REFERENCE 147（119 错误锚点 + 28 抑制） |

GT_UNOBSERVABLE 与预测 UNKNOWN 严格分桶（本池 0/0，规则已实现测试）；GT 歧义/不可观测不评定位，但仍统计其错误身份/错误参考点声明。3px≈1.074°，下游区域方位消费的是 bearing，不是 2D/世界方位/距离。

## 3. reference 失败根因分解（post-eval）

| 阶段（分母=参考可用 218） | 计数 | 占比 |
| --- | ---: | ---: |
| 3px 内正确 | 62 | 28.4% |
| 错误锚点 >3px | 119 | 54.6% |
| kpt 置信度 <tau_kpt 被抑制 | 28 | 12.8% |
| 可用参考上漏检 | 9 | 4.1% |

- 错误锚点：88/119 纵向主导（abs dy>=abs dx），错误子集 dy 中位 +2.67 px、dx 中位 -0.95 px；全部已发射 dy 中位 +1.22 px。
- 尺度：TINY 1/15=0.067、SMALL 18/91=0.198、MEDIUM 36/85=0.424、LARGE 7/27=0.259；族：near 3/23 最差、backoff 13/56、sweep 33/111、edge 13/28；截断 15/48 vs 未截断 47/170（截断非主因）。
- dev train 中 LARGE 目标 0 帧（TINY52/SMALL28/MEDIUM25/LARGE0）→ 训练分布缺口（候选 A 依据）。
- 标注误差/同源：GT reference=严格绿光质心（与模型 cue 同源 218/218，中位偏差 0.022px）→ 定位误差含同源循环，不能宣称独立物理精度；43 个 relaxed green 锚点无逐帧来源，只能给上限。
- 坐标变换：loader 闭环 0.0003px、纵向偏差随尺度变化且无统一偏移 → 预处理候选被 REJECTED。

### 3.1 TINY / 4–10 px 盲复标（development）

- 22 帧盲标（annot 独立，只看 diag 盲版清单与图像）：present 6 / undecidable 14（63.6%）/ absent 2。
- presence 严格 8/22=0.364 FAIL；可判定 8/8（覆盖仅 36.4%）；reference availability 8/8 PASS；同源 kpt 中位 0.823/P90 2.159px PASS；bbox IoU 中位 0.434 FAIL；TINY 正例 12/12 全 undecidable。
- 结论：9–14 px 目标 presence 不能可靠盲标；既有 TINY bbox 依赖投影先验，不是独立视觉 GT；小绿 cue（目标 21–124px）可标。TINY 不应进入认证分母。

### 3.2 MS1 与身份

- MS1（map-native 约 (3.0,4.0)，细长平顶柱+侧挂绿灯+蓝侧条，顶 z≈1.78m）与中央塔（宽锥塔身+顶灯架+居中绿顶灯+R+白阶梯底座）在中近距离外观可区分（62/62 development 代表帧可判）；<22px 不可靠。
- 单类 tower 输出没有身份判别通道：identity_claimed 仅由单候选+score/margin 决定，appearance_check=NOT_EVALUATED；MS1 从未作为训练负例进入（HN1 仅合成注入，map-native 无训练样本）；30/30 inner_north val 帧 candidate_count=1 只说明该批未误报，不证明身份判别。
- U1/U2 证伪：identity 只能显式 UNKNOWN 或加 appearance gate；本轮不认证。

## 4. ONNX 三路径端到端对齐

- 三路径：PyTorch .pt / Ultralytics 原生 ONNX predict / raw-ORT 手工解码（同预处理、同 letterbox、同 NMS、同阈值、同坐标域）。
- 共享预处理下 126 帧（real val 48 + old exploratory 24 只读 + 合成 54）**0 observation / 0 joint 决策翻转**；kpt 最大差 1.40e-4 px；raw 相对误差约 1e-4（相对 640），绝对最大 0.07 由坐标通道主导（相对判据通过且 self_check PASS）。冻结 ONNX 4ee4071d… 与重导出 65fb75ae… 的 raw 输出逐位一致（sha 差异来自序列化/元数据）。
- 旧 4.67px 差异：legacy 的 .pt 单图 auto/rect（640x480）与 ONNX 导出图 square（640x640，pad 80）letterbox 模式不同，锚点网格不同 → 旧 mixed 对比在 72 GT 帧上 18 次 joint 翻转（presence 5/reference 6/identity 5）；关键帧 dynamic_A_north_0-follow_only_g1_183.png 精确复现 dy=4.667px，rect joint PASS（2.57px）vs square joint FAIL（5.14px）→ **旧 4.67px 确实能翻转通过判定，但归因是预处理模式/设备口径混用，不是 ONNX 图或导出错误**。同画布后 0 翻转。
- 旧 eval_onnx 产物（raw 路径、无 NMS）复核：joint 4/95=0.042 vs pt 55/95=0.579，95 帧中 51 帧翻转、MULTIPLE_CANDIDATES 77/134，且其 ONNX sha 83925f46 当前不存在 → **旧 eval_onnx 数字不得作为模型证据**（勘误）；缺陷 D1 无 NMS / D2 rect-square 混用 / D3 PosePredictor box clip+round 未复刻，已先红后绿补 18 条测试。
- 覆盖：非方形合成图、边缘截断、多候选、关键点不可见、近阈值（合成变体无 GT，仅 observation 级比较）。脚本入库：scripts/landmark_export_onnx.py、scripts/landmark_onnx_parity.py、src/boom_birds/evaluation/landmark_onnx.py；去除私有绝对路径。RKNN/板端仍 UNKNOWN。

## 5. 工程修复与脚本入库

- scripts/landmark_train_cli.py（dataset 准备、预注册 PatienceStopper：warmup 15 内绝不早停、候选评估、协议 hash 守卫）、scripts/landmark_freeze_thresholds.py（仅 val 冻结阈值、拒绝覆盖）、scripts/evaluate_landmark_yolo.py、scripts/recompute_landmark_metrics.py；配置 configs/perception/landmark_train_cli_v1.json。
- 测试：train_cli 19、eval definitions 14、metrics 31、yolo 61、posteval 20 等；全仓在收尾统一跑。
- 旧标签坐标域 bug 勘误保留在上一阶段（旧 30 epoch INVALID、loader delta 0.0003px）；本轮未改旧结果。
- 标签漂移：训练期间 labels_val 被并行标注更新为 231 帧，train 判首轮 eval INVALID，改用稳定 163 帧文件 labels_val_validation163.json（sha a9bfda8f…），记录在 IMPROVEMENT 报告 §1。

## 6. 数据与身份案例（本轮新增）

- dev freeze v4（val HN 53/53）、v4.1（旧 exploratory 279 帧入 train 作为 DEVELOPMENT_TRAIN，train 16 组/1772 帧，val 不变）、v4.2（identity 7 组 190 帧进 val_identity；val_main 与 v4.1 相同）。
- HN 53 帧全覆盖：HN1 27=SIMILAR_STRUCTURE+verified 合成注入（EXTERNAL_EVIDENCE，非真实分布）；HN2 26=GT_UNOBSERVABLE（present+occluded、无 bbox、reference UNAVAILABLE，不是负例）。
- identity/confuser：7 case/169 accepted/62 帧代表标注（目标单独、MS1 单独且绿灯可见、三种同框、近距截断、完全遮挡）；MS1=map-native verified；唯一合成注入 hn2_occluder_v1；62/62 可区分（未虚构 ambiguous）。
- 泄漏审计 v4/v4.1/v4.2 PASS（train-val sha 0、像素近重复 0、同轨迹跨 split 0、family/group 0）；外部产物 3885 帧可读/hash 一致；暴露登记 v2：39 组全部 exposed_development、0 untouched。

## 7. 有界改进实验（预注册，实际执行）

预注册：configs/perception/landmark_improvement_gate_v1.json（先于结果冻结）+ landmark_improvement_protocol_v1.json。候选按 diag 根因：A=数据覆盖（CONFIRMED）；B=可用性决策标定（CONFIRMED 操作性）；C1 v=0 监督=SUSPECT 弃用；C2 预处理=REJECTED 弃用。

| 对比（同 val 163 帧、同预算 15 ep、seed0） | joint 窄口径 | presence P/R | reference coverage | identity P / FMR |
| --- | --- | --- | --- | --- |
| matched baseline（v4 train） | 36/95 = 0.379 | 0.830 / 0.768 | 6/41 = 0.146 | 0.833 / 9/39=0.231 |
| 候选 A（v4.1 train = +279 reuse） | 43/95 = 0.453（Δ+0.074） | 1.000 / 0.758 | 6/41 = 0.146（未提升） | 1.000 / 0/39=0.000 |
| 候选 B（tau_kpt 0.25–0.5） | 0.400（最好，无改善） | 同 baseline | 0.195（不变） | false_reference 0.093→0.130 变差 |

- A 机制：改善 presence/负例精度与部分 TINY/LARGE 帧，但 reference 3px 覆盖不变；Δ 差 0.006 未达 +0.08 且 joint<0.60 → FAIL。
- B：降低 tau_kpt 不提升覆盖、反而增加 false reference → FAIL。
- 决定：STOP；不推进优胜 3 seed；不触发 holdout（landmark_holdout_freeze_v1.json 仍 NOT_TRIGGERED，规则已预注册、未采集/未评价）。
- 预算：完整训练 1/4（baseline 60 ep，249s，4.16 s/epoch）；pilot 2 次；未用旧 final 调参。
- 同口径 reference/bearing：baseline pilot 2D 中位 6.60px / bearing 0.78°，2D>3px 但 bearing≤3° 占 73.7%；A 2D 中位 5.09px / bearing 0.63°，81.8%——再次支持 2D 为主瓶颈、bearing 可用，但 3px 内计数未变，不足以过门。

## 8. 路线建议

建议：停止“单类 pose + 3px 2D + 单类别身份”作为认证级路线；不要为凑 gate 继续追加 seed/epoch/候选。

可继续方向（需用户决定，且必须收窄口径）：
1. 消费端口径改 bearing-primary：下游区域接力需要图像 bearing（水平角），不是 2D 像素。旧 final 1.074° 口径已发射帧 149/218=0.683、3° 口径 181/218=0.830；同时报告发射率/漏检/TINY 排除。若接受粗略方位+显式 UNKNOWN，可继续开发；若要求 3px 2D 或世界方位，则停止。
2. 只在可标注域工作：排除 TINY（9–14 px）与 <3 px 绿灯；近距/中距（目标≥22px、绿光≥3px）作为开发域；补采近距大目标严格绿光参考帧并引入 ≥2 人独立标注/仲裁，才能分离同源标注误差与模型误差。
3. identity 必须显式 UNKNOWN 或 appearance-gated：单类 tower 不得映射中央塔 ID；MS1 已证伪唯一性；若下游需要身份，appearance/多候选/场景先验须作为独立模块验收。
4. 数据侧已被证实：近距 LARGE 训练覆盖缺失是真实缺口（A 有 +0.074 趋势但不足）；若继续，先补近距大目标数据并重新预注册，而不是扩大模型。
5. 认证级结论仍不可得：需新 untouched holdout + 独立标注 + 许可分发决策 + 板卡；本阶段 STOP 不触发 holdout，符合预注册。

## 9. 需要用户决定的最少事项

1. 是否接受 bearing-primary（粗方位 + UNKNOWN/拒绝）作为地标感知的开发验收口径；是则继续收窄路线（排除 TINY/小绿光，补近距大目标与独立标注），若必须 2D/身份认证则停止该路线。
2. 是否为下一轮投入独立人工标注（≥2 人+仲裁）与新未触碰 holdout 采集（认证级结论前置）。
3. 许可分发路线（AGPL/商业/备选）——仍只允许内部有界研究，本轮未变。
4. RK3576 板卡/真实相机（可选，非本轮阻塞，保持 UNKNOWN）。

## 10. 证据路径与验证

| 内容 | 路径 |
| --- | --- |
| post-eval 诊断 | docs/reports/perception/posteval_20261104/POSTEVAL_DIAGNOSIS_20261104.md + JSON + overlays + src/boom_birds/evaluation/landmark_posteval.py |
| 评价定义审计 | docs/reports/perception/EVAL_DEFINITION_AUDIT_20261104.md + src/boom_birds/evaluation/landmark_eval_definitions.py + 45 测试 |
| ONNX 三路径 | docs/reports/perception/onnx_parity_20261104.json + src/boom_birds/evaluation/landmark_onnx.py + scripts/landmark_onnx_parity.py |
| 改进实验 | docs/reports/perception/training_20261104/IMPROVEMENT_20261104.md + improvement_metrics_20261104.json + outputs/landmark_train/runs/improvement_v4/ |
| 数据冻结 v4/v4.1/v4.2 | configs/perception/landmark_split_freeze_v4*.json；docs/reports/perception/dataset_freeze_20261104/DATASET_FREEZE_V4*_20261104.md |
| 暴露登记 | configs/perception/landmark_exposure_registry_v2.json |
| HN/identity/TINY 标注 | docs/reports/perception/annotation_verify_20261104/HN_REMAINING_ANNOTATION_20261104.md、IDENTITY_DEV_ANNOTATION_20261104.md、TINY_BLIND_ANNOTATION_20261104.md |
| 采集与 MS1 | docs/reports/perception/capture_dev_20261104/IDENTITY_CAPTURE_20261104.md |
| 预注册 | configs/perception/landmark_improvement_gate_v1.json、landmark_improvement_protocol_v1.json、landmark_holdout_freeze_v1.json |
| 旧结果（保留） | docs/reports/perception/LANDMARK_EXPLORATORY_RESULTS_20261104.md、configs/perception/landmark_model_freeze_v1.json |

验证命令（收尾统一执行）：python -m pytest -q、python scripts/planning/audit_documents.py、python scripts/verify_landmark_dataset.py --freeze configs/perception/landmark_split_freeze_v4_2.json；旧 final 指标由 scripts/recompute_landmark_metrics.py 只读复算（33/33 一致）。

**边界：** 本阶段全部为诊断/dev 有界实验/主机一致性证据；不是模型效果达标、不是 sealed final、不是身份/板端/导航认证；未接控制、未启动 PPO、未提升任何 Gate。
