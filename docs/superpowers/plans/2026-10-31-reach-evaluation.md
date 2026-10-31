# 最小到点任务与统一评价实施计划（2026-10-31）

> **状态：** DONE（代码与单元测试）；仿真 smoke 为 INCOMPLETE
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §12.2、§20.2、§20.9、§20.11；旧 Task 4/5 方法
> **证据域：** 单元测试 + 仿真模型（ORACLE 真值）；不含视觉、真实目标与实机
> **Gate：** 仅作 BB22:G4 前置输入；G4 还依赖 G1/G2.6/G3，且需传统基线与统一评价冻结

## 输入与前置条件

- 输入：已验证的仿真速度执行链（commit 0fb76c3）、四维动作合同、V2.2 成功/失败判定优先级。
- 前置：无新增硬件；ORACLE 状态仅在仿真内部可用，不能作为部署观测。
- 不满足的前置：视觉感知（G3）未开始；难度分层、碰撞场景族、传感器退化均未实现。

## 修改文件（写域）

- 新增 @@src/boom_birds/sim/reach.py@@：ReachSpec / ReachEvaluator / GuidanceSpec / guidance_command。
- 新增 @@src/boom_birds/evaluation/__init__.py@@、@@episodes.py@@：EpisodeResult / summarize / manifest。
- 新增 @@tests/sim/test_reach_task.py@@、@@tests/evaluation/test_episode_metrics.py@@。
- 修改 @@scripts/run_sim_baseline.py@@：新增 @@--task reach@@ 分支与 manifest 输出。
- 新增 @@docs/reports/sim_reach/@@：报告、summary、manifest、日志。

## 接口与判定

- 成功：距目标 ≤ 0.3 m 且速度 ≤ 0.2 m/s 连续 0.5 s（PROPOSED）。
- 优先级：非法状态 > 碰撞 > 成功保持 > 超时；碰撞与到达同步发生时判失败。
- 超时：@@truncated=True@@、不算成功；分母保留。
- 统一评价：@@summarize@@ 输出 total/valid/invalid 与各 outcome 计数；成功率为 success/valid 并同时给出 total 分母；@@failure_cases@@ 列出失败 episode。
- manifest：强制字段 @@code_commit/working_tree/config_sha256/asset_versions/seeds/command/started_at/exit_code/outputs_sha256@@；已存在时默认拒绝覆盖。

## 验收方法

- @@python -m pytest tests/sim tests/evaluation -q@@ 全绿；全量 @@pytest -q@@ 不回归。
- 仿真 smoke：6 episodes、20 s 超时、ORACLE 引导；样本量 < PROPOSED 100 → 状态 @@INCOMPLETE@@，不得写 PASS。
- 检查：success/collision/timeout/invalid 计数与分母、失败样例、manifest 哈希、记录值有限。

## 运行预算与停止条件

- 预算：单次仿真 ≤ 3 min；6 episodes × ≤400 步；不训练、不扩环境。
- 停止条件：非有限值、manifest 写入失败、合同违约、成功率异常（全失败且无明确原因）。

## 失败处理

- 运行失败保留 @@*.error.txt@@ 与日志；先定位再改。
- 判定争议以 V2.2 §20.2 优先级为准；不得通过删除失败 episode 提高成功率。