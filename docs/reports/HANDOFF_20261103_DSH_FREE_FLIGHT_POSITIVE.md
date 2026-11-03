# 交接：单环境新接触模式自由飞行阳性验证与可复现交付（2026-11-03）

## 状态

- **PASS（单环境、自由飞行、预冻结生产入口）**：4 个原 C/D 案例 × FOLLOW_ONLY/SUPERVISOR × 2 重复 = **16 个正式 episode**。
- **FOLLOW_ONLY 8/8 自由飞行真实 filtered 接触阳性**（两重复一致；峰值 0.013053–0.037414 N；对象均为 `/World/envs/env_0/Obstacle`）；C_south_0 的 0.013053 N 低于 0.02 N 仍按真实接触保留。
- **SUPERVISOR 8/8 完整保留**：全部 ABORT/MAX_WAIT_EXCEEDED、物理 UNKNOWN、零接触；未改控制器/阈值/TTL/所有权/路线，不把 supervisor 的 ABORT 当性能失败。
- 独立核验 PASS：正能力/边界 **164 checks**；迁移 2×4,074 行；raw **8,148 行 0 errors**；`pytest -q` **774 passed**；文档审计待最终复核。
- **必要实现已入代码提交**：`d708acb`（新模式实现）；`1ebbcbe`（冻结 hash 行尾修复 + 失败→通过测试）。正式冻结/expected/核验器/报告在最后统一中文提交，不推送。
- **默认仍为 legacy/opt-in**：本轮不切换默认；正能力、异常处理、旧 20 场景回归已构成单环境评价升级候选，但范围仅 C/D 4 案例，supervisor 无阳性，实机/多环境/原生事件仍限制。

## 1. 代码提交与文件清单

### 已提交的必要实现（`d708acb`）

- `scripts/run_dynamic_eval.py` — 新模式 CLI、完整物理 reset + 分离握手、真实 filtered 测量、generation/结束记录、migration freeze 校验。
- `src/boom_birds/evaluation/clearance.py` — clearance v2、机器人参考原点球、障碍 cuboid 半对角线、legacy 保留。
- `src/boom_birds/evaluation/contact_readout.py` — Codex 修复的接触读取（张量/L2/原始零）。
- `src/boom_birds/evaluation/contact_raw_audit.py` — 原始向量重算。
- `src/boom_birds/evaluation/dynamic_migration_plan.py` — 预运行 freeze/参数/源码身份。
- `src/boom_birds/sim/dynamic_contact_session.py` — 单 body→障碍 filtered 会话、有界零握手。
- `src/boom_birds/sim/usd_body_envelope.py` — 真实 CollisionAPI 网格到 root-frame 包络。
- `scripts/verify_dynamic_migration.py` — 独立迁移核验。
- `tests/evaluation/test_contact_raw_audit.py`、`test_contact_readout.py`、`test_dynamic_migration_plan.py`、`test_production_geometry.py`、`tests/sim/test_dynamic_contact_session.py`。

### 后续可复现性修复（`1ebbcbe`）

- `dynamic_migration_plan._hash()` 将 CRLF 规范化为 LF 后再 hash；`tests/evaluation/test_dynamic_migration_plan.py` 新增 2 个失败→通过回归（LF/CRLF 源码和配置）。失败日志：`logs/dsh_linefix_failing_tests.log`。
- 该修复不改变物理/控制/接触行为，只让“完整代码提交”可在独立 checkout 中校验冻结。

### 未提交/不纳入

- 用户文档、配置和其他任务修改；Codex 未完成的非必要文件；`scripts/run_contact_verification.py` 等不属本轮生产入口的文件。
- 未执行 `git add .`、未回退、未切换共享工作树、未推送。

## 2. 正式冻结与结果

- 基础 freeze：`configs/scenarios/contact_positive_validation_linefix_v1.json`。
- 正式 freeze：`configs/scenarios/contact_positive_validation_linefix_v2.json`，sha256 `8383b3d488abc4d95310bf6d12fdecfeaab989970bd5d74395606078699d1b4d`，`frozen_at 2026-11-03T02:15:21Z`，Git HEAD `1ebbcbe`，包含 expected_reference / 4 案例 / 2 方法 / 2 重复 / 备用规则。
- expected：`configs/scenarios/contact_positive_validation_linefix_expected_v1.json`，sha256 `5da44ada2b87d42e491cbb94aa380c8d630e633e7b369f0ec934cbed1d5b1da5`。
- 正式运行：
  - `outputs/map_eval/production_contact_migration_positive/repeat1` 开始 `2026-11-03T10:15:44+08:00`；
  - `repeat2` 开始 `2026-11-03T10:21:26+08:00`；
  - 每次 8 episode，generation 1–8；独立串行进程，独立目录；前台 GUI/DirectX/D3D12。
- pre-linefix 16 次运行保留在 `pre_linefix_repeat1/2`，只作 pilot，不混入正式配对。

| case | 两重复 FOLLOW_ONLY | 峰值 filtered | 首次 contact (policy/physics step, time) | SUPERVISOR |
| --- | --- | --- | --- | --- |
| C_south_0 | COLLISION/OBSTACLE_CONTACT, CONTACT_MEASURED | 0.013053 N | 454 / 2280, 22.75 s | ABORT/MAX_WAIT, UNKNOWN |
| C_north_0 | 同上 | 0.029040 N | 542 / 7475, 27.15 s | 同上 |
| D_south_0 | 同上 | 0.029581 N | 635 / 12905, 31.80 s | 同上 |
| D_north_0 | 同上 | 0.037414 N | 551 / 18145, 27.60 s | 同上 |

- 初始几何余量 9.99–12.91 m；首次接触球重叠 0.2045–0.2623 m；filtered target 均为 `/World/envs/env_0/Obstacle`；`contact_max_force_n` 与原始 filtered 峰值一致。
- 结束：FOLLOW_ONLY `COLLISION`、SUPERVISOR `ABORT`；`env_terminated=false`、`env_truncated=false`，无 RUN 中 reset；`episode_length_buf` 结束值见 positive_metrics。
- GUI：正式运行 manifest `gui_mode=true`、`renderer='DirectX (--/app/vulkan=false)'`、`headless=false`；窗口截图见证据目录（正式/pre-linefix 与 linefix 诊断；截图不用于替代接触数值）。

## 3. 独立核验

| 核验 | 输出 | 结果 |
| --- | --- | --- |
| 正能力/边界 | `docs/reports/map_eval/contact_envelope/dsh_contact_positive_validation_verify_20261103.json` | **PASS 164 checks** |
| 迁移 repeat1/repeat2 | `.../dsh_contact_positive_linefix_repeat1_migration_verify.json`、`...repeat2...` | **PASS 4,074 rows each** |
| 原始向量 | `.../dsh_contact_positive_linefix_raw_audit.json` | **PASS 8,148 rows, 0 errors** |
| 全套 pytest | 当前工作树 | **774 passed** |
| 文档审计 | `scripts/planning/audit_documents.py` | 最终复核（见报告） |
| 导出恢复 | commit `1ebbcbe` worktree，`core.autocrlf=false` | 冻结校验 PASS；import PASS；pytest **774 passed**（需本地 `rmuc2027.local.yaml` 与既有 brake evidence） |

核验从原始 `filtered_by_target_n`/`net_vectors_n` 重算，不优先信任运行器缓存；检查了 4 案例×2 方法×2 重复身份、握手/generation、初始距离、首次接触/峰值/对象、实际结束、配对、冻结/source/config/产物 hash。修复的核验工具口径（policy step 0、行尾 canonical hash）已在报告中记录，不是运行数据放宽。

## 4. 可复现恢复步骤

1. 从提交恢复：`git worktree add --detach <export> 1ebbcbe42060212fadc3a2c8e583b7605f81c0b9`，并在 export 中 `git config core.autocrlf false`（或确保源码 LF；freeze hash 已规范化行尾，但旧的 brake 测试仍有本地行尾敏感）。
2. 本地小资产/配置：复制 `configs/maps/rmuc2027.local.yaml`；如跑全套测试，再复制现有 `docs/reports/map_eval/brake/verify_brake_final.json`。地图大资产继续引用 `configs/maps/rmuc2027.yaml` 中的 `E:/isaac/boom_birds_storage/assets/RMUC2027_IsaacSim`，不复制地图资产/venv。
3. 从工作树复制本轮正式 freeze/expected（或从最终提交恢复），设置 `PYTHONPATH=<export>/src`：
   - `python -c "import boom_birds..."`；
   - 验证 `validate_migration_freeze(freeze, parameters, root)`；
   - `pytest -q`。
4. GUI 正式运行按报告命令，需 Isaac 环境、前台窗口、DirectX/D3D12；不得 headless。导出纯软件检查通过，已由正式 GUI 16 集覆盖运行风险，未额外重复 GUI。

已验证：独立 worktree 冻结校验 PASS、import PASS、774 passed（复制本地配置/brake evidence）。未复制大资产或 venv。

## 5. 仍未解决 / 仅规避 / 口径变化

### 仍未解决
- 阳性覆盖仅 C/D 4 案例、单环境、单障碍尺寸/速度；未覆盖 E 类或其他动态情形。
- SUPERVISOR 无接触阳性，不能宣称监督器接触能力。
- 原生 event/impulse、负接触覆盖未建立；零读数仍 UNKNOWN；实机/多环境训练/真实感知/PX4 未验证。
- teleport/显式 reset 后的陈旧力仍是已知限制；正式评价只允许 episode 边界 reset。
- 旧两个 CONTACT_INFERRED 保持历史物理真值未确认，本轮未重跑。

### 仅规避/诊断保护
- 传送后陈旧数据未做底层清缓存；不填零、不把几何过滤称为修复。
- 导出时两个 brake 测试对本地证据文件行尾敏感，需复制本地既有证据；不是新模式缺陷。
- 预冻结/核验工具行尾规范化是交付修复，不改变物理行为。

### 验收口径变化
- 正式阳性矩阵只接受 linefix 冻结后的 16 集；pre-linefix 16 集退为 pilot，不混入配对。
- 来源 hash 以规范化 LF 文本计算（`1ebbcbe`），旧 raw-hash freeze 保留为历史；旧 20 场景结论不被改写。
- 默认仍 opt-in；单环境评价升级建议另行评审，实机/多环境不作为本轮无限期前置。

## 6. 文件/证据

- 报告：`docs/reports/map_eval/contact_envelope/DSH_FREE_FLIGHT_POSITIVE_20261103.md`
- 代码：`d708acb`、`1ebbcbe`（中文提交，未推送）
- freeze/expected：`configs/scenarios/contact_positive_validation_linefix_v2.json`、`...linefix_expected_v1.json`
- 核验：`dsh_contact_positive_validation_verify_20261103.json`、`...linefix_repeat1_migration_verify.json`、`...repeat2...`、`...linefix_raw_audit.json`
- 版本化证据：`docs/reports/map_eval/contact_envelope/evidence_20261103_positive/`（positive_metrics、两重复 summary/manifest/episodes、GUI 图像、hashes.json）
- 运行原始目录：`outputs/map_eval/production_contact_migration_positive/repeat1`、`repeat2`（steps 巨大，已 gitignore；hash 归档）
- 运行日志：`logs/dsh_positive_linefix_repeat1.log`、`...repeat2.log`、`logs/dsh_linefix_failing_tests.log`、`logs/dsh_positive_pilot.log`
