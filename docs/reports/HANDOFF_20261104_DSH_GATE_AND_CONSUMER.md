# 交接：阶段门勘误、不可变快照、候选 A 三 seed 与消费者协议（2026-11-04 四阶段收尾）

## 状态

- 分支 feat/v2.2-simulation-perception；开工 HEAD 3491cde；以提交为准。
- **旧 3px 协议：候选 A 3 seed 完成，holdout 门 PASS（joint 0.632 vs baseline 0.400；最差 seed 0.453）。**
- **消费者协议（身份+水平 bearing）：holdout 门 FAIL（身份确认通道缺失，strict_unknown consumer 成功=0）→ 本包 holdout NOT_TRIGGERED。**
- 未接控制/PPO、未提升 Gate、未推送；权重/大图/日志 ignored。

## 1. 阶段门勘误

- gate 文件 pilot 门 +0.05/FMR/coverage-0.02；A pilot Δ+0.074、FMR 0、coverage 相同 → PASS；上一包把 holdout 门（+0.08/joint≥0.60）误用于 pilot→3seed，导致提前 STOP。
- 已补完 3 seed；旧协议 holdout 门 PASS；勘误文档 GATE_STAGE_ERRATA_20261104.md（旧协议/旧报告未改）。

## 2. 不可变快照

- scripts/landmark_run_snapshot.py + configs v1/v5；启动前/选模前/结束后校验 13 artifacts；3 seed 全部 VALID；标签漂移（163→231）已被稳定文件阻断。

## 3. 候选 A 3 seed（旧 3px，val_main 163/95）

| seed | joint | refcov | identity P/FMR |
| --- | --- | --- | --- |
| 0 | 49/95=0.516 | 0.317 | 1.0/0.0 |
| 1 | 43/95=0.453 | 0.390 | 1.0/0.0 |
| 2 | 60/95=**0.632**（选定） | 0.561 | 1.0/0.0 |
| baseline | 38/95=0.400 | 0.195 | 0.865/0.180 |

- 冻结 configs/perception/landmark_model_freeze_v2.json（权重 sha 6b86ef1f…；阈值沿用先验 val 冻结值并注明未重调）。
- 旧协议 holdout 门 5 项 PASS（见 STAGE_VERIFICATION）。

## 4. 消费者协议

- 协议 configs/perception/landmark_consumer_protocol_v1.json（sha bdcc9ccd）。
- 双口径：raw claim upper bound（可记录）、strict_unknown（真实可交付）→ strict 下 all-positive 成功=0（身份确认通道缺失）。
- 单类 detector 无身份通道；appearance gate 在 annotated boxes 可分（aspect AUC 1.0）但 pipeline 预测框不可迁移（误拦 61/78 正确目标）；two-class detector NOT RUN。
- bearing：参考可用已发射子集全部 ≤3°（如 A3 seed0 last n=37 median 0.66°/P90 1.30°）；但 identity 缺口使 consumer 成功不成立。

## 5. 数据与身份案例

- v5 freeze（train 19 组/1857 帧、val 11 组/921=val_main 816+val_identity 105）；泄漏审计/外部索引 PASS；registry v2 修复 evidence sha。
- T25 补采 INCOMPLETE（formal CUDA OOM 无 run.complete；pilot 机位不合格）；T26 28 帧 PROVISIONAL_DIAGNOSTIC_ONLY，不并入 v5。
- holdout v2 预注册 SPEC_FROZEN_NOT_TRIGGERED（≥3 新族/200–400/6 类覆盖/固定抽样/一次性评测）；capture 草案 7 族/394 帧未触发。

## 6. 下一包建议与用户决定

1. 实现 two-class 身份通道（tower vs similar structure/MS1）——消费者验收必要条件；需第二类标签与一次新全量训练。
2. 重新预注册 consumer gate 后，再补采 holdout（按 v2 冻结规则）。
3. 若接受 bearing-primary + identity UNKNOWN 的阶段性口径，可先交付方位辅助但不得称身份关联。
4. 许可分发路线（未变）；板卡/真实相机可选 UNKNOWN。

## 7. 证据

- 汇总：docs/reports/perception/LANDMARK_ROUND4_GATE_AND_CONSUMER_RESULTS_20261104.md
- 勘误/阶段验证：GATE_STAGE_ERRATA_20261104.md、training_20261104/STAGE_VERIFICATION_20261104.md
- 消费评测：CONSUMER_EVAL_20261104.md/.json；identity 特征：posteval_20261104/MS1_IDENTITY_ANALYSIS、IDENTITY_APPEARANCE_FEATURES
- 数据 v5：landmark_split_freeze_v5.json、DATASET_FREEZE_V5_20261104.md、leakage/external index
- 快照：landmark_run_snapshot_v5.json、scripts/landmark_run_snapshot.py
- ONNX 三路径（候选 A）：ONNX_PARITY_20261104.md/JSON（T29 增量）
- 运行证据（ignored）：outputs/landmark_train/runs/stage_verify_v5/、outputs/perception/consumer_eval_20261104/
