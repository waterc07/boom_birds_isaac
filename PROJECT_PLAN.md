# Boom_Birds 项目总纲

> **当前路线：V2.2.0，2026-10-31 验收修订**，基于用户指定的 DSH V2.1.0。当前唯一设计正文为 [RMUC2027 完整架构](docs/design/RMUC2027_UAV_V2_2.md)，优先于本文件下方的 v1.2 历史内容和旧设计。见 [验收报告](docs/reports/ROUTE_V2_2_REVIEW_20261031.md)、[原始快照](docs/references/route_v2_1_20261030.md)及 [来源 hash](docs/references/route_review_provenance.json)。

## 当前实施状态（2026-11-04）

已实现范围、当前失败结论及证据优先级见 [当前状态索引](docs/reports/CURRENT_STATUS.md)。单环境接触新模式已成为动态评价默认；RGB/深度采集及自然地标消费者保持 shadow。模板和几何/绿灯方法已停止作为主候选，感知与导航未达标。下一项是消费者需求、轻量模型、标注和部署可行性评审；尚未选定实例分割，也未启动正式训练。

项目 PPO、真实感知、PX4 Sender、板端 Student、SITL/HIL/实机验收与全部 BB22 Gate 保持未通过。软件/仿真准备可按依赖推进，硬件输入针对具体物理验证收集。

## 新路线与早期实施记录（2026-10-31）

下方实施计数和“下一项”保留为当日历史；后续修订及当前结论以上述索引为准。

采用 RK3576、已购买 3S 350mAh、PX4 独立飞控、非 VIO 区域拓扑与地标接力、目标相对视觉和停靠触点通信。传感器模组、规则合规、固件和电池铭牌仍待核对。RL 用于局部技能；碰撞后旧导航参考、跟踪与策略历史作废，独立恢复控制器接管。大规模训练前先做完整代表性 Student 的 RK3576 部署验证。

2026-10-31 实施核对：BB22:G2.6 软件合同已实现（`boom_birds.message.v2.0` / `boom_birds.action.v2.0`，四级上下文、时钟与 PX4 重启隔离、不可续期 TTL、所有权交接、碰撞/reset 失效）；仿真速度执行链已实测（仅仿真模型）；最小到点与统一评价入口已建立；比例/制动两种传统制导完成 30 场景 × 2 方法 = 60 episode 配对比较与 4 类专项故障验证（状态 INCOMPLETE，新基线未优于比例法）。分层评价 v2 已完成五类自然场景（A 无障碍/B 静态障碍/C 动态实体/D 观测退化/E 物理扰动）与冻结后 125 valid episode：A 25/25、B 0/25（25/25 PhysX 接触）、C 24/25、D 25/25、E 3/25；独立核验 24 项 PASS。该结果是仿真评价扩展，不是 BB22:G4 放行。随后完成 E 类扰动越界诊断：确认横向力累计与整机质心杠杆力矩两项施力实现缺陷并修复，冻结集 E 类 19/25 越界降至 0/25，A/B/C/D 回归不变；报告见 `docs/reports/e_diagnosis/E_DIAGNOSIS_REPORT.md`。另完成 C 类残留越界诊断：定位为评价 episode 边界缺陷（环境随机化 episode 计数 + 运行器忽略 truncated），修复后 C 25/25、A–E 125 clean 回归 100/125 success、0 越界；报告见 `docs/reports/c_diagnosis/C_DIAGNOSIS_REPORT.md`。随后完成 episode 边界全入口修复与历史审计：C-021 及 layered final_run2/3 确认污染，velocity/reach 未发现证据但记录不足，compare/tuning 数据不足；以前台 GUI 重建 velocity/reach/compare/faults 干净基线并独立核验，报告见 `docs/reports/eval_audit/CLEAN_BASELINE_REPORT.md`。随后接入 RMUC2027 USD 地图动力学评价：地图配置/坐标/碰撞合同、禁用默认平面，冻结 10 episode（到点 6、起降 2、真实 PhysX 接触 2）全部完成并独立核验 PASS；官方 smoke 以 DirectX GUI 复跑 PASS。报告见 `docs/reports/map_eval/MAP_EVAL_REPORT.md`；不是比赛导航/避障验收，不提升 Gate。随后扩展到 4 个候选区域、3 个有效区域与 2 条跨区离线航点路线，冻结 24 episode（local 12、route 8、接触 4）完成并独立核验 24 项 PASS；报告见 `docs/reports/map_eval/MAP_ROUTES_REPORT.md`。随后加入动态障碍停止—等待—恢复监督器（ORACLE 观测、运动学真实碰撞障碍），A–E 20 场景×2 方法=40 配对 episode 与 8 个无障碍回归完成，独立核验 25 项 PASS；报告见 `docs/reports/map_eval/MAP_DYNAMIC_REPORT.md`。
随后将动态监督器执行路径显式迁移到 v2 上下文/接纳/不可续期 TTL/所有权门（模拟 PX4 身份），完成 20 动态 +8 回归 +14 软件故障 GUI、独立核验 43 项 PASS；报告见 `docs/reports/map_eval/MAP_V2_EXEC_REPORT.md`。
随后完成制动包络与故障后观测：36 制动 +8 故障后物理观测，实测停止距离 .185–.585 m、时间 1.25–3.25 s，确认旧 setpoint 到 TTL 后降级与 ABORT≠物理停止；报告 `docs/reports/map_eval/MAP_BRAKE_ENVELOPE_REPORT.md`。仅当前模型证据，不提升 Gate。v1 保留显式对照，不是 PX4 Sender/实机安全，不提升 Gate。不是 PX4 监督器/视觉避障/实机安全，不提升 Gate。MAVLink Sender、恢复控制器、感知（G3）、板端 Student 与训练仍未实现/未验证；所有新 Gate 未通过。旧环境依赖冲突和失败证据保留；官方 smoke 不代表新路线通过。新 Gate 使用 `BB22:G0` 等完整标识，不继承旧 PASS。

执行顺序：

1. 新 Phase 0：归档官方规则、实物 BOM 和准确 PX4 固件/参数来源，补 Schema 差异及可测试合同；重量、推进、供电联合门按 BB22:G0.5 留证。
2. 可先实施 BB22:G2.6 纯软件合同：时钟、PX4 重启、四级上下文、不可续期 TTL、合法重发和控制交接。先写失败测试，显式迁移旧 Schema。
3. Phase 1/2 验证飞控与真实传感链；Phase 2.5 测完整代表性 Student 的 CPU/NPU 划分、量化、并发和延迟；视觉数据采集可提前。
4. 仿真先复用旧 Task 3 的速度 → 外环 → 力/力矩 → 实际运动验证方法，再建立传统导航和统一评价。旧 Task 4–6 不自动继续，须按新 Gate 更新具体计划。
5. 后续 Teacher、Student、技能、恢复、泛化/退化、最终部署、HIL、受控自主飞行、机库按正文依赖推进。BB22:G12 同时依赖飞行、机库、规则和完整任务证据。

以上为后续实施顺序；截至 2026-10-31 已验证入口与证据见 [AGENTS.md](AGENTS.md)、[传统制导基线报告](docs/reports/guidance_baseline/GUIDANCE_BASELINE_REPORT.md)。保留现有 Isaac Lab、RSL-RL 5.0.1、`src/boom_birds`、测试和证据目录，不按逻辑蓝图重建平行工程；映射见正文第 19 章。上游许可继续以 [NOTICE](third_party/NOTICE.md)为准。

## v1.2 历史总纲（已被上述路线取代）

以下保留用于追溯，其阶段、Gate、硬件假设和“当前”表述均是 2026-10-11 的历史上下文，不是后续执行指令。

版本 v1.2，2026-10-11。用户已确定技术方向并要求完整规划；本版交付设计、学习路线与实施计划。接手后已运行P0环境核查和动作合同单测；本项目飞行任务、训练及新增实机能力仍未执行，不将规划验收或上游短例当作飞行验收。当前证据见[核查报告](docs/reports/p0/P0_ENVIRONMENT_REPORT.md)。

## 已确定的方向

主工程使用已有 Isaac Lab；以 NavRL 的任务、速度控制和 PPO 方法作为首个导航基线参考，择需移植而非安装其整套旧环境；DiffPhysDrone 作为轻量视觉与可微训练对照。使用成熟 PPO 库，不自行实现优化器/仿真器/飞控。训练库优先采用当前 Isaac Lab 已有且兼容的单一 PPO 集成，P0 核查后锁版本，不同时引入多套框架。

保留 PX4 1.17，首个部署接口为三轴速度＋偏航率。研究独立推进，PX4 通信与基础指令执行按可实现前提处理；无需等待旧实机项目或先搭完整联仿。正式迁移仍要验证控制响应、坐标、估计有效性与失效行为。

用户强调小体积、轻量化、低算力，以及低学习/集成/试错成本。按整个感知到动作链及整机质量功耗做选择。双目深度占用高是用户实测反馈，持续稠密深度不作为部署默认；RGB 是否充分、是否补有限前向测距仍是研究问题。

## 完整任务与范围

基础运动 → 固定简单场地的导航避障 → 敌方基地捕获 → 基地内小装甲识别与对准 → 规则允许的任务动作 → 返回机库附近 → 机库捕获与降落。约15×15cm是目标尺度估计，赛季图纸/安装和执行判定须核实。

一项 own_team=red|blue 配置派生敌我目标，不改变飞控坐标。前视彩色视觉为核心感知候选；PX4 原有 IMU 与光流/向下测距用于必要状态估计；下视相机按机库末段几何需求接入。传感器不是全部永久必装，网络也不接收所有原始流。

拦截飞镖/大弹丸作为独立 D 支线，先验证可见性、延迟和运动可达域；不拖住导航首闭环。侦察、数据卸载和能源循环保留扩展接口，具体首版任务要求待确认。

## 阶段和决策门

| 阶段 | 交付与决策 | 状态 |
| --- | --- | --- |
| P0 工程与上游审查 | 环境快照、上游版本/许可/差异表、最小复现入口；不为论文替换整套环境 | 环境/上游/动作合同已核查；依赖一致性有冲突；统一评价记录待实现 |
| P1 基础运动 | 同一速度接口的起始偏差、到点、停止与响应基线 | NOT RUN |
| P2 导航算法基线 | 简单静态障碍，传统简单对照与PPO；真值/理想距离观测明确标记 | NOT RUN |
| P3 真实可得观测 | RGB+状态及必要测距候选；选定观测、网络与算力预算 | NOT RUN |
| P4 返程与机库 | 返程重捕获、下视相对对准；决定定位与下视配置 | NOT RUN |
| P5 机载与PX4迁移 | 模型导出、真实传感链、SITL及受控实机验证 | NOT RUN |
| P6 比赛任务视觉 | 基地→小装甲、红蓝回归、接近与任务动作独立验收 | NOT RUN |
| P7 完整任务 | 连续任务、能量、故障恢复及版本冻结 | NOT RUN |
| D 拦截研究 | 观测→预测→可达性→受控验证；单独放行 | NOT RUN |

P4可用合成机库，P6集中开展真实目标采集；少量传感器可用性测试从P3开展。P5软件接入可与P4并行，真实飞行需对应前置门。具体工作包和投入范围见[路线](docs/design/03_ROADMAP.md)。

## 开始工作的顺序

先读[设计与需求](docs/design/01_PROJECT_DESIGN.md)、[学习路线](docs/design/07_LEARNING_PATH.md)，再按[首阶段执行计划](docs/design/04_FIRST_TASK.md)完成P0/P1。第一项产物是可复现的环境与上游差异报告，第一项功能产物是基础运动与到点基线，不是复杂赛场或真实装甲识别。

## 文档入口

- [设计、范围、需求追踪](docs/design/01_PROJECT_DESIGN.md)
- [系统架构与数据合同](docs/design/02_ARCHITECTURE.md)
- [阶段路线与工作包](docs/design/03_ROADMAP.md)
- [首阶段执行计划](docs/design/04_FIRST_TASK.md)
- [目录、工作区与版本管理](docs/design/05_WORKSPACE.md)
- [参数、预算与风险](docs/design/06_PARAMETERS_AND_RISKS.md)
- [需要学习的技术与完成标准](docs/design/07_LEARNING_PATH.md)
- [实验设计与验收](docs/design/08_EVALUATION.md)
- [开源复用与移植边界](docs/design/09_OPEN_SOURCE_BASELINE.md)
- [首阶段具体任务清单](docs/superpowers/plans/2026-10-11-p0-p1-foundation.md)
- [最新已知信息快照](docs/planning/10_CURRENT_FACTS_AND_ANALYSIS_20261011.md)
- [规划交付核查](docs/reports/PLANNING_ACCEPTANCE.md)

本版架构方向已接受；所有注明PROPOSED的实验门限、工时与硬件假设是规划初值。真实质量/赛季要求、机库几何、算力实测仍UNKNOWN。v1.1原文在docs/references/planning_v1_1_before_20261011保留，当前入口以本总纲和design/01–09为准。


## 单环境动态评价默认升级（2026-11-03）

`scripts/run_dynamic_eval.py` 的单环境评价默认已升级为 `--geometry-policy reference_origin_v2 --contact-mode measured_hard_reset`。历史复现必须显式传 `--geometry-policy legacy --contact-mode legacy_inference`；旧 v1 raw-hash/旧 boundary/latency freeze 在新默认下会被明确拒绝，不自动回退。新 freeze schema v2 记录 hash algorithm、实际生效配置与 default/explicit 来源。只影响该单环境评价入口，不影响训练/多环境/官方 smoke。证据见 `docs/reports/map_eval/contact_envelope/DSH_DYNAMIC_DEFAULT_UPGRADE_20261103.md`。
