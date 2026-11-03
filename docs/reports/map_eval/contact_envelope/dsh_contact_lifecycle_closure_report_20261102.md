# DSH 接触新鲜度最小闭环报告（2026-11-02）

> **状态：** PASS（仅单环境接触新鲜度矩阵；不提升 Gate；不宣称接触链整体修复）
> **来源：** `CODEX_LIFECYCLE_REVIEW_20261102.md`、`CONTACT_READOUT_FIX_HANDOFF_20261102.md`、`dsh_contact_lifecycle_report_20261102.md`、`CONTACT_REVIEW_CODE_AUDIT_20261102.md`
> **证据域：** Isaac Sim 5.1.0 前台可视 GUI（DirectX/D3D12，无 headless）、标准库单元测试；无真实感知/PX4/板端/SITL/HIL/实机
> **最后核对：** 2026-11-02

## 1. 结论

- **矩阵 PASS（77/77 独立检查）**：同进程静态障碍连续 3 集与实墙连续 3 集均完成；每集开始 `env.sim.reset(soft=False)` + 项目 `env.reset(seed=0)`，`physics_generation` 依次为 1/2/3；每集在已知分离位姿的有限步健康握手第 1 步即得到正零基线（`measured_force_n=0`、`read_ok=true`）；之后才允许进入 RUN 测量。
- **接触真实读数（非阈值判定）**：
  - 实墙：每集最大测得力 **0.647145 N**，filtered 归因命中 `/World/RMUC2027/Collisions/collision_014`；墙的 raycast 在测试高度命中该 prim（距离 3.613 m，测试高度 1.0 m），实际几何来源为比赛地图 collision prim。
  - 静态障碍：每集最大测得力 **0.016022 N**（低于 0.02 N），**按真实接触证据接受，不判无接触**；物理结果 `PHYSX_CONTACT_FORCE_MEASURED_BELOW_THRESHOLD`。
- **接触与测力阈值分离**：每步行同时保留原始 readout（reads、raw vector）、`measured_force_n`（任意幅值）、`threshold_event`（>0.02 N 的派生事件）、`geometry_overlap_sphere_m`、`UNKNOWN`/读取失败；零读数不判 `NO_CONTACT`。原生 contact callback 本轮未使用（Codex 复核显示 0 事件，不可用于无接触证明）。
- **旧结果/冻结不覆盖**：旧 `clearance_boundary_freeze_v1.json`、旧 `contact_verification_freeze_v2.json`、旧运行目录与核验结果均未修改；本阶段用新 `dsh_contact_lifecycle_*` 冻结/预期/核验器（v1/v2 版本化）。
- **两个旧案例闭环新测量：未完成，且不能宣称严格恢复**。未修改的旧 runner 以当前依赖导入并在新鲜单例进程运行：
  - `boundary_C_headon_collide_r0`：ABORT（MAX_WAIT_EXCEEDED），与旧 outcome 相同但步数 411 vs 旧 417；
  - `boundary_B_cross_late_r0`：SUCCESS（ROUTE_COMPLETE），与旧 ABORT/CONTACT_INFERRED **不同**；
  - 旧记录没有真实 contact sensor，单例新鲜进程丢失了旧 run 的前序 episode 物理上下文；因此不能把该结果当作旧案例严格复现，也不能用旧几何标签真伪判定。下一阶段需按完整旧 episode 序列 + 测量适配/新冻结重做，并记录依赖版本差异。
- **本阶段关闭的是接触新鲜度与连续三集验证**；生产接触入口的完整修复、旧案例闭环、包络迁移仍开放；不提升 Gate，不推广到多环境训练。

## 2. 本轮实现（在 Codex 修复之上，不重写读取模块）

- **接入 Codex `contact_readout`（未重写）**：`src/boom_birds/evaluation/contact_readout.py` sha256 `92c089905d02930d3859d2ad178d2663c44cfe2fa248a87a3f976c8dd7db6f55`；runner 保留正确张量解析、L2 模长、异常与原始零值；冻结记录该源码 hash。
- **`physics_hard_reset` 模式**（仅单环境评价）：`--physics-reset-mode hard`；每集开始 `env.sim.reset(soft=False)`，再 `env.reset(seed=0)`，然后重建 executor、重新应用 contact reporters、重建 per-link ContactSensor/view；记录 sensor 的 body_names/filter_count/错误、executor epoch、gate/动作队列（本入口不使用，显式记录 `not_used_in_this_entry`）和 `physics_generation`。RUN 阶段每一步断言 generation 不变；中途 reset 会抛错。
- **有界健康握手**：分离位姿（墙：x=-4；静态障碍：机器人 x=-2、障碍 x=0）最多 `--handshake-max-steps 20` 步，每步记录 force matrix、net、raw count/readout、实际位置、读取健康；仅当 read_ok 且 `measured_force_n <= 1e-6` 才允许测量；否则 episode `INITIALIZATION_FAILED`/UNKNOWN，不无限等待、不手动清零。
- **接触/阈值分离**：每 RUN 行保存 `measured_force_n`（任意幅值）与 `threshold_event`；episode 新增 `max_measured_force_n`、`contact_observed`、`threshold_event_steps`；物理结果含 `PHYSX_CONTACT_FORCE_MEASURED` / `..._BELOW_THRESHOLD` / `UNKNOWN`；零读数不映射为无接触。
- **版本化冻结/核验/预期**（旧文件未改）：
  - 冻结生成器：`scripts/dsh_make_contact_lifecycle_freeze.py`；schema `boom_birds.dsh_contact_lifecycle_freeze.v1`，包含 reset mode、handshake、`contact_readout` 源码 hash、contact evidence version、cases/expected/vehicle/map hashes、每段 run_plan、真实 UTC/HEAD/worktree 状态；拒绝覆盖。
  - 预期：`configs/scenarios/dsh_contact_lifecycle_minimal_expected_v1.json`（`dsh.contact_lifecycle_expected.v2`，`EXPECTED_NOT_CONCLUSION`）。
  - 核验器：`scripts/dsh_verify_contact_lifecycle_runs.py`（独立从原始逐步记录重算；检查冻结/hash/readout hash、3 集分母、generation、握手新鲜零、无中途 reset、接触真实、低幅接触、墙 raycast 几何、sensor 重初始化、时间单调、GUI）。
  - 案例：`configs/scenarios/dsh_contact_lifecycle_minimal_cases_v1.json`（`contact_W_wall3`、`contact_S_static3`，各 3 集）。

## 3. 预冻结与正式运行

| 项 | 值 |
| --- | --- |
| 预冻结 | `configs/scenarios/dsh_contact_lifecycle_freeze_v1.json`（`frozen_at 2026-11-02T14:30:59Z`，schema `boom_birds.dsh_contact_lifecycle_freeze.v1`，code commit `34bdaa8`，readout sha `92c08990…`，cases sha `6899f41d…`，expected sha `453510c7…`） |
| 正式运行（GUI） | `outputs/dsh_contact_lifecycle/formal_contact_S_static3`、`outputs/dsh_contact_lifecycle/formal_contact_W_wall3` |
| 世界/时机 | 单环境；每集 200/139 步；physics dt 0.01 s、policy dt 0.05 s；每集 hard reset；无中途 reset |
| 原始证据 | `steps.jsonl` 含 HANDSHAKE/RUN 行、原始 reads、`measured_force_n`、generation、时间戳；`episodes.jsonl`、`manifest.json`、`summary.json` |
| GUI 证据 | `docs/reports/map_eval/contact_envelope/screenshots/dsh_contact_lifecycle_formal_gui.png`（前台 Isaac Sim 5.1 窗口；正式冻结静态段运行期间截取） |

逐集结果（两段均 3/3 SUCCESS）：

| 段/集 | generation | 握手成功步 | 墙 raycast | 最大测得力 (N) | 物理结果 |
| --- | --- | --- | --- | --- | --- |
| contact_S_static3 ep0/1/2 | 1/2/3 | 1/1/1 | — | 0.016022 / 0.016022 / 0.016022 | BELOW_THRESHOLD |
| contact_W_wall3 ep0/1/2 | 1/2/3 | 1/1/1 | collision_014 @3.613 m, z=1.0 | 0.647145 / 0.647145 / 0.647145 | FORCE_MEASURED |

旧 `contact_*`/`bnd_*` 运行、旧 freeze、旧 verify JSON 保留未改。

## 4. 独立核验

- 命令：`python scripts/dsh_verify_contact_lifecycle_runs.py --freeze configs/scenarios/dsh_contact_lifecycle_freeze_v1.json --expected configs/scenarios/dsh_contact_lifecycle_minimal_expected_v1.json --run contact_W_wall3=outputs/dsh_contact_lifecycle/formal_contact_W_wall3 --run contact_S_static3=outputs/dsh_contact_lifecycle/formal_contact_S_static3 --repo-root . --output docs/reports/map_eval/contact_envelope/dsh_contact_lifecycle_verify_20261102.json`
- 结果：**PASS，77/77 checks，0 failures/missing**；JSON `dsh_contact_lifecycle_verify_20261102.json`。
- 检查覆盖：冻结 schema/hash/readout hash/版本；分母与 episode id；每集 generation；HANDSHAKE 行 read_ok/`fresh_zero`/最多 20 步；RUN generation 恒定（无中途 reset）；`measured_force_n>0` 真实接触；低幅接触与非无接触判定；墙 prim raycast/attribution；sensor 重新初始化 body/filter；时间单调；GUI DirectX 字段。
- `pytest -q`：**750 passed**（含 Codex 新增 25 项 readout 回归；未修改其测试/读取模块）。

## 5. 失败与限制（保留）

1. **首版核验器 GUI 判定缺陷**：把 `'(DirectX' in renderer` 写错（实际 `DirectX (--/app/vulkan=false)`），首轮出现 2 条假失败；已修正核验器并重跑 PASS。该缺陷不影响运行数据/冻结。
2. **硬 reset 的代价/时间语义**：每集重启物理，sensor/view 必须重建；仅单环境评价可用，未验证多环境/并行训练；未在训练链使用。
3. **墙 bbox 不可用**：`UsdGeom.BBoxCache` 对该 Mesh 返回无效范围，因此墙几何证据用 raycast（命中 prim/距离/高度）+ prim API 标记，未把无效 bbox 当证据。
4. **原生 contact callback**：本轮未接入；Codex 复核 3 集 0 事件，不能用于"无接触"证据；未来若要独立事件通道需另立合同。
5. **旧案例闭环**：未完成。未修改旧 runner 单例（当前依赖）结果：C ABORT 与旧 outcome 同但步数不同；B SUCCESS 与旧 ABORT 不同。旧运行无 contact sensor；严格恢复需完整前序 episode 序列、依赖版本/驱动/origin 等（`dsh_contact_lifecycle_replay_plan_v1.json` 已列缺口），且不能把新测量与旧几何标签混为同一证据。
6. **包络迁移**：仍为方案阶段（`dsh_contact_lifecycle_envelope_migration_plan_20261102.md`），生产入口未改用 body_envelope.v2/root-frame center offset。
7. 未提升任何 Gate；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；无真实感知/PX4/板端/SITL/HIL/实机。

## 6. 复现命令

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 预运行冻结（代码/案例/预期就绪后；已存在会拒绝覆盖）
& $py scripts/dsh_make_contact_lifecycle_freeze.py
# 正式矩阵（GUI，前台，无 headless）
& $py -u scripts/run_contact_verification.py --segment-id contact_S_static3 --physics-reset-mode hard --cases configs/scenarios/dsh_contact_lifecycle_minimal_cases_v1.json --expected configs/scenarios/dsh_contact_lifecycle_minimal_expected_v1.json --freeze configs/scenarios/dsh_contact_lifecycle_freeze_v1.json --code-commit 34bdaa8 --working-tree 'DSH pre-run freeze v1' --output outputs/dsh_contact_lifecycle/formal_contact_S_static3 --kit_args=--/app/vulkan=false --device cuda:0
& $py -u scripts/run_contact_verification.py --segment-id contact_W_wall3 --physics-reset-mode hard --cases configs/scenarios/dsh_contact_lifecycle_minimal_cases_v1.json --expected configs/scenarios/dsh_contact_lifecycle_minimal_expected_v1.json --freeze configs/scenarios/dsh_contact_lifecycle_freeze_v1.json --code-commit 34bdaa8 --working-tree 'DSH pre-run freeze v1' --output outputs/dsh_contact_lifecycle/formal_contact_W_wall3 --kit_args=--/app/vulkan=false --device cuda:0
# 独立核验
& $py scripts/dsh_verify_contact_lifecycle_runs.py --freeze configs/scenarios/dsh_contact_lifecycle_freeze_v1.json --expected configs/scenarios/dsh_contact_lifecycle_minimal_expected_v1.json --run contact_W_wall3=outputs/dsh_contact_lifecycle/formal_contact_W_wall3 --run contact_S_static3=outputs/dsh_contact_lifecycle/formal_contact_S_static3 --repo-root . --output docs/reports/map_eval/contact_envelope/dsh_contact_lifecycle_verify_20261102.json
& $py -m pytest -q
```

## 7. 证据 hash

| 产物 | SHA-256 |
| --- | --- |
| `freeze` | `e0f89f283f51e1665b27ad5c468386c05e499afba9498b2c822da18ff5bdf3be` |
| `cases` | `6899f41d76e038b4b2f6d48bd5eebf8b0125c2952d6c1df06eda185f1feaffcf` |
| `expected` | `453510c721363fc91c699f48719355e14df2c4e4eab294c27eed2e9155ffa7b9` |
| `readout` | `92c089905d02930d3859d2ad178d2663c44cfe2fa248a87a3f976c8dd7db6f55` |
| `runner` | `16fe593e0c15fd52559c15932669afe65b6efac299252a147e0c4c3ff223f3ec` |
| `freeze_generator` | `c7c5106fb1b0c973584209bc4ca94c49ef558183f61449f7f0b8d2691d3f0613` |
| `verifier` | `5befd06719658c34b8842108d1de8cdea4d3b53b124827ffb0f4c12d94834d5f` |
| `verify_json` | `54fdd97ea9d754711c78eddef97717d5f350b61570596d6c7d8252eda4f4a2a0` |
| `screenshot` | `e689fab0a01816828dbe8a9b350667bc243b4f1e98325dcff81ca2ef78ba00c4` |
| `formal_contact_S_static3/summary.json` | `1532a2c3b1cb2b12235b16244ec89fd3b09bd379b1f14e764e7dfaa4385f1dd7` |
| `formal_contact_S_static3/episodes.jsonl` | `998b8644e0abd2009e5dfe68eaf6efadc6a2f161c9c795dae25b8033d04cb736` |
| `formal_contact_S_static3/manifest.json` | `072525f46343acbd70d37ce8c2a65b9d613116f3dccfccb7e20c3656bd9ee0ed` |
| `formal_contact_S_static3/steps.jsonl` | `302e638d3fd97f8474eff53e109f1a66dea2e305e6ae12c77fb4435db41dbc94` |
| `formal_contact_W_wall3/summary.json` | `afc7bdf274d425961969d094f64769ce2474c17688e7412a932045c8e1708d44` |
| `formal_contact_W_wall3/episodes.jsonl` | `7a6330da8b2f4b9c69a24cabe3b79b083c86519c0bfc963d08ed2c0c0c9d8b5d` |
| `formal_contact_W_wall3/manifest.json` | `ded286a12345f730556a54b44f027fd1ab5ae0e59e4ccf9a6af17e50a9c35cc8` |
| `formal_contact_W_wall3/steps.jsonl` | `7abf68feb14b7a3a7a43b5ecf6d0f19b4ad4627740968e5da046d2cf4f537a0c` |

## 8. 下一步（未完成，不得宣称接触链整体修复）

1. 旧两例闭环新测量：恢复旧 run 的完整 episode 序列/依赖版本/驱动/origin，或明确以新 freeze 的"新版本重放"标注；测量适配需带 hard reset/handshake，并记录与旧运行差异。
2. 生产 `run_dynamic_eval.py` 是否需要接触测量接入与包络迁移；先做差异审查/新版本，不覆盖旧冻结。
3. 原生 contact event/raw data 独立通道（若需要"无接触"正证据）；当前只用 force/geometry/UNKNOWN 分层。
4. 多环境/训练链不推广 hard reset；本阶段仅单环境评价方案。
