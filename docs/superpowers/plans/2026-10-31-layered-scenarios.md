# 分层场景合同与五类自然场景评价实施计划（2026-10-31）

> **状态：** IN PROGRESS
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §12.2、§13.2–13.5、§20.2、§20.9、§20.11；HANDOFF_20261031_GUIDANCE.md §6
> **证据域：** 单元测试 + 仿真模型（Isaac Lab/PhysX，ORACLE 观测）；不含真实感知、SITL/HIL、实机
> **Gate：** 仿真评价扩展；不是 BB22:G4 放行，不提升任何 Gate

## 目标与边界

- 在既有统一评价入口（EpisodeResult / summarize / 配对与分层统计 / manifest）上扩展五类可重放自然场景：A 无障碍、B 静态障碍、C 动态实体、D 观测接口退化、E 外部物理扰动；用受控分层采样取得比例制导基线 ≥100 有效 episode（每类 ≥20）。
- 比例制导是参考基线；保留制动型方法但不要求调参或更优。障碍/动态实体用于测量基线局限与验证碰撞评价，不设“必须绕障成功”的验收条件，也不临时加入规划器。
- ORACLE 状态上的噪声/延迟/丢失只称“观测接口退化”，不称真实相机或感知链路验证。
- 不启动 PPO、板端、SITL/HIL、刷固件或实机。

## 评价版本修订（v2）

- 上一轮 v1 分层：距离 short<1.2 / medium<1.8 / long≥1.8；方位 front/side/rear 按相对方位。问题：long/rear 样本稀少（最终集 long 4、rear 6），无受控配额。
- v2 修订：距离 near∈[0.8,1.2) / mid∈[1.2,1.6) / far∈[1.6,2.0]（水平距离，另采样 dz∈[−0.15,0.15]，3D 距离记录）；方位 front |rel|≤45° / side ≤135° / rear >135°。按 3×3 网格配额采样（每类 25：3/3/2, 3/3/2, 3/3/3），保证 far/rear 有足够样本。旧 v1 结果与文件保留，不改写。

## 场景合同（每类 25 个预生成场景，debug 与 final 分离）

| 类 | 能力要求 | 输入权限 | 预期结果 | 适用边界 |
| --- | --- | --- | --- | --- |
| A 无障碍 | 速度外环+到点 | ORACLE 真值 | 高成功率、短到点时间 | 不证明感知/避障 |
| B 静态障碍 | 同上（无避障能力） | ORACLE 真值 | 可能碰撞；碰撞率用于测量局限 | 不是避障能力验收 |
| C 动态实体 | 同上（无动态避障） | ORACLE 真值 | 可能有碰撞/时序失败 | 运动学与动力学实体分开记录 |
| D 观测退化 | 同上（输入含噪声/延迟/丢失） | 仅控制器输入退化；评价用真值 | 成功率/时间退化 | 不是真实相机/感知验证 |
| E 物理扰动 | 同上（外力/力矩） | ORACLE 真值 + 记录扰动 | 跟踪偏差/超时 | 不是风场建模 |

几何与参数记录：起点/目标/yaw、障碍中心/尺寸/类型、实体轨迹或初速、退化参数、扰动单位/坐标系/大小/时序、seed；初始状态合法性校验（不与障碍相交）。

## 修改文件（写域）

- 新增 `src/boom_birds/sim/layered.py`：场景 v2 数据类、类规格、受控分层采样、manifest/hash。
- 新增 `src/boom_birds/sim/observation_interface.py`：噪声/延迟/丢失包装，reset 清队列。
- 新增 `src/boom_birds/sim/disturbance.py`：机体系力/力矩时序（单位 N、N·m）。
- 新增 `src/boom_birds/sim/contact_evidence.py`：接触力阈值与证据记录（纯逻辑）。
- 新增 `src/boom_birds/sim/isaac_layered_scene.py`：PhysX 障碍/实体/ContactSensor 适配（仅 Isaac 内导入）。
- 修改 `src/boom_birds/evaluation/episodes.py`、`comparison.py`：评价 v2 字段、按场景类汇总、接触证据统计。
- 修改 `scripts/run_sim_baseline.py`：`--task layered` 入口，复用 EpisodeResult/summarize/配对逻辑。
- 新增 `scripts/make_layered_scenarios.py`、`scripts/make_layered_freeze.py`。
- 新增 `tests/sim/test_layered_scenarios.py`、`test_observation_interface.py`、`test_disturbance.py`、`test_contact_evidence.py`、`tests/evaluation/test_layered_summary.py`。
- 新增 `configs/scenarios/layered_*.json`、`docs/reports/layered_eval/`。

## 验收方法

1. 先写失败测试：分层配额/范围/合法性、退化时序与 reset、扰动时序、接触阈值、v2 汇总/分母/按类统计。
2. debug 集：每类 3 个场景（15 episode），验证障碍/实体/接触/退化/扰动机制与产物完整性；失败保留独立目录。
3. 冻结：写 `configs/scenarios/layered_freeze_20261031.json`（配置、场景、评价版本、阈值、参数 hash），最终运行入口校验。
4. 最终集：五类各 25 个预生成场景 = 125 episode（≥100 valid、每类 ≥20）；运行前冻结，不因结果删场景或改阈值。
5. 独立核验：扩展 verify 脚本，从 episodes.jsonl 重算按类/总体计数、比率、Wilson、接触证据、退化/扰动记录，并核对 manifest/hash。
6. 回归：上一轮故障集入口与单元测试继续通过；新增接触/退化机制有运行证据。

## 运行预算与停止条件

- 预算：debug ≤ 1 次（≤4 min）；final ≤ 1 次（≤12 min）；失败重跑用新目录。
- 停止条件：非有限值进入 PhysX、接触传感器不可用、场景合法性失败、分类与预期不符且无法定位、产物缺失。

## 失败处理

- 失败运行保留目录与 error 文件；先定位再重跑。
- 障碍/实体机制不可用时，先修复或停止并报告，不用标志注入替代自然碰撞证据。
