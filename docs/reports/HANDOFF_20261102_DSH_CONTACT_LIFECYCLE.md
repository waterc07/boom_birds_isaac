# 交接：DSH 接触新鲜度最小闭环（2026-11-02）

## 状态

- 本阶段**矩阵 PASS**（单环境接触新鲜度/连续三集），但**接触链整体尚未关闭**：旧两例闭环新测量未完成，生产入口/包络迁移未做，不提升 Gate。
- 未创建/未标记 Goal；未提交 Git，未切分支，未回退/批量提交用户或 Codex 文件。共享工作树 HEAD 仍 `34bdaa8`（`codex/bb22-contact-envelope`）；Codex 的 `contact_readout` 修改已接入但未提交，双方文件均保留。
- 旧 freeze/旧运行/旧核验结果未覆盖：`clearance_boundary_freeze_v1.json`、`contact_verification_freeze_v2.json`、`outputs/map_eval/bnd_*` 等保持原样。

## 本阶段产物

| 类别 | 路径 |
| --- | --- |
| 最小矩阵案例 | `configs/scenarios/dsh_contact_lifecycle_minimal_cases_v1.json` |
| 预冻结预期（v2） | `configs/scenarios/dsh_contact_lifecycle_minimal_expected_v1.json` |
| 预运行冻结（v1） | `configs/scenarios/dsh_contact_lifecycle_freeze_v1.json` |
| 冻结生成器 | `scripts/dsh_make_contact_lifecycle_freeze.py` |
| 独立核验器 | `scripts/dsh_verify_contact_lifecycle_runs.py` |
| 正式运行（GUI） | `outputs/dsh_contact_lifecycle/formal_contact_S_static3`、`outputs/dsh_contact_lifecycle/formal_contact_W_wall3` |
| 核验 JSON | `docs/reports/map_eval/contact_envelope/dsh_contact_lifecycle_verify_20261102.json`（PASS，77/77） |
| 报告 | `docs/reports/map_eval/contact_envelope/dsh_contact_lifecycle_closure_report_20261102.md` |
| GUI 截图 | `docs/reports/map_eval/contact_envelope/screenshots/dsh_contact_lifecycle_formal_gui.png` |
| 旧案例重放计划（前期） | `configs/scenarios/dsh_contact_lifecycle_replay_plan_v1.json` |
| 旧案例单例探针（未修改旧 runner + 当前依赖） | `tmp/dsh_replay_probe/`（B，SUCCESS）、`tmp/dsh_replay_probe_c/`（C，ABORT） |
| 包络迁移方案 | `docs/reports/map_eval/contact_envelope/dsh_contact_lifecycle_envelope_migration_plan_20261102.md` |

## 运行摘要

- 两段各 3 集、同进程、每集 hard reset：`env.sim.reset(soft=False)` → `env.reset(seed=0)` → 重建 executor/reporters/sensors → 分离位姿有界握手（最大 20 步，零容差 1e-6 N）→ RUN。
- generation 依次 1/2/3；握手均第 1 步成功且 `measured_force_n=0`；RUN 内 generation 不变（无中途 reset）。
- 实墙：3/3 `PHYSX_CONTACT_FORCE_MEASURED`，最大测得力 0.647145 N/集，attribution 命中 `collision_014`；raycast 命中同 prim（距离 3.613 m，高度 1.0 m）。
- 静态障碍：3/3 `PHYSX_CONTACT_FORCE_MEASURED_BELOW_THRESHOLD`，最大测得力 0.016022 N/集；低于 0.02 N 仍按真实接触接受，不判无接触。
- 测试：`pytest -q` 750 passed；核验 77 checks PASS，0 failures/missing。

## 需 Codex 合并检查/决定

1. 审阅 runner 的 hard-reset/握手/测量字段改动（`scripts/run_contact_verification.py` 是双方共同修改文件；本阶段新增 `--physics-reset-mode`、`--handshake-*`、manifest/episode 字段）。
2. 审阅新冻结 schema/生成器/核验器/expected v2；决定是否将 hard-reset 模式与 readout 字段纳入正式冻结器/核验器版本，而非独立 DSH 脚本。
3. 旧两例闭环新测量方案：单例旧 runner（当前依赖）结果不同（B SUCCESS vs 旧 ABORT，C ABORT 但步数不同），不能称严格复现；需完整旧 episode 序列 + 旧依赖版本/驱动记录 + 测量适配，或新 freeze 标注新版本重放。
4. 包络迁移方案（仍只文档，无生产改动）与原生 contact event 通道（Codex 复核 0 事件，不可作无接触证明）。

## 剩余限制

- hard reset 仅单环境评价；未验证多环境/训练链；有每集重启开销与时间语义变化。
- 墙体 bbox 无效（BBoxCache 返回 inf），几何证据依赖 raycast + prim API；未把无效 bbox 当证据。
- 旧运行无 contact sensor，旧几何标签不能升级为真实接触；本轮测量只在最小矩阵成立。
- 原生 callback 未建立；零读数只记 UNKNOWN/几何分离，不判无接触。
- 包络迁移未完成；不提升 Gate；无真实感知/PX4/板端/SITL/HIL/实机。

## 证据 hash

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

## 复现

见报告 §6（冻结 → 两段 GUI 运行 → 独立核验 → pytest）；所有 Isaac 运行均前台可视 GUI/DirectX/D3D12，无 headless。
