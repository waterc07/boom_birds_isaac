# 地标改进实验：候选 A/B 有界 pilot 与 STOP 判定（2026-11-04）

> **状态：** BASELINE（dev 验证集有界实验；负结果；非能力认证）
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §9（感知与视觉算法架构）、§11.1（Student 输入边界）、§20.2（禁止项）、§20.11（分层报告）
> **证据域：** 仿真域 dev 验证集（163 帧 VALIDATION 子集）+ 离线决策标定；无 Isaac 运行、无板端/实机/SITL/HIL/导航验收
> **最后核对：** 2026-11-04

本文件是 task-18 的实际执行结果：按 lead 预注册的 [improvement gate](../../../configs/perception/landmark_improvement_gate_v1.json) 与 [improvement protocol](../../../configs/perception/landmark_improvement_protocol_v1.json) 实现两个诊断驱动候选，做同数据同预算对比。**结论：两个候选都未过 gate → STOP；不进入优胜 3 seed，不触发 holdout。** 旧 exploratory final 仅作只读诊断输入，未被用于调参/阈值；本实验未读 holdout、未改旧 final 结果、未提升 Gate。

## 0. 结论摘要

| 项 | 结果 | 证据 |
| --- | --- | --- |
| matched baseline pilot（v4 train，15 ep，seed0） | joint **0.379**（36/95） | `runs/improvement_v4/baseline_pilot15_seed0/` |
| 候选 A（v4.1 train = dev160 + reuse exploratory279，15 ep，seed0） | joint **0.453**（43/95），Δ **+0.074** | `runs/improvement_v4/candidateA_pilot15_seed0/` |
| A 的 gate 判定 | **FAIL**：Δ+0.074 < +0.08；joint 0.453 < 0.60 | `improvement_metrics_20261104.json#gate_evaluation` |
| 候选 B（tau_kpt 离线标定，baseline 60ep checkpoint） | 最好也只是 joint 0.400（与默认 0.5 相同），无改善 | `runs/improvement_v4/candidateB_tau_kpt_sweep/` |
| B 的 gate 判定 | **FAIL**：Δ0.000 < +0.08；joint 0.400 < 0.60 | 同上 |
| 最终决定 | **STOP**（两候选均不过门；不追加完整训练；holdout NOT_TRIGGERED） | gate `on_fail` |
| 完整训练预算 | 用 1/4（baseline 60 ep）；pilot 2 次（不计入完整训练）；优胜 3 seed 未执行 | `improvement_metrics_20261104.json#budget` |

## 1. 数据、标签版本与口径（含一次标签漂移处置）

| 项 | 值 |
| --- | --- |
| train（候选 A） | dev train 160 帧（labels sha `01977b9f…`，未变）+ 旧 exploratory 复用 279 帧（labels sha `7115ee04…`，v4.1 freeze 登记为 DEVELOPMENT_TRAIN）；合并标注 439 帧 sha `c936da6b…`，reuse→val 泄漏检查 0 |
| val（gate 口径） | **163 帧 VALIDATION 子集**（stable 文件 `labels_val_validation163.json` sha `a9bfda8f…`；95 正例 / 39 空负例 / 29 GT_UNOBSERVABLE 单列） |
| v4.1 freeze | file `531565a2…`，canonical `36840e7f…`；train 16 组/1772 帧，val 7 组/816 帧 |
| v4.2 freeze（后续） | val_main 163 与 v4.1 相同；新增 val_identity 62 帧**只做 identity 分层报告**，不混入主 joint；holdout `NOT_TRIGGERED` |
| 数据集 | `dev_v4`（baseline：train 157 图/val 134 图）；`dev_v4_1`（候选 A：train 436 图 = 343 正 + 93 空，val 134 图） |
| 标签漂移（已记录） | 训练期间 `labels_val.json` 从 v4 的 163 帧/sha `8c215597…` 被更新为 v4.1 的 231 帧/sha `6ade12bd…`（163 VALIDATION + 68 identity DEVELOPMENT）。首轮 eval 读到中间态 231 帧且数据集缺 identity 图像 → joint 0.21/0.27 **INVALID**，已弃用；本报告全部数字改用 163 帧 VALIDATION 口径，后续以 stable 文件 `a9bfda8f…` 固定读取（与早前 163 子集仅 int/float 序列化差异，标注数值相同） |

## 2. matched baseline（同预算 15 ep）

- v4 train（不含 reuse）15 epoch、seed0、pretrained yolov8n-pose.pt、batch16、imgsz640、AMP；**整个 pilot 位于 warmup(15) 内**，指标是趋势探针，不是收敛结果。
- 选中 checkpoint = best（joint 最高）：**joint 36/95 = 0.379**（失败 presence 22 + reference 37）；presence TP73/FP15/FN22/TN24（P 0.8295 / R 0.7684）；reference 覆盖 6/41=0.146、false_reference 0.0556；identity claims 90、P 0.8333、FMR 9/39=0.2308。
- 完整 60 epoch baseline（仅作参考/未来预算，不是 pilot 对比基准）：best.pt joint 38/95=**0.400**，presence 74/12/21/27（P0.8605/R0.7789），reference 覆盖 8/41=0.195，identity P0.8652、FMR 0.1795（负例 39）。

## 3. 候选 A（DATA）：reuse development 帧加入 train

- 实现：`outputs/landmark_train/scripts/build_v4_1_train_labels.py` 将 279 帧复用标注按 v4.1 `g_reuse_*` 组重新挂到 train（标注值逐字节保留，只改 source 归属）；数据集用 `scripts/landmark_train_cli.py --prepare-dataset` 生成。
- 诊断依据：diag §2.5/§5（dev train LARGE 目标=0；旧 exploratory LARGE/near 覆盖 7/27=0.259、lmf_near 3/23=0.130；错误锚点 4.2–7.6 px、kpt 置信度≈1.0）。
- 结果（15 ep，seed0，选中 last，joint 最高）：**joint 43/95 = 0.453（Δ+0.074）**（失败 presence 24 + reference 28）；presence TP72/FP0/FN23/TN39（P 1.000 / R 0.7579）；reference 覆盖 **6/41 = 0.146（未提升）**、false_reference 0.0185；identity claims 72、P 1.000、FMR 0/39=0.000。
- 机制核查（scale 分层，joint 分子/分母）：LARGE 14→**5/14**（baseline 3/14）、TINY **37/58**（baseline 30/58）、MEDIUM 1/19（baseline 3/19，回退）、SMALL 0/4。→ A 主要改善 **presence/空负例精确率与 TINY/LARGE 的部分帧**，但**没有改善 reference 定位覆盖率**（6/41 不变）。
- 判定：Δ 差 0.006 未达 +0.08，且 joint 0.453 < 0.60 → **FAIL**（不得因"接近"而放行）。

## 4. 候选 B（AVAILABILITY DECISION）：tau_kpt 离线标定

在 baseline 60 ep checkpoint 的 val 预测上扫 tau_kpt（不训练、不改网络）：

| tau_kpt | joint | joint 分子/分母 | reference 覆盖 | false_reference_rate | identity P | FMR |
| --- | --- | --- | --- | --- | --- | --- |
| 0.50（默认，PROPOSED 未标定） | 0.400 | 38/95 | 0.195 | 0.0926 | 0.8652 | 0.1795 |
| 0.45 | 0.400 | 38/95 | 0.195 | 0.0926 | 0.8652 | 0.1795 |
| 0.40 | 0.389 | 37/95 | 0.195 | 0.1111 | 0.8652 | 0.1795 |
| 0.35 | 0.389 | 37/95 | 0.195 | 0.1111 | 0.8652 | 0.1795 |
| 0.30 | 0.389 | 37/95 | 0.195 | 0.1111 | 0.8652 | 0.1795 |
| 0.25 | 0.389 | 37/95 | 0.195 | 0.1296 | 0.8652 | 0.1795 |

- 结论：在这批 v4.1 val 预测上，**降低 tau_kpt 不提高 reference coverage**（覆盖受 2D 定位精度限制，不是发射被抑制；baseline 3104 emission rate 已 92.7%），反而让 false_reference 从 0.093 升到 0.130 → **不采纳**。
- 与 diag 的差异说明：diag 在旧 exploratory final 上观察到 28 帧被 0.24–0.495 抑制；本实验在 v4.1 val 的 60ep baseline 上未复现该收益，说明"可用性阈值未标定"的收益依数据/checkpoint 而变，不可作为已证改进。B 判定 **FAIL**。

## 5. Gate 判定（预注册规则，逐条）

| 条件 | A | B |
| --- | --- | --- |
| val joint 相对 matched baseline 绝对提升 ≥ +0.08 | 0.074 → **FAIL** | 0.000 → **FAIL** |
| identity 高置信误配不恶化 | A FMR 0.000 vs baseline 0.2308 → 通过 | B FMR 0.1795 vs baseline 0.1795 → 通过（但 false_reference 0.093→0.130 变差，另见 §4） |
| val joint ≥ 0.60 | 0.453 → **FAIL** | 0.400 → **FAIL** |
| 是否推进 3 seed | **否** | **否** |

- 决定：**STOP**。不追加完整训练（完整训练使用 1/4：baseline 60 ep）；不触发 holdout（`landmark_holdout_freeze_v1.json` 仍 NOT_TRIGGERED）；不读 final/exploratory 版本作验证。

## 6. 同口径 reference/bearing 诊断（旧 3px 与 bearing 并报）

| 指标 | baseline pilot15（选中 best） | 候选 A pilot15（选中 last） |
| --- | --- | --- |
| GT 正例 / 参考可用 | 95 / 41 | 95 / 41 |
| 已发射 kpt / 无 kpt | 38 / 3（发射率 92.7%） | 33 / 8（80.5%） |
| 3px 内 correct / wrong anchor | 6 / 32（覆盖 0.146） | 6 / 27（覆盖 0.146） |
| 2D 误差 中位 / P90 / max | 6.60 / 13.08 / 24.13 px | 5.09 / 8.76 / 10.63 px |
| 纵向 dy 中位（+下） | +1.12 px | +0.34 px |
| bearing 误差 中位 / P90 / max | 0.78° / 2.73° / 5.30° | 0.63° / 2.13° / 2.64° |
| 2D>3px 但 bearing≤3° | 28/38 = **73.7%** | 27/33 = **81.8%** |

- 与 diag 一致：**主要瓶颈是 2D 定位（纵向为主）而非水平 bearing**；旧 3px 2D 口径对"消费端只用水平 bearing"偏严（此为新诊断口径，不替换旧 3px 结果）。
- A 的 2D 中位与 bearing 有改善、dy 偏差减小，但 3px 内计数不变（6/41），因此 reference coverage 没有实质提升。

## 7. 预算与协议记录

- 完整训练：1/4（v4 baseline 60 ep，249 s，4.16 s/epoch，无 OOM；因他人 pytest 竞争 CPU 偏慢）。
- pilot：2 次（baseline 15 ep、候选 A 15 ep；不计入完整训练上限）。
- 未执行：优胜 3 seed（gate 未过）、holdout（未触发）、identity val_identity 评测（STOP 前未进入 identity 门）。
- 协议：`configs/perception/landmark_improvement_protocol_v1.json`（已登记 v4/v4.1/v4.2 引用、候选 A/B、diag sha、gate 判定与 STOP）。

## 8. 失败诊断与路线建议（不改判本实验结果）

1. **reference 定位精度是主瓶颈**：41 个参考可用帧只有 6 个在 3px 内，2D 中位 6.6 px；发射率已 92.7%，说明不是"找没找到参考"的问题。
2. **数据补充（A）有效但不足**：复用 279 帧把 TINY/LARGE 部分帧与 presence 精度拉上来（Δ+0.074），但未改善近距 LARGE 的定位精度；建议下一版**专门采集/标注近距（1.5–2 m）大目标的严格绿光参考帧**，并用"严格绿光质心重测"分离标注误差与模型回归误差（diag §2.5）。
3. **可用性决策（B）不是本 checkpoint 的瓶颈**：降低 tau_kpt 无收益且增大 false reference；不建议作为独立候选再投预算。
4. **评测口径**：若要按消费端用途验收，建议 lead/evaltool 预注册"bearing-primary + 2D diagnostic"的新口径；本报告只并列报告，不改旧 3px 结果。
5. **identity**：MS1 已证伪 U1/U2，identity 不认证；v4.2 val_identity 62 帧已就绪，但本路线 STOP 前未使用。

## 9. 限制与非声明

- pilot 15 epoch 全在 warmup 内（趋势探针）；单 seed；不是收敛模型结果。
- val 负例 39（12 TARGET_ABSENT + 27 合成 HN1）；FMR 分母不足以认证 0.5%；HN1 为合成注入、非真实分布；HN2 26 帧 GT_UNOBSERVABLE 单列排除。
- 不声明旧 final 通过、不声明模型效果达标、不声明 identity/板端/导航/认证能力；未提交 git、未提升 Gate、未接控制/PPO。

## 10. 证据路径

| 内容 | 路径 |
| --- | --- |
| 指标 JSON | `docs/reports/perception/training_20261104/improvement_metrics_20261104.json` |
| baseline 60ep | `outputs/landmark_train/runs/improvement_v4/baseline_seed0/`（证据 `bounded_evidence_seed0.json`） |
| matched baseline pilot15 | `runs/improvement_v4/baseline_pilot15_seed0/` |
| 候选 A pilot15 | `runs/improvement_v4/candidateA_pilot15_seed0/` |
| 候选 B sweep | `runs/improvement_v4/candidateB_tau_kpt_sweep/tau_kpt_*/` |
| reference/bearing 分析 | `runs/improvement_v4/*/reference_error_analysis*.json` |
| train 合并证据 | `outputs/landmark_train/dataset/v4_1_train_merge_evidence.json` |
| v4.1 dataset | `outputs/landmark_train/dataset/dev_v4_1/dataset_build.json` |
| 预注册协议 | `configs/perception/landmark_improvement_protocol_v1.json` |
| gate | `configs/perception/landmark_improvement_gate_v1.json` |
| diag | `docs/reports/perception/posteval_20261104/POSTEVAL_DIAGNOSIS_20261104.md`（DRAFT） |
