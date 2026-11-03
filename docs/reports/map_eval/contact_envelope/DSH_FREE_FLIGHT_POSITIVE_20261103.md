# DSH 单环境新接触模式：自由飞行阳性验证与可复现交付（2026-11-03）

> **状态：** PASS（单环境、自由飞行、预冻结生产入口；新模式仍为 opt-in，不直接切换默认）
> **证据域：** Isaac Sim 5.1 前台可视 GUI（DirectX/D3D12，无 headless）、4 个原动态案例 × FOLLOW_ONLY/SUPERVISOR × 2 重复 = 16 个正式 episode；单环境评价，不是实机/多环境训练证据
> **最后核对：** 2026-11-03T10:30+08:00

## 1. 结论

- 从原 FOLLOW_ONLY 曾碰撞的 C/D/E 类中选取 **C_south_0、C_north_0、D_south_0、D_north_0**（覆盖 C/D 两类、south/north 两条路线）；每案例 FOLLOW_ONLY 与 SUPERVISOR 各 **2 次重复**，共 **16 个预冻结正式 episode**。
- **FOLLOW_ONLY 8/8 全部产生自由飞行真实 filtered 接触阳性**，两个重复一致；峰值 **0.013053–0.037414 N**，filtered 对象均为 `/World/envs/env_0/Obstacle`；首次接触发生在 episode 中段（policy step 454–635，约 22.75–31.80 s），起始几何余量 **9.99–12.91 m**，首次接触时有明确几何重叠。没有通过初始穿模、传送机器人、锁定姿态或修改速度制造阳性。
- **SUPERVISOR 8/8 完整保留**：全部 `ABORT / MAX_WAIT_EXCEEDED`、物理证据 `UNKNOWN`、无测力正样本；这是监督器的实际结果，不是性能要求，也没有为凑阳性改控制器/阈值/TTL/所有权/路线参数。
- 每集开始完整物理 reset，生成 **generation 1–8**（每个重复独立序列），有界分离握手 8/8 成功且零基线；RUN 内无 reset；实际结束由 `COLLISION`（FOLLOW_ONLY）或业务 `ABORT`（SUPERVISOR）停止，`env_terminated/env_truncated=false`，未发生未声明环境 reset。
- **C_south_0 峰值 0.013053 N 低于旧 0.02 N 派生阈值**，仍作为原始非零 filtered 力保留并计为真实接触，不判无接触；零读数（SUPERVISOR）仍为 **UNKNOWN**，未改写成 NO_CONTACT。
- 独立核验 **PASS（164 checks）**：从原始 `filtered_by_target_n`/`net_vectors_n` 重算峰值、首次接触、对象、缓存一致性、初始几何、generation/握手/结束信号、重复配对、冻结/source/产物 hash；迁移核验 2×PASS（各 4,074 行），原始向量审计 PASS（8,148 行）。
- **可复现交付：** 必要实现先形成代码提交 `d708acb`；随后发现冻结源码 hash 对 checkout 行尾敏感，先加失败回归测试、最小修复并提交 `1ebbcbe`，再生成**新冻结**并重跑全部 16 个正式 episode（旧 16 个 pre-linefix 运行保留为 pilot，不混入正式配对）。独立导出 worktree（commit `1ebbcbe`）在关闭 CRLF 转换、仅引用本地小配置/既有地图资产后：冻结校验 PASS、`pytest -q` **774 passed**、导入 PASS。
- **默认模式：本轮仍不切换。** 正能力、异常处理和旧 20 场景回归已具备单环境评价候选条件；但阳性仍只覆盖 C/D 4 案例，supervisor 无接触，原生事件/负覆盖/实机/多环境未验证。建议下一次单独评审后升级“单环境评价默认”，本轮保持 legacy 默认。

## 2. 实现审查与代码提交

- **代码提交 `d708acb`（`feat(contact): 交付单环境新接触/几何评价模式的必要实现`）**：纳入经审查的必要实现：
  - `scripts/run_dynamic_eval.py`（新 `--geometry-policy reference_origin_v2`、`--contact-mode measured_hard_reset`、`--write-migration-freeze`、完整 reset/握手、真实 filtered 测量、结束 generation 记录）；
  - `src/boom_birds/evaluation/clearance.py`（clearance v2、参考原点机器人球、cuboid 半对角线障碍球；legacy 保留）；
  - `src/boom_birds/evaluation/contact_readout.py`、`contact_raw_audit.py`、`dynamic_migration_plan.py`；
  - `src/boom_birds/sim/dynamic_contact_session.py`、`usd_body_envelope.py`；
  - `scripts/verify_dynamic_migration.py` 与 5 个对应测试文件。
  - 未提交用户文档、用户/其他任务的 `scripts/run_contact_verification.py` 等无关修改；未执行 `git add .`。
- **可复现性修复提交 `1ebbcbe`（`fix(contact): 冻结源码与配置 hash 规范化行尾以保证恢复一致`）**：
  - 先在 `tests/evaluation/test_dynamic_migration_plan.py` 增加“LF/CRLF 同逻辑源码和配置 freeze 仍校验”测试；失败日志 `logs/dsh_linefix_failing_tests.log` 保留；
  - 最小修复 `dynamic_migration_plan._hash()` 仅将 CRLF 规范化为 LF 后 hash；测试通过，`pytest` 从 772 增至 **774 passed**；
  - 该提交只影响冻结身份校验，不改变运行器物理/控制/接触行为。
- 正式冻结基于 `1ebbcbe`；源码 hash 不再依赖 checkout 行尾，独立 worktree 可校验。

## 3. 正式预冻结与运行

- 选择规则：**primary 4 案例** C_south_0/C_north_0/D_south_0/D_north_0；备用规则预先写入 expected：若某 primary FOLLOW_ONLY 两重复均无 filtered 阳性或几何无接触过程，保留失败，按同 class/route 声明 backup（C/D 各自 south/north 的 `*_1`）在新冻结下补跑，不删除失败、不放宽结果。
- 正式冻结：`configs/scenarios/contact_positive_validation_linefix_v2.json`（sha256 `8383b3d4…`，`frozen_at 2026-11-03T02:15:21Z`，Git HEAD `1ebbcbe`）；预期：`configs/scenarios/contact_positive_validation_linefix_expected_v1.json`（sha256 `5da44ada…`）；基础 base freeze：`...linefix_v1.json`。
- 冻结覆盖：完整源码 hash（规范化行尾）、config/cases/map/vehicle/brake hash、4 案例、两种方法、2 重复、几何/接触 policy、reset/握手容差、控制参数、评价版本、预期分类和备用规则。旧 `contact_positive_validation_v2.json`（pre-linefix）与运行保留为 pilot，不用于正式配对。
- 正式运行：`outputs/map_eval/production_contact_migration_positive/repeat1`、`repeat2`；前台 GUI、DirectX/D3D12、cuda:0；两次串行独立进程，每次 8 episode；`repeat1` 开始 10:15:44、`repeat2` 开始 10:21:26（+08:00）。pre-linefix 16 次运行保留在 `pre_linefix_repeat1/2`。
- 运行命令（正式）：

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
$cases = 'dynamic_C_south_0,dynamic_C_north_0,dynamic_D_south_0,dynamic_D_north_0'
# 重复 1/2 各执行一次，串行、独立目录
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --only-cases $cases --methods follow_only,supervisor --execution-path v2 --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --screenshots --device cuda:0 --gpu-driver 'NVIDIA 581.80 (observed)' --kit_args=--/app/vulkan=false --freeze configs/scenarios/contact_positive_validation_linefix_v2.json --output outputs/map_eval/production_contact_migration_positive/repeat1
& $py -u scripts/run_dynamic_eval.py ... --freeze configs/scenarios/contact_positive_validation_linefix_v2.json --output outputs/map_eval/production_contact_migration_positive/repeat2
```

## 4. 正式结果（16/16 episode）

每案例两重复结果一致；FOLLOW_ONLY：

| 案例（class/route） | 重复 | 结果/原因 | 物理 | 峰值 filtered (N) | 首次接触 policy/physics step | 首次接触时间 | 起始几何余量 (m) | 接触对象 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C_south_0（C/south） | 1,2 | COLLISION / OBSTACLE_CONTACT | CONTACT_MEASURED | **0.013053** | 454 / 2280 | 22.75 s | 10.1158 | `/World/envs/env_0/Obstacle` |
| C_north_0（C/north） | 1,2 | COLLISION / OBSTACLE_CONTACT | CONTACT_MEASURED | **0.029040** | 542 / 7475 | 27.15 s | 12.8259 | 同上 |
| D_south_0（D/south） | 1,2 | COLLISION / OBSTACLE_CONTACT | CONTACT_MEASURED | **0.029581** | 635 / 12905 | 31.80 s | 9.9861 | 同上 |
| D_north_0（D/north） | 1,2 | COLLISION / OBSTACLE_CONTACT | CONTACT_MEASURED | **0.037414** | 551 / 18145 | 27.60 s | 12.9097 | 同上 |

SUPERVISOR 8/8：`ABORT / MAX_WAIT_EXCEEDED`，物理 `UNKNOWN`，峰值 filtered=0，无 `contact_prim`。所有 FOLLOW_ONLY 原始 filtered 与 net 峰值一致；首次接触时球重叠分别为 0.2045/0.2236/0.2623/0.2427 m；初始距离均远大于两球半径和，排除初始穿模。

- `contact_max_force_n` 与原始 filtered 峰值一致；C_south 0.013053 N **低于 0.02 N**，未丢弃、未改写。
- `env_terminated=false`、`env_truncated=false`；结束由业务 collision/abort 条件停止；未声明 reset 未发生；`episode_length_buf` 结束值分别为 455/543/636/552（FOLLOW_ONLY）和 0（supervisor abort 记录）。
- 4 案例、2 类动态情形（C/D）、south/north 均覆盖；没有使用 E 类，未删除任何失败。

## 5. 独立核验

- **正能力/边界核验** `scripts/verify_contact_positive_validation.py` → `docs/reports/map_eval/contact_envelope/dsh_contact_positive_validation_verify_20261103.json`，**PASS，164 checks，0 failures/missing**。从原始向量重算：峰值、首次接触 step/time、filtered target、缓存一致性、generation 恒定、每重复 8 次握手、初始几何余量、首次接触几何、实际结束、配对/重复身份、冻结/expected/source/config hash。
- **迁移核验** `scripts/verify_dynamic_migration.py` 对 repeat1/repeat2 各 **PASS，4,074 行/8 集**；输出 `..._linefix_repeat1_migration_verify.json`、`..._repeat2...`。
- **原始向量审计** `scripts/verify_contact_raw_samples.py`：**PASS，8,148 行，0 errors**；`..._linefix_raw_audit.json`。
- **全套测试**：当前工作树 `pytest -q` **774 passed**；包含新增行尾回归测试。
- **冻结校验/独立导出**：在临时 worktree（commit `1ebbcbe`，`core.autocrlf=false`）中：
  - `validate_migration_freeze(linefix_v2, parameters, root)` → **PASS**；
  - 从 `<export>/src` 导入全部新模式模块 → PASS；
  - 复制本地小配置 `configs/maps/rmuc2027.local.yaml` 和既有本地证据 `docs/reports/map_eval/brake/verify_brake_final.json`（不复制地图资产/venv），`pytest -q` → **774 passed**；
  - 未额外重跑 GUI：正式 16 集已在同一提交/冻结上前台 GUI 完成；导出检查仅用于纯软件恢复与冻结校验，风险足够低，没有无依据重复仿真。
- 修复过的核验工具问题：首次 verifier 把 policy step 0 当 1（已修正）；行尾冻结问题由独立导出暴露，先失败测试后修复，**不是**放宽运行数据。
- 旧 20 场景结论不改写：本轮的 C/D 4 案例是新的自由飞行阳性矩阵，不替换 `DSH_DYNAMIC_REGRESSION20` 的 20/20 UNKNOWN supervisor 结论；旧 `CONTACT_INFERRED` 两例仍保持历史物理真值未确认。

## 6. GUI 与证据

- 正式运行均前台可视 GUI、DirectX/D3D12，串行独立目录；`manifest.gui_evidence = {gui_mode: true, renderer: 'DirectX (--/app/vulkan=false)', headless: false}`，gpu driver 记录为观察值（未改驱动/全局渲染）。
- GUI 证据：`evidence_20261103_positive/gui_formal_window_pre_linefix.png`（pre-linefix 正式运行窗口，直接证明可视 GUI；不作为接触数值证据）、`gui_linefix_diagnostic_window.png`（linefix 代码诊断窗口）、`gui_diagnostic_collision_pre_linefix.png`；均为非空有效 PNG，已人工查看至少一张。正式接触数值由原始数据/独立核验证明，不使用截图代替。
- 版本化证据目录：`docs/reports/map_eval/contact_envelope/evidence_20261103_positive/`，包含 positive_metrics.json、两重复 summary/manifest/episodes、GUI 图像与 hashes.json。

## 7. 可复现交付与 Git

- 代码提交：
  - `d708acb`：新模式必要实现；
  - `1ebbcbe`：冻结 hash 行尾规范化 + 失败→通过测试。
- 本轮新增/修改的核验器、正式冻结、expected、报告和证据在最后统一中文提交（仅显式列出，不推送；不执行 `git add .`）。
- 从 `1ebbcbe` 恢复运行：
  1. `git clone`/`git worktree` 到独立目录并 checkout `1ebbcbe`；设置 `core.autocrlf=false`（或确保源码 LF）；
  2. 仅复制本地 `configs/maps/rmuc2027.local.yaml`（以及现有本地 brake evidence，若跑完整测试）；
  3. 复制本轮正式冻结 `contact_positive_validation_linefix_v2.json` 和 expected；地图大资产继续引用 `E:/isaac/boom_birds_storage/assets/RMUC2027_IsaacSim`，不复制 venv；
  4. 以 `PYTHONPATH=<export>/src` 运行 `pytest -q` 和 CLI；正式 GUI 运行需要 Isaac 环境，按报告命令执行。
- 不能只说当前脏工作树：代码已提交；正式实验冻结记录 `git_head=1ebbcbe`、源码/config hash；pre-linefix 运行不混入正式配对。

## 8. 仍存限制 / 仅规避项

1. **正能力范围仍小**：只覆盖 C/D 4 案例、单环境、单一障碍尺寸/速度、single body filter；未覆盖 E 类、其他动态情形或更多地图区域。
2. **原生 event/impulse 未建立**；负接触覆盖未验证；零读数仍 UNKNOWN。实机、多环境训练、真实感知、PX4 等不在本轮范围，不阻塞单环境评价交付但限制默认升级广度。
3. **SUPERVISOR 无接触阳性**：只保留 8/8 ABORT UNKNOWN；不能声称监督器在这些场景有接触能力。
4. **传送/陈旧力**：本轮正式 episode 只在 episode 边界 reset；先前 teleport 对照中的陈旧力仍是已知限制，未做底层缓存修复，也未用其作为正式证据。
5. **导出测试的两个行尾敏感旧测试**：独立 worktree 中如不复制本地 `verify_brake_final.json` 会因 CRLF/LF 失败（不是新模式缺陷）；按上述本地资产复制后 774 passed。该限制已记录，不包装成修复。
6. **默认升级**：本轮保留 opt-in。建议在单环境评价中另立变更评审升级 default；实机/多环境不是本轮的无限期前置，但仍是缺省推广限制。

## 9. 版本化摘要

- 代码：`1ebbcbe42060212fadc3a2c8e583b7605f81c0b9`（必要实现修复）；`d708acbd00626e2be1a492e7f0f94ec1d7ac49f1`（新模式实现）。
- 正式冻结 `8383b3d4…`；expected `5da44ada…`；完整 hash 见 `evidence_20261103_positive/hashes.json` 与交接。
- 正式 16 集原始 `steps.jsonl` 位于忽略的 `outputs/.../repeat1`、`repeat2`，hash 已归档；旧 20 场景证据未改。
