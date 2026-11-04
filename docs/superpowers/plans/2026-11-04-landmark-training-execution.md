# 地标训练执行阶段：规范闭环、完整数据、工具链与有界训练（2026-11-04 二阶段）

前置：HEAD 800c53b；用户已授权主候选（YOLOv8n-pose/AGPL-3.0）仅用于内部有界研究，分发另行决策。

- [x] 修正准入/评价口径：探索启动条件 E1–E5 与最终认证条件 C1–C8 分开；代理标注/有限样本/无板卡限制结论而非无条件阻塞。
- [x] 分母审计：预测 UNKNOWN/REJECTED 不从召回/覆盖/joint 分母消失；GT 不可判定与预测 UNKNOWN 分开；GT 参考点不可见不评定位误差但保留 presence；失败测试覆盖。
- [x] 暴露审计：34 帧试点使 final 6 族池降级 development/exploratory；检查同组近邻污染；不冒称 sealed。
- [x] spec v2.1：四边截断元数据、参考点像素可用判据、未验证 confuser 状态；v2 向后兼容；冻结后用于 final。
- [x] 完整标注：dev train/val 去重代表抽样 + 标注；final 探索池 279 帧完整标注；来源/QA/争议记录；标签 ignored。
- [x] 补采 dev 轨迹族（避免 val 仅北走廊）与 HN1 带绿灯相似结构 / HN2 完全遮挡；GUI 可见；记录合成干预。
- [x] 工具链：标签转换/单关键点 v=0 映射/letterbox 逆变换/推理输出/多候选拒绝/分层评价入口。
- [x] 隔离 venv（不改 Isaac venv）→ GPU 单关键点 smoke → 小样本过拟合 → ONNX 一致性 → 单 seed pilot → 最多 3 seed × 100 epoch 有界训练；仅 val 选 checkpoint/阈值/seed。
- [x] final：模型/阈值冻结后对 exploratory 池只评一次，明确 exploratory 而非 sealed。
- [x] RKNN 自定义模型转换：条件满足时执行，否则 UNKNOWN；无板卡不阻塞主机实验。
- [x] 同步 CURRENT_STATUS/报告/交接；全套测试 + 文档审计；中文提交、不推送。
- [x] 实际结果：val joint 0.484/0.579/0.442（选 seed1）；exploratory final presence P1.000/R0.916、ref coverage 0.284、joint 0.298；效果门未达、认证 INCOMPLETE、不回调。
