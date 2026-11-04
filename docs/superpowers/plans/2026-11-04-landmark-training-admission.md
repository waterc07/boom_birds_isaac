# 地标学习训练前闭环与数据准备（2026-11-04）

工作包目标：把“能否开始训练”变成可执行、可审查的准入结论；不启动训练、不装训练依赖、不下载模型。

- [x] 修正任务与实验定义：tower 类别检测 vs landmark_id 关联；唯一性假设 U1–U3、困难负例 HN1–HN6、多候选拒绝 M1–M6；presence/reference/identity/joint 判定与分母（含 GT 不可观测规则）；warmup 15/patience 20/诊断 vs 中止；三 seed 仅用验证集比较/选模/冻阈值后一次 final，不回调。定义 → `docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md`；协议 → `configs/perception/landmark_training_plan_v2.json`；可执行分母 → `src/boom_birds/evaluation/landmark_metrics.py` + 9 条测试。
- [x] 验证标注可用性：盲复标 21 帧/33 旧记录（bbox IoU 0.649、keypoint 1.155 px=0.414°、不可判定 19.0%、visibility 5/21 分歧）；格式 QA 与语义分开；代理复标未冒称专家；证实“目标存在但参考点不可见”可表达、旧 schema 缺原因/候选/三态 → spec v2；旧 0.036° anchor 被证实为同源绿色质心循环证据。
- [x] 数据准备与防泄漏：实况核查 13 目录/3002 帧/2909 accepted（旧 inventory 漏列 9 目录/1300 帧）；dev 划分 v1/v2 冻结（v2 保守：train 7 组 1320 帧、val 3 组 575 帧、excluded 9 组 1107 帧；val 仅北走廊 → held-out INCOMPLETE）；不随机拆连续帧（工具 + 31 条测试）；新增 6 新轨迹族 / 297 RGB / 279 accepted final 池，覆盖近距/远景/侧向/右缘截断/目标缺席/出视场；Isaac 采集保持可见前台 GUI（D3D12/RTX 5080/驱动 581.80）并保存窗口截图/运行证据；未回退 headless。
- [x] 访问边界与封存：标注者可看 test，但 test 内容/结果不得用于模型或阈值开发；无法可信隔离时如实标记，只凭 hash 不称 sealed；final 池分组/清单/逐帧 hash/标签状态冻结（完整语义标签 PENDING）；原始 320×240 帧与 obs 留 ignored outputs，仓库只存清单+hash+小证据。
- [x] 训练准入结论：许可待决项引用官方原文并区分来源陈述/项目决策/未确认解释；不擅自认定接受 AGPL、不自动切备选；复核 8.2.0 版本、RTX 5080 sm_120/torch 2.7.0+cu128、自定义 1-keypoint ONNX/RKNN（UNKNOWN）；仅查证据、未改 Isaac 环境。判定 INCOMPLETE / 训练启动 BLOCKED → `docs/reports/perception/TRAINING_ADMISSION_20261104.md` + JSON。
- [x] 同步训练计划、CURRENT_STATUS.md、报告与交接；跑单测与文档审计；中文提交、不推送。
