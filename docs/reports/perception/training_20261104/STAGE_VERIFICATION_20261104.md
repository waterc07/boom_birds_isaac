# 候选 A 三 seed 阶段验证（旧 3px 协议）与两级门判定（2026-11-04 修正版）

> **状态：** BASELINE（dev 验证集，旧 3px 协议；非认证、非板端/导航）
> **来源章节：** V2.2 §20.9/§20.11；configs/perception/landmark_improvement_gate_v1.json（冻结值 +0.05 pilot / +0.08+joint0.60 holdout）；landmark_improvement_protocol_v1.json
> **证据域：** 隔离 venv 训练 + val_main 163 帧只读评测；无 final、无板端/实机
> **最后核对：** 2026-11-04

本文件更正上一包“阶段门误用”并补完候选 A 的 3-seed 阶段验证。**旧 3px 协议的两级门分开判定：pilot 门 PASS（已由勘误确认）→ 3-seed；3-seed 后旧协议 holdout 门 PASS。** 但本包的消费者协议（身份+bearing）holdout 门因**身份确认通道缺失** FAIL，详见 CONSUMER_EVAL 与最终报告。

## 1. 执行（不可变快照）

- 运行：`stage_verify_v5/seed{0,1,2}`，v4.1 train（16 组/1772 帧，labels 01977b9f + 7115ee04），epochs 60、batch16、imgsz640、cache=ram、workers=0、seed 0/1/2、warmup15、patience20 从 warmup 后起算。
- 不可变快照：每次运行前 create+verify（13 artifacts：v4.1 freeze、dev/reuse/merged train labels、val_main 163、spec v2.1、protocol、gate、model yaml、data.yaml 等）；pre_train/pre_selection/post_train 校验；seed0/seed1/seed2 的 pre_train 均 VALID；无 mismatch。
- baseline：复用 v4 60ep seed0（`improvement_v4/baseline_seed0`；matched baseline 定义=同一 recipe、v4 train 不含 reuse）。
- 运行时间：seed0 60ep≈4.5min（最后一次稳定配置）；seed1 42ep 早停（warmup 后 patience 20）；seed2 60ep；无 OOM/RAM 失败（失败尝试目录保留为诊断证据）。

## 2. 每 seed 结果（val_main 163；joint=旧 3px 窄口径，分母 95）

| seed | 选中候选 | joint | presence P/R | reference coverage | identity P / FMR | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | last | 49/95=0.516 | 1.000 / 0.779 | 0.317 | 1.000 / 0.000 | epoch20/40/best 更低（0.211/0.358/0.326） |
| 1 | last | 43/95=0.453 | — | 0.390 | 1.000 / 0.000 | 42ep 早停（warmup 后 patience） |
| 2 | last | **60/95=0.632** | **1.000 / 0.821** | **0.561** | **1.000 / 0.000** | 选定；worst fam 28/50=0.56 |
| baseline (v4 60ep) | best | 38/95=0.400 | 0.86 / 0.78 | 0.195 | 0.865 / 0.180 | worst fam_dev_static_low 0/15 |

- 选定：**seed2/eval_last**（最高 val joint；并列规则未触发）。最差 seed=1（0.453）。
- 相对 baseline：Δ joint = **+0.2316**（0.632−0.400）。
- 冻结：configs/perception/landmark_model_freeze_v2.json（权重 sha 6b86ef1f…；阈值沿用先验 val 冻结值并注明未重调）。

## 3. 旧协议 holdout 门（gate 文件冻结条件）

| 条件 | 值 | 判定 |
| --- | --- | --- |
| val joint ≥0.60 | 0.6316 | PASS |
| 改善 ≥+0.08 | +0.2316 | PASS |
| identity FMR ≤ baseline | 0.000 vs 0.1795 | PASS |
| reference coverage ≥0.50 | 0.561 | PASS |
| worst-group 不差于 baseline >0.05 | 0.56 vs 0.00 | PASS |

**旧 3px 协议 holdout 门 = PASS。** 也就是说，上一包“候选 A 未进 3 seed”是阶段门误用；补完后 A 在旧协议下满足 holdout 门。

## 4. 消费者协议 holdout 门（本包目标）

| 条件 | 值 | 判定 |
| --- | --- | --- |
| 确认身份下 consumer 成功 ≥0.50 | strict_unknown 口径下 =0（身份确认通道缺失）；raw claim 上界 0.6–0.76 不是有效 gate 输入 | FAIL |
| 身份确认通道可用 | 单类 detector + appearance gate 在 pipeline 预测框上不可迁移（误拦 61/78 正确目标）；two-class detector NOT RUN | FAIL |
| bearing/reference 条件 | bearing 中位/P90 满足 PROPOSED（0.66°/1.30°）、拒绝正确率满足；但这些不能救 identity | 部分 PASS |

**消费者协议 holdout 门 = FAIL（身份确认通道缺失）。** 因此本包不采集 holdout：旧协议 holdout 即使 PASS，用旧 3px 口径评测也无法回答“身份+水平 bearing”这一消费者要求。

## 5. 结论与建议

- 旧 3px 协议：pilot 门 PASS → 3-seed 完成 → holdout 门 PASS（joint 0.632，Δ+0.232；最差 seed 0.453）。这更正了上一包的 STOP 叙述：A 在旧口径下是有效改进。
- 消费者协议：身份确认通道未解决 → holdout 门 FAIL；建议下一包执行 two-class（tower vs similar structure/MS1）身份通道，重新预注册 consumer gate 后再评估 holdout。
- 旧结果/旧 STOP 文档保留原字节；本文件为其勘误与补充。
