# 单环境动态评价新模式的默认升级评审与验证（2026-11-03）

> **状态：** PASS（单环境软件评价链）；默认升级已实施并完成最小等价验证；不提升任何 Gate。
> **证据域：** Isaac Sim 5.1 前台可视 GUI（DirectX/D3D12，无 headless）、单环境、预冻结；4 个等价 episode（2 案例 ×2 方法 × 默认/显式两种配置）。
> **最后核对：** 2026-11-03T19:40+08:00

## 1. 评审结论

**通过**：将 `scripts/run_dynamic_eval.py` 单环境评价的默认组合升级为：

```text
--geometry-policy reference_origin_v2
--contact-mode measured_hard_reset
```

历史复现必须显式传：

```text
--geometry-policy legacy --contact-mode legacy_inference
```

本轮没有自动切换到 legacy；旧冻结或旧默认参数不会被静默重新解释。默认只影响该单环境评价入口，不影响训练、多环境、官方 smoke 或其他脚本。

## 2. 逐项评审

| 项目 | 结论与证据 |
| --- | --- |
| 单环境限制 | `QuadcopterEnvCfg.scene` 固定 `num_envs=1`；运行时调用 `require_single_env()`，否则抛 `single-env only`；manifest 写 `single_env_only: true`。不提供多环境 fallback。 |
| 每集完整 reset | measured 模式每集 `env.sim.reset(soft=False)`、`physics_generation += 1`、`boundary.start`、机器人/障碍重置、executor/epoch 重置、delay wrapper 清空、新建 filtered sensor；每集有 1 次 1e-6 N 有界零握手。等价运行 generation 均为 1–4，握手 4/4 成功。 |
| 接触/几何/UNKNOWN 分层 | 原始 filtered force（含低于 0.02 N 的真实接触）、0.02 N 派生阈值、geometry overlap、UNKNOWN、业务 ABORT/COLLISION 分别记录；零读数保持 UNKNOWN。等价运行 A 类 2 集 `SUCCESS/UNKNOWN`；C 类 FOLLOW_ONLY `COLLISION/CONTACT_MEASURED/0.013053 N`，C 类 SUPERVISOR `ABORT/MAX_WAIT_EXCEEDED/UNKNOWN`。 |
| 旧冻结 | migration freeze v2（canonical-text）与 v1（raw-byte）显式区分；新默认遇 v1/旧 boundary/latency 冻结在 AppLauncher 前拒绝，并提示 `--geometry-policy legacy --contact-mode legacy_inference`；不自动回退。`logs/dsh_old_freeze_reject.log` 记录旧 v1 freeze 在默认下 exit 1。 |
| 旧视觉 bbox / max(size)/2 | 新默认只走真实 CollisionAPI 网格 + root-frame 参考原点球 + 障碍 cuboid 半对角线；旧公式仅在显式 legacy 路径保留。新旧混合 geometry/contact 组合被拒绝（`mixed ... not supported`）。 |
| 运行结束释放 | runner 在所有路径 `finally: env.close()`、`finally: app.close()`；本轮两次等价运行结束后无残留 python/Isaac 进程。 |
| 失败/Kit exit 0 | 新增 `run.complete.json`（只有成功写出 summary/episodes/steps 后才生成，含 status/completed/error=false）；异常路径写 `summary.error.txt`，不生成 completion marker。独立核验同时检查 completion marker、error 文件缺失、summary 状态和 outputs hash；不把 Kit exit 0 当完成。precheck 失败目录保留 `summary.error.txt`，无 marker。 |

## 3. LF/CRLF 冻结修复审查（1ebbcbe + 本轮）

- freeze schema 已从 v1 升为 **v2**；v2 顶层记录：
  - `hash_algorithm: {name: sha256, text_canonicalization: crlf_to_lf_v1, scope: declared_text_source_and_config_only, binary_assets: raw_sha256_not_in_freeze}`
  - `effective_config`（实际生效 geometry/contact）
  - `argument_sources`（`default` 或 `explicit`）
- 只对 `.py` 源码和声明的 YAML/JSON 配置 `_hash` 做 CRLF→LF；不做 strip、空白压缩、忽略行或内容归一化；轨迹/地图资产、PNG、USD、权重不在 freeze 源 hash 中，manifest 的 terrain/preview 等继续 raw sha256。
- 有效内容修改仍拒绝：现有源码/配置/参数变更测试 + 新增“行尾空白修改仍拒绝”测试通过。
- v1 raw-hash freeze 使用原始字节校验；v1 在默认新模式下被拒绝；只有显式 legacy 参数才可进入 old freeze 路径。**旧 freeze 不会被按新算法悄悄解释。**
- 本轮先新增失败测试再实现：`test_dynamic_eval_policy.py` 8 项（新默认、显式 legacy、混合拒绝、单环境、v1/v2 freeze 规则）；`test_dynamic_migration_plan.py` 10 项（v2 hash 算法/effective/sources、v1 raw、内容/参数/配置篡改）；全套最终 **786 passed**。

## 4. 实施与兼容迁移

- `--geometry-policy`/`--contact-mode` 默认值改为 `None` 后由 `dynamic_eval_policy.resolve_modes` 解析为 measured/reference-origin；显式 legacy 必须同时存在。
- 旧 freeze 提前在 AppLauncher 启动前校验，避免 AppLauncher 对 args 的注入污染参数 hash（`d332e0e`）。
- 新 freeze 记录实际生效配置与显式/默认来源；默认运行 freeze 与显式运行 freeze 分别记录各自的 `argument_sources`，等价验证不混用。
- `--help` 已输出默认说明：
  - geometry：`default: reference_origin_v2; use legacy only for historical reproduction`
  - contact：`default: measured_hard_reset; use legacy_inference only for historical reproduction`
- AGENTS/README/项目计划加入兼容入口说明（见 §11）；历史报告和命令保持原样，只加新默认/legacy 提示，不改历史事实。
- 默认升级只改 `run_dynamic_eval.py` 及其 policy/freeze 支持，不扩散到训练/多环境/官方 smoke/其他入口。

## 5. 预冻结与最小等价验证

- 预冻结（代码 commit `fc82d5a`，运行前生成）：
  - default freeze `configs/scenarios/dynamic_default_equivalence_default_v3.json` sha256 `2b261d4e…`
  - explicit freeze `..._explicit_v3.json` sha256 `6cc19557…`
  - expected `..._expected_v3.json` sha256 `1f55a5a7…`
  - 两个 freeze 均记录源码 hash、config hash、effective_config、argument_sources、Git HEAD、真实 UTC 时间。
- 运行配置：`dynamic_A_south_0`（正常完成）与 `dynamic_C_south_0`（FOLLOW_ONLY 已有真实 filtered 接触）；方法 FOLLOW_ONLY/SUPERVISOR；地图/车辆/控制/测量/阈值/TTL/所有权均相同。
- GUI：前台 Isaac Sim、DirectX/D3D12、串行；default 开始 `19:29:28`，explicit 开始 `19:33:57`（+08:00）；每次 4 episode，共 8 个正式 episode；均生成非空 `run.complete.json`，无 `summary.error.txt`。

| 方法/案例 | 默认（不传参数） | 显式新模式 | 一致 |
| --- | --- | --- | --- |
| A_south_0 FOLLOW_ONLY | SUCCESS/ROUTE_COMPLETE/UNKNOWN | 同左 | 是 |
| A_south_0 SUPERVISOR | SUCCESS/ROUTE_COMPLETE/UNKNOWN | 同左 | 是 |
| C_south_0 FOLLOW_ONLY | COLLISION/OBSTACLE_CONTACT/CONTACT_MEASURED/0.013053 N | 同左 | 是 |
| C_south_0 SUPERVISOR | ABORT/MAX_WAIT_EXCEEDED/UNKNOWN | 同左 | 是 |

- 实际生效配置一致（均 `reference_origin_v2` + `measured_hard_reset`；manifest 分别记录 `argument_sources=default/explicit`）；业务/物理/generation/握手/边界一致；`duration_s`、`wait_total_s`、逐步 position/velocity/time 最大差均为 **0.0**。没有为一致修阈值或删失败。
- 独立等价核验 `scripts/verify_dynamic_default_equivalence.py`：**PASS，52 checks**，0 failures，trajectory max diff 0.0；检查 freeze/expected/source/config、GUI、completion/error、effective config、4 集配对、原始 filtered 重算、接触对象、generation/握手、时间/轨迹。
- 迁移核验 default/explicit 各 PASS（3,050 行、4 集）；原始向量审计 PASS（6,100 行、0 errors）。

## 6. 测试、审计与恢复

- 全套 `pytest -q`：**786 passed**。
- 文档审计：`scripts/planning/audit_documents.py` PASS。
- 本工作包 diff check：staged/committed work package PASS（使用 `core.whitespace=cr-at-eol` 处理声明的 CRLF freeze 文件；不把未提交用户文件混入）。
- 独立导出恢复（worktree commit `fc82d5a`，`core.autocrlf=false`）：
  - 本地小配置 `configs/maps/rmuc2027.local.yaml` + 既有 `docs/reports/map_eval/brake/verify_brake_final.json`；地图大资产继续引用现有 `E:/isaac/boom_birds_storage/assets/RMUC2027_IsaacSim`，不复制地图/venv；
  - default/explicit v3 freeze **校验 PASS**；
  - 模块导入 PASS；
  - `pytest -q` **786 passed**。
- 正式运行源码 commit 为 `fc82d5a`；最终交付 commit 在其后只增加 freeze/expected/核验/报告/证据（以及兼容文档），不再改运行逻辑；报告与 hash 记录该关系。

## 7. 交付与默认状态

- 单环境评价默认已升级，legacy 显式入口保留；旧 freeze 不自动兼容。
- **没有**将默认推广到训练、多环境或其他脚本；没有改共享控制/接触/reset/失效逻辑，因此没有重复 20+16 历史运行；等价验证只比较默认解析与显式新模式。
- 旧 20 场景、16 个阳性 episode 的结论保持；旧 CONTACT_INFERRED 保持历史物理真值未确认；旧报告/命令未重写。

## 8. 适用边界

- 单环境、单障碍尺寸/速度、当前自由飞行 C/D 4 案例与 A 类代表案例；未证明全姿态/全地图/多障碍复杂场景。
- 原生 event/impulse、负接触覆盖未建立；零读数仍 UNKNOWN，不能升级为无接触保证；实机/多环境训练/真实感知/PX4/SITL/HIL 未验证。
- 传送后陈旧力仍是已知限制；正式评价只允许 episode 边界声明 reset，未声称底层 PhysX 已修复。
- 规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK；未提升 Gate。

## 9. 真正阻断后续架构工作的事项

- 本轮默认升级没有新的单环境评价阻断项；剩余真实阻断在后续架构：真实感知/定位、PX4 Sender/固件、板端 Student、多环境训练与实机安全链，均不在本轮范围。
- 单环境软件评价链可作为后续 V2.2 主路线输入，但不得外推为实机/Gate 通过。

## 10. 精确命令

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
$cases = 'dynamic_A_south_0,dynamic_C_south_0'
$common = @('--cases','configs/scenarios/map_dynamic_cases_v1.json','--only-cases',$cases,'--methods','follow_only,supervisor','--execution-path','v2','--screenshots','--device','cuda:0','--gpu-driver','NVIDIA 581.80 (observed)','--kit_args=--/app/vulkan=false','--code-commit','fc82d5a3dd261f4306cc6671c318b697dc3b86e0','--working-tree','default-upgrade code commit fc82d5a')
# 默认（不传 geometry/contact）
& $py -u scripts/run_dynamic_eval.py @common --freeze configs/scenarios/dynamic_default_equivalence_default_v3.json --output outputs/map_eval/dynamic_default_equivalence/default
# 显式新模式
& $py -u scripts/run_dynamic_eval.py @common --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --freeze configs/scenarios/dynamic_default_equivalence_explicit_v3.json --output outputs/map_eval/dynamic_default_equivalence/explicit
# 独立等价核验
& $py scripts/verify_dynamic_default_equivalence.py --root outputs/map_eval/dynamic_default_equivalence --default-freeze configs/scenarios/dynamic_default_equivalence_default_v3.json --explicit-freeze configs/scenarios/dynamic_default_equivalence_explicit_v3.json --expected configs/scenarios/dynamic_default_equivalence_expected_v3.json --repo-root . --output docs/reports/map_eval/contact_envelope/dsh_dynamic_default_equivalence_verify_20261103.json
& $py -m pytest -q
& $py scripts/planning/audit_documents.py
```

## 11. 文档兼容入口

- `--help` 已说明新默认和 legacy 提示。
- AGENTS/README/PROJECT_PLAN 增加 2026-11-03 默认升级/legacy 兼容说明；历史报告保持原样。
- 新计划/报告：本文件、`docs/superpowers/plans/2026-11-03-dynamic-default-upgrade.md`、交接 `docs/reports/HANDOFF_20261103_DSH_DYNAMIC_DEFAULT_UPGRADE.md`。
- 正式 freeze/expected、核验 JSON、证据与 hash 见交接和 `evidence_20261103_default_upgrade/`。
