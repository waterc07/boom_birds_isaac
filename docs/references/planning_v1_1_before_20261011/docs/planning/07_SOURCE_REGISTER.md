# 规划来源核查登记

查证日期2026-10-09。来源状态与适用范围如下；运行通过单列，不因资料公开而升级为PASS。

| 来源 | 直接取得/核查 | 支持的结论及边界 |
| --- | --- | --- |
| 用户最新需求 | 本聊天及目标提示词 | 中场起飞、敌方底线约15cm模块；2026-10-10已确认敌方基地小装甲，安装/高度仍待核查，保留PX4、降低验错成本 |
| 2027前瞻/继承规则 | handoff RULE_BASELINE快照；原PDF未取得 | 质量外廓公式、制作悬停/保护/典型任务、继承30s；后续规则/判定仍需原文，不冒充原PDF复核 |
| [2026规则PDF](../references/field_research_20261009/RMUC2026_rules_v1.3.0.pdf) | 本地V1.3.0，文字提取及场图/基地图渲染检查 | 历史28×15m、地形与模块差异；不是最新2026或2027地图 |
| [2026制作PDF](../references/field_research_20261009/RM2026_robot_spec_v1.3.0.pdf) | 本地V1.3.0，尺寸图页71查看 | 普通小装甲135mm宽/125mm板长；不代表基地各类模块 |
| [PX4 v1.17 Offboard](https://docs.px4.io/v1.17/en/flight_modes/offboard) | 版本页面核查 | 支持字段/估计条件/生存流；不证明本机模式运行 |
| [v1.17接收源](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/src/modules/mavlink/mavlink_receiver.cpp) | LOCAL_NED分支与yaw/yawspeed赋值直接读 | 三轴速度＋yaw_rate合同有源码依据；仍需SITL |
| [ODOMETRY流](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/src/modules/mavlink/streams/ODOMETRY.hpp) | vehicle_odometry、frame/reset/quality字段核查 | 可规划重置与质量接口；默认流/实际含义需运行核查 |
| [ESTIMATOR_STATUS流](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/src/modules/mavlink/streams/ESTIMATOR_STATUS.hpp) | 主估计器solution_status_flags映射核查 | 数值与有效性分离；各flag适用与阈值尚需锁配置验证 |
| [MAVLink common](https://mavlink.io/en/messages/common.html#SET_POSITION_TARGET_LOCAL_NED) | frame/单位/type_mask定义 | velocity+yaw_rate掩码1479推导；协议支持不等于飞控运行通过 |
| [v1.17 SIH](https://docs.px4.io/v1.17/en/sim_sih/) | 官方quadx命令/模型参数说明 | 无FC的SITL主候选；GPS等模拟源不得当无GPS证据 |
| [PX4 WSL环境](https://docs.px4.io/main/en/dev_setup/dev_env_windows_wsl) | main页面核查；版本路径获取失败后用此页 | Ubuntu/WSL候选，main不能冒充精确发布包锁，实施时固定提交脚本 |
| [PX4 v1.17.0发布](https://github.com/PX4/PX4-Autopilot/releases/tag/v1.17.0) | git ls-remote tag/解引用提交 | 候选commit d6f12ad1c4f70ad3230afd7d86e971421e02fef4；未安装构建 |
| [pymavlink官方](https://github.com/ArduPilot/pymavlink) | 项目与安装说明核查 | 成熟协议库候选；Python/ARM/精确依赖在实施时测试锁定 |
| [MAVSDK指南](https://mavsdk.mavlink.io/main/en/cpp/guide/offboard.html) | 官方语义审查记录 | 自动重发与yaw API差异，作为备选代价；不是首版第二发送端 |
| [MicoAir精确45A型号](https://micoair.com/flightcontroller_micoair743v2_aio_45a/) | 厂商重量/BEC/Compass规格核查 | VENDOR10g/5V2A/无板载磁力计；实板revision与供电/固件未通过 |
| [Pi5官方](https://www.raspberrypi.com/products/raspberry-pi-5/) | 供电/主动散热说明核查 | 5V5A建议额定供电，不是实测25W；BOM和负载需测 |
| 现有环境报告/preflight | 本地历史记录；当前WSL只读复核仍无发行版 | 既有Isaac基础步进历史PASS；项目SITL和训练NOT RUN |
| 深度研究报告/补充引用 | 原始文本保存，重点纠错见research/04 | 作者演示不证明项目机载；SIGN代码状态等以审查为准 |

官方PDF下载URL与SHA见references/field_research_20261009/sources.json；原交接SHA见snapshot_sources.json。预算的假设输入在budget_results.json独立标注，不用上述页面为未测性能背书。

后续版本漂移需按影响重新核查：固件/板卡变化重验协议/估计/回退，镜头/安装变化重标定，规则变化重做需求/BOM/任务差异，不无条件沿用此登记。

2026-10-10补充：用户确认敌方基地小装甲、阵营切换、拦截期望，以及PX4 1.17无GPS/光流/无磁力计定高实飞与MAVLink通信。官方历史PDF规则p24/67、制作p44/46/47用于球/镖规格（表格已渲染查看）；最新规则目录与未成功取得的新版本区别记录在[专项修订](09_TARGET_TEAM_AND_INTERCEPTION.md)，历史数值不冒充2027最终值。
