# 交接记录：评价 episode 边界全入口修复与干净基线（2026-10-31）

## 1. 分支与提交

- 工作区 E:\isaac\proj_boom_birds；分支 `codex/bb22-eval-audit`（自 `c62fb8d`）；未推送远端。
- 本工作包提交：
  - `cba2d86` 统一 episode 边界合同（EpisodeBoundary）并接入 velocity/reach/compare；新增核验与历史审计脚本。
  - `34f9717` 修正 evaluation CSV 列表列引用、历史审计 legacy 解析、manifest gui_mode。
  - `d18a244` velocity manifest schema 引用、reach working_tree 记录。
  - `adefade` velocity manifest 依赖导入、核验兼容 CSV 布尔拼写。
  - `bc169ea` velocity manifest started_at、官方 smoke 元数据。
  - 待提交 docs：本交接、干净基线报告、历史审计、修订索引、指导报告/分层报告适用性说明。

## 2. 根因与入口

QuadcopterEnv._reset_idx 在整环境 reset 时随机化 episode_length_buf；旧评价入口只读 terminated、忽略 truncated，导致静默 auto-reset 后继续记录（C-021 已实证）。本轮统一合同：
- EpisodeBoundary.start：env.reset + 清零计数/标志，记录 reset 快照；
- after_step：记录 terminated/truncated、计数连续性、reset 快照；
- 终止分类使用步前物理状态（不得用 auto-reset 后状态）；截断/未声明 reset → INVALID 并保留原因；
- velocity 遇边界违例直接中止并写 error 文件。

入口清单见 ENTRYPOINT_INVENTORY.md；training 入口不存在（无 PPO），未套用评价清零规则。

## 3. 历史污染审计（摘要）

- 已确认污染：layered final_run2（8 episode）、final_run3（9 episode）、c_diagnosis legacy（3 次）。
- 未发现证据（辅助检测，非证明无污染）：velocity_chain/full、reach run1/run2（旧 CSV 列表列未引用，用括号感知解析；无计数/标志字段）。
- 数据不足：compare tuning_run1/2、final_run1、faults_run2/4（仅 episode 级记录）。
- 旧文件与 hash 保留；详见 HISTORICAL_AUDIT.json/md 与 CLEAN_BASELINE_REPORT.md。

## 4. 干净基线（前台可视 GUI，无 --headless）

| 运行 | 结果 | 证据/核验 |
| --- | --- | --- |
| 官方 smoke | 100 步 PASS（历史 GUI 记录；后续重跑异常未确认） | outputs/eval_audit/official_smoke_gui/result.json；日志 |
| velocity | PASS（11/11）；边界干净；位移与历史一致 | velocity_clean3 + verify_velocity_reach PASS |
| reach | 6/6 SUCCESS；INCOMPLETE smoke | reach_clean/run2 + verify PASS |
| compare | 60 episode；比例 30/30、制动 30/30；比例均值 3.285 s vs 3.403 s（制动慢 +0.118 s）；配对方向不变 | compare_clean/final_run1 + verify PASS（18 项） |
| faults | 16 episode 全部预期分类；PhysX 接触 4/4 | faults_clean/run1 + verify PASS |
| layered | 沿用 final_run4：125 valid，success 100、collision 25 | verify_layered_runs 25 项 PASS |

- 旧→新替代：velocity/reach 方向结论不变；compare 绝对时间/末距更新（比例 3.478→3.285 s，制动 3.597→3.403 s；配对 Δ 仍 +0.118 s）；faults 分类相同；layered C-021 OOB→SUCCESS（final_run4）。
- 调参：历史 tuning 只有 episode 级记录，无法判定；候选 A 配置 hash 17e8058f 未保留 → 参数选择依据待重验，最终比较仍用既有冻结参数，未调参、未挑场景。

## 5. GUI 与失败保留

- 所有新增 Isaac 运行均为 GUI：日志含 Creating window for environment；manifest gui_mode=true；历史 headless 记录不改写。
- 失败/重试保留：velocity_clean（manifest NameError）、velocity_clean2（缺 started_at）、reach_clean/run1（manifest 已存在拒绝覆盖）、smoke_gui2/3 尝试（启动后无 PASS，原因未确认）；正式证据使用后续成功目录。

## 6. 独立核验

- verify_guidance_runs.py：compare 18 项、faults 全项 PASS（边界字段/无截断/计数连续/时长一致/配对场景集）。
- verify_baseline_runs.py：velocity/reach PASS（边界、计数、时间步长、终止分类）。
- verify_layered_runs.py：final_run4 25 项 PASS（含 no_silent_auto_reset）。
- 全部从原始记录重算，不依赖 summary 标签。

## 7. 剩余问题与下一工作包

1. 官方 smoke 的后续 GUI 重跑异常（无 PASS/结果，原因未确认）；需先定位，禁止自动改 headless。
2. 调参依据待重验：重建原候选配置并在调参集重跑后再冻结；不得用最终比较集调参。
3. compare 历史无逐 step，无法证明无污染；以 clean 结果为准。
4. layered 沿用历史 final_run4（headless）；本轮未改该路径，隔离论证成立；若再动共享边界层，需 clean 重跑 125。
5. 比赛地图 E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim\（rmuc2027_preview.usda / assets/rmuc2027_terrain.usdc）仅登记为后续集成资产，未接入评价/训练。
6. 未运行 PPO/板端/SITL/HIL/实机；规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK；不提升 Gate。

## 8. 复现

见 CLEAN_BASELINE_REPORT.md 的“命令（GUI）”与各核验脚本；所有运行目录在 outputs/eval_audit/，证据副本在 docs/reports/eval_audit/evidence/。
