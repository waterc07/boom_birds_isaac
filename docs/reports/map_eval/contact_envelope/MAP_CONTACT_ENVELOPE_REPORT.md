# 接触证据恢复、分层接触合同与包络中心修正报告（2026-11-02）

> **状态：** ASSESSMENT（仿真证据；不提升任何 Gate）
> **来源章节：** `docs/reports/HANDOFF_20261102_CLEARANCE_BOUNDARY.md`、`docs/reports/map_eval/MAP_CLEARANCE_BOUNDARY_REPORT.md`、`docs/design/CLEARANCE_GEOMETRY_CONTRACT.md`；历史 `MAP_EVAL_REPORT.md`、`MAP_ROUTES_REPORT.md`、`MAP_DYNAMIC_REPORT.md`、`LAYERED_EVALUATION_REPORT.md`
> **证据域：** 标准库单元测试 + 前台可视 GUI 仿真动力学（DirectX/D3D12）；无真实感知/PX4/板端/SITL/HIL/实机
> **最后核对：** 2026-11-02

## 1. 结论

- **历史可测、当前不可测的差异已有证据支持的解释**（详见 `CONTACT_DIAGNOSIS_20261102.md`）：
  - 原样运行历史入口 `run_dynamic_eval.py@92757f0`（FOLLOW_ONLY `dynamic_C_south_0`）在当前机器/当前 Isaac 版本下仍测得 **0.0231 N** 真实接触力（`tmp/historical_repro1`）→ 不是 GPU/驱动/Isaac 能力问题；
  - 历史地图墙接触路径（地图 spawn 后逐碰撞 prim `PhysxContactReportAPI` + body sensor filter 精确 prim）本轮 **probe2 复现 0.042 N**；
  - 当前边界入口的探针链差异：障碍 spawn 的 `activate_contact_sensors=True` 只把 reporter 加在 obstacle **root**（碰撞 shape 初始无 reporter）；`replicate_physics=True` 时 post-hoc 给 collider shape 加 reporter **不进入 PhysX 复制场景**（probe6/7=0，probe11 关闭 replication 后=0.0081 N）；
  - 接触报告在单进程内仅 **首个 episode** 可靠：B 第 2 次重复物理推挤仍在但 net/filtered 均 0；改为 **每 episode 独立进程**后两次均测得 0.0276 N；
  - 因此"0 N"只能是 `UNKNOWN`/覆盖不足，不能判 `NO_CONTACT`；受控 C 的 `NO_CONTACT` 仅当 sensor available 且 force 有效为零、无 event 时成立。
- **当前入口已接入真实 PhysX 接触证据**：`scripts/run_contact_verification.py`（wall/obstacle/clearance/geometry/replay）；受控 A/B/C/D 共 8 episode 全部完成：
  - A 墙接触 **0.1563 / 0.9406 N**（filtered、attribution=`collision_014`）；
  - B 运动学障碍真实接触 **0.0276 N**（net force，`CONTACT_FORCE_MEASURED_UNATTRIBUTED`；filtered 通道为 0，未伪造 prim 归因）；
  - C 合法近距离 **NO_CONTACT**（sensor 有效零、球包络间隙 −0.078 m、无 event/force）；
  - D 球重叠但碰撞几何未接触 **GEOMETRY_OVERLAP_ONLY**（overlap 0.022 m >0.02、event=false、force 有效零）；
- **分层接触合同 `boom_birds.contact_evidence.v2`**：`PHYSX_CONTACT_EVENT` / `PHYSX_CONTACT_FORCE`（N，窗口=policy step 聚合）/ `PHYSX_CONTACT_IMPULSE`（N·s，本轮不可用）/ `GEOMETRY_OVERLAP`（仅推断）/ `UNKNOWN`（传感器不可用/覆盖不足）；sensor invalid 与 valid zero 可区分；impulse 不得当 N；geometry 不得升级为 PhysX 事件/力；net force 不得当 per-prim。
- **旧案例复核**（同配置接触几何重放，非闭环重放）：
  - `boundary_B_cross_late_r0`、`boundary_C_headon_collide_r0`（旧标签 CONTACT_INFERRED）：重放几何重叠 0.122/0.119 m，但未测得真实力 → **UNDECIDABLE**；旧标签保留、仅加适用性说明，不改写其余未复核 episode；
  - `boundary_A_static_offpath_r0`（旧标签 NO_CONTACT）：**CONSISTENT**（sensor 有效、无 event/force、无球重叠）。
- **包络中心查明并修正**：机器人碰撞 AABB（root 系）half=`[0.0545422337, 0.0382082667, 0.0135880403]` m，center offset=`[5.90e-05, 2.42e-08, 0.0148685]` m；`r_origin=|| |offset|+half ||=0.0724634 m`，旧 `r_legacy=||half||=0.0679659 m` **低估 0.0044975 m**。机器人碰撞几何只有 body 碰撞体；螺旋桨/子体在 prim inventory 中无 CollisionAPI（仅视觉），coverage 标 collision_geometry + limitations（非全姿态网格扫掠、桨叶未覆盖）。修正分析见 `analyze_envelope_correction.json`；旧报告/旧分析及 hash 保留。
- **独立核验**：**PASS**：`status=PASS`、29/29 checks（data_integrity 7、contact_contract 9、envelope_geometry 4、scenario_expectation 5、performance_boundary 4）、failures=0、deviations=0、missing_fields=0；接触证据域：A 墙 filtered 力+attribution、B 障碍 net 力 UNATTRIBUTED、C 有效零 NO_CONTACT、D geometry-only、2 个旧 CONTACT_INFERRED 重放 UNDECIDABLE（旧标签保留）、1 个旧 NO_CONTACT 重放 CONSISTENT；包络 r_origin=0.0724634 m（旧 0.0679659，delta 0.0044975）。

## 2. 证据现场

| 项 | 内容 |
| --- | --- |
| 分支/提交 | `codex/bb22-contact-envelope`；先 `ba13c37`（contact contract/envelope/runner/freeze/verifier/cases/expected），后 `be24f6b`（replay/net-force 修复）、`c50de1f`（replay UNDECIDABLE 语义） |
| 预运行冻结 | `configs/scenarios/contact_verification_freeze_v2.json`（真实 UTC；code_commit `c50de1f`；worktree digest；6 段 11 episode；budget 2/2/2/2/2/1；replay 引用 `outputs/map_eval/bnd_boundary_default` 并校验路径存在） |
| 正式运行 | `outputs/map_eval/contact_A_wall|contact_B_obstacle|contact_C_clearance|contact_D_geometry|replay_contact_inferred|replay_no_contact`（11 episode；GUI DirectX；每段独立目录；B 段每 repeat 独立进程后合并原始记录） |
| 旧证据 | `outputs/map_eval/bnd_boundary_default` 等保留；旧边界报告/冻结与 hash 不改写 |
| 诊断探针 | `outputs/map_eval/contact_probe1..11`、`tmp/historical_repro1`、`outputs/map_eval/bnd_boundary_default`（历史 final_dynamic1 证据保留在 `outputs/map_eval/final_dynamic1`） |
| 调试/失败保留 | `contact_smoke*`、`contact_B_obstacle_*_pilot_v1`、`replay_smoke1` 保留，不进入正式分母 |

## 3. 分层接触合同（`src/boom_birds/evaluation/contact_contract.py`）

- schema `boom_birds.contact_evidence.v2`；每步记录：`sensor{available,status}`、`sampling{window_s,source,aggregation}`、`layers{event,force,impulse,geometry,attribution}`、`classification`、`validity`、`unknown_reasons`。
- 力单位 N、冲量单位 N·s；`force.window_s` 明确为 policy step 聚合窗（physics substeps 内由 PhysX 聚合，`force.basis ∈ {filtered_force, net_force}`）；`impulse.available=false`（本环境未取得可靠冲量，不用力值冒充）。
- 分类（严格 `>0.02 N` 判定、原始值不改写）：`CONTACT_FORCE_MEASURED` / `CONTACT_FORCE_MEASURED_UNATTRIBUTED` / `CONTACT_EVENT_ONLY` / `GEOMETRY_OVERLAP_ONLY` / `NO_CONTACT` / `UNKNOWN`；`UNKNOWN` 优先且 force=None；有效零 force=0.0 且 validity.valid=true。
- 归因：`ATTRIBUTED`（filtered per-prim，prim_paths 必须等于 >阈值 prim 集）/`UNATTRIBUTED`（net，prim_paths 必须为空，禁止伪造）/`UNKNOWN`；geometry 层永不升级。
- runner 每步 `steps[].contact_record` 内嵌完整记录；episode `contact_summary` 由独立汇总函数生成；manifest 记录 `contact_sensor`、`physics`（physics_dt 0.01、decimation 5、substeps 5、update_order after_env_step、replicate_physics=false）、`prim_inventory`（robot/obstacle/map 每 prim 的 Collision/RigidBody/ContactReport 标志）、`body_envelope`。

## 4. 受控验证矩阵（A/B/C/D，各 2 次；预冻结 cases/expected/freeze v2）

| 类 | episode | 结果 | 真实接触证据 | 力/冲量 | 归因 |
| --- | --- | --- | --- | --- | --- |
| A 墙接触 | r0/r1 | SUCCESS 2/2 | `PHYSX_CONTACT_FORCE_MEASURED`（event=true） | 0.1563 / 0.9406 N；impulse 不可用 | ATTRIBUTED → `/World/RMUC2027/Collisions/collision_014` |
| B 运动学障碍接触 | r0/r1 | SUCCESS 2/2 | `CONTACT_FORCE_MEASURED_UNATTRIBUTED`（net force） | 0.0276 N（两次相同；filtered 0） | UNATTRIBUTED（不伪造对象 prim） |
| C 合法近距离 | r0/r1 | SUCCESS 2/2 | `NO_CONTACT`（sensor valid） | 有效零 0.0 N | 无 event/force；球重叠 −0.078 m |
| D 球重叠未接触 | r0/r1 | SUCCESS 2/2 | `GEOMETRY_OVERLAP_ONLY` | 有效零 0.0 N | 无 event/force；overlap +0.022 m |

- D 构造依据（非关闭碰撞）：机器人碰撞几何为 body AABB（half y=0.0382），障碍 half y=0.30 → 横向无接触阈值 0.3382 m；而保守球半径和 0.372463 m；取横向 0.35 m 时 box gap 0.0118 m（未接触）、球 overlap 0.02246 m >0.02 m。`contact_D_geometry/expected` 记录该几何依据。
- 阈值 0.02 N 仅用于接触判定，原始力/重叠原样记录；A/B 的 episode 同时记录 `max_force_n`；C/D 记录 `max_geometry_overlap_m`。
- 接触窗口/更新：`physics_dt=0.01 s`、`decimation=5` → policy step 0.05 s、5 substeps；sensor 在 env.step 后读取（`update_order='after_env_step'`）；event/force 是 policy step 聚合值，不声称逐物理子步事件。

## 5. 旧案例复核（3 例，不批量改写）

| 旧 episode | 旧标签 | 重放方式 | 新证据 | verdict |
| --- | --- | --- | --- | --- |
| `boundary_B_cross_late_r0` | CONTACT_INFERRED | 脚本化接触几何重放（机器人固定在旧接触时刻位姿，障碍轨迹重放） | 球重叠 0.122 m，未测得真实力 | **UNDECIDABLE** |
| `boundary_C_headon_collide_r0` | CONTACT_INFERRED | 同上 | 球重叠 0.119 m，未测得真实力 | **UNDECIDABLE** |
| `boundary_A_static_offpath_r0` | NO_CONTACT | 同上（机器人旧起始位姿，静态障碍） | sensor 有效、无 event/force、无重叠 | **CONSISTENT** |

- 重放是"接触几何重放"，不是闭环 episode 重放；`replay.basis` 已显式记录。未复核的其余 episode 保留旧 `CONTACT_INFERRED` 标签，仅在本报告增加适用性说明（旧推断不能升级为真实接触证据）。

## 6. 包络中心与覆盖

- 测量对象：机器人 root（`/World/envs/env_0/Robot`）AABB（default+render purpose），用 root 位姿逆变换到机器人参考系后求 half/offset；同时记录 collision API prim 集 `/World/envs/env_0/Robot/body/body_collision/geometry`。
- half=`[0.0545422337, 0.0382082667, 0.0135880403]` m；offset=`[5.9024e-05, 2.4214e-08, 0.01486853]` m；`r_origin=0.0724634 m`；旧 `r_legacy=0.0679659 m`；delta=0.0044975 m。
- 阈值处球包络间隙（扣机器人 r_origin + 障碍 0.3 m）：1.1 m → **0.727537 m**（旧 r_legacy 口径 0.732034 m）；候选 1.38 m → **1.007537 m**（旧口径 1.012034 m）。修正分析 `analyze_envelope_correction.json` 对 18 个旧边界 episode 用 r_origin 重算最小路径净空与停止需求 margin；旧报告/旧分析 hash 保留。
- coverage：`collision_geometry`，prim=`body_collision/geometry`，sub_bodies=`body`；螺旋桨/子体无 CollisionAPI（prim_inventory 证明），`limitations` 明确"非全姿态三角网格扫掠、桨叶碰撞几何未覆盖、单关节状态界"；`attitude_scope=any_rigid_rotation_about_reference_origin`。
- 旧 `CLEARANCE_GEOMETRY_CONTRACT` 的球心/半径口径由 `boom_birds.body_envelope.v2` 取代：生产用 `sphere_about_origin`，`sphere_about_aabb_center` 仅对比；`validate_body_envelope_record` 拒绝低估与旧口径冒充。

## 7. 独立核验

- 工具：`scripts/verify_contact_verification_runs.py`（纯标准库；导入 contact_contract/body_envelope 独立重算；四值/六分类枚举；冻结/分母/hash/EpisodeBoundary/时间/physics substep；sensor invalid vs valid zero；attribution 库存与伪造；geometry/impulse/net 隔离；包络半径/覆盖/limitations/legacy delta；场景角色预期；replay verdict/basis；性能统计）。
- 输出：`docs/reports/map_eval/contact_envelope/verify_contact_verification.json`；****PASS**：`status=PASS`、29/29 checks（data_integrity 7、contact_contract 9、envelope_geometry 4、scenario_expectation 5、performance_boundary 4）、failures=0、deviations=0、missing_fields=0；接触证据域：A 墙 filtered 力+attribution、B 障碍 net 力 UNATTRIBUTED、C 有效零 NO_CONTACT、D geometry-only、2 个旧 CONTACT_INFERRED 重放 UNDECIDABLE（旧标签保留）、1 个旧 NO_CONTACT 重放 CONSISTENT；包络 r_origin=0.0724634 m（旧 0.0679659，delta 0.0044975）。**

## 8. 复现命令

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 预运行冻结（代码提交 c50de1f 之后、正式运行之前）
& $py scripts/make_contact_verification_freeze.py --output configs/scenarios/contact_verification_freeze_v2.json
# 受控段（逐段独立目录；B 每 repeat 独立进程后合并）
& $py -u scripts/run_contact_verification.py --segment-id contact_A_wall --cases configs/scenarios/contact_verification_cases_v1.json --expected configs/scenarios/contact_verification_expected_v1.json --freeze configs/scenarios/contact_verification_freeze_v2.json --code-commit c50de1f --kit_args=--/app/vulkan=false --device cuda:0 --output outputs/map_eval/contact_A_wall
# 其余：contact_C_clearance / contact_D_geometry / replay_contact_inferred / replay_no_contact 同理；
# contact_B_obstacle: --repeat-index 0/1 两次独立进程 → tmp/merge_contact_runs.py 合并（记录 merged_from）
& $py tmp/merge_contact_runs.py outputs/map_eval/contact_B_obstacle_rep0 outputs/map_eval/contact_B_obstacle_rep1 outputs/map_eval/contact_B_obstacle
& $py scripts/analyze_envelope_correction.py --output docs/reports/map_eval/contact_envelope/analyze_envelope_correction.json
& $py scripts/verify_contact_verification_runs.py --freeze configs/scenarios/contact_verification_freeze_v2.json --run contact_A_wall=outputs/map_eval/contact_A_wall --run contact_B_obstacle=outputs/map_eval/contact_B_obstacle --run contact_C_clearance=outputs/map_eval/contact_C_clearance --run contact_D_geometry=outputs/map_eval/contact_D_geometry --run replay_contact_inferred=outputs/map_eval/replay_contact_inferred --run replay_no_contact=outputs/map_eval/replay_no_contact --expected configs/scenarios/contact_verification_expected_v1.json --repo-root . --output docs/reports/map_eval/contact_envelope/verify_contact_verification.json
& $py -m pytest -q
```

## 9. 限制与未完成

- **接触力归因**：墙接触为 filtered+ATTRIBUTED；运动学障碍仅 net force（UNATTRIBUTED），未取得 per-prim filtered 通道。不得把 UNATTRIBUTED 力归到具体障碍 prim；后续需在 env 创建前配置 shape reporter 或自定义 spawn 流程。
- **冲量**：本轮 `impulse.available=false`；没有可靠冲量，不用力值冒充。
- **单进程接触报告仅首 episode 可靠**：B 重复用独立进程规避，manifest `merged_from` 与 `merge_note` 记录；这是当前接触链覆盖限制，不能声称"任意多 episode 同进程均可靠"。
- **旧案例复核**：2 个 CONTACT_INFERRED 重放为 UNDECIDABLE（脚本化几何重放，非闭环）；旧推断标签保留，不能升级为真实接触证据。其余未复核 episode 不改写。
- **包络**：AABB 基于机器人 root 与单关节状态；桨叶无碰撞几何；不是全姿态三角网格扫掠；AABB 中心偏移已修正但未覆盖视觉 mesh 与碰撞 mesh 差异（root AABB 可能含视觉子几何，本轮报告按实测记录并标注）。
- **历史差异**：历史 `MAP_DYNAMIC_REPORT` 原样入口在当前环境可复现 0.0231 N；但历史入口上下文与当前边界入口不同，"历史有力/当前无力"的差异由 reporter 覆盖层、`replicate_physics` 下 post-hoc shape reporter 不生效、单进程首 episode 限制共同解释（详见诊断报告）。旧报告数字不重写，只加适用性说明。
- **不提升 Gate**；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；无真实感知/PX4/板端/SITL/HIL/实机。

## 10. 证据与 hash

| 产物 | SHA-256 |
| --- | --- |
| `contact_verification_freeze_v2.json` | `184beecc779d768964fa7412724502ac9e342ad0ef68a8101aed00ac543f6fba` |
| `contact_verification_cases_v1.json` | `b337a18a37e9a4854ae7ed624d85eead6471b69947f1b6e8db8342d3b971979c` |
| `contact_verification_expected_v1.json` | `3b71936851d117fcfd6fb88c37b8a1073bf54f236e2207dd38490d1533b4b187` |
| `contact_A_wall/summary.json` | `d5e4693830de592250154648455c4d8f5057c5a568e4af351f22a06049c7fd7c` |
| `contact_A_wall/episodes.jsonl` | `feec0c97910a39d35631f9d56b03caa98680f8fae6e8d6b4d1f246a69e1d5893` |
| `contact_A_wall/manifest.json` | `058301230d39738b2530b7b7bf5e9ee2664af9c5e6eb94058a70c98248568b16` |
| `contact_A_wall/steps.jsonl (raw, gitignored)` | `2091b1689b2e2beade1d493e69f765e96d85c525a9ddff4fabe4846fe73d1cd1` |
| `contact_B_obstacle/summary.json` | `03f4fdc94f01a64a64e5c3c27eb011be02a85359f8c482b7be1b2001bf505370` |
| `contact_B_obstacle/episodes.jsonl` | `eac7fa3fce584b35dc62061742caf4a1c755b5d224be1c4e922660f1028a4fcb` |
| `contact_B_obstacle/manifest.json` | `29d5ddf98158e06ac76383309f8cd7de8d196cbca62fbff39f530cb12b24e041` |
| `contact_B_obstacle/steps.jsonl (raw, gitignored)` | `f4368387cb8a9aafd61199defe71f970a3d6b7a2e06a89adc90b75e476384fdd` |
| `contact_C_clearance/summary.json` | `8f0cf3692e3d7a0c7b9ea69fd7b192b0d6402ae3940cc12605ceb86800e09b63` |
| `contact_C_clearance/episodes.jsonl` | `1b09eb7b848928103baf8b63038b73373cecff3ba4f902e15cdcb146a009c730` |
| `contact_C_clearance/manifest.json` | `6d13baac02eadd5f5173aba89cc6a3d7e987bfe41a8a98efd8729c3339067e05` |
| `contact_C_clearance/steps.jsonl (raw, gitignored)` | `01ef935e02dad57f056d92debd7ebb8ae1b046f93e001dca8287abcb19a57c04` |
| `contact_D_geometry/summary.json` | `4042942e4d93220507802a16e8b4427b441bb7cfef58b6e61e8b242ad9584a1a` |
| `contact_D_geometry/episodes.jsonl` | `4f0cce0414a5a0b6b0968c7d486b56d43a7b50e26019a7f2b0e4f2648a1cc8d5` |
| `contact_D_geometry/manifest.json` | `420580181c704b35f8860b1d8ab974af709566531d382cd5faf79515e0118897` |
| `contact_D_geometry/steps.jsonl (raw, gitignored)` | `9bbeaeefec261ac5121d3f4a214b30da81cb0843ed238b44785f82d92f1d7c33` |
| `replay_contact_inferred/summary.json` | `b3bd3e3df1ee1ac0fb86c4d560d87f31087bfe2deb95272a460548e8bff5d7e2` |
| `replay_contact_inferred/episodes.jsonl` | `1b3c4fad6fbad9ff6f4288437b9dac4c7f212e3ddc2992e17b435fab3359db1c` |
| `replay_contact_inferred/manifest.json` | `95630a0e8b209bf3fe3a01faa15a7cc01ec912002f47496125c5e07efab309fb` |
| `replay_contact_inferred/steps.jsonl (raw, gitignored)` | `18772b7843e2a8c51b2d7997fec62fd83b358bbe5ff9536531e66889153d1932` |
| `replay_no_contact/summary.json` | `529f3815af103dee6809af492c433a41d3d72bc587901cacc3db08b02a7ccb5a` |
| `replay_no_contact/episodes.jsonl` | `514f847157df3e4b67b3947ae5eb41cfe213936fa3b0f6867461ac35d2db4d47` |
| `replay_no_contact/manifest.json` | `7a343f0cdb1bd7ff6ab7315e7f73dffcb3307207d88cb8fb1b1256d7a2038b67` |
| `replay_no_contact/steps.jsonl (raw, gitignored)` | `57c8357c766c68600947331a73a0935f65bc565efb9036537b68a047a7ae5bc8` |
| `probes/probe2_wall_ok` | `bcd3c28ebbbd85404dae759bb2f6f07501ccbb6ee0b686362d88cf5536a58d32` |
| `probes/probe4_unfiltered_obstacle_zero` | `1f5706ee307c1d2a6c793aec7538b216cd8be20a50f749fe75fac1828c2ca4ae` |
| `probes/probe6_replicate_true_obstacle_zero` | `ea75f8d8c72df3d737af66af9114b05c31fd2fe94ddf7640ca8bd9322d51efa8` |
| `probes/probe7_posthoc_shape_reporter_zero` | `1ea41d68d6b3840b5684296c1e7ae51a0be0eb0eb429ab8bfa1fab8d33ba1328` |
| `probes/probe8_physics_sensor_zero` | `ffa5a9629f759039bb2c4840ca3053bc7c7960663636548ca8092af8f7a5f2f6` |
| `probes/probe11_replicate_false_ok` | `b9d50c46a6e21d04f3b7a66fdad320687df829baac2bc835327b5090ff52ccf6` |
| `probes/historical_repro1_episodes` | `29cb17250e15faebacbb1a8fabb10a8710aa2f8f4370dea3394c0462a4dbeffe` |
| `probes/historical_repro1_manifest` | `edd2bb3e25ec8f87ef01bced0684c4d23c8b29e30d4f9ab4c93822d230bdfa09` |
| `screenshots/gui_wall_contact.png` | `319b34b50423d33fbe087bececab1a24c360e11989dab5667dde5120dce0ceba` |
| `verify_contact_verification.json` | `1484cc5274ff6da683481a35a1f02ef6f15d75b7b521018dfd794d79bddf2c1c` |
| `analyze_envelope_correction.json` | `8e5e275b30cd947f0fac78098aca9bdaae7c11921680b999ed8acb856de03068` |
| `CONTACT_DIAGNOSIS_20261102.md` | `68769d940cd08d5851feda74d4b03d9a7bd110c0e04add9353886e3753472c8f` |
