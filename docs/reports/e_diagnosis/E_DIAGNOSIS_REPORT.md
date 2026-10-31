# E 类扰动越界诊断与修复报告（2026-10-31）

> **状态：** 主因已证实并修复；修复后冻结 125 场景回归 PASS（E 类 19/25 越界 → 0/25）。**不是 BB22:G4 放行**，不提升任何 Gate。
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §10.4、§13、§17、§20.2；HANDOFF_20261031_LAYERED.md §5
> **证据域：** 单元测试 + 仿真模型（Isaac Lab/PhysX，ORACLE 观测）；不含真实感知、SITL/HIL、实机
> **最后核对：** 2026-10-31

## 结论（区分已证实、可能、未确认）

**已证实原因（两项独立缺陷，均属施力实现而非控制器）：**

1. **扰动横向力逐策略步累计。** 环境每步只重写机体 z 推力，横向推力分量没有任何模块归零；注入代码使用 `+=` 累加，于是 0.02 N 的探针扰动在 8 个策略步内升至 **0.37 N（18.5 倍）**，造成大幅加速度与姿态失控。证据：pre-fix 力探针时间序列（applied_thrust_x 0.0→0.37 N，最大俯仰角速度 19.6 rad/s、倾角 3.09 rad、最终 vz −1.28 m/s）。
2. **外力施加点与整机质心的杠杆力矩未被补偿。** 仅修复累计后，0.02 N 横向力仍产生持续俯仰（倾角 1.56 rad、俯仰角速度 2.06 rad/s），因为外力作用在基座质心，而整机质心（含桨叶质量）存在约 2 mm 偏置，形成约 4×10⁻⁵ N·m 的未记录力矩。按整机质心偏置补偿后，同一探针倾角 0.001 rad、俯仰角速度 0.001 rad/s，纯平移。

**已排除的替代解释：** 质量/重力/周期/推力单位（冲量/质量与实测 Δv 吻合 2.7%）、FLU/ENU 与机体系/世界系（yaw=90° 时 +x 机体力对应世界 +y 加速度）、接触/实体/传感器污染（E 类无活动实体、无接触证据，重复运行轨迹完全一致）、控制周期错位（扰动时间窗与实测力逐点一致）、控制器饱和（修复后倾角 0.001 rad 远低于 0.2 rad 限幅）。

**未确认/限制：** 质心偏置来自运行时 Isaac Lab 质量与 COM 数据，换资产/固件需重新标定；C 类剩余 1 个越界与扰动无关且两轮一致，尚未定位；场景仍是 ORACLE + 简化刚体模型，非真实风场。

**修复范围：** 仅扰动注入与组合实现（`compose_actor_wrench`），未改控制器、阈值、成功条件、场景清单或冻结参数。

## 第一阶段：实验链路核查（全部实际执行）

| 检查 | 实际结果 |
| --- | --- |
| 质量/惯量/重力/周期 | 0.0282 kg；[1.657e-5, 1.666e-5, 2.926e-5] kg·m²；9.81 m/s²；`step_dt=0.05 s`（20 Hz） |
| 推力/力矩单位与限幅 | 归一化动作 → 机体 z 推力 [0, 1.9W]；力矩 ±0.01 N·m；`max_tilt=0.2 rad` |
| 无扰动悬停探针 | 2 s 内位置/速度保持（0,0,0.75 m） |
| 机体系 +x 力 0.02 N（yaw=0，窗口 0.5–1.5 s） | 修复后 applied_x 恒 0.02 N；窗口内 Δvx = **0.655 m/s**，冲量/质量预期 0.674 m/s（差 2.7%）；倾角 0.001 rad |
| 同一机体力、yaw=90° | 加速度沿世界 **+y** 0.655 m/s，证明机体系语义 |
| 纯 z 力矩 2×10⁻⁴ N·m | 修复后水平位移 0；滚转/俯仰角速度 8×10⁻⁷ rad/s，纯偏航 |
| 时间顺序 | 每步记录“命令 → 施力 → 实测状态”；扰动窗口与 `wrench_at` 逐点一致，无一步错位 |
| 实体/接触/reset | E 类无活动实体（动力实体停放于 (300,300,50)），无接触证据；重复运行位置差 0.0 |
| 累计缺陷 | pre-fix：applied_x 0.02→0.37 N；修复后恒 0.02 N；重放中记录的最大扰动 = 场景规范值（0.0041–0.0096 N） |
| 杠杆力矩缺陷 | 仅修累计时仍有俯仰（倾角 1.56 rad）；补偿整机质心偏置后消失（0.001 rad） |
## 第二阶段：最小回放与因果链

回放用例从原冻结 E 集中按“扰动强度/方向、力矩有无、成功对照”选择：

| 用例 | 选择依据 | 扰动力（N）/时长 | 修复前（final_run2，施力缺陷污染） | 修复后（2 次重放） |
| --- | --- | --- | --- | --- |
| E_disturbance-10000-002 | 强 +x/+y、有 z 力矩 | 0.0096 / 0.44 s | OUT_OF_BOUNDS，56 步，末距 5.77 m | SUCCESS ×2（54 步） |
| E_disturbance-10000-003 | 弱 −x/−y、有 z 力矩 | 0.0043 / 0.45 s | OUT_OF_BOUNDS，47 步，末距 3.86 m | SUCCESS ×2（51 步） |
| E_disturbance-10000-019 | 小 +x/+y、**无力矩** | 0.0041 / 0.41 s | OUT_OF_BOUNDS，34 步，末距 4.21 m | SUCCESS ×2（74 步） |
| E_disturbance-10000-000 | 成功对照 | 0.0067 / 0.31 s | SUCCESS，73 步 | SUCCESS ×2（52 步） |

单因素对照与可复现性：

- 每个用例在相同配置下重复 2 次：**同一轨迹位置最大差 0.0**（确定性）。
- 有扰动 / 无扰动两版对照：全部 SUCCESS；步数差 0–1 步（扰动仅造成轻微时间差，不再越界）。
- 修复后记录的最大扰动严格等于场景规范值（0.0041–0.0096 N），不再累计。
- 修复前/后同场景对照不构成控制器改善：修复前 E 类整体结果由施力缺陷污染，仅作缺陷证据。

**因果链（时间序列支持）：**

1. 扰动窗口开始后，第一步出现异常：applied_thrust_x 从 0.02 N 开始逐策略步增长（累计缺陷），远超场景规范；
2. 异常力导致横向加速度与俯仰角速度增长（pre-fix 19.6 rad/s）；
3. 姿态倾斜使推力矢量偏离竖直，垂直支撑下降、水平漂移加快，最终越界/坠落；
4. 仅修累计后，applied_thrust_x 恒定 0.02 N，但仍出现俯仰（第二因子：质心偏置杠杆力矩）；
5. 补偿整机质心偏置后，姿态保持水平、纯平移，异常链在第一步即被切断。

证据文件：[probes/force_probe_timeseries.csv](probes/force_probe_timeseries.csv)（pre-fix 与 final-code 逐步对照），[probes/](probes/) 三个探针摘要，[replay/](replay/) 16 episode 回放记录，[DIAGNOSIS_METRICS.json](DIAGNOSIS_METRICS.json)。

## 第三阶段：修复与回归

修复实现（提交 `6b26542`）：

- `compose_actor_wrench`（新增纯函数，3 条回归测试）：横向分量赋值而非累加；按整机质心偏置计算补偿力矩；零扰动时清除横向残留。
- `DisturbanceInjector`：使用设备一致的整机质量张量（此前 CPU/CUDA 混用异常被静默吞掉，导致补偿从未生效），每步计算整机质心偏置并传入组合函数；扰动仍通过既有 wrench 接口施加，单位为 N / N·m、机体系。
- 旧 E 类结果（final_run2，19/25 越界）标记为“施力缺陷污染”，保留原文件与 hash，不作为控制器结论。

冻结集回归（同一冻结场景/配置/阈值，仅代码修复）：

| 类 | 修复前（final_run2） | 修复后（final_run3） |
| --- | --- | --- |
| A 无障碍 | 25 success | 25 success（不变） |
| B 静态障碍 | 25 collision（均有接触证据） | 25 collision（不变） |
| C 动态实体 | 24 success / 1 out_of_bounds | 24 success / 1 out_of_bounds（不变） |
| D 观测退化 | 25 success | 25 success（不变） |
| E 物理扰动 | **3 success / 3 timeout / 19 out_of_bounds** | **25 success / 0 / 0** |
| 总体 | 77/125 success，20 out_of_bounds | 99/125 success，1 out_of_bounds（C 类） |

- 独立核验：`verify_layered_runs.py` 对 final_run3 的 24 项检查全部 PASS（配额、按类统计重算、接触、退化/扰动时序、实体运动、冻结与产物 hash）。
- C 类剩余 1 个越界在修复前后完全一致，说明与扰动修复无关；按“不为提高成功率而掩盖”原则保留并列为下一项诊断。
## 精确复现命令

`powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -m pytest -q
# 第一阶段：力接口探针（无扰动 / 机体 +x / yaw90 / 纯力矩）
& $py -u scripts/diag_e_class.py --mode probes --config configs/vehicles/sim_reference.yaml --output outputs/e_diagnosis/probes9_final --headless --device cuda:0
# 第二阶段：3 个原越界案例 + 1 成功对照，各重复 2 次，含无扰动对照
& $py -u scripts/diag_e_class.py --mode replay --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --scenario-id E_disturbance-10000-002 --scenario-id E_disturbance-10000-003 --scenario-id E_disturbance-10000-019 --scenario-id E_disturbance-10000-000 --repeats 2 --timeout-s 12 --output outputs/e_diagnosis/replay_fixed1 --headless --device cuda:0
# 第三阶段：修复后冻结集 125 场景回归
& $py -u scripts/run_sim_baseline.py --task layered --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --classes all --methods proportional --timeout-s 12 --freeze configs/scenarios/layered_freeze_20261031.json --require-coverage --min-valid-per-class 20 --min-valid-total 100 --code-commit 6b26542a750a5627afbf8d114e892845483912bb --headless --device cuda:0 --clone-in-usd --output outputs/layered_eval/final_run3
& $py scripts/verify_layered_runs.py --run-dir outputs/layered_eval/final_run3 --freeze configs/scenarios/layered_freeze_20261031.json --output docs/reports/e_diagnosis/verify_after_fix.json
`

## 证据与 hash

| 产物 | 位置 | SHA-256 |
| --- | --- | --- |
| 诊断指标汇总 | [DIAGNOSIS_METRICS.json](DIAGNOSIS_METRICS.json) | `2577920e8c61ab7a6bf6d34f34fda9b7db6dc131c43ce0540a21801dd994c56b` |
| 修复后独立核验 | [verify_after_fix.json](verify_after_fix.json) | `32a8b2c37d59f563c89c93042c2911ec4471efb462a4ab5b8d3740daa39d90e3` |
| 修复后评价摘要 | [after_fix/summary.json](after_fix/summary.json) | `2137762ce658729aeb2c4d039ad50cc9e18398958b777803952f90486c356678` |
| 修复后逐 episode | [after_fix/episodes.jsonl](after_fix/episodes.jsonl) | `1355112720b6c944f9e7e907f2ce6a8086be4a264a804212af48705e700c1b3a` |
| 修复后逐 step（忽略目录） | `outputs/layered_eval/final_run3/steps.jsonl` | `265f3a11f81dc2416d0eff5ec3490cbd53fa001dcdd3b4843cbcaeb23bb1b653` |
| pre-fix 探针逐 step（忽略目录） | `outputs/e_diagnosis/probes1/steps.jsonl` | `d2d3615bbdac2af699101a4e5567929b8baacaf1af17f6e089b1b16c8657766d` |
| 修复后回放逐 step（忽略目录） | `outputs/e_diagnosis/replay_fixed1/steps.jsonl` | `e4cae0bb6392fe87d7e4c4fdba00fd5d19aa58e660a3c46fd37cfb8e2346f535` |
| 时间序列对照 | [probes/force_probe_timeseries.csv](probes/force_probe_timeseries.csv) | 见文件 |
| 修复前 E 类证据（保留） | `outputs/layered_eval/final_run2/` | 旧报告：summary `c2e766d1…`、episodes `96beaa64…` |

## 受限与未解决问题

- 质心偏置补偿依赖运行时 Isaac Lab 质量/COM 数据；换机体或固件后需要重新核对，不能直接沿用。
- 扰动仍以机体系点力 + 力矩施加于整机质心；不是风场/气动模型，也不是真实风扰验证。
- C 类 1 个 out_of_bounds 在修复前后一致，尚未定位；与 E 类施力修复无关，作为下一项诊断对象。
- 125 episode 仍为本工作包采样下限，不替代 V2.2 §20.11 正式冻结要求；本报告不提升任何 Gate。
- 未运行 PPO、板端、SITL/HIL、固件或实机。

## 下一工作包

1. 定位 C 类单个越界（动态实体场景，无接触证据）的控制/时序原因。
2. 将质心偏置与施力补偿纳入场景 contract 的资产参数（不同机体验证）。
3. 需要时再扩大扰动包络与方向族，检查修复后的控制裕度，但不改阈值或删失败。
