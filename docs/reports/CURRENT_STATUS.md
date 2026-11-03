# 当前进度与接手续查（2026-11-04）

本页汇总仓库内已交付能力与证据边界。设计正文仍为 [V2.2 架构](../design/RMUC2027_UAV_V2_2.md)，本页不修改其合同或放行任何 Gate。正文中的开工时实现状态、早期计划和历史交接应按日期阅读，不能代替当前源码和后续修订。

## 已实现与证据入口

| 层次 | 已交付范围 | 主要证据与适用边界 |
| --- | --- | --- |
| 软件合同 | 四级上下文、时钟/模拟飞控身份、消息溯源、不可续期 TTL、动作接纳及所有权合同 | [G2.6 报告](g2_6/G2_6_CONTRACTS_REPORT.md)；不是实际 PX4 Sender，G2.6 整体仍 INCOMPLETE |
| 仿真执行与评价 | 速度外环至 PhysX、到点、传统制导比较、episode 边界修复及历史污染审计 | [干净基线](eval_audit/CLEAN_BASELINE_REPORT.md)、[分层评价修订](c_diagnosis/C_DIAGNOSIS_REPORT.md)；不等于训练或实机能力 |
| 地图与动态监督 | RMUC2027 配置引用、局部路线、停止/等待/恢复、v2 执行与故障后物理观测 | [路线](map_eval/MAP_ROUTES_REPORT.md)、[v2 执行](map_eval/MAP_V2_EXEC_REPORT.md)、[制动](map_eval/MAP_BRAKE_ENVELOPE_REPORT.md)；ORACLE 状态、运动学障碍、当前仿真模型 |
| 延迟和净空 | 到达队列、模拟双时钟、clearance 字段化、有限制动支持区间 | [延迟](map_eval/MAP_LATENCY_ENVELOPE_REPORT.md)、[边界](map_eval/MAP_CLEARANCE_BOUNDARY_REPORT.md)；旧结果的验收变更和包络修正须一并阅读 |
| 单环境接触评价 | hard reset、分离握手、generation、原始向量 L2 读出、真实碰撞几何包络；新模式已成为单环境动态入口默认 | [自由飞行阳性](map_eval/contact_envelope/DSH_FREE_FLIGHT_POSITIVE_20261103.md)、[默认升级](map_eval/contact_envelope/DSH_DYNAMIC_DEFAULT_UPGRADE_20261103.md)；零测力仍 UNKNOWN，传送后陈旧力未做底层修复 |
| 模拟传感器 | 渲染 RGB/深度、v2 消息溯源和 shadow 消费 | [采集](map_eval/contact_envelope/DSH_SENSOR_SHADOW_20261103.md)、[统计与时间勘误](map_eval/contact_envelope/DSH_SENSOR_SHADOW_ERRATA_20261103.md)；SIM_UPDATE_SAMPLE_TIME 不是真实曝光时间，单像素深度不是 ToF 或目标距离 |
| 自然地标感知 | 模板和几何/绿灯消费者已完成有界实验，均停止作为当前主候选 | [独立测试](perception/DSH_LANDMARK_INDEPENDENT_20261103.md)、[根因审查](perception/DSH_LANDMARK_ROOT_CAUSE_20261103.md)、[几何方法](perception/DSH_GEOMETRY_GREEN_20261104.md)；软件交付完成，感知/导航能力未达标，不进入地标关联控制 |

## 当前能力限制

- 几何/绿灯独立测试 presence TP/FP/FN/TN 为 13/0/5/12；18 个正例中有 9 个定位标注，定位子集联合达标 3/9。3/18 表示全部正例中已确认达标的比例，不能把未标注帧一律解释为定位失败。成功检测样本上的低 anchor 误差不代表全部正例的整体精度。
- 旧 route/reset 数据属于同轨迹重复采集；旧 presence TP 未验证目标框，bbox 中心方位不能直接当作绿灯参考点方位。旧指标仅按对应勘误使用。
- 原生 contact event/impulse、负接触覆盖、多环境 reset/训练及完整实机外廓未验证。旧 CONTACT_INFERRED 的两个历史案例仍不具备确认物理真值的证据。
- 官方 Vulkan GUI、USD 克隆的 100 步短例有历史 PASS 记录，见 [核验摘要](official_gui_smoke/vulkan_current_verification.json)；并不证明默认 Fabric 路径、地图长时稳定性或驱动根因。后续地图正式实验使用 D3D12 的原证据保持原边界。
- 项目 PPO、真实感知设备、PX4 Sender、板端 Student、SITL/HIL 与实机均未完成本项目验收；旧官方 PPO 兼容短例不能替代项目训练。规则、BOM、准确固件/参数来源仍为 UNKNOWN/RULE-CHECK，不提升任何 BB22 Gate。

## 下一项

先依据 V2.2 下游需求明确地标身份、物理参考点和方位输出是否足够，再评审轻量学习方法、数据规范与部署可行性。实例分割只是候选，不是已选架构；不继续堆模板/几何阈值，不自动开始训练。实物输入针对具体迁移目标收集，不笼统阻塞离线软件准备。

## 运行与历史复现

- 所有 Isaac 采集、仿真、诊断、重放及训练必须前台可视 GUI；离线分析、单元测试和文档审计不要求 GUI。本次整理未重新运行 Isaac。
- 当前单环境动态评价默认：`--geometry-policy reference_origin_v2 --contact-mode measured_hard_reset`。显式历史模式：`--geometry-policy legacy --contact-mode legacy_inference`。不能混用，不能将旧冻结直接套到新默认。
- 旧冻结、失败、pilot、无效标签轮次和历史验证文件保留原路径及字节，不因入库而变成当前正式验收证据。原始大图、逐步日志、权重、地图资产及本机配置继续留在忽略目录或外部存储。
- 冻结匹配原源码/配置与当时工作树；当前 HEAD 前进并不使历史冻结适用于新源码。复现时按对应报告选择源码，不重写历史 commit/hash。
