# 地标感知任务定义与有界学习实验包

- [x] 审查 18 正例/9 定位/3 joint 口径，追加勘误；区分 3/9、3/18 下界、未标注不自动失败。
- [x] 核对 anchor .036° 样本数/family/标注同源问题；不宣称亚像素实物精度。
- [x] 从 V2.2 §7.4/7.5/7.7/7.8/9.1/10.1 提取上游→感知→关联→决策需求；明确身份/绿灯 anchor/图像 bearing/bbox 辅助/mask 非必需/拒绝条件；提出 PROPOSED 接口。
- [x] 比较 YOLOv8n-pose、YOLOX-Nano、分割三方案；主候选 YOLOv8n-pose（AGPL，RKNN zoo 有 pose 例）、备选 YOLOX-Nano（Apache，anchor 仍经典）；分割因无 mask 消费者不选。
- [x] 整理数据清单：全部暴露、无 sealed；按轨迹组划分规则；new test 需 ≥3 新组/200–400 帧。
- [x] 标注规范+12 帧样例+QA 工具；letterbox/roundtrip/hflip 测试；代理标注局限。
- [x] 只读部署检查：Isaac venv 未改；无超分/RKNN/权重；隔离环境计划、RK3576 UNKNOWN。
- [x] 形成可执行有界训练计划（数据/预算/seeds/早停/验证选模/一次性 final/proPOSED 门限/停止/命令），不执行训练。
- [x] 报告/交接/证据；下文提交不推送。

下一项：若 AGPL 可接受且数据组满足，执行 YOLOv8n-pose 有界训练；否则先跑 Apache YOLOX-Nano 检测+经典 anchor。任何训练前先冻结数据/标注/源码/版本。
