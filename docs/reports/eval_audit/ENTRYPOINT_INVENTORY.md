# 评价入口与 episode 边界风险清单（2026-10-31）

> **状态：** DONE（本轮审计）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §8.6、§10.4、§17、§20.2、§20.11
> **证据域：** 源码审计 + 单元测试 + 仿真
> **最后核对：** 2026-10-31

## 缺陷背景

QuadcopterEnv._reset_idx 在整环境 reset 时先由父类清零 episode_length_buf，随后用 randint 随机化（训练去同步）。历史评价入口直接调用 env.reset 后未清零，也未读取 truncated；环境在计数到达上限时静默 auto-reset，运行器继续记录 reset 后轨迹，导致终止分类错误（C 类 C-021 已实证）。

## 入口清单与处理

| 入口 | 评价/诊断 | reset 处理 | terminated/truncated | 本轮结论 |
| --- | --- | --- | --- | --- |
| run_sim_baseline --task velocity_step | 诊断基线（10 场景） | EpisodeBoundary.start 清零计数；reset_old_epoch 的合法 reset 重新开始边界 | 捕获 terminated/truncated；截断/未声明 reset 立即 RuntimeError 并写 error 文件；行内记录边界字段 | 已修复并 clean 重跑 |
| run_sim_baseline --task reach | smoke（6 episode） | EpisodeBoundary.start | 截断→INVALID ENV_TRUNCATED；计数异常→INVALID ENV_UNEXPECTED_RESET；终止用步前物理状态分类 COLLISION/OUT_OF_BOUNDS | 已修复并 clean 重跑 |
| run_sim_baseline --task compare（tuning/final/fault） | 正式比较与专项故障 | EpisodeBoundary.start（每 episode） | 同上；collision_contact 的 PhysX 接触与 collision_flag 注入分开；episode 记录边界字段 | 已修复；final 60 + faults 16 clean 重跑 |
| run_sim_baseline --task layered | A–E 分层评价 | c1d7583 已用 clear_episode_buffers；本轮未改该路径 | 已读 truncated，INVALID ENV_TRUNCATED | 未修改；复用 final_run4（隔离论证） |
| scripts/diag_e_class.py replay/probes | 诊断/回放 | 正常模式 clear_episode_buffers；legacy 模式故意保留旧行为 | 正常模式截断→INVALID；legacy 用于复现缺陷 | 已有针对性证据；legacy 单列 |
| scripts/check_official_quadcopter.py | 官方 smoke | 不评价 episode 边界 | 记录 terminated/truncated 样本 | GUI 方式重跑 |
| verify_layered_runs.py | 独立核验 | 从逐 step 重算 | no_silent_auto_reset（出生位姿签名，辅助） | final_run4 PASS |
| verify_guidance_runs.py | compare/fault 独立核验 | 从 episode 记录重算 | boundary 字段存在、无截断、计数连续、时长=步数×dt、配对场景集一致 | clean 运行 PASS |
| verify_baseline_runs.py | velocity/reach 独立核验 | 从 CSV 重算 | 边界字段、计数连续、时间步长、终止分类 | clean 运行 PASS |
| audit_historical_runs.py | 历史审计 | — | 出生位姿/零速度突变（辅助）；旧格式兼容解析 | 已生成审计结果 |

## 合同要点

1. 每个评价 episode 从清零的 episode_length_buf 与 reset 标志开始。
2. 环境 terminated/truncated 是**主信号**；出生位姿+零速度+单位姿态仅为辅助证据，不能单独证明无 reset。
3. 当前 Isaac Lab 版本中 env.step 返回的 terminated/truncated 是复位前判定，但 step 后直接读取的机器人状态在 auto-reset 时已经是 reset 后状态；终止分类必须使用步前物理状态或 reset 快照，不得使用 reset 后状态。
4. 任务可预期超时（ReachSpec timeout）为有效失败 TIMEOUT；环境截断/未声明 reset 为 INVALID 基础设施错误，保留原因与记录，不拼接两段轨迹。
5. 成功、碰撞、超时、环境边界与 INVALID 的优先顺序：先判环境边界/终止信号，再判任务成功/超时；碰撞使用 PhysX 接触证据或合同注入标志。
6. reset 需同时清除控制记忆（executor/reset）、观测接口队列、外力缓冲、故障注入、实体状态；各入口已在 episode 起点执行。
7. 评价入口的 manifest 记录实际源码 commit、working tree、GUI 模式、配置/场景 hash 与产物 hash；每次运行独立目录。
