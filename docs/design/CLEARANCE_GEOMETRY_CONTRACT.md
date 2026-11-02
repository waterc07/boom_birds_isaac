# Clearance 几何与停止需求合同（2026-11-02）

> **状态：** BASELINE（当前仿真实现合同；数值均为仿真模型证据，不是实机安全包络）
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §10.4、§16.1–16.3、§16.6、§17.3、§26.6–26.7、§27.3–27.7；`docs/superpowers/plans/2026-11-02-clearance-boundary.md`
> **证据域：** 标准库单元测试 + 前台 GUI 仿真动力学（DirectX/D3D12）
> **最后核对：** 2026-11-02

## 1. 目的

把"stop_distance_m"所依赖的几何语义、包络、预测、观测/动作延迟、停止需求和适用范围固化为可校验接口，避免一个字段同时承载中心距、点到线段距离和表面间隙，并禁止超出实测支持范围的外推。

## 2. clearance 合同（`src/boom_birds/evaluation/clearance.py`）

- `schema_version = boom_birds.clearance.v1`；`algorithm.id = supervisor_predicted_path_clearance`；`version = 1.0.0`；单位 m；坐标系 world ENU Z-up；时间基准 simulation_time_s；预测时域 1.0 s、步长 0.1 s（11 点）。
- 定义：`path_clearance_m = min over预测障碍中心 of point-to-segment distance`，线段为 `[机器人当前中心 → 当前航点中心]`；障碍预测为"观测位置 + 观测速度 × t"。
- 四个几何量**不得互相替代**：
  1. `center_distance_m`：机器人/障碍当前中心欧氏距离（观测域，用于诊断）；
  2. `envelope_gap_sphere_m`：`center_distance_m − r_robot_sphere − r_obstacle_sphere`；
  3. `path_clearance_m`：生产判定值（监督器 risk 使用）；
  4. `path_clearance_gap_sphere_m`：`path_clearance_m − r_robot_sphere − r_obstacle_sphere`。
- 包络：robot 取 spawn 姿态 USD AABB 半尺寸的**半对角线** `r=sqrt(Σh²)`（对任意绕质心刚体旋转保守；不得使用 max-half-extent）；obstacle 取 case cuboid `r=max(size)/2`。AABB/球是近似，**不是**网格扫掠证明；AABB 中心相对机器人原点的偏移未记录/未校核时，完整外廓保守性标未确认。
- `validity`：观测无效（dropout/时钟映射不可用）时 valid=false、reasons 记录；`metrics` 可为 null；不得用零值伪装有效。
- `applicability`：`SUPPORTED`/`UNSUPPORTED` + reasons + notes；生产记录实际判定值，独立分析从 `inputs` 重建。

## 3. 停止需求合同（`src/boom_birds/evaluation/stop_requirement.py`）

- `schema_version = boom_birds.stop_requirement.v1`；`model_id = brake_final4.v1`；制动模型 `configs/scenarios/brake_model_v1.json`，来源 `docs/reports/map_eval/brake/verify_brake_final.json`（sha256 记录），支持区间 `[0.248041, 0.851428] m/s`，区间内分段线性，**区间外不外推**。
- `basis`：
  - `actuation`：brake_distance 来自执行器级实测（从执行器实际制动起点测量，不含传输延迟），故 `transport_reaction_m = v*action_delay` 单列；
  - `trigger`：若使用"STOP 决策触发→停止"实测距离（已含传输延迟），则 `transport_reaction_m=0`，禁止重复计延迟。
- `terms`：`brake_distance_m`、`transport_reaction_m`、`observation_age_motion_m = closing_speed*observation_age_bound`、`envelope_sum_m = r_robot+r_obstacle`；
  `required_clearance_m = 四项之和`；`margin_to_threshold_m = stop_threshold − required − proposed_margin`（`proposed_margin=0.2 m` 为 PROPOSED 规划余量，不是已验证安全余量）。
- `status=UNSUPPORTED` 条件：机器人速度高于制动模型支持上限、观测年龄不可证、动作 TTL 在到达前已过期等；此时 `brake_distance/required/margin = null`，禁止外推。低于支持下限按保守说明处理（d(v<min) ≤ d(min)），不得当作已验证高速能力。`CLOSING_SPEED_NOT_MODELLED`/`PREDICTION_HORIZON_SHORTER_THAN_STOP_TIME` 为非阻塞标记。

## 4. 记录与核验

- 运行器每步记录 `steps[].clearance`、`steps[].stop_requirement` 与生产值 `clearance_m`；episode 记录 `metrics.min_path_clearance_m`、`min_path_clearance_gap_sphere_m`、`min_envelope_gap_sphere_m`、`conservative_envelope`、`stop_requirement_extremes`、`contact_evidence_summary`。
- 独立核验从原始 `inputs` 重建生产值（容差 1e-6），核对包络半径规则、四个几何量语义、观测年龄、TTL/执行、制动/接触、场景预期与冻结/hash；数据完整性、合同不变量、场景预期、性能边界四类分开报告，偏差不并入 PASS。
- 接触：本环境接触力传感不可用，采用球重叠（>0.02 m）运动学推断，显式标注 `kinematic_inference`，不是测力证据。

## 5. 适用边界

- 仅当前仿真模型/单地图/单机体/ORACLE 观测；host 时间=Isaac 仿真时间，camera=模拟第二时钟域；无真实跨设备时钟、串口、PX4、执行器延迟。
- 制动模型只覆盖实测速度区间与当前执行器配置；样本最大值不是严格最坏上界，不构成实机安全包络，不替代 PX4 failsafe。
- 任何超出支持区间的输入必须返回明确 UNSUPPORTED 状态；不得把"未发现违约"写成严格安全保证。
