# DSH 新接触/几何模式：20 个动态场景预冻结回归 — 2026-11-02

> **状态：** PASS（20/20 动态场景、SUPERVISOR、新模式单环境评价；不提升 Gate，不替换 legacy 默认）
> **证据域：** Isaac Sim 5.1 前台可视 GUI（DirectX/D3D12，无 headless）、单环境、预冻结运行；不是实机/多环境训练证据
> **基线线索：** 交接中的 772 tests、4 集 GUI 结果仅作线索；本轮重新执行 20 集预冻结回归与独立核验后才写本结论
> **最后核对：** 2026-11-03 凌晨（Asia/Shanghai）

## 1. 结论

- 原 20 个动态场景（`map_dynamic_cases_v1.json` 全部 case，A/B/C/D/E 各 4 集）以新模式 `--geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --methods supervisor --execution-path v2` 完成 **20/20 episode**；无场景删除、无阈值改动、无 `INVALID`，分母完整。
- 业务结果：**SUCCESS 8 / ABORT 12 / COLLISION 0 / TIMEOUT 0 / OUT_OF_BOUNDS 0 / INVALID 0**；原因：`ROUTE_COMPLETE` 8、`MAX_WAIT_EXCEEDED` 8、`OBSERVATION_STALE` 4。与旧 v2 supervisor 逐场景比较 **业务 outcome/reason 差异 0**；`duration_s`、`wait_total_s` 最大差均为 0（确定性一致），没有通过删场景/改阈值制造一致。
- 物理证据：20 集全部 **UNKNOWN**（未测得 filtered 正力），没有把零读数改写成 `NO_CONTACT`，也没有 `CONTACT_INFERRED`/`CONTACT_MEASURED` 伪标签；旧 v2 supervisor 的 `contact_max_force_n` 也均为 0。即本矩阵的 20 个 SUPERVISOR 轨迹在 abort/route-complete 前没有进入可测接触，不能据此声称新测力通道在这些场景“验证了接触”。接触通道的正向能力由独立受控接触结束专项（`DSH_CONTACT_END_FRESHNESS_20261102.md`，0.0125–0.0127 N 低幅实测）单独支持。
- 初始化：20 集完整物理 reset，generation 依次 **1–20**；每集分离握手均成功且原始测力为零（1e-6 N 容差）；正式 RUN 未再执行完整 reset。
- 独立核验：20 场景核验 **PASS（27 checks）**；迁移记录核验 **PASS（13,149 行）**；原始向量审计 **PASS（13,149 行，0 errors）**；全套 `pytest -q` **772 passed**；文档审计 **PASS**。
- **是否可升级默认：本轮不具备升级默认的证据**。全 20 集物理接触为 UNKNOWN、无原生 event/impulse、仅单环境 reset、覆盖与实机噪声未标定；继续保留 legacy 默认，新模式为显式 opt-in 评价路径。

## 2. 预冻结与执行

- 预期参考：`configs/scenarios/contact_production_migration_20_expected_v1.json`（sha256 `f3502baa…`），记录旧 v2 supervisor 每 case 的 outcome/reason 哈希、可接受业务结果集与物理结果集，并声明“比较不强制相等、不得删场景/改阈值”。
- 正式预冻结：`configs/scenarios/contact_production_migration_20_v2.json`（sha256 `049d7a6c…`，`frozen_at 2026-11-02T15:37:31Z`），包含：
  - `source_hashes`：50 个 `src/**/*.py` + `scripts/run_dynamic_eval.py` 的真实 sha256；
  - `config_hashes`：cases / map / vehicle / local / brake model；
  - `parameters`：cases、methods=supervisor、execution v2、geometry/contact policy、stop distance 1.1、delay/clock/fault 参数、reset 相关模式等；
  - `expected_reference`：上述 expected 文件 hash、旧 v2 episodes/manifest hash；
  - 真实 Git HEAD 与 `frozen_at`（早于运行开始 `2026-11-02T23:41:36+08:00`）。
- 冻结生成说明：先由生产 runner 的 `--write-migration-freeze` 生成 v1（`contact_production_migration_20_v1.json`，PASS 的 pilot 预冻结），再在**运行前**派生 v2，仅新增 `expected_reference` 元数据，不重写基础 schema、不改时间。v1 pilot 运行在发现“冻结未含预期参考”后停止，输出移到 `outputs/map_eval/production_contact_migration/regression20_pilot_v1`，**不作为验收结果**；正式结果只来自 v2 冻结后的运行。旧 v3 冻结、旧 v2 supervisor 结果与旧 final3 结果均保留未改。
- 运行目录：`outputs/map_eval/production_contact_migration/regression20`；前台 GUI、DirectX/D3D12、cuda:0；逐集串行；运行用时约 17.6 min。
- GUI 证据：运行目录 `screenshots/` 含 8 张成功集截图（均 >700 KB、有效 PNG；A/B 各 4 集）；版本化代表图 `evidence_20261103/regression20_success_A_south_0.png`。

## 3. 逐场景/分组结果

| 场景组 | 集数 | 新业务结果 | 原因 | 新物理结果 | 旧 v2 supervisor | 与旧差异 |
| --- | --- | --- | --- | --- | --- | --- |
| A（南/北 ×2） | 4 | SUCCESS | ROUTE_COMPLETE | UNKNOWN | SUCCESS, 0 力 | 无 |
| B（南/北 ×2） | 4 | SUCCESS | ROUTE_COMPLETE | UNKNOWN | SUCCESS, 0 力 | 无 |
| C（南/北 ×2） | 4 | ABORT | MAX_WAIT_EXCEEDED | UNKNOWN | ABORT, 0 力 | 无 |
| D（南/北 ×2） | 4 | ABORT | MAX_WAIT_EXCEEDED | UNKNOWN | ABORT, 0 力 | 无 |
| E（南/北 ×2） | 4 | ABORT | OBSERVATION_STALE | UNKNOWN | ABORT, 0 力 | 无 |
| 合计 | 20 | 8 SUCCESS / 12 ABORT | — | 20 UNKNOWN | 8/12 | 0 |

- 旧/新逐集 `duration_s`、`wait_total_s` 最大差为 0；没有新的超时、越界、碰撞或基础设施错误。
- 全 20 集 `contact_max_force_n=0.0`、无 `contact_prim`；新模式未观测到 filtered 正力，因此没有“新实测接触 vs 旧几何推断”的差异样本。旧两例 `CONTACT_INFERRED` 历史案例**不在这 20 集内**，本轮未重跑、未改写其“物理真值未确认”状态。
- `FOLLOW_ONLY` 本轮未成组补跑：20 个 supervisor 的业务/原因/时长与旧 v2 完全一致且无接触实测差异，没有“实际受影响场景”需要配对；此前 final3 的 A/C FOLLOW_ONLY 4 集只作为交接线索，不作为本报告验收分母。

## 4. 几何与失效语义审查

| 项 | 新路径实际值/行为 | 审查结论 |
| --- | --- | --- |
| 机器人包络 | schema `boom_birds.body_envelope.v2`；coverage=`collision_geometry`，prim `/World/envs/env_0/Robot/body/body_collision/geometry`；half=`[0.0500000007, 0.0500000007, 0.0149999997]` m；center_offset=`[0,0,0]`；radius=`0.0722841624` m | 使用真实 CollisionAPI 网格、root-frame 中心偏移；不是视觉 bbox |
| 障碍包络 | 尺寸 `[0.4,0.4,0.6]` m，半径 `norm(size/2)=0.4123105626` m，两球和 `0.4845947250` m | cuboid 半对角线；不是旧 `max(size)/2` |
| clearance | 所有 RUN 行 schema `boom_birds.clearance.v2`；13,149 行中 12,989 行有观测中心，逐行核对 `center_distance_m` 与 decision-time 输入一致；160 行 `OBSERVATION_DROPOUT` 的 metrics 为 `None`，保持 UNKNOWN/不适用 | 新公式只在 v2；旧 max/2 与视觉 bbox 仅 legacy 历史 |
| 停止阈值/控制器 | `stop_distance_m=1.1` 未改；velocity executor/supervisor/v2 gate/TTL/所有权未改 | 只测量，不顺带调参 |
| 失效分类 | 业务 `SUCCESS/ABORT`；物理 `UNKNOWN`；`INVALID=0`；`COLLISION/TIMEOUT/OUT_OF_BOUNDS=0`；零读数未改为无接触；E 的观察 dropout 保留在 20 分母 | 分类分开，未知不移出分母 |
| reset 范围 | 每集开始完整物理 reset + 分离零握手；RUN 内无硬 reset；generation 1–20 | 仅单环境评价；不推广多环境训练 |

## 5. 独立核验（从原始向量/状态重算）

1. **20 场景核验**：`scripts/verify_dynamic_regression20.py`，输出 `dsh_dynamic_regression20_verify_20261102.json`，**PASS，27 checks**，0 differences、0 expected failures。覆盖冻结/hash/源码/参数早于运行、GUI 非 headless、20 集身份/分母、20 次 generation+握手、原始 filtered/net 重算、物理结果映射、body/obstacle 半径与 clearance v2、旧 v2 逐场景比较、UNKNOWN 保留、截图有效 PNG。
2. **迁移记录核验**：`scripts/verify_dynamic_migration.py`，**PASS，13,149 行、20 集，0 failure**；覆盖产物 hash、源 hash、包络公式、每步 clearance/contact raw 一致性。
3. **原始向量审计**：`scripts/verify_contact_raw_samples.py`，**PASS，13,149 行、0 errors**；直接由原始 `net_vectors_n`/`filtered_by_target_n` 重算，校验缓存与 episode 最大值。该脚本本轮扩展了生产嵌套 `contact_evidence.measurement` 路径（此前只支持 DSH 生命周期顶层行），扩展后旧 final3 运行也复核 **PASS，3,050 行**。
4. 全套 `pytest -q`：**772 passed**（基线未减少）；包含 Codex/DSH 的 contact/migration/geometry 回归。
5. 文档审计：`python scripts/planning/audit_documents.py` **PASS**，`planning_audit.json` 前后 hash 未变（`ABB227D8…`）。
6. 核验工具自身修正（非生产行为变更）：
   - 首次 20 集核验把 `config_hashes` 的逻辑键当路径，`FileNotFoundError: cases`；修正为从 freeze parameters 解析真实配置路径。
   - 首次核验把局部变量 `expected` 覆盖成物理字符串；重命名后通过。
   - 首次几何核验把 160 行 observation-dropout 的非适用 clearance 当缺失而失败；改为只要求有观测中心的行，dropout 保持 UNKNOWN/非适用。修正的是核验口径，不是运行数据。
   - raw 审计扩展生产嵌套 measurement 路径；扩展前后数据未改。
   这些修正均有运行日志/失败 JSON 保留；没有为了让结果 PASS 放宽生产合同或删除场景。

## 6. 失败与限制

1. **物理证据仍为 UNKNOWN**：20 个 supervisor 轨迹均未测得 filtered 正力；不能声称这些场景接触已实测验证。接触通道的正向能力只在受控专项中出现（约 0.0126 N）；两者证据域不同。
2. **原生 event/impulse 未建立**：零事件仍不能证明无接触；负接触覆盖未验证。
3. **单环境**：完整物理 reset 只用于单环境评价，未验证多环境训练；每集重启成本与时间语义变化未推广。
4. **包络覆盖**：碰撞网格 AABB/球在固定关节状态测量；未证明螺旋桨扫掠、全姿态 mesh 精确覆盖或 PhysX 接触 offset 外扩。
5. **实机域缺失**：无真实感知/PX4/板端/SITL/HIL/实机；规则/BOM/PX4 保持原 UNKNOWN/RULE-CHECK；未提升 Gate。
6. **旧事实**：两个旧 `CONTACT_INFERRED` 案例不在本 20 集内，保持物理真值未确认；新模式不能改写旧事实。
7. **pilot 停止**：v1 冻结未含预期参考，运行被停止；正式 v2 预冻结后才执行。该失败保留在 `regression20_pilot_v1` 与日志中。

## 7. 精确命令

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 1) 预冻结 v1（基础身份；pilot）
& $py scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --methods supervisor --execution-path v2 --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --screenshots --device cuda:0 --gpu-driver 'NVIDIA 581.80 (observed)' --kit_args=--/app/vulkan=false --output outputs/map_eval/production_contact_migration/regression20 --write-migration-freeze configs/scenarios/contact_production_migration_20_v1.json
# 2) 运行前生成 expected_v1 + 派生 v2（仅新增 expected_reference，不改基础 schema/时间）
# 3) 正式运行（GUI，前台）
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --methods supervisor --execution-path v2 --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --screenshots --device cuda:0 --gpu-driver 'NVIDIA 581.80 (observed)' --kit_args=--/app/vulkan=false --freeze configs/scenarios/contact_production_migration_20_v2.json --output outputs/map_eval/production_contact_migration/regression20
# 4) 独立核验
& $py scripts/verify_dynamic_regression20.py --run outputs/map_eval/production_contact_migration/regression20 --freeze configs/scenarios/contact_production_migration_20_v2.json --expected configs/scenarios/contact_production_migration_20_expected_v1.json --old-run outputs/map_eval/final_v2_dynamic1 --repo-root . --output docs/reports/map_eval/contact_envelope/dsh_dynamic_regression20_verify_20261102.json
& $py scripts/verify_dynamic_migration.py --run outputs/map_eval/production_contact_migration/regression20 --freeze configs/scenarios/contact_production_migration_20_v2.json --output docs/reports/map_eval/contact_envelope/dsh_dynamic_regression20_migration_verify_20261102.json
& $py scripts/verify_contact_raw_samples.py --run outputs/map_eval/production_contact_migration/regression20 --output docs/reports/map_eval/contact_envelope/dsh_dynamic_regression20_raw_audit_20261102.json
& $py -m pytest -q
$py scripts/planning/audit_documents.py
```

## 8. 版本化摘要与 GUI

- 冻结：`configs/scenarios/contact_production_migration_20_v2.json`（`049d7a6c…`）；预期：`..._20_expected_v1.json`（`f3502baa…`）；旧 v3 冻结 sha `86335031…` 未改。
- 核验 JSON：`dsh_dynamic_regression20_verify_20261102.json`、`dsh_dynamic_regression20_migration_verify_20261102.json`、`dsh_dynamic_regression20_raw_audit_20261102.json`。
- 版本化证据：`evidence_20261103/regression20_summary.json`、`regression20_manifest.json`、`regression20_success_A_south_0.png`；完整 steps/episodes 位于忽略的 `outputs/.../regression20`，hash 见 `evidence_20261103/hashes.json` 与交接。
- GUI：8 张非空有效 PNG 成功集截图；代表图已人工查看为有效地图 viewport，非空图片/仅文件不作为可视运行唯一证据，运行日志另含前台 GUI 启动与关闭记录。

## 9. 是否具备升级默认条件

**否，暂不替换默认。** 具备：显式模式、预冻结、完整 20 集分母、独立核验、几何公式固定、无业务差异。尚缺：20 集内真实接触阳性样本、原生 event/impulse、负接触覆盖、实机噪声标定、多环境 reset 策略与更大场景族；这些是升级 default 的前置证据，当前只作为 opt-in 评价模式。
