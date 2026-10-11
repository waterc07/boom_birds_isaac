# Boom_Birds

微型四旋翼自主系统研究工作区。统一入口：[项目总纲](PROJECT_PLAN.md)。

2026-10-10，规划已修订为v1.1（基地小装甲、阵营切换、拦截和实飞基础），历史基线2026-10-09。保留PX4，首版速度＋偏航率；传统基线优先，监督学习/PPO按缺口引入。本研究工作区尚无业务代码。用户确认PX4 1.17无GPS/光流/无磁力计定高实飞及MAVLink通信已完成；速度Offboard、SITL、视觉、Pi全链与跨场/拦截仍未验证；现有Isaac官方基础步进只是历史环境证据。

现在阅读[首阶段执行计划](docs/design/04_FIRST_TASK.md)：W01软件合同→W02单套Linux PX4 SIH工具链和模式/故障验证。安装、训练、刷写、部署和飞行不属于当前规划目标的执行授权。

- [六份设计入口与需求追踪](docs/design/01_PROJECT_DESIGN.md)
- [架构与接口](docs/design/02_ARCHITECTURE.md)
- [阶段路线与工作包](docs/design/03_ROADMAP.md)
- [目录与工作区](docs/design/05_WORKSPACE.md)
- [重大未知与放行](docs/design/06_PARAMETERS_AND_RISKS.md)
- [场地与目标研究](docs/planning/04_RM_FIELD_AND_VISION.md)
- [可复算预算](docs/planning/06_FEASIBILITY_BUDGETS.md)
- [来源核查](docs/planning/07_SOURCE_REGISTER.md)与[后续任务验收协议](docs/planning/08_TASK_ACCEPTANCE_PROTOCOL.md)
- [v1.1：基地小装甲、阵营切换、实飞复用与拦截](docs/planning/09_TARGET_TEAM_AND_INTERCEPTION.md)
- [决策：PX4接口](docs/decisions/ADR-001_PX4_OFFBOARD.md)、[基线优先](docs/decisions/ADR-002_BASELINE_FIRST.md)、[最小工具链](docs/decisions/ADR-003_TOOLCHAIN.md)
- [规划验收](docs/reports/PLANNING_ACCEPTANCE.md)
- [目标模式要求](docs/planning/05_GOAL_MODE_PROMPT.md)

VS Code打开BoomBirds.code-workspace；不会自动激活旧环境或启动仿真。工作区路径已由用户确定，不等于所有建议门限已接受。参数分MEASURED/VENDOR/USER_PROVIDED/ASSUMED/UNKNOWN，门限PROPOSED/ACCEPTED，实验PASS/FAIL/NOT RUN。

原交接、报告和旧设计保存在docs/references及docs/research。旧设计与phase0计划备份在docs/references/design_before_v1_20261009，仅供历史追踪。当前实施以总纲和design/01–06为准。现有Isaac环境保留；本阶段不复制venv，不先训练或接运行时桥。
