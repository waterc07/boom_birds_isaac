# 最小感知消费者（shadow）

- [x] 重算 sensor shadow 统计：1728 total、846+490 accepted、392 invalid；18 差异为 RGB WARMUP 口径；追加 errata。
- [x] 审查/修复 capture 时间语义：v2 `SIM_UPDATE_SAMPLE_TIME`、exposure UNKNOWN、capture interval 250ms；旧 v1 输入显式 legacy/UNKNOWN；失败测试→修复。
- [x] 选择自然 RoboMaster 塔地标模板；消费者只读 RGB/intrinsics/template，不读 truth/pose/labels；输出检测/unknown/not_detected、bearing、score、拒绝原因；distance UNAVAILABLE。
- [x] 预冻结算法/模板/阈值/标签/split：freeze v4；train route_0，test route_1/reset0/reset1/static；标签按 episode 分离。
- [x] 离线正式评价：TP9/FP0/FN9/TN18，precision1.0/recall0.5；FN 遮挡/边缘/尺度失败保留；无 FP；test rejection 0。
- [x] 独立核验 24 checks PASS；pytest 799；文档审计；diff；样例 TP/FN/TN/UNKNOWN；hash。
- [x] 报告/交接/证据/中文提交（不推送）。

正式 consumer freeze source commit `1f8e242`；最终交付只增 freeze/template/labels/核验/报告/证据。下一项：真实相机/镜头/CSI/时间戳 + 地标数据库/区域拓扑，再接 shadow 区域消费者，不接控制。
