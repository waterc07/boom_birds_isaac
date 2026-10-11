# Boom_Birds

微型四旋翼自主系统研究工作区，规划 v1.2（2026-10-11）。打开 `BoomBirds.code-workspace`，从[项目总纲](PROJECT_PLAN.md)开始。

已确定：Isaac Lab 主工程；NavRL 为首个导航/PPO基线参考；DiffPhysDrone 为轻量视觉与可微训练参考；PX4保留，首版速度＋偏航率。研究独立于旧项目，先基础运动和避障，再任务视觉。稠密双目深度不是部署前提。

当前已完成P0环境核查与标准库动作/时效合同：官方四旋翼100步、官方PPO单迭代兼容检查和31项合同测试通过；仍有环境依赖冲突。速度执行器、到点任务和本项目训练/部署均尚未实现。详见[当前核查报告](docs/reports/p0/P0_ENVIRONMENT_REPORT.md)，不要把未来命令当作已有入口。PX4 1.17无GPS、光流、无磁力计条件下的定高和MAVLink通信为用户已确认成果，其他能力不因此视为通过。

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
