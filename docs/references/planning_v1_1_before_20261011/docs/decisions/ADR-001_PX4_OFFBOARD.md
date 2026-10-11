# ADR-001：保留PX4，主接口选择速度＋偏航率

2026-10-09，v1.1。用户明确保留PX4并授权接口选型；采用此架构，实现/SITL/实板NOT RUN。

## 决策

上位机输出ENU三轴速度(m/s)和逆时针偏航率(rad/s)，PX4承担速度以下闭环。局部速度和航向仍须有效，接口选择不能免除估计。位置技能仅定位有效后放行；首版不输出姿态/推力或电机。

位置接口便于航点但需要可信位置；速度接口与相对视觉/短程技能匹配；姿态/推力需要更多稳定性/动力验证；直控电机绕过常规姿态保护，与首版目的不符。

唯一网关以pymavlink发送SET_POSITION_TARGET_LOCAL_NED，LOCAL_NED frame1、mask1479，保留velocity/yaw_rate，ENU→NED=[vy,vx,-vz]及偏航率负号。真实字段与质量/时钟/epoch/模式合同以[架构](../design/02_ARCHITECTURE.md)及[首阶段](../design/04_FIRST_TASK.md)为准。

[PX4 v1.17接收源码](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/src/modules/mavlink/mavlink_receiver.cpp)核实该frame的速度和yaw_rate分别进入setpoint.velocity/yawspeed；这是源码证据，不是运行通过。[协议字段](https://mavlink.io/en/messages/common.html#SET_POSITION_TARGET_LOCAL_NED)定义单位/掩码。

## 代价与备选

pymavlink提供成熟协议库，但网关需显式管理消息率、时钟/质量、确认和超时；不自己写协议编解码。MAVSDK减少部分模式封装，却有自动重发20Hz及NED yaw角/机体yaw_rate不同API语义；替换须先证明同一合同和失效行为，不能混用两种发送端。[MAVSDK指南](https://mavsdk.mavlink.io/main/en/cpp/guide/offboard.html)

20Hz策略/50Hz网关/TTL150ms是初值PROPOSED。重发不续期；ACK不等于模式已确认；无效估计不能靠零速度保证悬停。实际失联/RC/无GPS回退由锁定PX4配置和测试矩阵确定。[版本Offboard文档](https://docs.px4.io/v1.17/en/flight_modes/offboard)

## 变更触发及历史

仅当任务确需位置保持且误差预算已通过时增加显式位置技能；仅当速度层确有不可解决缺口且动力/内环研究获授权时研究下层接口。学习器无解锁/模式/参数权限。

原记录中固定学习首任务、F0/F1必须联仿、M阶段顺序及lab/三包目录已由ADR-002与当前设计取代。旧记录保存于references/design_before_v1_20261009。保留接口原则，不恢复旧PPO前置安排。
