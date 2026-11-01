# 动态障碍停止—等待—恢复监督器计划（2026-11-01）

> **状态：** IN PROGRESS
> **来源章节：** RMUC2027_UAV_V2_2 §10.4、§11.3、§17、§20.2、§20.11；HANDOFF_20261031_MAP_ROUTES.md
> **证据域：** 单元测试 + ORACLE 仿真（前台 GUI，DirectX/D3D12）
> **Gate：** 不提升任何 Gate；不是视觉避障/在线重规划/实机安全系统

## 目标与边界

1. 在现有 south/north 冻结航点路线上加入运动学动态障碍（真实碰撞几何，标注 KINEMATIC）。
2. 实现最小监督器状态机 FOLLOW/BRAKE/HOLD/WAIT/RESUME/ABORT（+ 观测降级），仅使用障碍当前位置/速度和有界预测；不读取未来脚本。
3. 设计 A–E 五类场景（每类≥4，共≥20），FOLLOW_ONLY 与监督器配对，≥40 episode；另 8 个无动态障碍 route 回归。
4. 冻结、运行、独立核验、报告与交接；失败保留；不以成功率为唯一标准。

## 架构边界

- 监督器是仿真适配层，不是 PX4 控制监督器；不绕过动作有效期/限幅/reset/所有权；不宣称 v2 端到端集成。
- 停止命令仅通过既有 VelocitySetpoint/执行器与 TTL；暂停不重置航点、超时、episode 或位置。
- 障碍观察带时间戳/年龄/有效性；过期显式降级，不用零值伪装。
- 所有阈值 PROPOSED，需调试场景测量后冻结。

## 状态机合同

- FOLLOW：沿当前航点执行；风险进入 → BRAKE。
- BRAKE/HOLD：零速度命令，记录制动/停止距离；停止或最短保持后 → WAIT。
- WAIT：净空持续 release_hold → RESUME；等待 > max_wait → ABORT；观测过期 → DEGRADED。
- RESUME：恢复当前航点，不跳过/重置；持续 resume_hold → FOLLOW；风险再现 → BRAKE。
- ABORT：终态，单独分类，不计成功。
- 风险判据：障碍当前位置/速度有界预测（horizon）到当前航段最小距离 < stop_distance；释放需 > release_distance 持续 release_hold（迟滞）。
- 计时：航点分段/总计时在暂停期间冻结（route_active 时钟），墙钟总超时仍生效；max_wait 独立。

## 场景

- A 障碍在到达前横穿离开；B 临时占据后释放；C 持续占据超 max_wait；D 阈值附近反复；E 观测过期/丢失（物理继续）。
- 每类 4 个，覆盖 south/north；变化进入时机/位置/速度，非换 seed。
- 障碍为运动学立方体（真实碰撞几何），沿脚本轨迹；reset 恢复位姿、时钟、观测队列。

## 评价

- 每场景同控制器/路线/物理/观测权限运行 FOLLOW_ONLY 与 SUPERVISOR；配对差异；分类 SUCCESS/COLLISION/TIMEOUT/OUT_OF_BOUNDS/ABORT/INVALID。
- 指标：完成率、碰撞率、主动退出率、等待时间、路线耗时、切换次数、最小距离/接触。
- 独立核验障碍轨迹/相对距离/观测年龄/请求与实测速度/状态切换/航点/接触/边界/hash。

## 写域

- scripts/run_dynamic_eval.py（或 run_map_eval 扩展）、scripts/make_dynamic_cases.py、make_dynamic_freeze.py、verify_dynamic_runs.py。
- src/boom_birds/sim/dynamic_obstacle.py、src/boom_birds/evaluation/supervisor.py。
- configs/scenarios/map_dynamic_cases_v1.json、map_dynamic_freeze_v1.json。
- tests/sim/test_dynamic_obstacle.py、tests/evaluation/test_supervisor.py。

## 验收

- 状态机与场景合同；针对性测试；≥40 配对 + 8 回归；实际覆盖停止/等待/恢复/ABORT；独立核验；pytest/审计/diff；报告/GUI/交接；中文提交，不推送。
