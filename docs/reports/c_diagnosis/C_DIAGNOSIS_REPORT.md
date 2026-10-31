# C 类剩余 OUT_OF_BOUNDS 诊断与修复报告（2026-10-31）

> **状态：** 根因已证实（评价 episode 边界缺陷），已修复；C 类 25/25 成功，A–E 125 场景 clean 回归 PASS。**不是 BB22:G4 放行**，不提升任何 Gate。
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §8.6、§13.5、§20.2、§20.11；HANDOFF_20261031_E_DIAGNOSIS.md §6
> **证据域：** 单元测试 + 仿真模型（Isaac Lab/PhysX，ORACLE 观测）；不含真实感知、SITL/HIL、实机
> **最后核对：** 2026-10-31

## 结论（区分已证实、可能、未确认）

**已证实根因（评价链缺陷，不是动态实体或控制器能力问题）：**

1. **任务环境在整环境 reset 时随机化 episode 长度计数。** `QuadcopterEnv._reset_idx` 先调用父类清零 `episode_length_buf`，随后若重置全部 env，故意执行 `episode_length_buf = torch.randint_like(..., high=max_episode_length)`（训练时去同步 reset 的技巧）。评估流程直接沿用，使新 episode 可能从接近上限的计数开始。
2. **评价运行器只读取 `terminated`，忽略 `truncated` 与环境静默 auto-reset。** C_dynamic-8000-021 从计数 1168/1200 开始，在第 30 步触发 time_out，环境 auto-reset 到 (0,0,0.5)、速度与姿态归零；运行器继续记录 reset 后的 126 步，最终在 reset 后轨迹上高度越界，被分类为 OUT_OF_BOUNDS / ENV_ALTITUDE_LIMIT。

**排除项：** 动态实体、接触、初始穿模、控制器发散、观测退化、E 类施力残留。失败前无接触记录（实体距离与几何独立核对）；单因素对照（移除实体 / 冻结实体 / 禁用实体碰撞）在旧逻辑下全部得到完全相同的 INVALID ENV_TRUNCATED@31；修复后三种对照均为 SUCCESS 71 步。该失败在 final_run2/final_run3 两次完整运行中逐字节一致复现，并与 legacy 模式 3 次重复一致。

**未确认/限制：** 同一环境随机化也作用于运行器的其他任务路径（velocity/reach/compare）与既往 guidance 证据；本轮只修复分层评价循环，未重跑 guidance 基线。此项已登记为下一工作包，不能据此宣称历史 guidance 结论已复核。

## 第一阶段：复现与范围缩小

- 失败 episode：C_dynamic-8000-021（seed 8021，far/side；运动学实体速度 (0.094,−0.258,0) m/s；动力学球初速 (−0.19,0.45,0.29) m/s）。
- 旧结果：final_run2 与 final_run3 均为 OUT_OF_BOUNDS / ENV_ALTITUDE_LIMIT，156 步，min_z 0.1038 m，末距 1.09 m，无接触记录（两次运行完全一致）。
- 原始 step 数据显示：第 29 步位置 (0.137,−0.209,0.819)，第 30 步突变为 (0,0,0.5)、速度为零、姿态单位四元数——环境默认出生位姿，随后继续记录 126 步。
- 诊断运行（diag，未清零计数）：`POST_RESET_BUF 1168 max 1200`；第 30 步 `env_truncated=True, reset_time_outs=True`，reset 后 `episode_length_buf=532`。确认是 time_out truncation，不是 died。
- 轨迹差异：同一场景在隔离 diag 运行中（未清零计数）post-reset 后以 SUCCESS 210 步结束；两次完整运行中 post-reset 后高度越界 OOB 156 步。post-reset 轨迹本身依赖上下文，进一步证明该段记录不是有效评价。

## 第二阶段：单因素因果诊断

保持初始状态、目标、控制器与评价阈值一致；实体模式分别实现为：原样、移除（停放至远处）、冻结（保留几何与初始位置、每步写回位姿/零速度）、禁用实体碰撞（保留几何与运动、关闭 collision）。四者是不同实验，未混称。

| 条件 | 旧逻辑（保留随机化计数） | 修复后（清零计数） |
| --- | --- | --- |
| 原始实体 | INVALID ENV_TRUNCATED，31 步（3 次重复一致） | SUCCESS 71 步 |
| 移除实体 | INVALID ENV_TRUNCATED，31 步 | SUCCESS 71 步 |
| 冻结实体 | INVALID ENV_TRUNCATED，31 步 | SUCCESS 71 步 |
| 禁用实体碰撞 | INVALID ENV_TRUNCATED，31 步 | SUCCESS 71 步 |
| 成功对照 C-019 | — | SUCCESS 71 步 ×2 |
| 成功对照 C-020 | — | SUCCESS 70 步 ×2 |

- 旧逻辑下四种实体条件均在**同一第 31 步**触发 ENV_TRUNCATED，说明触发与实体是否存在、是否运动、是否可碰撞无关。
- 修复后四种条件均为 SUCCESS，进一步说明原 OOB 不是动态实体相互作用造成的。
- 接触独立核对：失败前机器人—球/运动学实体几何距离始终 >0.5 m（球半径 0.1 m、方块半对角 0.21 m），当时无接触记录是可信的；旧分类也不应改判为 COLLISION。
## 第三阶段：修复与回归

修复提交 `c1d7583`：

- 新增 `clear_episode_buffers`（清零 `episode_length_buf` / `reset_terminated` / `reset_time_outs`），在每个分层评价 episode 的 `env.reset` 之后调用；含回归测试 `tests/evaluation/test_episode_buffers.py`。
- 分层评价循环读取 `truncated`；若仍出现截断，分类为 `INVALID / ENV_TRUNCATED` 并立即终止，不再记录 reset 后轨迹；不再把 reset 后高度终止误判为控制越界。
- 独立核验新增 `no_silent_auto_reset` 检查（逐 step 检测出生位姿/零速度/单位姿态突变），final_run4 通过。
- 未修改控制器、动作合同、场景清单、冻结参数、成功阈值或失败分母。

修复后 clean 运行（final_run4，同一冻结 manifest/config/freeze，仅代码修复）：

| 类 | final_run3（修复前） | final_run4（修复后） |
| --- | --- | --- |
| A 无障碍 | 25 success | 25 success |
| B 静态障碍 | 25 collision（接触证据 25/25） | 25 collision（不变） |
| C 动态实体 | 24 success / **1 OOB** | **25 success** |
| D 观测退化 | 25 success | 25 success |
| E 物理扰动 | 25 success | 25 success |
| 总体 | 99/125 success，1 OOB | **100/125 success，0 OOB，0 invalid** |

- 独立核验：`verify_layered_runs.py` 对 final_run4 的 25 项检查全部 PASS（含配额、按类统计重算、PhysX 接触、退化/扰动时序、实体运动、冻结/hash、no_silent_auto_reset）。
- run3 与 run4 的逐 episode 差异恰好是 run3 中检测到 auto-reset 的 9 个 episode（C-000/C-006/C-021、D-000/D-011/D-023、E-004/E-022/E-024）；其中 C-021 由 OOB 变为 SUCCESS，其余 8 个成功→成功但步数变化（例如 C-000 66→54、C-006 139→54、D-000 103→57、E-004 91→54）。类别计数除 C 外不变。

## 旧结果的适用限制（已保留原产物和 hash）

- final_run2 有 8 个、final_run3 有 9 个 episode 检测到静默 auto-reset；这些 episode 的逐 step 轨迹与时间不再代表原始初始条件下的行为。
- 旧 layered 报告中的 C-021 越界、以及 C/D/E 个别 episode 的到点时间，不应用于控制器/扰动/观测退化的能力结论；类别计数在修复后除 C 外保持一致，但更细的统计应以 final_run4 为准。
- E 类诊断结论（施力累计与杠杆力矩缺陷）不受本缺陷影响：E 修复的 force 探针与时间序列是独立证据；但 E 的旧逐 episode 数据同样受 auto-reset 污染，final_run4 为 clean 版本。
- `outputs/layered_eval/final_run2`、`final_run3` 原样保留，未覆盖。

## 验证

- 单元测试：`pytest -q` → **227 passed**（新增 episode 边界回归测试）。
- 文档审计：PASS（119 链接）。
- 本工作包 diff 检查：`git diff --check 90c0911..HEAD` → 0（提交前执行）。
- 仿真：final_run4 标记 `BOOM_BIRDS_LAYERED_EVAL_PASS`，无 `summary.error.txt`；冻结校验通过；125 valid episode。
- 训练 / 板端 / SITL/HIL / 实机：**NOT RUN**；本报告不提升任何 Gate，125 episode 不替代 V2.2 §20.11 正式冻结。
## 精确复现命令

`powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -m pytest -q
# 旧逻辑复现：保留随机化 episode 计数（legacy），同一失败 3 次
& $py -u scripts/diag_e_class.py --mode replay --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --scenario-id C_dynamic-8000-021 --no-disturbance --repeats 3 --timeout-s 12 --legacy-episode-buffer --entities original --headless --device cuda:0 --output outputs/c_diagnosis/legacy_original_r3
# 修复后最小回放与单因素对照（entities: original/removed/static/no_collision）
& $py -u scripts/diag_e_class.py --mode replay --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --scenario-id C_dynamic-8000-021 --no-disturbance --repeats 1 --timeout-s 12 --entities removed --headless --device cuda:0 --output outputs/c_diagnosis/fixed_removed
# 成功对照（C-019/C-020，各 2 次）
& $py -u scripts/diag_e_class.py --mode replay --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --scenario-id C_dynamic-8000-019 --scenario-id C_dynamic-8000-020 --no-disturbance --repeats 2 --timeout-s 12 --headless --device cuda:0 --output outputs/c_diagnosis/fixed_controls
# 修复后冻结集 125 场景回归
& $py -u scripts/run_sim_baseline.py --task layered --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --classes all --methods proportional --timeout-s 12 --freeze configs/scenarios/layered_freeze_20261031.json --require-coverage --min-valid-per-class 20 --min-valid-total 100 --code-commit c1d7583c85ec7e5599442da2d0eaba87f13ce89e --headless --device cuda:0 --clone-in-usd --output outputs/layered_eval/final_run4
& $py scripts/verify_layered_runs.py --run-dir outputs/layered_eval/final_run4 --freeze configs/scenarios/layered_freeze_20261031.json --output docs/reports/c_diagnosis/verify_after_fix.json
`

## 证据与 hash

| 产物 | 位置 | SHA-256 |
| --- | --- | --- |
| 修复后评价摘要 | [after_fix/summary.json](after_fix/summary.json) | `eeaad46678f5763be79baaaa52cd56acdd281c762f722b179efe9c724616b88d` |
| 修复后逐 episode | [after_fix/episodes.jsonl](after_fix/episodes.jsonl) | `803facaa6053697bb71b93fe9ee2111178eec97104f557f966850e5cbc18ed56` |
| 修复后 manifest | [after_fix/manifest.json](after_fix/manifest.json) | `1119fd7ad0c9d99a912c1cedb74bac954b83d8cc396a5791115fa8879bc0db58` |
| 场景清单副本 | [after_fix/scenario_manifest.json](after_fix/scenario_manifest.json) | `fedb6b2fedfb2a5a0cb4094ede98fe509b113edf4239420e8a8b9337de7eb7d2` |
| 修复后逐 step（忽略目录） | `outputs/layered_eval/final_run4/steps.jsonl` | `e4e00d641a0015b4a2927dec67d0a0c1fd2a2666c40d4dbb85f520c5ceb15b66` |
| 独立核验 | [verify_after_fix.json](verify_after_fix.json) | `3f1aacff4d5edf7fd8194e5a360f936e0ec6a5e7268dc67a7b59eff60a647877` |
| 污染度量（旧运行 reset 清单、逐 episode 差异） | [CONTAMINATION_METRICS.json](CONTAMINATION_METRICS.json) | `2a030fadb8af93ae2e8998d88e308188b2e9f2f763beecc408111e2b0a10d97f` |
| 关键 trace（reset 发生时刻） | [replay/trace_reset.txt](replay/trace_reset.txt) | `5f911b1833c459bfe97e28bca96d5eea6e6a4093a3512e5e7edd9c1eabcf81d0` |
| 旧逻辑失败 3 次 | [runs/legacy_original_r3_summary.json](runs/legacy_original_r3_summary.json) | `0ea729aae233f588925e8d1e6dae5f9d733dd134425a260c63d048c138785ce3` |
| 旧逻辑失败 trace steps（忽略目录） | `outputs/c_diagnosis/replay_021_trace2/steps.jsonl` | `da67fc961dd62d7abdb0e95c2ee7363c6b889ccdf0d13465978dca372affc6c4` |

## 未解决与下一工作包

1. **其他任务路径的同一缺陷风险：** `run_sim_baseline.py` 的 velocity_step / reach / compare 等循环仍直接使用 `env.reset`，未清零随机化 episode 计数；既往 guidance 基线与更早的 velocity/reach 证据可能包含同样的静默 auto-reset。必须先审计这些运行的 spawn 位姿突变并补同款修复，再决定是否重跑 guidance 基线。
2. 本轮只修复分层评价循环；没有改控制器或场景，因此不能把 C-021 原 OOB 归因于控制能力；也不把修复后的 C 25/25 当作新的能力提升。
3. 125 episode 仍为本工作包采样下限，不替代 V2.2 §20.11 正式冻结；未运行 PPO、板端、SITL/HIL、实机。
4. 规则、BOM、PX4 来源缺口保持 UNKNOWN/RULE-CHECK；不提升任何 Gate。
