# 阶段门勘误、消费者协议与候选A阶段验证（2026-11-04 四阶段）

前置：HEAD 3491cde；旧结果/协议/hash 只增不改。

- [x] 阶段门审计与勘误：确认 pilot 门为 +0.05/FMR/coverage-0.02；A 满足 pilot 门；上一包把 holdout 门误用于 3-seed 晋级 → 追加勘误，三分结论（pilot 可继续 / holdout 未获准 / 路线未被证伪）。
- [x] 不可变运行快照：数据/标签/spec/protocol sha 在启动前、选模前、结束后校验；变化即 INVALID；接入训练 CLI。
- [x] 标签漂移审计与稳定基线；TINY 结论收敛为当前样本/方法下不可标注，全域分母与三类分母分列，不删难例。
- [x] consumer 协议冻结（身份+参考点可用+水平 bearing+有效观测；2D 仅诊断；全域/可观测域分母；拒绝/发射/错误身份率）。
- [x] 数据：v5 freeze（identity train/val 组划分、MS1 真负例、近距 LARGE/截断/绿光可用样本）；补采相互遮挡/远景 MS1；训练实际使用样本核查。
- [x] 候选 A 3 seed × ≤60ep 阶段验证（旧协议），每 seed/最差 seed/最差组；baseline 复用既有 v4 60ep seed0。
- [x] consumer + appearance-gate 身份评估（val_main/val_identity），stage-specific gate 判定；未过则停止该版并保留证据。
- [x] 过 development 门则补采新 holdout（≥3 新族/200–400 帧，采样先冻结）→ 冻结后一次性评价；未过则记录 NOT_TRIGGERED 与依据。
- [x] ONNX 新模型身份/拒绝/bearing 决策翻转检查。
- [x] 同步状态/报告/交接/AGENTS；全套测试+文档审计；中文提交、不推送。

- [x] 实际结果：pilot 门勘误确认；A 3 seed（seed2 0.632 选定）旧协议 holdout 门 PASS；consumer strict 成功=0（身份通道缺失）→ holdout NOT_TRIGGERED；未推送。
