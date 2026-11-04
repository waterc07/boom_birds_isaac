# 第四阶段：阶段门勘误、不可变快照、候选 A 三 seed 与消费者协议结果（2026-11-04）

> **状态：** BASELINE / 结果与勘误（内部有界研究；非认证、非 sealed、非板端/导航）
> **来源章节：** V2.2 §20.9/§20.11；configs/perception/landmark_improvement_gate_v1.json；landmark_consumer_protocol_v1.json（PRE_REGISTERED, sha bdcc9ccd）
> **证据域：** 隔离 venv 训练 + val_main 163 帧 + val_identity 62 帧只读评测；无 final、无板端/实机/SITL/HIL
> **最后核对：** 2026-11-04

本包纠正上一包阶段门执行、建立不可变运行快照、补完候选 A 的 3-seed 阶段验证，并按 V2.2 消费链（身份 + 参考点可用 + 水平 bearing + 新鲜有效）做消费者协议评测。结论：**A 在旧 3px 协议下通过 holdout 门（joint 0.632），但消费者协议因身份确认通道缺失而 FAIL → 本包不触发 holdout；停止的是该版本消费者实验，不是整条架构被证伪。**

## 0. 结论先行

| 项 | 结果 |
| --- | --- |
| 阶段门勘误 | 上一包把 holdout 门（+0.08/joint≥0.60）误用于 pilot→3-seed；gate 文件 pilot 门为 **+0.05/FMR/coverage 降≤0.02**，A pilot Δ+0.074、FMR 0<0.231、coverage 相同 → **pilot 门 PASS，本应进 3 seed**。已追加 GATE_STAGE_ERRATA（旧协议/旧报告未改）。 |
| 不可变快照 | 13 artifacts（v4.1 freeze、dev/reuse/merged labels、val_main 163、spec v2.1、protocol、gate、model yaml、data.yaml）在 pre_train/pre_selection/post_train 校验；3 seed 全部 VALID；标签漂移风险已阻断（训练/评测固定 snapshot 与 stable val 文件）。 |
| 候选 A 3 seed（旧 3px） | seed0 49/95=0.516、seed1 43/95=0.453、**seed2 60/95=0.632（选定）**；baseline 38/95=0.400；Δ+0.232；presence P1.0/R0.821、refcov 0.561、identity P1.0/FMR 0；最差 seed=seed1。 |
| 旧协议 holdout 门 | **PASS**（joint≥0.60、Δ≥+0.08、FMR、coverage≥0.50、最差组均满足）。 |
| 消费者协议 | **FAIL（身份确认通道缺失）**：单类 detector 无身份判别；appearance gate 在 annotated box 可分（aspect 0.50/0.60、AUC 1.0）但 **pipeline 预测框不可迁移**（误拦 61/78 正确目标）；two-class detector NOT RUN。strict_unknown 下 consumer 成功=0；raw claim 上界 0.6–0.76 只能记录，不能作 gate。 |
| holdout | **NOT_TRIGGERED**：消费者协议 holdout 门 FAIL；旧协议 holdout 门虽 PASS，但旧 3px 评测不能回答身份+bearing 消费需求。未采集/未评价。 |
| 数据 | v5 freeze（train 19 组/1857 帧、val 11 组/921=val_main 816+val_identity 105）；泄漏审计 PASS；T25 采集 INCOMPLETE / T26 PROVISIONAL 均不纳入。 |
| ONNX 三路径 | 候选 A 选定模型（seed2 last）opset18 导出 + 三路径 parity **PARITY_PASS**：186 帧/134 metric 帧，presence/reference/identity claim/identity gt/false claim/reject reason/bearing/bearing presence/joint **全部 0 决策翻转**；raw 相对差 1.48e-6；证据 onnx_parity_20261104.json#t29_candidate_A。RKNN/板端 UNKNOWN。 |

## 1. 阶段门勘误（已确认）

- gate 文件（sha 7c81ae51）pilot 门：Δ≥+0.05、FMR 不恶化、coverage 降≤0.02；holdout 门：joint≥0.60、Δ≥+0.08、FMR、coverage≥0.50、最差组。
- 上一包执行：协议里记录“lead 澄清 +0.08/joint≥0.60 用于 3 seed 晋级” → 把 holdout 门套到 pilot，A 被判 FAIL 而 STOP；3 seed 从未执行。
- 更正：pilot 门 PASS（Δ+0.074≥+0.05；FMR 0 vs 0.231；coverage 0.146=0.146）。三个结论分开：pilot 可继续（成立）；holdout 未获准（当时成立，因为 3-seed 未做）；路线无效（**不成立**，不能用未执行的阶段否定路线）。
- 详情：[GATE_STAGE_ERRATA_20261104.md](perception/GATE_STAGE_ERRATA_20261104.md)。

## 2. 不可变快照与标签漂移

- `scripts/landmark_run_snapshot.py` + config（v1/v5）；每次运行前 create、pre_train/pre_selection/post_train verify；mismatch→INVALID、exit 2；snapshot 不可重写。
- 3 seed 全部 pre_train VALID；13 artifacts 无 mismatch；日志 `snapshot_checks.jsonl`。
- 上一包标签漂移（labels_val 163→231）已被阻断：训练/评测固定 v4.1 快照与 `labels_val_validation163.json`（sha a9bfda8f）；训练期间不再共享可变标签文件。

## 3. 候选 A 三 seed（旧 3px 协议，val_main 163/95 分母）

| seed | candidate | joint | presence P/R | refcov | identity P/FMR | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | last | 49/95=0.516 | 1.000/0.779 | 0.317 | 1.000/0.000 | |
| 1 | last | 43/95=0.453 | — | 0.390 | 1.000/0.000 | 42ep 早停 |
| 2 | last | **60/95=0.632** | **1.000/0.821** | **0.561** | **1.000/0.000** | 选定；worst fam_north 28/50=0.56 |
| baseline v4 60ep | best | 38/95=0.400 | 0.86/0.78 | 0.195 | 0.865/0.180 | worst fam_dev_static_low 0/15 |

- 选定 seed2/last（权重 sha 6b86ef1f…）；冻结 configs/perception/landmark_model_freeze_v2.json。
- 阈值沿用先验 val 冻结值（tau_det/tau_conf 0.605476、tau_margin 0.1、tau_px 3.0、tau_iou 0.3、tau_kpt 0.5）；未在本次 3-seed val 上重调（避免 double dipping），已在冻结清单注明。
- 旧协议 holdout 门 5 项全 PASS（见 stage verification 报告）。

## 4. 消费者协议评测（身份 + 参考点可用 + 水平 bearing + 有效观测）

协议：configs/perception/landmark_consumer_protocol_v1.json（sha bdcc9ccd，PRE_REGISTERED）；三套分母（all-positive / observable / reference-available）+ negatives；UNKNOWN/漏检/无 keypoint 保留在分母。

| 数据/策略 | all-positive | observable | ref-available | negatives | wrong claims | bearing median/P90 |
| --- | --- | --- | --- | --- | --- | --- |
| val_main baseline raw | 60/121=0.496 | 60/95 | 38/41 | 25/39 | 17（MS1_ONLY 13） | 1.09°/1.84° |
| val_main A 3-seed(seed2) 正式（冻结阈值） | 58/121=0.479 | 58/95=0.611 | 35/41 | 39/39 | 0 | 0.453°/1.094° |
| identity 62 baseline raw | 28/53=0.528 | 28/44 | 17/18 | 9/9 | 1 | 1.07°/2.05° |
| identity 62 A 3-seed(seed2) 正式 | 27/53=0.509 | 27/44=0.614 | 18/18 | 9/9 | 0（MS1-only 0/9） | 0.546°/1.550° |
| **strict_unknown（当前真实可交付状态）** | **0/121** | **0/95** | **0/41** | 39/39 | 0 | bearing 不受影响 |

- strict_unknown：未确认身份一律 UNKNOWN；当前无身份确认通道 → GT-present 消费者成功 = 0（这是身份通道缺失导致的真实上限）。raw claim 上界（val_main 58/121=0.479、identity 27/53=0.509）只能作诊断，**不能当认证或 gate 输入**。
- 正式对照（冻结阈值 tau_det 0.605476，未在本次 val 重调）：baseline matched 45/121=0.372、A pilot 51/121=0.421、seed0 last 53/121=0.438、seed1 last 30/121=0.248、**选定 seed2 58/121=0.479（Δ+0.107 vs baseline）**。gate 逐条：success≥0.50 FAIL（0.479；strict=0）、Δ≥+0.05 PASS、wrong-claim ≤0.05 PASS（0/39；MS1-only 0/27）、bearing median/P90 PASS（0.453°/1.094°）、ref 拒绝 PASS（0.981/false-ref 0.019）、worst-group PASS。主因身份确认通道缺失。
- 参考可用子集 bearing 误差全部 ≤3°（如 A3 seed0 last n=37 median 0.66°/P90 1.30°），reference 拒绝正确率高；但身份通道缺口使 consumer 成功无法成立。

## 5. 身份方案（≤2）与结论

- 方案 1（单网络 + appearance gate）：diag 在 annotated boxes 上可分（bbox aspect：目标 0.63–1.78 vs MS1 0.20–0.44，AUC 1.0，阈值 0.50/0.60 → 0 误拦/0 漏拦；green_rel_y 0.18，仅发射 kpt 时）。但 evaltool 在 **pipeline 预测框**上验证：v2 gate 把 identity all-positive 从 0.528 降到 0.208（baseline）/0.660→0.302（A），val_main 0.496→0.025 / 0.579→0.074；主因 GREEN_TOO_HIGH_ON_BBOX_MS1 + TOO_SMALL。 → **不冻结、不可迁移**。
- 方案 2（two-class detector：tower vs similar structure/MS1）：**NOT RUN**——需要新全量训练，超出本包 4 次完整训练预算（已用于 baseline+3 seed）；第二类标签未冻结。作为唯一可行身份通道记录给下一包。
- 结论：单类 detector 无法提供身份确认；identity 必须显式 UNKNOWN；消费者成功在 strict 口径为 0，这是本包最关键的负面结果。

## 6. 已确认原因 / 仍未证实假设

**已确认**：
- 阶段门误用（pilot 用 holdout 门）→ 上一包提前 STOP；A 满足 pilot 门。
- 候选 A 3-seed 在旧 3px 协议下改善有效（joint 0.632 vs 0.400），且 holdout 门通过。
- 身份问题真实且严重：val_main baseline 17 wrong claims（MS1_ONLY 13）；单类 detector 无身份通道。
- appearance gate 在 pipeline 预测框上不可迁移（不是“特征不可分”，而是“预测框几何与标注框几何不同”）。
- 参考可用子集 bearing 误差满足 PROPOSED 3°/5°；2D 像素误差不能作为 bearing 的唯一准入。
- TINY（9–14px）在当前样本/方法下不可靠标注；盲标 presence 0.364、TINY 正例 12/12 undecidable；全域分母保留。

**仍未证实（假设）**：
- A 的 joint 改善有多少来自 reuse 数据的“近距大目标覆盖”vs 随机种子波动（seed 间 0.453–0.632，仅 3 seed，未做 nested 统计）；不外推为架构能力。
- 旧 3px joint 与消费者 bearing 成功之间的映射关系（本包未建立正式映射；只显示 bearing 子集满足）。
- two-class detector 能否提供身份通道并恢复 consumer 成功（未跑）。
- 真实赛场分布/真实相机下的可行性与规则合规（UNKNOWN）。

## 7. 停止依据与路线建议

- **停止依据**：消费者协议 holdout 门 FAIL（条件：确认身份下 consumer 成功 ≥0.50；identity 确认通道缺失 → strict 0）。因此本包不采集新 holdout、不评 final。
- 同时报告：旧 3px 协议 holdout 门 PASS（joint 0.632）——这是真实改进，不因消费者协议失败而抹去；但它不满足 V2.2 消费链。
- 建议下一包：①实现 two-class 身份通道（tower vs similar structure/MS1），重新预注册 consumer gate；②在确认身份通道可用后，再补采 holdout（≥3 新族/200–400 帧/6 类覆盖，采样规则已冻结于 holdout v2）；③继续保留 bearing-primary 作为辅助判据、2D 仅诊断。
- 不建议：继续在当前单类配方上调阈值/加 seed；不建议用 raw claim 上界宣布通过。

## 8. 需用户决定的最小事项

1. 是否批准下一包实现 two-class 身份通道（需要第二类标签与一次新全量训练预算；这是消费者验收的必要条件）。
2. 是否接受“bearing-primary + identity 显式 UNKNOWN”作为地标感知的阶段性交付口径（若接受，可在无身份关联的情况下先做方位辅助；若要求身份关联，则必须等 two-class）。
3. 许可分发路线（AGPL/商业/备选）——仍仅内部有界研究，未变。
4. RK3576 板卡/真实相机（可选，非阻塞；保持 UNKNOWN）。

## 9. 证据与验证

| 内容 | 路径 |
| --- | --- |
| 阶段门勘误 | docs/reports/perception/GATE_STAGE_ERRATA_20261104.md |
| stage verification | docs/reports/perception/training_20261104/STAGE_VERIFICATION_20261104.md |
| 模型/阈值冻结 v2 | configs/perception/landmark_model_freeze_v2.json（权重 sha 6b86ef1f…） |
| 3-seed 运行 | outputs/landmark_train/runs/stage_verify_v5/seed{0,1,2}/（ignored；含 snapshot/checks/results/eval） |
| consumer 评测 | docs/reports/perception/CONSUMER_EVAL_20261104.md + .json；outputs/perception/consumer_eval_20261104/ |
| 身份特征与 gate | docs/reports/perception/posteval_20261104/MS1_IDENTITY_ANALYSIS_20261104.json、IDENTITY_APPEARANCE_FEATURES_20261104.json |
| 数据 v5 | configs/perception/landmark_split_freeze_v5.json、DATASET_FREEZE_V5_20261104.md、leakage/external index |
| 快照 | configs/perception/landmark_run_snapshot_v5.json、scripts/landmark_run_snapshot.py |
| holdout 预注册 | configs/perception/landmark_holdout_freeze_v2.json（SPEC_FROZEN_NOT_TRIGGERED） |

验证：`python -m pytest -q`、`python scripts/planning/audit_documents.py`、`python scripts/verify_landmark_dataset.py --freeze configs/perception/landmark_split_freeze_v5.json` 于收尾执行（结果见提交说明）。

**边界：** 非认证；旧结果/旧协议/旧 hash 保留；不接控制/PPO；不提升 Gate。
