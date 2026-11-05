# Two-class 身份通道与消费者验证（2026-11-05 新工作包）

> 预注册：configs/perception/landmark_two_class_protocol_v1.json（先于训练/评测冻结）；标签规范：landmark_two_class_label_spec_v1.json；旧包 47d1063 封闭、旧模型/协议/hash 不改。

## 阶段
- [x] P0 工作包与接手清理：核对现场、修 CURRENT_STATUS/AGENTS 过时当前限制、发布预注册/规范/门/预算/manifest。
- [x] P1 数据：two-class 训练批量采集（8 新族 ~360 帧，GUI）；两类标注（annot/annot2 分片）；val_main MS1 附加标注；v6 freeze + snapshot v7 + 泄漏审计。
- [x] P2 工程 smoke：nc=2 loader、class1 kpt v=0 loss mask、tiny overfit、无 GT 推理、单类接口兼容、测试。
- [x] P3 训练：R1 直接 two-class（从单类 v5 权重微调）单 seed ≤15ep pilot；按 pilot 门判定；仅明确失败证据才启用 R2。
- [x] P4 三 seed：优胜配方 seeds 0/1/2 ≤60ep；仅 val 选模/阈值；全部 seed/最差 seed/最差组。
- [x] P5 消费者评测：两类混淆、identity P/R/FMR、MS1 错误塔声明、同框目标选择、reference/bearing/成功覆盖、全正例 consumer 成功率；单类冻结基线同口径对照。
- [x] P6 门判定：development→holdout 门逐条判定；未过则停止本版（不采 holdout），交付错误分析与路线建议。
- [x] P7 过门则新 holdout v3：≥3 新族/200–400 帧/覆盖 MS1 单独、塔单独、同框、尺度、截断遮挡、缺席；采样先冻结；冻结后一次性评价。
- [x] P8 ONNX：two-class 权重导出，pt/原生ONNX/raw-ORT 对两类/同框/NMS/identity/reject/bearing 决策对齐。
- [x] P9 收尾：报告/状态/交接/计划/AGENTS；回归+全套测试+文档审计；中文提交、不推送。

## 实际结果（2026-11-05 收尾）

- R1（v6.1，15ep pilot）：MS1 recall 10/35=0.286 <0.50 → pilot gate FAIL（唯一硬失败）；原因=近距 MS1 OOD + class1 head 重初始化/15ep/val class1=0 选模盲。
- R2（v6.2+近距 MS1 102，15ep pilot，唯一变量=数据）：MS1 recall 20/35=0.571 修复、tower 0.853；但 official same-frame 15/47=0.319、13/26=0.500 <0.60 → pilot gate FAIL；identity false-ref 0.077→0.500、consumer all 0.698→0.434、val negative claims 2/39、GT_UNOBS improper 2 回退。
- 预算：2 pilot、0 完整训练；未 3-seed；holdout v3 NOT_TRIGGERED；ONNX 无最终选定权重 → NOT_RUN。
- 结论：停止本版 two-class；近距数据有效但 same-frame/参考通道未解决；下一版需新预注册。
