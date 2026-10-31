# 传统制导基线与失败路径/随机化验证报告（2026-10-31）

> **状态：** INCOMPLETE（60 episode 配对比较 + 4 类专项故障已完成；30 场景不足以冻结 G4，不代表 Gate 通过）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §10.6、§12.2、§20.2、§20.9、§20.11；docs/reports/HANDOFF_20261031.md §6
> **证据域：** 单元测试 + 仿真模型（Isaac Lab/PhysX，ORACLE 观测权限）
> **最后核对：** 2026-10-31

> **2026-10-31 评价 episode 边界修订：** 本报告旧运行产生于边界修复前，逐 episode 记录无边界字段，无法排除静默 auto-reset；干净重跑（compare 60 + faults 16）见 [CLEAN_BASELINE_REPORT](../eval_audit/CLEAN_BASELINE_REPORT.md)。比例/制动均 30/30、制动更慢的配对方向不变，但绝对时间与末距数值被 clean 结果替代；tuning 数据不足，调参依据待重验。

## 结论

- 已实现并验证两种传统到点制导，共用同一 ORACLE 位置/速度/姿态观测、同一四维动作约束、20 Hz 控制、同一动力学与同一成功判定/评价代码：
  - **proportional（保留原方法）**：位置误差 × 增益，无速度反馈。
  - **braking（新基线）**：制动速度剖面 `v_des = min(v_max, sqrt(2 a d))` + 速度反馈 `v_cmd = v_des + k_fb (v_des - v_actual)`，接近目标主动降速、超速时反向修正。
- **调参集与最终集分离**：调参 8 场景（configs/scenarios/tuning_20261031.json），最终 30 场景（final_20261031.json）；参数、阈值、场景清单在最终比较前冻结（freeze_20261031.json，运行入口校验通过）。
- **配对比较**：30 场景 × 2 方法 = **60 episode**，双方均 30/30 成功，valid 分母 30；成功率 1.0，Wilson 95% 区间 [0.886, 1.0]。proportional 平均到点 3.478 s，braking 平均 3.597 s；配对 30/30 均为 proportional 更快（平均差 +0.118 s，范围 +0.05–+0.20 s）；braking 平均最终误差 0.121 m，比 proportional 的 0.027 m 差 0.094 m。**新基线没有优于原方法，本报告不通过挑选 seed、删失败或改阈值制造优势。**
- **专项故障**：16 episode（4 类 × 2 场景 × 2 方法），分类全部符合预期；PhysX 真实接触 4/4 观测到接触/静止，标志注入 4/4 无接触（仅证明判定链路）；超时 4/4 TIMEOUT；观测层非有限输入 4/4 INVALID/NONFINITE，注入不写入 PhysX。
- **独立核验**：scripts/verify_guidance_runs.py 从 episodes.jsonl 重算计数、比率、Wilson 区间、配对差与故障分类，并与 summary.json 对照，最终集与故障集均 PASS。
- **状态 INCOMPLETE**：30 场景 < §20.11 PROPOSED 100 valid episode；本轮只完成仿真基线与评价链路，不是 BB22:G4 冻结，也不提升任何 Gate。

## 算法差异（同一输入/约束下）

| 项 | proportional | braking |
| --- | --- | --- |
| 期望速度来源 | 位置误差 × gain | 制动剖面 min(v_max, sqrt(2 a d)) |
| 速度反馈 | 无 | k_fb (v_des - v_actual)，超速时反向制动 |
| 到点行为 | 到到达半径内归零 | 先降速再归零，速度反馈可产生反向指令 |
| 观测/动作/频率/动力学 | ORACLE 位置+速度+姿态；4 维；20 Hz；同一执行链 | 同左 |
| 参数 | gain=1.0, v_max=0.6, arrival=0.25 | a=1.2, k_fb=0.4, v_max=0.6, arrival=0.25 |

## 运行标识与冻结

| 项 | 值 |
| --- | --- |
| 最终比较源码提交 | `007e2ebf86bfd042864a3e68c6fab59317f35469` |
| 故障运行源码提交 | `9c02dbd97e9997d469e7c2186c1f640d9fc3b811`（含故障汇总修正） |
| 分支 | `codex/bb22-guidance-baseline` |
| 解释器 | `E:\isaac\env_isaaclab\Scripts\python.exe`（Python 3.11.9） |
| 仿真栈 | Isaac Sim 5.1.0.0；Isaac Lab 源码 b4c3210；任务源码 SHA-256 `01b36ac09a88e5b4e9522870efba22636aa07765f36d646ba4d40fce25c9bd02` |
| 资产 | Crazyflie `cf2x.usd`（远程引用） |
| 控制 | 20 Hz（`step_dt=0.05`）、1 环境 |
| 配置 SHA-256 | `6d1c23a2c09e79f65ee864ec78618807d5ebddcb463155ee10bfa59067dbe731` |
| 最终场景清单 SHA-256 | `0db366b63305335e1503cfda85a933f7cf2f5c003392c21dcd607e8fbb15ffd2`（30 场景） |
| 调参场景清单 SHA-256 | `961024239962cdc13b65c34f6cb65dc00bb85ba1753fb15340dc4f6c545bd070`（8 场景） |
| 冻结文件 SHA-256 | `2d09abb1606ec14a841ddc643e1cc52d951bcff7629b3bb1cf71b465abeea858` |
| 工作树差异 | status SHA-256 `207b67be9cae856a5091162b3e67b1de0270087d5421ff1e1d6a66f83b6d2af7`；未暂存 diff SHA-256 `34df07a3ec41fdff64db22a0498c5b3511e3d96a6877ffe38f88a0146657d898` |
| 用户未提交设计正文 SHA-256 | `a96276a328aebca90177c48b55046a4a85ba6c292efbf0ca2dced60d44340a94`（保留未提交） |

上述 worktree hash 为证据收集时点值；收尾（含 PROJECT_PLAN/README/AGENTS 本地状态同步）后为 status SHA-256 @@08be1dd0d5cbb83910f345afc1ebc297e9041c6aa80b54944b4536809a6f438b@@、未暂存 diff SHA-256 @@8c581eb613c99a4452107c0f8e418df9f3f24320b157f64d80d718541c7716f1@@，以现场 git status 为准。

场景抽样范围（configs/scenarios/*.json 内逐条记录实际值）：起点 xy ∈ [−0.5, 0.5] m、z ∈ [0.65, 0.85] m、yaw ∈ [−π, π]；目标 x ∈ [0.9, 1.6] m、y ∈ [−1.0, 1.0] m、z ∈ [0.65, 0.95] m；目标距离 ∈ [0.8, 2.5] m。

## 调参过程（仅调参集）

| 候选 | 参数 | 成功 | 平均到点 (s) | 平均最终误差 (m) |
| --- | --- | --- | --- | --- |
| A（run1） | a=0.8, k_fb=0.8 | 8/8 | 3.319 | 0.104 |
| B（run2，选定） | a=1.2, k_fb=0.4 | 8/8 | 3.306 | 0.111 |

预设选择准则：先 valid 成功率，再到点时间，最后最终误差。A/B 成功率相同，B 到点时间更低，故冻结 B；最终误差略差 0.007 m 一并记录。调参运行目录保留在忽略目录（outputs/guidance_compare/tuning_run1|run2），摘要副本见 [tuning/](tuning/)。
## 最终配对比较（30 场景，冻结后）

| 指标 | proportional | braking |
| --- | --- | --- |
| total / valid / invalid | 30 / 30 / 0 | 30 / 30 / 0 |
| success / collision / timeout | 30 / 0 / 0 | 30 / 0 / 0 |
| success_rate_of_valid（分母） | 1.0（30） | 1.0（30） |
| Wilson 95% | [0.886, 1.0] | [0.886, 1.0] |
| mean / median 到点 (s) | 3.478 / 3.425 | 3.597 / 3.550 |
| 到点范围 (s) | 2.45–6.60 | 2.55–6.70 |
| mean / worst 最终误差 (m) | 0.027 / 0.044 | 0.121 / 0.217 |

配对结果（30 对，同场景）：both_success=30，a_only=0，b_only=0，neither=0；时间 30/30 判 proportional 更快，median 差 +0.100 s，mean 差 +0.118 s；最终误差 mean 差（braking−proportional）= +0.094 m。

分层（每层 total/valid/成功，两方法一致）：距离 short 5/5/5、medium 21/21/21、long 4/4/4；相对方位 front 8/8/8、side 16/16/16、rear 6/6/6。逐场景配对明细见 [final/pairs.csv](final/pairs.csv)。

## 专项故障（独立统计，不混入自然成功率）

| 故障 | 样本 | 计数 | 期望 | 证据层 | 判定 |
| --- | --- | --- | --- | --- | --- |
| collision_contact | 4 | COLLISION 4 | COLLISION | PHYSX_CONTACT（4/4 观测接触） | PASS |
| collision_flag | 4 | COLLISION 4 | COLLISION | CONTRACT_PATH_ONLY（0/4 接触） | PASS |
| timeout | 4 | TIMEOUT 4 | TIMEOUT | TIMEOUT_TRUNCATION（truncated） | PASS |
| invalid_observation | 4 | INVALID 4 | INVALID | INTERFACE_LAYER（NONFINITE，注入观测层） | PASS |

故障集总 16 episode，natural_performance_rates_excluded=true；碰撞与超时计入各自分类计数，INVALID 原因明确为 NONFINITE，不用于隐藏控制失败。真实接触运行使用不终止的 done 判定让机体与地面 PhysX 碰撞/静止后分类；标志注入仅在接口层置位，不写入 PhysX。

## 独立核验与产物

| 产物 | 位置 | SHA-256 |
| --- | --- | --- |
| 最终 summary | [final/summary.json](final/summary.json) | `e080afc6b51cca9a9e4e624c6af2e67ad18eb2153211e0a125dc2367110ec8c5` |
| 最终逐 episode | [final/episodes.jsonl](final/episodes.jsonl) | `dfaa1b1dc3dec7763c30ee1e2fb04052ea6300d97db953497d827f883025deb5` |
| 最终 manifest | [final/manifest.json](final/manifest.json) | `d91bc7fa953e0ad2c41ca11958a4c20f1c9926c6141efeaf10c2333abce1436f` |
| 故障 summary | [faults/summary.json](faults/summary.json) | `1af2deb2473177fd7c008147016607e7b1bb5ca6683d89a606867e4b54c6de28` |
| 故障逐 episode | [faults/episodes.jsonl](faults/episodes.jsonl) | `401a1a8a9b7f9a3ef52683718ef5963a848c085d2af125a1a2a79412604b9e51` |
| 故障 manifest | [faults/manifest.json](faults/manifest.json) | `a8e0cf9f461608711ad51df8ae61c6c171e0a80d80cdb2fa736f226af8195f04` |
| 独立核验（最终） | [verify_final.json](verify_final.json) | PASS（13 项检查） |
| 独立核验（故障） | [verify_faults.json](verify_faults.json) | PASS（17 项检查） |

manifest 中的 outputs_sha256 已与落盘文件逐项比对一致；每次运行使用独立输出目录，未覆盖既有运行。
## 失败与修复（保留证据）

1. **faults_run1**（源码 007e2eb）：故障汇总对 EpisodeResult 调用 .get → AttributeError；失败证据 [faults/faults_run1_failure_error.txt](faults/faults_run1_failure_error.txt)，运行目录保留。修复方式：抽出带回归测试的 fault_classification_summary（按 fault 分组，dict 记录）。
2. **faults_run3**（源码 f481698）：状态判定仍引用已删除的局部变量 fault_summary → NameError；证据 [faults/faults_run3_failure_error.txt](faults/faults_run3_failure_error.txt)。修复后 faults_run4 PASS。
3. **核验器首版误报**：故障集按 (method, scenario) 判重，未把 fault 纳入键，导致合法重复被判 FAIL；已修正核验键（非运行缺陷）。
4. **注意**：上述失败运行 PowerShell 仍显示 exit 0（Kit 关闭路径吞掉退出码）。每轮以 summary.error.txt、阶段标记和产物完整性判定，不以 exit 0 单独判定成功。

## 限制与 NOT RUN

- 观测为 ORACLE 仿真状态；无感知、无视觉、无真实目标、无障碍、无风扰/传感器噪声/延迟。
- 单刚体 + 机体推力/力矩模型；无旋翼/电机/气动/电池模型。
- 样本 30 场景（60 episode）低于 §20.11 PROPOSED 100 valid episode；分层中 long/rear 样本少；不构成 G4 冻结。
- 未做 PPO、板端、SITL/HIL、刷固件或实机；不提升任何 Gate；规则/BOM/固件缺口仍为 UNKNOWN/RULE-CHECK。
- 调参只使用调参集；最终阈值/参数未因结果调整；新基线未优于原方法，结论按实际报告。

## 下一工作包

1. 扩到 ≥100 valid episode，增加随机化难度分层（障碍、动态实体、传感器退化）与重复 seed 置信区间。
2. 传统基线 vs Teacher PPO 同条件对比（需 BB22:G4 + G2.5 前置，当前不满足）。
3. G4 评价冻结仍依赖 G1（飞控基础）、G2.6 板端复检、G3（感知）；本轮只提供仿真评价链路与首轮基线证据。