# 最小到点任务与统一评价验证报告（2026-10-31）

> **状态：** INCOMPLETE（仿真 smoke 通过，但样本量与失败覆盖不足，不放行）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §12.2、§20.2、§20.9、§20.11
> **证据域：** 单元测试 + 仿真模型（ORACLE 状态）；不含视觉、障碍、真实目标与实机
> **最后核对：** 2026-10-31

## 结论

- 已在同一仿真执行链上跑通“无障碍到点/停止”：6 个 episode 全部成功，平均 4.28 s 到达并稳定，最终距目标平均 0.027 m、最差 0.029 m。
- 状态标 **INCOMPLETE**：样本 6 远低于 §20.11 的 PROPOSED 100 episode 冻结样本；且本场景没有随机化，6 个 seed 实际是同一确定场景的重复，不能当作独立统计样本，也不能证明泛化或失败路径。
- 失败路径（碰撞 / 超时 / 非法）只由单元测试覆盖，**没有仿真失败样本**；不得据此宣称碰撞恢复、鲁棒性或安全包络已验证。
- 证据域为 ORACLE 仿真状态；感知、真实传感器与部署观测均未参与。

## 运行现场

| 项 | 值 |
| --- | --- |
| 源码提交 | `38159ee7ec5b2a951c680e3790a24b3c0444b3fd` |
| 分支 | `codex/bb22-g2-6-contracts` |
| 解释器 | `E:\isaac\env_isaaclab\Scripts\python.exe`（Python 3.11.9） |
| 仿真栈 | Isaac Sim 5.1.0.0；Isaac Lab 源码 b4c3210 |
| 配置 | `configs/vehicles/sim_reference.yaml`，SHA-256 `23fd7ca7cfbfa3e98de840c8257242f916df05de0b2b225cd495d8ffc0dd8eec` |
| 任务源码 SHA-256 | `01b36ac09a88e5b4e9522870efba22636aa07765f36d646ba4d40fce25c9bd02` |
| 资产 | `https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac/Robots/Bitcraze/Crazyflie/cf2x.usd` |
| 控制频率 | 20 Hz（`step_dt=0.05`） |
| episode / seed | 6 个，seed 0–5 |
| 超时 / 目标 | 20 s / (1.5, 1.0, 0.75) m |
| 退出码 | 0 |

实际命令：

`powershell
& E:\isaac\env_isaaclab\Scripts\python.exe -u scripts/run_sim_baseline.py ^
  --task reach --config configs/vehicles/sim_reference.yaml --episodes 6 ^
  --timeout-s 20 --goal 1.5,1.0,0.75 --code-commit 38159ee7ec5b2a951c680e3790a24b3c0444b3fd ^
  --headless --device cuda:0 --clone-in-usd ^
  --output outputs/sim_reach/run2/reach_summary.json --csv outputs/sim_reach/run2/reach.csv
`

## 统一评价结果

| 指标 | 值 |
| --- | --- |
| total / valid / invalid | 6 / 6 / 0 |
| success | 6 |
| collision / timeout | 0 / 0 |
| success_rate_of_valid | 1.0（分母 6） |
| success_rate_of_total | 1.0（分母 6） |
| mean_duration_s | 4.283 |
| mean_final_distance_m | 0.027 |
| worst_final_distance_m | 0.029 |
| failure_cases | 无 |
| 状态 | INCOMPLETE（样本不足，门槛 PROPOSED 未冻结） |

判定规则（PROPOSED 阈值，未冻结）：距目标 ≤ 0.3 m 且速度 ≤ 0.2 m/s 连续 0.5 s 为成功；碰撞优先于成功；超时为 truncated 且不算成功；非法状态单独计数并给原因码。

## 失败路径与优先级（单元测试覆盖，仿真未覆盖）

- 10 步保持才成功、9 步不成功；条件中断后计数清零。
- 同一步碰撞 + 到达 → 失败（碰撞优先）。
- 超时 → truncated 且不算成功。
- 非有限状态 → INVALID/NONFINITE；越界 → INVALID/OUT_OF_BOUNDS。
- 统一评价分母：8 成功 + 1 碰撞 + 1 超时 → 成功率 0.8；无效 episode 单列但保留在 total 与 failure_cases。

## 产物与哈希

| 产物 | 位置 | SHA-256 |
| --- | --- | --- |
| 评价摘要（版本化） | [reach_summary.json](reach_summary.json) | `AF7A381645F492B6CE1F0855B70A6B2FF9DEE511C2D8454919F5448CE1D646DE` |
| run manifest（版本化） | [manifest.json](manifest.json) | `BA37FB5E901B29BD5CFD5EA10344E7725526FCE859B2FCB7A4E8F740A93D3053` |
| 逐步 episode CSV（忽略目录） | `outputs/sim_reach/run2/reach.csv` | `BF071C805EE0190C1F6C9E5A1EE7483D3BA9E45D3975A0E7997EDAA33AB82AC5` |
| 运行日志（忽略目录） | `logs/sim_reach_run2.log` | `75A760CCC33815C2786BB4FCAF69B877C2C36AED3FDD5E3384012EEAD8C3EC96` |
| 测试日志（版本化） | [tests-green.log](tests-green.log) | 见 commit 内文件 |

## 测试

`python -m pytest -q` → **144 passed in 0.47 s，exit 0**（合同 101 + 控制器 25 + 任务 13 + 评价 5）。

## 限制与 NOT RUN

- 引导使用 ORACLE 位置/姿态；部署侧观测不可得。
- 无静态/动态障碍、无风扰与传感器退化、无真实目标与视觉；场景无随机化。
- 未接 PX4/SITL/HIL；未做传统制导与 PPO 的同条件对比；未做多种子置信区间。
- 未冻结任何性能门槛；§20.11 样本量、§20.12 门槛仍是 PROPOSED。
- **不是 BB22:G4 通过**；G4 需要传统基线、统一评价冻结与 G1/G2.6/G3 前置。

## 下一工作包

在同一 `--task reach` 评价入口接入传统控制基线与训练入口 smoke；补充随机化与失败注入（碰撞、超时、非法状态）以覆盖失败分母；之后才讨论 G4 评价冻结。真实感知（G3）与飞控（G1）仍需硬件与固件来源。
