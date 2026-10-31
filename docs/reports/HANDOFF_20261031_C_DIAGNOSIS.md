# 交接记录：C 类剩余越界诊断与修复（2026-10-31）

## 1. 分支与提交

- 工作区 E:\isaac\proj_boom_birds；分支 `codex/bb22-c-diagnosis`（自 `a267db6`）；未推送远端。
- 本工作包提交：
  - `c1d7583` fix: 修正分层评价的 episode 边界与静默 auto-reset（新增 clear_episode_buffers 与回归测试、truncated 处理、diag legacy/实体模式）。
  - 待提交 docs：C 类诊断报告、污染度量、trace、单因素/对照证据、本交接、layered 报告适用性修订与计划状态。
- 前序：E 类诊断 `6b26542 / a267db6`；分层评价 `9924d32 / 8e87ee0 / 90c0911`。

## 2. 已证实根因（评价链缺陷）

1. QuadcopterEnv._reset_idx 在整环境 reset 时（父类清零后）用 randint 随机化 episode_length_buf（训练去同步技巧）。
2. 分层评价运行器直接沿用该计数，且只读取 terminated、忽略 truncated/auto-reset；C-021 从 1168/1200 起步，第 30 步 time_out 静默 reset，随后继续记录 126 步并在 reset 后高度越界，误分类 OUT_OF_BOUNDS。

排除：动态实体、接触、初始穿模、控制器发散、E 类施力残留。旧逻辑下移除/冻结/禁用碰撞实体三种对照均在同一第 31 步 INVALID ENV_TRUNCATED；修复后均为 SUCCESS 71 步。

## 3. 最小回放与单因素证据

- 旧结果：final_run2、final_run3 的 C-021 完全一致（OOB 156 步、min_z 0.1038、无接触）。
- legacy 模式（保留随机化计数）3 次重复：INVALID ENV_TRUNCATED，31 步。
- 隔离 diag（旧逻辑）post-reset 后曾以 SUCCESS 210 步结束——证明 reset 后轨迹依赖上下文、不能作为有效评价。
- 修复后：C-021 SUCCESS 71 步；移除/冻结/禁用碰撞实体均 SUCCESS 71 步；成功对照 C-019/C-020 各 2 次 SUCCESS（71/70 步）。
- 接触：失败前机器人与球/运动学实体距离 >0.5 m，几何上不可能接触；无接触记录可信，旧分类也不应改判 COLLISION。

## 4. 回归与独立核验

| 类 | final_run3 | final_run4（clean） |
| --- | --- | --- |
| A | 25 success | 25 success |
| B | 25 collision（接触 25/25） | 25 collision |
| C | 24 success / 1 OOB | **25 success** |
| D | 25 success | 25 success |
| E | 25 success | 25 success |
| 总体 | 99/125，1 OOB | **100/125，0 OOB，0 invalid** |

- run3 与 run4 的 episode 差异恰好等于 run3 中检测到 auto-reset 的 9 个 episode；C-021 由 OOB→SUCCESS，其余成功但步数变化。
- 独立核验 25 项 PASS，新增 no_silent_auto_reset；pytest 227 passed；审计 PASS；diff 检查 0。
- 旧 final_run2/3 文件未覆盖；旧 layered 报告加“episode 边界适用性”修订，C/D/E 逐 episode 时间与 C-021 旧越界不作控制器结论。

## 5. 未解决与下一工作包

1. **同缺陷风险扩散**：velocity_step/reach/compare 等循环仍直接 env.reset，未清零随机化计数；既往 guidance 基线可能同样被静默 reset 污染。下一步先扫描这些运行的 spawn 突变，补同款修复，再决定重跑 guidance 基线。
2. 本轮未改控制器/场景/阈值；C-021 原 OOB 是评价链缺陷，不能归因控制能力。
3. 125 episode 仍为工作包下限，不替代 §20.11；不提升 Gate；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK。
4. AGENTS/PROJECT_PLAN/README 的状态同步仍在工作树（含用户既有修改），未提交。

## 6. 复现命令

见 [C_DIAGNOSIS_REPORT.md](../c_diagnosis/C_DIAGNOSIS_REPORT.md)；核心为 `scripts/diag_e_class.py --mode replay ... [--legacy-episode-buffer] [--entities ...]`、`run_sim_baseline.py --task layered ... --freeze ...`（commit c1d7583）、`verify_layered_runs.py`。
