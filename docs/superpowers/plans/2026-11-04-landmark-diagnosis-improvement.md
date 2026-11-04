# 地标失败诊断、工程修复与有界改进实验（2026-11-04 三阶段）

前置：HEAD 0c27525；用户已授权 YOLOv8n-pose 仅内部有界研究；旧 final/模型/协议/预测/hash 只增不改。

- [x] post-evaluation 诊断：评价定义审计（presence/identity/reference-availability/localization 分开；joint 正确拒绝口径；UNKNOWN/错误身份/漏检不消失；GT 歧义单列错误声明）、reference 失败分解、MS1 视觉可区分证据、TINY 可标注性盲复标。
- [x] 3px 2D 与 horizontal bearing 分开报告并核对消费者需求；旧结果保留、新口径单列。
- [x] PyTorch / Ultralytics 原生 ONNX / raw-ORT 端到端对齐；解释 4.67px 是否造成判定翻转；必要脚本入库 + CLI/配置，移除私有路径。
- [x] 实现缺陷先补失败回归再修；旧受影响结果追加勘误。
- [x] 补齐 HN 剩余帧与 identity/confuser development 案例；明确“只有一个检测框”不等于身份唯一。
- [x] dev v4 冻结（家族隔离、困难负例）、暴露登记更新、旧 exploratory 登记为 development、泄漏审计。
- [x] ≤2 个改进候选（对应确认根因），同数据同预算 pilot（单 seed ≤15ep）→ 优胜 3 seed ≤60ep，新完整训练 ≤4 次；仅 val 选模/阈值。
- [x] 预注册 development→holdout 门（val joint≥0.60 且改善≥+0.08 且误配不恶化且 coverage≥0.50）→ 触发才补采 ≥3 新族 200–400 帧 holdout，冻结后一次性评价；否则停止路线并交付失败诊断。
- [x] 同步状态/报告/交接/AGENTS；全套测试 + 文档审计；中文提交、不推送。
- [x] 实际结果：post-eval 诊断 + 评价审计 + ONNX 三路径 0 翻转 + 候选 A/B pilot；gate FAIL → STOP；holdout NOT_TRIGGERED；路线建议已写入汇总报告。
