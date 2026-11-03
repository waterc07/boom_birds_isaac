# 交接：单环境动态评价默认升级、兼容迁移与验证（2026-11-03）

## 状态

- **评审通过并实施**：`scripts/run_dynamic_eval.py` 单环境评价默认 = `--geometry-policy reference_origin_v2` + `--contact-mode measured_hard_reset`。
- **历史复现入口保留**：显式 `--geometry-policy legacy --contact-mode legacy_inference`；旧 freeze 不自动回退。
- **最小等价验证 PASS**：2 案例 ×2 方法 × 默认/显式 = **8 个 GUI 预冻结 episode**；default/explicit 实际配置、业务、接触、generation、握手、边界、时间/轨迹一致（trajectory diff 0.0）。
- **独立核验 PASS**：等价核验 52 checks；迁移 2×3,050 行；raw 6,100 行 0 errors；`pytest -q` **786 passed**；文档审计 PASS；独立导出恢复 786 passed、freeze 校验 PASS。
- 默认升级仅影响该单环境评价入口；未改训练/多环境/官方 smoke/其他脚本；未提升 Gate。

## 1. 代码提交

| commit | 内容 |
| --- | --- |
| `8ae45d8` | 默认升级 + policy 兼容、freeze v2（hash algorithm/effective config/sources）、失败测试、completion marker |
| `d332e0e` | 冻结校验移到 AppLauncher 启动前，避免 args 注入污染；v1/v2 兼容 |
| `fc82d5a` | 拒绝 legacy/new 混合策略；正式等价运行源码 commit |
| 最终交付（本轮后续） | freeze/expected、核验器、报告、证据、AGENTS/README/PROJECT_PLAN 兼容说明 |

正式运行源码 commit `fc82d5a`；最终 commit 只增加文档/证据/freeze，不改变运行逻辑（报告中记录）。

主要实现文件：

- `scripts/run_dynamic_eval.py`（默认解析、单环境校验、v1/v2 freeze 分支、completion marker）
- `src/boom_birds/evaluation/dynamic_eval_policy.py`（默认/legacy、混合拒绝、单环境、freeze schema 策略）
- `src/boom_birds/evaluation/dynamic_migration_plan.py`（freeze v2 hash 算法、effective config/sources、v1 raw 校验）
- `tests/evaluation/test_dynamic_eval_policy.py`、`tests/evaluation/test_dynamic_migration_plan.py`
- `scripts/verify_dynamic_default_equivalence.py`（本轮新增独立核验）
- `scripts/verify_dynamic_migration.py`、`scripts/verify_contact_raw_samples.py`（复用）

未提交：用户/其他任务修改；未执行 `git add .`，未推送。

## 2. 正式 freeze 与运行

- default freeze：`configs/scenarios/dynamic_default_equivalence_default_v3.json`，sha256 `2b261d4e67ddce3e2c1777f6a38c317ca16e70dc26d62a2390227f3ac2718bf1`
- explicit freeze：`configs/scenarios/dynamic_default_equivalence_explicit_v3.json`，sha256 `6cc1955784b787f5776733943cc107946f8fe762497d7d69942dbc935b697af9`
- expected：`configs/scenarios/dynamic_default_equivalence_expected_v3.json`，sha256 `1f55a5a72a454e6ba683d21e7f65876756d227ca5421000494210ef382a3093a`
- 案例：`dynamic_A_south_0`（正常完成）+ `dynamic_C_south_0`（FOLLOW_ONLY 真实 filtered 接触）；方法 FOLLOW_ONLY/SUPERVISOR；各 4 episode，共 8。
- 目录：`outputs/map_eval/dynamic_default_equivalence/default`、`explicit`；default 开始 `19:29:28`，explicit 开始 `19:33:57`（+08:00）；前台 GUI/DirectX/D3D12。
- 结果：A 两方法 SUCCESS/ROUTE_COMPLETE/UNKNOWN；C FOLLOW_ONLY COLLISION/OBSTACLE_CONTACT/CONTACT_MEASURED/0.013053 N；C SUPERVISOR ABORT/MAX_WAIT_EXCEEDED/UNKNOWN；两种配置逐项一致。
- 每 run 4 集、generation 1–4、4/4 分离零握手；`run.complete.json` 存在且 status PASS，`summary.error.txt` 不存在。

## 3. 评审结论摘要

- 单环境：运行时 `require_single_env` + `single_env_only` manifest；不提供多环境 fallback。
- reset：完整物理 reset、epoch/队列/延迟 wrapper 清理、有界握手；等价运行已验证。
- 接触：filtered 原始力、0.02 N 派生阈值、几何 overlap、UNKNOWN、业务 ABORT/COLLISION 分层；零读数仍 UNKNOWN。
- 旧 freeze：v1 raw 只有显式 legacy 可进入；新默认遇旧 freeze 在 AppLauncher 前拒绝（`logs/dsh_old_freeze_reject.log`）。
- 旧 bbox / max(size)/2：仅 legacy 显式路径；新默认只走真实 CollisionAPI/root-frame/半对角线；混合策略被拒绝。
- 进程释放：finally env.close/app.close；本轮结束无残留进程。
- Kit exit 0：新增 completion marker + error 文件 + 独立核验；不单靠 exit code。
- LF/CRLF：v2 记录 hash 算法/范围；仅文本源码/配置 CRLF→LF；二进制不进 freeze；不 strip；内容篡改仍拒绝；v1 不被新算法解释。

## 4. 验证

- `scripts/verify_dynamic_default_equivalence.py` → `docs/reports/map_eval/contact_envelope/dsh_dynamic_default_equivalence_verify_20261103.json`：PASS 52 checks，0 failures，trajectory 0.0。
- 迁移核验 default/explicit：PASS，各 3,050 行/4 集。
- 原始向量审计：PASS 6,100 行，0 errors。
- 全套 pytest：786 passed。
- 文档审计：PASS。
- 独立导出（commit `fc82d5a`，`core.autocrlf=false`，本地 `rmuc2027.local.yaml` + 既有 brake evidence）：
  - default/explicit freeze 校验 PASS；
  - 导入 PASS；
  - `pytest -q` 786 passed；
  - 地图资产继续引用现有本地路径，不复制大资产/venv。

## 5. 适用边界 / 保留限制

- 默认升级只覆盖单环境动态评价；训练、多环境、官方 smoke 和其他脚本不变。
- 已验证的等价案例只有 A_south_0/C_south_0；全地图/全姿态/多障碍、更多 case 仍未覆盖。
- 原生 event/impulse、负接触覆盖未建立；零读数不能当无接触保证；实机/多环境训练/真实感知/PX4/SITL/HIL 未验证。
- 传送后陈旧力保留已知限制；正式评价只允许 episode 边界 reset，不声称底层 PhysX 修复。
- 旧 20 场景、16 阳性 episode 结论不改写；旧 CONTACT_INFERRED 保持历史物理真值未确认。
- 规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK；未提升 Gate。

## 6. 文档兼容说明

- `--help` 已显示新默认和 legacy 提示。
- AGENTS/README/PROJECT_PLAN 已加入 2026-11-03 默认升级/legacy 兼容说明（工作树中的用户既有修改保留；仅可分离的任务说明进入提交）。
- 历史报告/命令保持原样；新默认入口只在本轮报告/计划/交接中声明。
- 新计划：`docs/superpowers/plans/2026-11-03-dynamic-default-upgrade.md`。

## 7. 下一项推进 V2.2 主路线的工作

单环境软件评价链已闭合（默认升级、兼容、等价验证、可复现）。下一步应停止继续拆分接触诊断，转向 V2.2 主路线中的 **传统控制/延迟/失效链在更多动态场景下的封闭**：用已升级默认入口做少量（不扩大正式样本）的 C/D/E 场景回归与异常注入，验证默认路径在观测延迟、执行器拒绝、ABORT/超时下的分层语义；随后再进入感知/定位或 PX4 Sender 前置工作。

## 8. 证据/文件

- 报告：`docs/reports/map_eval/contact_envelope/DSH_DYNAMIC_DEFAULT_UPGRADE_20261103.md`
- 核验：`dsh_dynamic_default_equivalence_verify_20261103.json`、`...default/explicit_migration_verify_...`、`...raw_audit_...`
- 版本化证据：`docs/reports/map_eval/contact_envelope/evidence_20261103_default_upgrade/`（含 summary/manifest/episodes、GUI 截图、precheck 失败、hashes.json）
- 运行原始：`outputs/map_eval/dynamic_default_equivalence/`（gitignored steps；hash 归档）
- 旧 freeze/旧证据保持不变。
