# Boom_Birds P0/P1 Foundation Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Do not dispatch agents unless current instructions permit it. Steps use checkbox syntax; all unchecked steps are NOT RUN. Task 1/2于2026-10-11按实际证据更新；Task 3–6业务入口尚未实现。

**Goal:** 在现有Isaac Lab基础上建立可复现的无障碍到点、停止、速度接口和PPO研究基线。

**Architecture:** 一个Isaac Lab任务扩展与一个轻量boom_birds包。标准库合同隔离训练/部署，速度执行器模拟PX4外环响应，传统简单制导与成熟PPO共用场景和评价。

**Tech Stack:** Python，当前Isaac Lab匹配的PyTorch与单一成熟PPO集成，pytest；精确版本由Task 1登记后锁定。

**Spec:** [项目设计](../../design/01_PROJECT_DESIGN.md)、[接口](../../design/02_ARCHITECTURE.md)、[首阶段](../../design/04_FIRST_TASK.md)、[评价](../../design/08_EVALUATION.md)。

## Global Constraints

- 主工作区 `E:\isaac\proj_boom_birds`；现有环境保留，不全局升级或复制venv。
- Isaac Lab主工程；NavRL导航方法参考；DiffPhysDrone轻量视觉参考；不安装三套完整训练栈。
- PX4通信按可实现前提，P0/P1不依赖真实PX4、WSL/SITL、旧项目或真实目标图像。
- 策略动作4维[-1,1]，水平FLU前/左、向上速度、逆时针偏航率；运行合同为ENU物理单位。
- 初始限值PROPOSED：水平1m/s，垂直0.5m/s，yaw_rate 0.5rad/s；20Hz，episode20s。
- 初始到点PROPOSED：距离≤0.3m、速度模长≤0.2m/s连续0.5s；碰撞优先失败。
- 10×6×3m空场，半径0.12m为假设包络，不是实机尺寸；参数均进入配置。
- 150ms TTL，now >= expiry判过期；重发不延长原到期时间。
- 调试10seed；正式3训练seed×同一100评估episode，训练/验证/最终集隔离。
- 优先复用成熟实现，不手写PPO；原版成功和移植成功要用不同描述。

## Review Focus

1. ENU/NED/水平FLU混淆会让飞行方向错误：Task 2用显式向量例固定。
2. 仿真reset和真实origin重置留下过期动作/隐藏状态：Task 2/4/6测试epoch/reset。
3. 速度动作误接到推力、电机：Task 3用阶跃和停止响应证明实际语义。
4. timeout当成功或碰撞后算到点：Task 4/5固定互斥判定和分母。
5. 本机环境和模型无法重现：Task 1/5/6固定版本、配置、seed和导出/重放入口。

## Task 1：环境、上游与版本记录（W00）

**Files:** Create `scripts/preflight.py`, `env/manifests/host.json`, `env/manifests/upstream.json`, `env/locks/README.md`, `third_party/NOTICE.md`, `pyproject.toml`; modify `.gitignore` only for actual generated artifacts. Git初始化在检查现有内容后执行，不删除旧文件。

**Interfaces:** `collect_environment() -> dict`输出host/OS/Python/IsaacLab/IsaacSim/PyTorch/GPU/driver/launcher；未得到的字段标unknown，不填推测版本。上游记录repo/commit/license/core_paths/adaptation。

- [x] 只读确认当前解释器、启动器和Isaac/PyTorch版本；保存既有包清单，不先安装依赖。
- [x] 固定NavRL和DiffPhysDrone上游SHA，核对许可、网络/观测/动作/训练入口，填复用/移植/不采用表；未明许可不复制代码。
- [x] 运行本机版本对应官方四旋翼最小例，记录准确命令、退出码和日志；官方例失败时先定位而非构建新任务。
- [x] 选择当前集成中能支持所需观测、可扩展时序策略的一种PPO后端，登记具体版本及选择理由；不自行实现PPO。
- [x] 建立单包元数据和Git基线，保持env/外部权重不入库；不自动push远端。
- [x] 验证：`python scripts/preflight.py --output env/manifests/host.json`在已确认解释器运行；人工检查环境记录可追踪、无伪造值，并记录源码提交。

**Deliverable:** G0环境部分通过，或明确最小阻塞与修复方案；不是算法通过。

## Task 2：动作、坐标和时效合同（W01）

**Files:** Create `src/boom_birds/contracts/{types,frames,timebase}.py`, `tests/contracts/test_action_contract.py`, `tests/contracts/test_timebase.py`, `configs/runtime/default.yaml`。

**Interfaces:** `decode_action(action, yaw_rad, limits, now_ns, mission_epoch) -> VelocityCommand`; `enu_to_ned(vector) -> tuple`; `command_is_valid(command, now_ns, mission_epoch) -> bool`。类型字段来自架构02。

- [x] 添加失败测试：yaw=0时动作[1,0,0,0]得到ENU[1,0,0]；yaw=π/2得到[0,1,0]；ENU[1,2,3]得到NED[2,1,-3]；yaw_rate 0.5转NED -0.5。
- [x] 添加失败测试：动作长度非4、NaN/Inf拒绝；有限越界值限幅；同一到期时间的重发不可续期。
- [x] 添加失败测试：水平上限1m/s、yaw=0、动作[1,1,0,0]得到ENU[1/√2,1/√2,0]，水平模长不超过1；训练与部署使用同一投影和缩放规则。
- [x] 添加失败测试：expiry-1ns有效、expiry无效；mission_epoch改变拒绝；时钟来源不匹配不能计算虚假capture年龄。
- [x] 运行 `python -m pytest tests/contracts -q`，确认失败原因对应未实现合同；实现最小逻辑后全部通过。
- [x] 检查contracts不导入Isaac/Torch/相机库，记录接口版本并提交本任务变更。

**Deliverable:** 单位、符号和时间合同可在无GPU环境测试。

## Task 3：仿真速度执行器（W02的一部分）

**Files:** Create `src/boom_birds/sim/controllers/velocity.py`, `configs/vehicles/sim_reference.yaml`, `tests/sim/test_velocity_response.py`, `scripts/run_sim_baseline.py`。

**Interfaces:** `VelocityExecutor.step(command: VelocityCommand, state: VehicleState, dt_s: float) -> actuator_action`；actuator_action使用Task 1确定的Isaac资产接口，不让控制器合同直接绑定未知motor编号。参数包含速度/加速度限幅、响应时间常数、延迟、动力/质量来源。

- [ ] 在官方资产上明确重力、单位、姿态约定和执行器类型；写出速度指令到实际执行器的路径，禁止直接赋速度等同于模拟真实飞行。
- [ ] 建立阶跃测试：正前/左/上及转向方向正确；无指令变化时状态连续；停止输入下速度下降，记录超调/整定/停止距离。
- [ ] 建立过期指令和重置测试，停止沿用旧动作；具体模拟降级行为在配置中写明，不推导为实机安全动作。
- [ ] 实现或复用适用控制器，用1环境生成响应曲线；任何使用理想速度源的对照必须标KINEMATIC，不用于迁移验收。
- [ ] 验证：`python scripts/run_sim_baseline.py --task velocity_step --config configs/vehicles/sim_reference.yaml`保存逐步指令/状态与manifest；此命令在Task 3实现后才有效。
- [ ] 运行合同与响应测试，记录模型假设和可用域，提交变更。

**Deliverable:** 控制响应可解释，具备后续与PX4实测对齐的位置。

## Task 4：到点、停止与episode环境（W02）

**Files:** Create `src/boom_birds/sim/tasks/reach.py`, `src/boom_birds/sim/observations.py`, `configs/tasks/reach.yaml`, `configs/observations/state.yaml`, `tests/sim/test_reach_episode.py`。

**Interfaces:** `ReachTask`按Task 1锁定Isaac Lab接口实现reset/step；`build_actor_observation(state, goal, spec)`返回带schema的批量观测。状态观测明示ORACLE：目标相对位置、速度、姿态相关量和前一步动作，维度由配置/manifest登记，不继承旧固定27维。

- [ ] 写到点测试：距离0.29m、速度0.19m/s保持10个20Hz步后成功；9步不成功；距离或速度超界清除连续计数。
- [ ] 写优先级测试：同一步碰撞与到点同时发生为失败；20s超时为truncated且不算成功；非法状态中止并带reason。
- [ ] 写批量reset测试：只重置选中环境，其他环境不变；前一步动作/成功计数/episode随机状态正确清除。
- [ ] 实现任务，训练用目标和状态真值明确标记；奖励与成功判定分别实现，防止改reward悄悄改变验收。
- [ ] 用简单比例制导跑10个固定seed，保存失败和响应；在1环境通过后扩8/32/64测资源并锁定首轮并行数。
- [ ] 验证：`python scripts/run_sim_baseline.py --task reach --config configs/tasks/reach.yaml --seed-set smoke`；运行Task 2–4测试，记录并提交。

**Deliverable:** 第一项可独立运行的基础飞行任务；尚无障碍/真实视觉。

## Task 5：统一评价与实验记录（W01/W02）

**Files:** Create `src/boom_birds/evaluation/{episodes,metrics,manifests}.py`, `configs/evaluation/{smoke,frozen}.yaml`, `scripts/evaluate.py`, `tests/evaluation/test_episode_metrics.py`。

**Interfaces:** `summarize(results: list[EpisodeResult]) -> dict`; `write_manifest(run_dir, metadata) -> Path`；seed集合版本明确，manifest绑定代码/配置/资产/观测/模型。

- [ ] 失败测试：10个有效episode中8成功、1碰撞、1超时，成功率=0.8、碰撞率=0.1、超时率=0.1；不能将超时从分母删除。
- [ ] 失败测试：基础设施错误单列invalid且有原因；同场景重试不得覆盖原结果；不同schema/hash不能合并成同条件对比。
- [ ] 固定训练/验证/最终测试seed与场景分割，防止调参访问最终集；所有checkpoint用同一评估入口。
- [ ] 实现CSV/JSON逐episode结果和报告，保存响应/失败片段索引；大文件放配置存储，摘要保存在docs/reports。
- [ ] 验证：`python -m pytest tests/evaluation -q`，手工复算一组统计并核对原始episode；记录提交。

**Deliverable:** 不依赖reward曲线的真实任务评价。

## Task 6：成熟PPO连接、checkpoint与重放（W03）

**Files:** Create `src/boom_birds/learning/ppo_adapter.py`, `configs/agents/ppo.yaml`, `scripts/train.py`, `scripts/replay.py`, `tests/sim/test_training_adapter.py`。

**Interfaces:** `train(task_config, agent_config, seed, run_dir) -> checkpoint_path`; `load_policy(checkpoint_path, observation_spec, action_spec)`拒绝不匹配schema。库的内部类由Task 1选定，不额外抽象多后端。

- [ ] 写适配测试：向量观测/动作shape一致，terminated/truncated正确传递，归一化统计随checkpoint恢复；不匹配schema拒绝。
- [ ] 连接所选PPO库，先少量rollout检查NaN、饱和动作、episode统计与资源；训练日志关闭会阻塞的远端上传依赖。
- [ ] 确认相机未开启，保存短训练checkpoint；重放时关闭探索噪声，保留固定seed和确定性设置说明。
- [ ] 验证命令：`python scripts/train.py --task reach --agent ppo --seed 0`；随后 `python scripts/replay.py --run-dir <实际run目录> --seed-set smoke`。入口实现时须与此CLI保持一致或同步修改计划。
- [ ] 完成3训练seed正式比较前，冻结训练预算与评估集；通过G1或报告失败根因，不凭一次好轨迹晋升。
- [ ] 写P1报告：比例制导与PPO同条件结果、响应模型限制、资源、失败样例、下一阶段差异。提交本任务变更。

**Deliverable:** 可保存、重放和评价的首个PPO基线。

## P0/P1完成与后续计划

- [ ] W00–W03结果与G0/G1逐项对应，所有未通过项明确记录。
- [ ] 源码、配置、seed、上游、模型与结果可追踪；当前资料中的NOT RUN仅按实际证据更新。
- [ ] 再编写P2静态避障具体实施计划，明确采用NavRL哪些文件/公式/设计，哪些属于本项目改动。
- [ ] P3视觉传感、P4机库、P5部署、P6任务各自形成独立实施计划；依赖前一门实测，不在当前文件编造未来硬件接口。

原规划交付时仅有计划。2026-10-11接手后已初始化Git、完成Task 1/2；环境依赖冲突、官方Fabric克隆差异及验证边界见docs/reports/p0/P0_ENVIRONMENT_REPORT.md。未安装上游环境，Task 3–6仍NOT RUN。
