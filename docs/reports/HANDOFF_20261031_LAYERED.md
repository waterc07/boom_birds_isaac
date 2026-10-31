# 交接记录：分层场景与五类自然场景评价（2026-10-31）

> 接续 HANDOFF_20261031_GUIDANCE.md；以文件与 git 现场为准。

## 1. 分支与提交

- 工作区 E:\isaac\proj_boom_birds；分支 `codex/bb22-layered-eval`（自 `87d2a7e`）；未推送远端。
- 本工作包提交：
  - `9924d32` feat: 分层场景合同、五类场景、PhysX 接触证据、观测退化、物理扰动、v2 评价、run_sim_baseline --task layered、场景/冻结工具、回归测试。
  - `8e87ee0` fix: 动态实体远端停放、独立核验脚本 verify_layered_runs.py。
  - 待提交 docs：本交接、评价报告、debug 证据、计划状态。
- 前序工作包见 HANDOFF_20261031.md / HANDOFF_20261031_GUIDANCE.md。

## 2. 最终结果（冻结后，125 valid episode，每类 25，0 invalid）

| 类 | 成功 | 碰撞 | 超时 | 越界 | 成功率（Wilson 95%） |
| --- | --- | --- | --- | --- | --- |
| A 无障碍 | 25/25 | 0 | 0 | 0 | 1.00 [0.867,1.0] |
| B 静态障碍 | 0/25 | 25（25/25 PhysX 接触） | 0 | 0 | 0.00 [0.000,0.133] |
| C 动态实体 | 24/25 | 0 | 0 | 1 | 0.96 [0.805,0.993] |
| D 观测退化 | 25/25 | 0 | 0 | 0 | 1.00 [0.867,1.0]（248 步无效输入） |
| E 物理扰动 | 3/25 | 0 | 3 | 19 | 0.12 [0.042,0.300] |

- 状态 PASS 仅指本仿真评价扩展与证据完整性；不是 BB22:G4 放行，不提升任何 Gate。
- 总体混合采样：success 77/125，collision 25，timeout 3，out_of_bounds 20；仅代表该采样混合。
- 独立核验 24 项 PASS（配额/统计/接触/退化/扰动时序/实体运动/冻结与 hash）。

## 3. 复现命令

`powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -m pytest -q
& $py scripts/planning/audit_documents.py
# 场景与冻结（固定种子与时间戳，可复现同一 hash）
& $py scripts/make_layered_scenarios.py --per-class 25 --base-seed 6000 --generated-at '2026-10-31T18:00:00+08:00' --output configs/scenarios/layered_final_20261031.json
& $py scripts/make_layered_freeze.py --config configs/vehicles/sim_reference.yaml --manifest configs/scenarios/layered_final_20261031.json --output configs/scenarios/layered_freeze_20261031.json --frozen-at '2026-10-31T18:30:00+08:00' --timeout-s 12
# 最终评价（入口会校验 freeze）
& $py -u scripts/run_sim_baseline.py --task layered --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --classes all --methods proportional --timeout-s 12 --freeze configs/scenarios/layered_freeze_20261031.json --require-coverage --min-valid-per-class 20 --min-valid-total 100 --code-commit 8e87ee05bde84491462d081aa4b8ccdb78807c13 --headless --device cuda:0 --clone-in-usd --output outputs/layered_eval/final_run2
# 独立核验
& $py scripts/verify_layered_runs.py --run-dir outputs/layered_eval/final_run2 --freeze configs/scenarios/layered_freeze_20261031.json --output docs/reports/layered_eval/verify_final.json
`

## 4. 验证层级

| 层 | 状态 |
| --- | --- |
| 单元测试 | 223 passed，exit 0（含分层/退化/扰动/接触/评价 v2） |
| 项目动力学仿真 | 125 episode 冻结集 + 15 episode debug；仿真模型 + ORACLE |
| 训练 / 板端 / SITL/HIL / 实机 | NOT RUN |

## 5. 未解决问题

1. E 类扰动下出现 19/25 越界，说明当前比例制导+外环在 0.004–0.012 N、0.2–0.5 s 扰动下会失去跟踪；需后续定位控制根因，不得改阈值或删失败。
2. B 类 0% 成功是能力边界，不是评价缺陷；不应通过临时加规划器"修复"本轮结果。
3. 场景为 ORACLE 观测与简化刚体模型；D 类仅接口退化，不能称真实感知验证。
4. 125 episode 仅为本工作包下限，不满足 V2.2 §20.11 正式冻结要求。
5. 规则原文、BOM、PX4 固件/参数仍 UNKNOWN/RULE-CHECK。
6. AGENTS/PROJECT_PLAN/README 的本地状态同步仍未提交（保留用户修改）。

## 6. 下一工作包

1. E 类失败的控制层根因分析与可复现最小案例（同一场景回放），区分外环饱和、姿态回路与扰动包络。
2. 扩样本至正式规模并增加障碍布局/动态实体时序/退化强度场景族与重复 seed。
3. 传统基线 vs PPO 同条件对比（前置 BB22:G4 + G2.5）。
