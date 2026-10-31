# 交接记录：传统制导基线与故障/随机化（2026-10-31）

> 本文件接续 [HANDOFF_20261031.md](HANDOFF_20261031.md)，记录本轮工作包后的现场状态。以文件为准，不依赖聊天记忆。

## 1. 分支与提交

- 工作区 `E:\isaac\proj_boom_birds`；分支 `codex/bb22-guidance-baseline`（自 `53dc46c` 起）；未推送远端。
- 本工作包提交：
  - `007e2eb` feat: 制动型制导基线、随机化场景、故障注入、Wilson/分层/配对统计、compare 入口与冻结（最终比较所用源码）。
  - `f481698` fix: 故障汇总抽取为带测试的 helper；新增独立核验脚本。
  - `9c02dbd` fix: 故障运行状态引用修正（faults_run4 所用源码）。
  - 后续 docs 提交：本报告、本交接、计划状态与证据副本。
- 之前工作包提交见 HANDOFF_20261031.md（`c730c75/533708e/39a7812/86f0f2f/0fb76c3/38159ee/7e341bc/53dc46c`）。

## 2. 本轮结果

| 项 | 结果 |
| --- | --- |
| 调参集 | 8 场景 × 2 方法 × 2 候选；A/B 均 8/8 成功；按准则选 B（a=1.2, k_fb=0.4） |
| 最终配对比较 | 30 场景 × 2 方法 = 60 episode；双方 30/30 成功；Wilson 95% [0.886,1.0]（分母 30） |
| 到点时间 | proportional 平均 3.478 s，braking 3.597 s；配对 30/30 proportional 更快（平均 +0.118 s） |
| 最终误差 | proportional 0.027 m，braking 0.121 m（braking 差 0.094 m） |
| 专项故障 | 4 类 × 4 样本 = 16 episode，分类全部符合预期；PhysX 接触 4/4 观测，标志注入 0/4 接触 |
| 独立核验 | 最终/故障核验脚本均 PASS |
| 状态 | INCOMPLETE（30 场景 < PROPOSED 100；不是 G4 冻结） |

## 3. 复现命令

`powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -m pytest -q
& $py scripts/planning/audit_documents.py
# 场景与冻结（标准库；固定 --generated-at 可复现同一 hash）
& $py scripts/make_scenarios.py --count 8  --base-seed 1000 --generated-at '2026-10-31T17:30:00+08:00' --output configs/scenarios/tuning_20261031.json
& $py scripts/make_scenarios.py --count 30 --base-seed 2000 --generated-at '2026-10-31T17:30:00+08:00' --output configs/scenarios/final_20261031.json
# 最终比较（入口会校验 freeze 的 config/scenario/guidance/threshold 一致）
& $py -u scripts/run_sim_baseline.py --task compare --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/final_20261031.json --methods proportional,braking --run-kind final --timeout-s 20 --freeze configs/scenarios/freeze_20261031.json --code-commit 007e2ebf86bfd042864a3e68c6fab59317f35469 --headless --device cuda:0 --clone-in-usd --output outputs/guidance_compare/final_run1
# 专项故障（4 类）
& $py -u scripts/run_sim_baseline.py --task compare --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/final_20261031.json --methods proportional,braking --run-kind fault --fault collision_flag,collision_contact,timeout,invalid_observation --fault-step 10 --fault-timeout-s 1.5 --scenario-limit 2 --code-commit 9c02dbd97e9997d469e7c2186c1f640d9fc3b811 --headless --device cuda:0 --clone-in-usd --output outputs/guidance_compare/faults_run4
# 独立核验
& $py scripts/verify_guidance_runs.py --run-dir outputs/guidance_compare/final_run1 --output docs/reports/guidance_baseline/verify_final.json
& $py scripts/verify_guidance_runs.py --run-dir outputs/guidance_compare/faults_run4 --output docs/reports/guidance_baseline/verify_faults.json
`

## 4. 验证层级

| 层 | 状态 |
| --- | --- |
| 单元测试 | 175 passed，exit 0 |
| 文档审计 | 本轮收尾执行，结果见最终提交 |
| 项目动力学仿真 | 最终配对 60 episode + 故障 16 episode；仿真模型 + ORACLE |
| 训练 / 板端 / SITL / HIL / 实机 | NOT RUN |

## 5. 未解决问题

1. 规则原文、BOM 铭牌、PX4 固件/参数/validity 映射仍 UNKNOWN/RULE-CHECK。
2. 样本不足（30 场景）与分层不均衡（long/rear 较少）；无风扰/传感器退化随机化。
3. 新基线未优于比例法：可在更真实动力学/扰动下继续比较，但不得改阈值或删失败。
4. Isaac 入口异常可能显示 exit 0；以 error 文件与产物为准。
5. 用户 V2.2 文档与 AGENTS/PROJECT_PLAN/README 的本地状态同步仍保留未提交。

## 6. 下一工作包

1. 扩样本至 ≥100 valid episode，加入障碍/动态实体/传感器退化分层与重复 seed。
2. 同一评价入口接传统基线 vs PPO（前置：BB22:G4 + G2.5，当前未满足）。
3. 硬件前置：PX4 固件与参数导出、BOM 铭牌、规则原文；取得后再推进 G1/G2/G3。
