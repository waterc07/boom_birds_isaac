# 仿真速度执行链验证报告（2026-10-31）

> **状态：** PASS（仅仿真模型层；检查门槛为 PROPOSED，不是 Gate 通过）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §10.4、§13.1–13.2、§26.3、§27.6；旧 Task 3 方法
> **证据域：** 仿真模型（Isaac Lab / PhysX）；不含 SITL/HIL/台架/实飞
> **最后核对：** 2026-10-31

## 结论

- 已打通并实测本项目执行链：归一化四维动作 → 坐标/时效检查 → 速度外环控制器 → 机体总推力 + 机体力矩 → PhysX 刚体 → 实测位置/速度/姿态。
- 本次运行 **11/11 检查通过**（前/左/上/偏航符号、组合方向、90° 航向、过期拒绝且不续期、reset 后旧 epoch 拒绝、悬停高度、全部记录值有限）。
- **证据边界：** 这是单刚体 + 机体推力/力矩的仿真模型结果。它未对接 PX4/MAVLink，不含旋翼/电机/气动/电池模型，**不是** BB22:G1/G4/G5 的通过证据，也不能用于迁移验收。
- 直接写根速度的对照已单列为 **KINEMATIC**，只用于说明差异，不参与动力学验收。

## 运行现场（可追踪标识）

| 项 | 值 |
| --- | --- |
| 源码提交 | `86f0f2f5b1f9595e3881b808eb3a3246ab2aa2c0`（基线 `39a7812`） |
| 分支 | `codex/bb22-g2-6-contracts` |
| 解释器 | `E:\isaac\env_isaaclab\Scripts\python.exe`（Python 3.11.9） |
| 仿真栈 | Isaac Sim 5.1.0.0；Isaac Lab 源码 b4c3210（发行包 2.3.2 / tasks 0.11.16 / rl 0.5.2） |
| 任务源码 | `E:\isaac\IsaacLab\source\isaaclab_tasks\isaaclab_tasks\direct\quadcopter\quadcopter_env.py` |
| 任务源码 SHA-256 | `01b36ac09a88e5b4e9522870efba22636aa07765f36d646ba4d40fce25c9bd02` |
| WrenchComposer SHA-256（推力/力矩在 link 即机体系） | `5499CA69823D6C67AF2A4691D21EB9E8488E289F5443665D5329DC632487D9C9` |
| 资产 USD | `https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac/Robots/Bitcraze/Crazyflie/cf2x.usd`（远程引用，本次未逐字节哈希） |
| 配置 | `configs/vehicles/sim_reference.yaml`，SHA-256 `23fd7ca7cfbfa3e98de840c8257242f916df05de0b2b225cd495d8ffc0dd8eec` |
| 实测质量 / 惯量 | 0.0282 kg / [1.6572e-5, 1.6656e-5, 2.9262e-5] kg·m²（运行时读取，非抄录） |
| 控制频率 | `decimation=5` × `sim.dt=0.01` → `step_dt=0.05 s`（20 Hz） |
| seed / 环境数 | 0 / 1 |
| 场景 / 步数 | 10 场景 × 40 步 = 400 行 |
| 动作语义 | 归一化总推力 + 三个机体力矩（`moment_scale=0.01 N·m`） |
| 退出码 | 0（`SIM_EXIT=0`） |

## 实际命令

`powershell
& E:\isaac\env_isaaclab\Scripts\python.exe -u scripts/run_sim_baseline.py ^
  --task velocity_step --config configs/vehicles/sim_reference.yaml --scenarios all ^
  --headless --device cuda:0 --clone-in-usd ^
  --output outputs/sim_velocity_chain/full.json --csv outputs/sim_velocity_chain/full.csv
`

## 场景结果（世界系 ENU，相对各场景起点）

| 场景 | 类别 | Δ位置 [E, N, U] (m) | Δyaw (rad) | 峰值速度 (m/s) | 过期拒绝步 | 旧 epoch 拒绝 |
| --- | --- | --- | --- | --- | --- | --- |
| hover_trim | DYNAMIC | [0.000, 0.000, −0.013] | 0.000 | 0.074 | 0 | 0 |
| forward_step | DYNAMIC | [0.546, 0.000, −0.011] | 0.000 | 0.525 | 0 | 0 |
| left_step | DYNAMIC | [−0.000, 0.437, −0.012] | 0.000 | 0.420 | 0 | 0 |
| up_step | DYNAMIC | [0.000, 0.000, 0.202] | 0.000 | 0.212 | 0 | 0 |
| yaw_step | DYNAMIC | [−0.000, −0.000, −0.013] | +0.504 | 0.074 | 0 | 0 |
| combined_step | DYNAMIC | [0.411, 0.367, 0.145] | +0.306 | 0.413 | 0 | 0 |
| heading_yaw90_forward | DYNAMIC | [0.000, 0.546, −0.011] | 0.000 | 0.525 | 0 | 0 |
| expiry_single_command | DYNAMIC | [0.075, 0.000, −0.020] | 0.000 | 0.128 | **37** | 0 |
| reset_old_epoch | DYNAMIC | [0.289, −0.000, 0.001] | 0.000 | 0.511 | 0 | **1** |
| kinematic_reference | **KINEMATIC** | [0.500, 0.000, −0.029] | 0.000 | 0.501 | 0 | 0 |

说明：`expiry_single_command` 只在 t=0 下发一次 0.15 s TTL 动作且不重发；40 步中有 37 步被 `ACTION_EXPIRED` 拒绝，横向速度回落到约 4.7e-5 m/s。`reset_old_epoch` 在 t=1.0 s 重置并递增 control epoch，1 条旧 epoch 动作被拒绝，之后新 epoch 动作正常工作。

## 检查项（PROPOSED，未冻结）

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| `forward_moves_east` | PASS | +vx 使 +E 位移，N 向偏差小 |
| `left_moves_north` | PASS | +vy_left 使 +N 位移 |
| `up_climbs` | PASS | +vz_up 使高度上升 |
| `positive_yaw_rate_is_ccw` | PASS | +yaw rate 使 yaw 增加（从上方看逆时针） |
| `combined_direction_within_45deg_of_commanded` | PASS | 组合方向误差约 0.14 rad |
| `forward_at_yaw90_moves_north` | PASS | 航向对齐坐标系生效 |
| `expired_command_rejected_and_not_renewed` | PASS | 37 步拒绝，未续期 |
| `motion_stops_after_expiry` | PASS | 过期后横向速度 < 0.2 m/s |
| `reset_old_action_rejected` | PASS | 旧 control epoch 动作被拒绝 |
| `hover_holds_altitude` | PASS | 2 s 内高度漂移 −0.013 m |
| `all_recorded_values_finite` | PASS | 400 行全部有限 |

## 产物与哈希

| 产物 | 位置 | SHA-256 |
| --- | --- | --- |
| 逐场景摘要（版本化） | [velocity_chain_summary.json](velocity_chain_summary.json) | `FFBE904B8A8798F8A0511FBC9FAE3674C98E147285FE427642D91CC94261A3D7` |
| 完整逐步行 CSV（忽略目录） | `outputs/sim_velocity_chain/full.csv` | `489B66C144510BDA18DCEE9708D88C8BEA6119A3476A84563B081539BD972734` |
| 运行日志（忽略目录） | `logs/sim_velocity_full.log` | `E4CAC9FE7943171ACB607E7FFDE8C12C8E3A8200BC88B1A8E8FA2B99DDAA7C70` |
| 运行摘要日志（版本化） | [run-summary.log](run-summary.log) | `079BFC1198D8E80F1EC8A5292CD3C3A04F4B7A235AAD24D5C01E10B6A3645EC0` |
| 全量测试日志（版本化） | [tests-green.log](tests-green.log) | `574AE9570F028363742A133D3E9749B1340774C3D2DA2B14F09E8D7EC96DC107` |

## 测试

- `python -m pytest -q` → **126 passed in 0.40 s，exit 0**（既有合同 101 条 + 控制器 25 条）。
- 控制器测试覆盖：符号/航向映射、推力与推力方向、垂直推力增减、偏航力矩符号、倾角/力矩/动作限幅、过期与 epoch 拒绝、reset 清除积分与航向参考、非法参数与零四元数拒绝、KINEMATIC 标签。

## 失败与修复记录

| 运行 | 现象 | 处理 |
| --- | --- | --- |
| 1 | 进程正常退出但无产物、无 traceback | Kit 的 `app.close()` 在异常打印前终止进程；脚本加入阶段标记与 `*.error.txt` 兜底 |
| 2 | `env._body_id[0].item()` AttributeError（单环境下为 int） | 兼容 int / tensor |
| 3 | `ControlOutput` 与 KINEMATIC 字典混用，`output['reason']` TypeError | 统一为记录用字典 |
| 4 | PASS | 本报告证据 |

注意：Isaac 入口的前几次失败在 PowerShell 中仍显示 `SIM_EXIT=0`（Kit 关闭路径吞掉退出码），失败真相以 `outputs/sim_velocity_chain/full.error.txt` 与阶段标记为准；最终运行已确认无 error 文件。

## 限制与 NOT RUN

- 官方模型为单刚体 + 机体总推力/机体力矩，无旋翼转速、电机、桨叶、气动阻力、电池电压与地面效应；与真实机体响应不等价。
- 控制增益、TTL 0.15 s、倾角上限 0.2 rad 均为 **PROPOSED**，未做系统辨识与冻结。
- 未做多环境、随机化、扰动、传感器噪声与延迟注入；未做重复 seed 统计。
- 未对接 PX4、MAVLink、SITL/HIL；未验证 `SET_POSITION_TARGET_LOCAL_NED` 掩码 1479/1511；未做板端或实机。
- **不是 BB22:G4 通过**：G4 还要求传统基线与统一评价入口；G4 依赖 G1 + G2.6 + G3，其中 G1 与 G3 仍 NOT STARTED/NOT RUN。

## 下一工作包

最小到点/停止任务与统一评价：在同一执行链上实现无障碍到点、失败分母、超时/碰撞/无效试验判定，先标 ORACLE 真值；再进入传统控制基线与训练入口 smoke。需先完成本包的提交与后续计划登记。
