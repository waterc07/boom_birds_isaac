# 仿真速度执行链实施计划（2026-10-31）

> **状态：** DONE（仿真模型层；不是 Gate 通过）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §10.4、§13.1–13.2、§26.3、§27.6；旧 Task 3 方法
> **证据域：** 仿真模型（Isaac Lab / PhysX）；不含 SITL/HIL/台架/实飞
> **Gate：** 仅作 BB22:G4 前置输入，不是任何 Gate 的通过证据

## 输入与前置条件

- 输入：@@boom_birds.message.v2.0@@ / @@boom_birds.action.v2.0@@ 合同（BB22:G2.6）、四维归一化动作语义（水平 FLU 前/左、向上、逆时针偏航率）。
- 前置：现有 Isaac Lab 5.1.0.0 / Isaac Lab 源码 b4c3210 环境与官方 Crazyflie 资产可用；不安装/不重建环境。
- 已知缺口：官方资产是单刚体 + 机体总推力/机体力矩模型（无旋翼动力学、无电机模型）；不能代表真实机体响应。

## 修改文件（写域）

- 新增 @@src/boom_birds/sim/velocity_control.py@@：车辆参数、增益、速度设定值、状态、外环控制器、KINEMATIC 参考源。
- 新增 @@tests/sim/test_velocity_control.py@@：纯数学符号/限幅/过期/epoch/reset 回归。
- 新增 @@scripts/run_sim_baseline.py@@：Isaac 适配与场景执行入口。
- 新增 @@configs/vehicles/sim_reference.yaml@@：PROPOSED 增益与力矩尺度。
- 新增 @@docs/reports/sim_velocity/@@：报告、summary、运行日志副本。

## 接口

- @@VelocitySetpoint(vx_forward, vy_left, vz_up, yaw_rate, issued_at_s, expires_at_s, control_epoch)@@
- @@VehicleState(position_world, velocity_world, quat_wxyz, angular_velocity_body)@@
- @@VelocityExecutor.step(setpoint, state, now_s) -> ControlOutput@@：速度误差 → 加速度 → 推力矢量/期望姿态 → 机体力矩；过期/epoch 不匹配 → 拒绝并进入显式降级（仿真专用，不推导为实机安全动作）。
- @@ControlOutput.to_actuator_action(params)@@ → 官方资产动作 @@[归一化总推力, 机体力矩x, y, z / moment_scale]@@。
- 适配路径：动作 → 官方 @@QuadcopterEnv._pre_physics_step@@（机体 +Z 推力、机体力矩，WrenchComposer @is_global=False@）→ PhysX → @@root_pos_w / root_lin_vel_w / root_quat_w / root_ang_vel_b@@。

## 验收方法（PROPOSED，非冻结门槛）

- 控制频率 20 Hz（@@decimation=5@@、@@sim.dt=1/100@@），1 环境，seed 0，共 10 场景 × 40 步 = 400 行。
- 检查项：前/左/上/偏航符号、组合动作方向、90° 航向下前进、过期拒绝且不续期、reset 后旧 epoch 拒绝、全部记录值有限、悬停高度保持。
- 明确标注 KINEMATIC 对照（直接写根速度）不参与动力学验收。
- @@python -m pytest tests/sim -q@@ 全绿；脚本输出 JSON 含 checks/status，失败退出非 0。

## 运行预算与停止条件

- 预算：单次运行 ≤ 3 min（已实测启动约 1–2 min、400 步约 20 s）；不启动训练、不扩环境数。
- 停止条件：非有限值、合同违约、脚本崩溃不可定位、控制器发散。先保存日志、错误文件和最小复现再改。

## 失败处理

- 原生崩溃/无 traceback：脚本写 @@outputs/.../*.error.txt@@（含阶段标记与 traceback），日志保留；先定位再改。
- 控制器不稳定：仅调 PROPOSED 增益并记录每次运行参数；不修改合同语义。