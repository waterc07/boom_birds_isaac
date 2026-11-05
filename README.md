# Boom_Birds

微型四旋翼自主系统研究工作区，当前路线 **V2.2.0（2026-10-31 验收修订）**，基于用户指定的 DSH V2.1.0。见 [完整架构](docs/design/RMUC2027_UAV_V2_2.md)与 [验收修改报告](docs/reports/ROUTE_V2_2_REVIEW_20261031.md)。采用 RK3576、非 VIO 区域/地标接力、局部 RL、独立碰撞恢复与触点通信；板端可行性验证先于大规模训练。

**当前进度（2026-11-05）：** 地标单类有界训练、阶段门勘误及 two-class 身份通道实验已完成归档。旧 3px 协议候选 A 三 seed 的 holdout 门通过，但消费者协议身份通道未通过；随后 two-class R1/R2 两次 pilot 均未通过 pilot→3seed 门，two-class 本版 STOP，未进入三 seed 完整训练，未触发新 holdout。R2 pilot ONNX 三路径对齐仅为诊断性工程证据（NOT_SELECTED_VALIDATED_PILOT_ONLY / DIAGNOSTIC_ONLY_NOT_GATE），不是效果、身份或板端验收。 感知保持 shadow，不进入控制，不提升 Gate。详细证据、历史勘误和下一项见 [当前状态索引](docs/reports/CURRENT_STATUS.md)。

## 历史说明（2026-10-11；已被新路线取代）

下方阶段、硬件和“当前”用语是历史信息，后续实施从上述完整架构及项目总纲开始。打开 `BoomBirds.code-workspace`，从[项目总纲](PROJECT_PLAN.md)开始。

已确定：Isaac Lab 主工程；NavRL 为首个导航/PPO基线参考；DiffPhysDrone 为轻量视觉与可微训练参考；PX4保留，首版速度＋偏航率。研究独立于旧项目，先基础运动和避障，再任务视觉。稠密双目深度不是部署前提。

当前已完成P0环境核查与标准库动作/时效合同：官方四旋翼100步、官方PPO单迭代兼容检查和33项合同测试通过；仍有环境依赖冲突。速度执行器、到点任务和本项目训练/部署均尚未实现。详见[当前核查报告](docs/reports/p0/P0_ENVIRONMENT_REPORT.md)，不要把未来命令当作已有入口。PX4 1.17无GPS、光流、无磁力计条件下的定高和MAVLink通信为用户已确认成果，其他能力不因此视为通过。

| 要解决的问题 | 阅读入口 |
| --- | --- |
| 做什么、如何算完成 | [设计](docs/design/01_PROJECT_DESIGN.md)、[验收](docs/design/08_EVALUATION.md) |
| 先学什么 | [学习路线](docs/design/07_LEARNING_PATH.md) |
| 先实现什么 | [首阶段](docs/design/04_FIRST_TASK.md)、[具体任务](docs/superpowers/plans/2026-10-11-p0-p1-foundation.md) |
| 模块怎样连接 | [架构](docs/design/02_ARCHITECTURE.md) |
| 文件放哪里 | [工作区](docs/design/05_WORKSPACE.md) |
| 哪些代码复用 | [开源基线](docs/design/09_OPEN_SOURCE_BASELINE.md) |
| 完整开发顺序 | [路线](docs/design/03_ROADMAP.md) |
| 哪些未知会改变路线 | [参数与风险](docs/design/06_PARAMETERS_AND_RISKS.md) |

现有资料、预算和历史检查在docs/planning、docs/references、env。数值标签：USER_PROVIDED/MEASURED/ASSUMED/UNKNOWN；门限标签：PROPOSED/ACCEPTED；实验标签：NOT RUN/PASS/FAIL。本版规划核查见[交付报告](docs/reports/PLANNING_ACCEPTANCE.md)。


## 单环境动态评价默认升级（2026-11-03）

`scripts/run_dynamic_eval.py` 的单环境评价默认已升级为 `--geometry-policy reference_origin_v2 --contact-mode measured_hard_reset`。历史复现必须显式传 `--geometry-policy legacy --contact-mode legacy_inference`；旧 v1 raw-hash/旧 boundary/latency freeze 在新默认下会被明确拒绝，不自动回退。新 freeze schema v2 记录 hash algorithm、实际生效配置与 default/explicit 来源。只影响该单环境评价入口，不影响训练/多环境/官方 smoke。证据见 `docs/reports/map_eval/contact_envelope/DSH_DYNAMIC_DEFAULT_UPGRADE_20261103.md`。
