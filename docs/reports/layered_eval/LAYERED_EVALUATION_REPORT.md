# 分层场景合同与五类自然场景评价报告（2026-10-31）

> **状态：** PASS（仅仿真评价扩展；不是 BB22:G4 放行，不提升任何 Gate）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §12.2、§13.2–13.5、§20.2、§20.9、§20.11
> **证据域：** 单元测试 + 仿真模型（Isaac Lab/PhysX，ORACLE 观测）；不含真实感知、SITL/HIL、实机
> **最后核对：** 2026-10-31

> **2026-10-31 修订（全部层级结果的 episode 边界适用性）：** 在 C 类诊断中发现，QuadcopterEnv 在整环境 reset 时会随机化 episode_length_buf（训练去同步），而评价运行器只读取 terminated、忽略 truncated；因此本报告及之前所有分层运行中，部分 episode 在飞行途中被静默 auto-reset，随后记录的轨迹/结果不再是原始初始条件下的行为。识别到 final_run2 有 8 个、final_run3 有 9 个受影响 episode（C-000/C-006/C-021、D-000/D-011/D-023、E-004/E-022/E-024）。修复（清零 episode 边界、读取 truncated、独立核验加入 no_silent_auto_reset）后的 clean 运行见 [final_run4 证据](../c_diagnosis/C_DIAGNOSIS_REPORT.md)：125 场景中 success 100、B 碰撞 25、C 25/25、无越界/无效。旧文件与数字保留，但 C/D/E 的逐 episode 时间与 C-021 旧越界不应用作控制器结论。

> **2026-10-31 修订（E 类结果适用性）：** 本报告 E 类的 19/25 越界已被证实由扰动注入实现缺陷（横向力逐策略步累计 + 外力施加点与整机质心的杠杆力矩未补偿）污染，仅作为缺陷证据保留，**不能用于控制器扰动鲁棒性结论**。修复、最小回放与修复后冻结集回归见 [E 类诊断与修复报告](../e_diagnosis/E_DIAGNOSIS_REPORT.md)。A/B/C/D 类结论不受该缺陷影响（修复前后逐项一致）。

## 结论

- 在既有统一评价入口（EpisodeResult / summarize / 分层与配对统计 / manifest / 独立核验）上完成评价 **v2** 与五类可重放自然场景：A 无障碍、B 静态障碍、C 动态实体、D 观测接口退化、E 外部物理扰动。
- 最终冻结集：**125 个有效自然场景 episode（每类 25，全部 valid、0 invalid）**；场景清单、配置、阈值、评价版本在最终运行前冻结，运行入口完成冻结校验。
- 总体（混合采样，仅代表本采样混合）：success 77/125（0.616）、collision 25（0.20）、timeout 3（0.024）、out_of_bounds 20（0.16）；全部失败保留在有效分母。
- 分类结论：
  - **A**：25/25 成功，平均到点 3.198 s，平均最终误差 0.026 m。
  - **B**：0/25 成功，**25/25 碰撞，全部有 PhysX 接触证据**（contact 阈值 0.02 N）；比例制导无避障能力，碰撞是能力边界而非评价缺陷。
  - **C**：24/25 成功（0.96），1 次 out_of_bounds；运动学实体与动力学实体均在仿真中运动，未发生接触。
  - **D**：25/25 成功，但控制器输入累计 248 步无效（丢失/过期），评价始终使用未污染真值。
  - **E**：3/25 成功（0.12），3 次超时、19 次 out_of_bounds；25/25 施加了记录在案的外力/力矩窗口；本控制器在该扰动下多次失去跟踪并越界，属于控制能力失败，保留在有效分母。
- 独立核验：`verify_layered_runs.py` 从 `episodes.jsonl`/`steps.jsonl` 重算统计、接触归因、退化/扰动时序、实体运动与冻结一致性，**24 项检查全部 PASS**。
- **边界**：本结论只说明该仿真场景混合下的比例制导表现；不证明避障、真实感知、比赛分布或任何 Gate。

## 评价 v2 修订（保留 v1 结果）

- v1：distance short<1.2 / medium<1.8 / long≥1.8，样本无配额，最终集 long=4、rear=6 偏少。
- v2：分层距离 near∈[0.8,1.2) / mid∈[1.2,1.6) / far∈[1.6,2.0]（水平距离；另采样 dz∈[−0.15,0.15]）；相对方位 front≤45° / side≤135° / rear>135°；按 3×3 配额 **[[3,3,2],[3,3,2],[3,3,3]]**（每类 25）受控采样，far=9、rear=8。
- v2 新增有效失败结果 `OUT_OF_BOUNDS`（控制能力失败进入有效分母），并新增 scene_class、接触证据、退化步数、扰动标记字段；v1 结果与旧报告原样保留。
## 场景合同（每类 25 个预生成场景，debug 与 final 分离）

| 类 | 能力要求 | 输入权限 | 预期结果 | 适用边界 |
| --- | --- | --- | --- | --- |
| A 无障碍 | 速度外环 + 到点/停止 | ORACLE 位置/速度/姿态 | 高成功率 | 不证明感知或避障 |
| B 静态障碍 | 同上，无避障能力 | ORACLE 状态 | 可能碰撞；碰撞率测量局限 | 不是避障验收 |
| C 动态实体 | 同上，无动态避障 | ORACLE 状态 + 实体位姿 | 可能碰撞/时序失败 | 运动学与动力学实体分开记录 |
| D 观测退化 | 同上，输入含噪声/延迟/丢失 | 仅控制器输入退化；评价用真值 | 成功率/到点时间退化 | 不是真实相机/感知验证 |
| E 物理扰动 | 同上 + 机体系外力/力矩 | ORACLE 状态 + 扰动记录 | 跟踪偏差/超时/越界 | 不是风场建模 |

记录字段：起点/目标/yaw、障碍中心/尺寸/类型、运动学实体速度、动力学实体质量/半径/初速、退化参数、扰动力/力矩/起始/持续时间、seed；起始状态与障碍保持 ≥0.35 m 距离（生成时校验）。

## 最终运行（冻结后）

| 项 | 值 |
| --- | --- |
| 源码提交 | `8e87ee05bde84491462d081aa4b8ccdb78807c13`（实现提交 `9924d32`） |
| 分支 | `codex/bb22-layered-eval` |
| 评价版本 | `boom_birds.evaluation.v2` |
| 场景清单 | [scenario_manifest.json](scenario_manifest.json)（内容 hash `fedb6b2f…` 文件、`850da12e…` 规范） |
| 冻结文件 | `configs/scenarios/layered_freeze_20261031.json`（config `6d1c23a2…`，scenario `850da12e…`，评测版本 v2，min 20/类、100 总） |
| 控制 | 20 Hz、1 环境、比例制导、ORACLE 观测 |
| 最终 episode | 125（每类 25），0 invalid |
| 退出码 | 0，标记 `BOOM_BIRDS_LAYERED_EVAL_PASS`，无 `summary.error.txt` |

## 分类结果（有效分母，冻结后不可改阈值）

| 类 | valid | success | collision | timeout | out_of_bounds | 成功率（Wilson 95%） | 平均到点 | 平均最终误差 | 接触/退化/扰动证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 25 | 25 | 0 | 0 | 0 | 1.00 [0.867, 1.0] | 3.198 s | 0.026 m | — |
| B | 25 | 0 | 25 | 0 | 0 | 0.00 [0.000, 0.133] | — | 1.347 m | 接触 25/25（obs0/obs1） |
| C | 25 | 24 | 0 | 0 | 1 | 0.96 [0.805, 0.993] | 3.415 s | 0.070 m | mover/ball 运动均验证 |
| D | 25 | 25 | 0 | 0 | 0 | 1.00 [0.867, 1.0] | 3.676 s | 0.035 m | 无效观测累计 248 步 |
| E | 25 | 3 | 0 | 3 | 19 | 0.12 [0.042, 0.300] | 2.933 s | 4.175 m | 扰动 25/25（0.004–0.012 N） |

失败案例全部保留在 [episodes.jsonl](episodes.jsonl)（含 episode_id、outcome、reason、steps、contact_step、min_z、退化步数、扰动标记、scenario 全量参数）；失败清单见 summary 的 `failure_cases`（B 25、C 1、E 22）。
## 独立核验（24 项全部 PASS）

- 场景配额：五类各 25，3×3 分层逐格等于配额；场景 manifest 内容 hash 与 summary/manifest 绑定。
- 统计重算：按类 total/valid/invalid/success/collision/timeout/out_of_bounds/成功率/平均到点与 summary 一致；Wilson 区间重算一致；总体分母一致。
- 接触证据：B/C 所有 COLLISION episode 在原始 `steps.jsonl` 对应 `contact_step` 有 ≥0.02 N 的 PhysX 接触力，且接触资产属于该类（B: obs0/obs1；C: mover/ball）。
- 退化证据：D 类无效观测步数与 episode 记录一致；无效样本原因仅为 DROPOUT/STALE、年龄 >0、位置未被零值填充。
- 扰动证据：E 类每步扰动向量与该场景记录的力/力矩时序（含 0.1 s ramp）逐点一致；施加标记与是否存在非零扰动一致。
- 实体运动：C 类每个 episode 运动学实体位移 >0.1 m、动力学实体位移 >0.05 m。
- 冻结：配置 hash、场景 hash、最低样本量（20/类、100 总）、评价版本均与冻结文件一致。
- 产物 hash：manifest 中 summary/episodes/steps 的 SHA-256 与落盘文件一致。

## 失败与修复记录（debug 过程，全部证据保留）

| 运行 | 现象 | 根因与修复 |
| --- | --- | --- |
| debug_run1 | NameError GuidanceSpec | 分层分支漏导入，补齐导入 |
| debug_run2 | 传感器找不到 contact reporter | 机器人 spawn 未启用接触报告；改为在障碍/实体资产上启用并显式激活 API |
| debug_run3 | set_world_poses 收到 list | RigidPrim 需要 torch tensor，统一转换 |
| debug_run4 | ContactSensor 无 _is_outdated | 独立传感器需显式初始化，补 _initialize_callback |
| debug_run5 | 仍无 contact reporter | 在资产 spawn 后显式 activate_contact_sensors |
| debug_run6 | DisturbanceSpec 类型不匹配 | 分层与扰动模块重复定义，统一为单一实现 |
| debug_run7 | 输出打印 NameError | 修正 summary 引用；contact 仍为 0 |
| contact_probe1–3 | force_matrix 全 0 | 独立传感器未调用 update；修正为每步 sensor.update |
| contact_probe4 | C 类 step0 误报接触 obs1 | 传感器残留上一场景接触；新增邻近归因门与 reset 清零 |
| final_run1 | PASS，但动力学实体停放在原点附近受重力下落 | 将动态实体停放到 (300,300,50)；final_run2 重跑，结论不变 |
| debug_full1 | E 类因扰动出现越界并把越界记为 INVALID | 将 OUT_OF_BOUNDS 定义为有效失败结果（v2），失败保留在分母 |

## 产物与 hash

| 产物 | 位置 | SHA-256 |
| --- | --- | --- |
| 评价摘要（版本化） | [summary.json](summary.json) | `c2e766d186adab087ae1ce42f046017310cad92be71f93080ca014c7e681267e` |
| 逐 episode（版本化） | [episodes.jsonl](episodes.jsonl) | `96beaa641f7b12bfeaf1b0572cffbf19ce2ce0434e9181441d58bd0e71dc3275` |
| run manifest | [manifest.json](manifest.json) | `b5cffff4116a918686d67ddbf26d087ca2aa376811958e65c7657d1736d16431` |
| 场景清单副本 | [scenario_manifest.json](scenario_manifest.json) | `fedb6b2fedfb2a5a0cb4094ede98fe509b113edf4239420e8a8b9337de7eb7d2` |
| 独立核验 | [verify_final.json](verify_final.json) | `14f8ea258e5d4b97f4e01d54f6f664f4f8b5453978560c29c69649d0408fb0d3` |
| 逐 step 原始记录（忽略目录） | `outputs/layered_eval/final_run2/steps.jsonl` | `00804f358716b51c66faedb1ecd4a7643dfaa7c6ca7eb156df026aad17904d8f` |
| debug 汇总 | [debug/summary.json](debug/summary.json) | 见目录 |
| debug 失败证据 | [debug/](debug/) | 各 error.txt 原样保留 |

## 限制与 NOT RUN

- 观测为 ORACLE 状态；D 类只退化控制器输入，评价用真值；不涉及真实相机、感知网络或视觉链路。
- 场景为单刚体仿真模型；障碍为立方体，动态实体为球体；无风场、无电机/气动/电池模型、无真实地图。
- B 类 0% 成功是比例制导无避障能力的直接测量，不构成避障能力验收；E 类失败表明当前控制器在该扰动幅度/时长下会失去跟踪，需在后续工作中定位并可复现。
- 125 episode 满足本工作包采样下限（每类 ≥20、总 ≥100），但不替代 V2.2 §20.11 按场景族/阵营的正式样本量与冻结要求；不提升任何 Gate。
- 未做 PPO、板端、SITL/HIL、刷固件或实机；规则/BOM/固件仍 UNKNOWN/RULE-CHECK。

## 下一工作包

1. 对 E 类失败做控制层面定位（姿态/速度回路增益、扰动包络、恢复策略），不改阈值或删失败。
2. 扩到正式样本量与场景族（含障碍布局族、动态实体时序族、退化强度族），增加重复 seed 与最差场景报告。
3. 传统基线 vs PPO 同条件对比（前置 BB22:G4 + G2.5，当前未满足）。