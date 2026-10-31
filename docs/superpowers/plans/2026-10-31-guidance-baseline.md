# 传统控制基线对比与失败路径/随机化实施计划（2026-10-31）

> **状态：** IN PROGRESS
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §10.6、§12.2、§20.2、§20.9、§20.11；docs/reports/HANDOFF_20261031.md §6
> **证据域：** 单元测试 + 仿真模型（ORACLE 观测权限）；不含感知、PX4、SITL/HIL、实机
> **Gate：** 仅仿真基线证据；不是 BB22:G4 冻结或通过

## 目标与算法差异

- 保留现有比例制导（`ProportionalGuidance`，位置误差 × 增益，无速度反馈），它本身已经是传统方法。
- 新增制动型到点制导（`BrakingGuidance`）：
  1. 期望速度由制动剖面给出 `v_des = min(v_max, sqrt(2 a d))`，接近目标时主动降速；
  2. 速度反馈 `v_cmd = v_des + k_fb (v_des - v_actual)`，超速时产生反向修正，提前制动；
  3. 水平/垂直分别限幅，目标到达半径内输出零，保持四维动作约束不变。
- 两者使用**相同** ORACLE 观测（位置/速度/姿态）、相同动作限幅、相同 20 Hz 控制、相同动力学、相同成功判定与评价代码。ORACLE 是观测权限，不是算法名。

## 输入与前置

- 已提交执行链（`38159ee`）与到点评价（`12 流程`）；无新增硬件。
- 随机化与场景清单先于最终比较生成并冻结；调参集与最终集分离。

## 修改文件（写域）

- 新增 `src/boom_birds/sim/guidance.py`：两种制导方法、工厂、参数校验。
- 新增 `src/boom_birds/sim/scenarios.py`：随机化规格、确定性场景生成、manifest 读写与 hash 校验。
- 新增 `src/boom_birds/evaluation/comparison.py`：Wilson 置信区间、分层汇总、配对比较。
- 修改 `src/boom_birds/evaluation/episodes.py`：EpisodeResult 增加 method/scenario/time_to_goal/final_error 等字段（保持既有位置参数兼容）。
- 修改 `scripts/run_sim_baseline.py`：新增 `--task compare` 与故障注入参数。
- 新增 `scripts/make_scenarios.py`：纯标准库场景生成 CLI。
- 新增 `configs/scenarios/`：调参集、最终集、冻结文件。
- 新增 `tests/sim/test_guidance_methods.py`、`tests/sim/test_scenarios.py`、`tests/evaluation/test_comparison.py`。
- 新增 `docs/reports/guidance_baseline/`：报告、汇总、逐 episode 记录、manifest、日志。

## 验收方法

1. 单元测试先行：制导符号/限幅/制动/速度反馈/到达零输出；场景确定性与范围；Wilson/配对/分层统计；全量 pytest 与文档审计。
2. 调参集：8 个随机场景 × 2 方法，仅用于选择制动参数（a、k_fb），记录参数选择依据。
3. 冻结：写 `configs/scenarios/freeze_20261031.json`，含 sim 配置、制导参数、判定阈值、调参集与最终集 hash；最终运行前校验。
4. 最终比较：30 个预生成场景 × 2 方法 = 60 episode，同一场景清单，逐 episode 记录、分层与配对统计、Wilson 95% 区间；阈值与参数不因结果调整。
5. 专项故障：碰撞（PhysX 真实接触 + 标志注入两种，分别标注）、超时、非有限输入（观测/接口层注入）各至少 1 个仿真样本；故障集单独统计，不混入自然成功率。
6. 每次运行独立输出目录；同时核对完成标记、日志、`*.error.txt` 与产物完整性，不以 exit 0 单独判定成功。

## 运行预算与停止条件

- 预算：调参 ≤ 2 次运行、每次 ≤ 4 min；最终比较 1 次 ≤ 8 min；故障集 1 次 ≤ 5 min；每次 1 环境、20 Hz。
- 停止条件：非有限值进入 PhysX、合同违约、分类与预期不符且无法定位、产物缺失。

## 失败处理

- 保留失败运行目录与日志，不覆盖；先定位再重跑新目录。
- 若制动基线不稳定：只调其参数并记录；不得改成功阈值、删除失败或挑选 seed。
