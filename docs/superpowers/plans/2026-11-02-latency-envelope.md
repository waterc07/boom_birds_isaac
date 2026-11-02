# 动作延迟包络正式评价计划（2026-11-02）

> **状态：** BASELINE（本工作包执行计划；不是验收结论）
> **来源章节：** V2.2 §10.4、§16.1–16.3、§16.6、§17.3、§26.6–26.7、§27.3–27.7；HANDOFF_20261101_BRAKE_ENVELOPE、MAP_BRAKE_ENVELOPE_REPORT、MAP_V2_EXEC_REPORT
> **证据域：** 标准库单元测试 + 前台可视 GUI 仿真动力学（DirectX/D3D12）
> **最后核对：** 2026-11-02

## 1. 目标与现状

正式完成 latency-envelope 工作包：补齐"动作传输到达时有效期/上下文/所有权检查"与"模拟双时钟偏移/漂移/映射误差"到 GUI 动力学链，生成**预运行冻结**，之后串行分段跑 A/B 各 12 个配对 episode 与必要专项，用独立核验脚本从原始记录重算，最后给出参数结论与交接。

现场（2026-11-02 核对）：

- 分支 `codex/bb22-latency-envelope`，HEAD `dff8650`；工作树含 23 个与本工作包无关的用户/上一工作包文档修改，**不得回退、不得纳入本工作包提交**；另有 `configs/scenarios/latency_pair_freeze_v1.json`（运行后补写，`status=FROZEN_AFTER_RUNS_RECORDED`），只能作探索证据。
- 已有探索运行 `outputs/map_eval/latency_formal_A`、`latency_formal_B`（A/B 各 12，`--obs-delay-s 0.15 --action-delay-s 0.10`，stop 1.1/1.38），冻结在其后生成 → **探索证据，不升级为正式证据**。A/B 逐 case 结果相同（SUCCESS 6 / ABORT 6）。
- 已实现但**未接入 GUI 动力学链**：`src/boom_birds/evaluation/dual_clock.py`（SimClock/SimMapping/EventQueue）、`envelope.py`（Envelope/StopRequirement）仅单元测试使用；`action_transport.py` 只有 TTL 到达拒绝，没有到达时上下文/所有权/同步代次检查；`run_dynamic_eval.py` 只把 `--clock-offset-ms` 加到观测年龄，没有漂移/映射误差/时钟域记录，也没有到达时刻与"实际执行 setpoint"记录。
- `run_dynamic_eval.py` 的 `--action-delay-s` 已用 `DelayedVelocityExecutor` 接入执行器；`--sync-fail-step` 在接纳前推进 sync 代次（发端拒绝）；`case.fault` 支持 7 类软件故障；ABORT 时立即结束，没有拒绝后物理观测窗口。

硬约束：所有 Isaac 运行必须前台可视 GUI（保留窗口，DirectX/D3D12，`--kit_args=--/app/vulkan=false`，**禁止 `--headless`/隐藏窗口**）；串行分段、每段独立目录；不启动 PPO/真实感知/PX4 Sender/板端/SITL/HIL/实机；不提升任何 Gate；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；不推送远端；提交消息中文。

## 2. 实现缺项与最小修复（先失败测试，再实现）

### 2.1 `src/boom_birds/evaluation/dual_clock.py`（扩展，保持向后兼容）

- `SimClock`：保留 `read_ns(host_ns) = round(host_ns + offset_ns + host_ns*drift_ppm/1e6)`；新增 `read_uncertainty_ns()`（返回 `abs(uncertainty_ns)`）。
- `SimMapping`：在现有字段**末尾**追加 `drift_ppm: float = 0.0`（不得破坏现有位置参数测试 `SimMapping('camera','host',100,10,3,0,1000)`）。
  - `usable(host_ns, sync_generation)` 语义不变（valid + sync 匹配 + 有效窗口）。
  - `map_uncertainty_ns(host_reference_ns=0)`：`abs(offset_ns) + uncertainty_ns + ceil(abs(drift_ppm)*1e-6*abs(host_reference_ns))`；默认调用仍返回 110（现有测试）。
  - `to_host_ns(clock_ns)`：逆映射点估计。
  - 新增纯函数 `mapping_age(capture_clock_ns, host_now_ns, mapping, sync_generation)` → `dict(valid, reason, age_point_s, age_bound_s, mapped_host_ns, error_bound_ns)`：
    - mapping 不可用（invalid/sync 不匹配/窗口外）→ `valid=False, reason='CLOCK_MAPPING_UNUSABLE'`；
    - 否则 `mapped = to_host_ns(capture_clock_ns)`，`age_point = (host_now - mapped)/1e9`，
      `age_bound = age_point + map_uncertainty_ns(host_now)/1e9`，`valid=True, reason='ACCEPT'`。
    - **age_bound 必须 ≥ age_point**（保守上界），负年龄按 0 处理并在 reason 中保留 `NEGATIVE_AGE`。
- `EventQueue` 保留。
- 新增失败测试（先写、先失败）：漂移 100ppm 时读取与映射误差随 host 时间线性增长；sync 不匹配时 mapping 不可用；age_bound ≥ age_point；映射往返误差 ≤ 界。

### 2.2 `src/boom_birds/evaluation/action_transport.py`（重写为到达门）

保留 `DelayedActionQueue` 单调投递语义。`DelayedVelocityExecutor` 新语义：

- 新增 `ActionTicket`（冻结 dataclass）：`setpoint`、`action_id`、`issued_at_s`、`expires_at_s`、`control_epoch`、`epochs`（六元代次元组）、`sync_generation`、`owner`。
- `DelayedVelocityExecutor(executor, delay_s)`：
  - `update_context(*, epochs, owner)`：记录当前上下文（每个控制步由运行器从 `V2ActionGate` 同步；`epochs=(system_boot, mission, localization, control, px4_boot, sync_generation)`）。
  - `set_delay(delay_s)`：允许运行中改变传输延迟（用于超 TTL 专项），已排队项保持原投递时刻。
  - `step(setpoint, state, now_s)`：
    1. 若 `setpoint` 非空：取 `setpoint` 上的 `action_id/control_epoch/sync_generation`（见 2.3），用当前 `update_context` 的 epochs 构造 ticket，投递时刻 `now_s + delay_s`。
    2. `take_due(now_s)` 后**逐项到达校验**（顺序）：`now_s >= expires_at_s` → `ACTION_EXPIRED`；epochs 任一元组不匹配 → `REJECT_CONTROL_EPOCH`（mission/localization/boot 分别用对应原因码）；sync 不匹配 → `REJECT_SYNC_OR_PX4_BOOT`；owner 不允许 → `REJECT_OWNER`。通过者成为 active（后到覆盖先到）。
    3. 对 active 每步复核同样条件：过期/上下文失效 → 丢弃并记录，传 `None` 给内层；否则**继续传 active 的原始 setpoint（不得续期、不得改写 expires）**。
    4. 返回内层 `step` 结果；记录 `last_transport`：`status ∈ ('DIRECT','APPLIED','HOLDING','REJECTED','NONE')`、`action_id`、`executed_action_id`、`issued_at_s`、`expires_at_s`、`scheduled_arrival_s`、`arrival_s`、`age_s`、`dispatch_delay_s`、`reason`、`executed`。
  - `arrivals` 列表保存全部到达记录；`rejections` Counter；`clear()` 清队列+active；`reset(state)` 清队列+active+内层 reset（reset/撤权后队列隔离）。
  - `control_epoch` 属性仍代理内层。
- 关键语义：**被拒绝的动作永不执行；已接纳但仍在有效期内的旧 setpoint 继续执行并如实记录为 HOLDING；拒绝 ≠ 立即停止**。重发不续期。
- 新增失败测试：
  - 到达时 sync 代次变化 → 拒绝且未执行；
  - 到达前 epochs 变化 → 拒绝且旧 active 立即失效；
  - `reset()` 清空队列与 active（隔离）；
  - 旧 active 在 `expires` 前继续执行（记录 HOLDING），到期后 `NONE`；
  - 拒绝动作 id 不出现在 `executed_action_id`；重发同一动作不改变 `expires-issued`。

### 2.3 `src/boom_birds/sim/velocity_control.py`（只加可选字段）

`VelocitySetpoint` 追加默认字段（不得破坏既有位置参数构造）：`action_id: str = ''`、`sync_generation: int = -1`、`epochs: tuple | None = None`。`check()` 语义不变。

### 2.4 `scripts/run_dynamic_eval.py`（Lead 负责集成；其他成员不得改）

新增 CLI（命名固定，冻结与运行器共用）：

```
--config-id A|B            # 配对配置标识，进入 episode_id
--ttl-ms 150 --max-age-ms 150 --allowed-observation-age-ms 300
--clock-drift-ppm 0 --clock-uncertainty-ms 0   # 与既有 --clock-offset-ms 共用
--post-abort-observe-s 0
--obs-mapping-fail-step -1
--transport-stall-step -1 --transport-stall-delay-s 0.15
--segment-id ''            # 专项段标识，进入 episode_id
--freeze <path>            # 已存在；v2 schema 时做完整预冻结校验
```

行为：

1. 相机时钟域：`camera_clock = SimClock('camera_sim', offset_ns=clock_offset, drift_ppm=clock_drift, uncertainty_ns=clock_uncertainty)`；每步真实采集时刻 `capture_host_ns = max(0, host_now_ns - obs_delay_ns - case_observation_delay_ns)`；`capture_clock_ns = camera_clock.read_ns(capture_host_ns)`；`mapping = SimMapping('camera_sim','host_monotonic', offset_ns=clock_offset, uncertainty_ns=clock_uncertainty, drift_ppm=clock_drift, sync_generation=gate.sync_generation)`；用 `mapping_age()` 得到观测年龄点估计与保守上界；mapping 不可用或到达 `--obs-mapping-fail-step` 后 → 观测 `valid=False, reason='CLOCK_MAPPING_UNUSABLE'`。监督器使用**保守上界 age_bound_s**。
2. 动作构建：`observation_time_ns = mapped_capture_host_ns`（不得再用 `now_ns` 掩盖观测年龄）；`V2ActionGate.build(..., ttl_ns=ttl)`；`VelocitySetpoint` 带 `action_id/control_epoch/sync_generation/epochs`；每个 episode 开始把 `executor.control_epoch` 设为 gate 当前 control epoch，并 `update_context`。
3. 执行：每步 `executor.update_context(epochs=..., owner=...)` 后 `executor.step(setpoint, state, now_s)`，其中 `now_s` 统一使用与 gate 相同的时刻（修正现有 `elapsed` 与 `step*dt` 的 1 tick 偏差：setpoint `issued_at_s` 与 `expires` 均以 gate 的 `now_ns` 为准）。
4. ABORT 后物理观测：`--post-abort-observe-s > 0` 时，业务 ABORT 后继续推进 PhysX（不再发新动作、不再更新监督器），记录 `phase='POST_ABORT'`，直到窗口结束或接触/越界；用于证明"拒绝 ≠ 停止"与旧 setpoint 残余。
5. 每步记录（schema 见 §3）；episode 结束时从本 episode 原始 steps 重算 `metrics`（见 §3.2）；manifest/summary 增加 §3.3 字段；运行开始前调用冻结校验（§4.3）。

### 2.5 隔离与回归

- `--action-delay-s 0` 且时钟参数为 0 时，到达门不生效、观测年龄与既有路径一致；共享监督器/执行器语义不变 → 只需 pytest + 小规模默认参数 GUI 回归（1 无障碍 + 1 动态）证明隔离，不重跑昂贵的 24+ 旧运行。
- 改变的是延迟/时钟专项路径（仅 `--action-delay-s > 0` 或时钟参数非 0 时启用），报告必须写明该隔离依据。

## 3. 原始记录 schema（verifier 唯一依据）

### 3.1 `steps.jsonl` 每行（在原字段基础上新增，字段名固定）

```
phase: 'RUN' | 'POST_ABORT'
clock: {
  host_now_ns, capture_host_ns, capture_clock_ns, camera_clock_id,
  mapping_host_ns, mapping_error_ns, mapping_sync_generation,
  mapping_usable, mapping_reason, age_point_s, age_bound_s
}
observation_age_s            # = clock.age_bound_s（保留旧字段，语义为保守上界）
observation_valid, observation_reason   # 旧字段；mapping 不可用时 valid=False
transport: {
  status, action_id, executed_action_id, issued_at_ns, expires_at_ns,
  scheduled_arrival_ns, arrival_ns, dispatch_delay_s, arrival_age_s,
  reason, executed
}
applied: { vx_forward_mps, vy_left_mps, vz_up_mps, yaw_rate_ccw_world_radps,
           action_id, issued_at_ns, expires_at_ns, age_s, is_held }
# applied 为 None 时（无 active setpoint）记录零值 + action_id='' + is_held=False
v2_* 旧字段保留（admission/action_id/issued/expires/context/owner/source/fault）
```

`--action-delay-s 0` 时 `transport.status='DIRECT'`、`executed_action_id=action_id`；`applied` 仍记录。

### 3.2 `episodes.jsonl` 每行新增 `metrics`（运行器从 steps 重算，verifier 独立重算比对）

```
metrics: {
  brake_start: {step, time_s, position_world_m, velocity_world_mps, speed_mps,
                supervisor_state, observation_age_s} | null,
  initial_speed_mps, stop_distance_m, stop_time_s, stop_definition,
  final_speed_mps,
  min_center_distance_m, min_center_distance_time_s,
  min_envelope_gap_m, envelope: {body_half_extents_m, obstacle_half_extents_m,
                                 body_radius_m, obstacle_radius_m},
  max_closing_speed_mps, max_relative_speed_mps,
  contact_max_force_n, contact_prim,
  executed_action_count, arrival_rejection_count, arrival_reject_reasons,
  post_abort: {steps, residual_distance_m, time_to_stop_s, contact}
}
```
另加 `config_id`、`segment_id`、`pair_key = case_id`、`phase_summary`。

### 3.3 `manifest.json` / `summary.json` 新增

```
latency_plan: {role, segment_id, config_id, obs_delay_s, action_delay_s, ttl_ms,
               max_age_ms, allowed_observation_age_ms, stop_distance_m,
               post_abort_observe_s, sync_fail_step, obs_mapping_fail_step,
               transport_stall_step, transport_stall_delay_s, execution_path, methods, case_ids}
clock_plan: {camera_clock_id, offset_ms, drift_ppm, uncertainty_ms}
freeze: {path, sha256, schema_version, frozen_at, code_commit}
body_envelope: {half_extents_m, source='measured_usd_aabb_at_runtime', measured_prim}
evaluation_version: 'boom_birds.latency_eval.v1'
```

manifest 另记 `episode_ids`（唯一性）与 `gui_evidence`（日志窗口/渲染器关键行摘要）。summary 另记 `config_id`、`pair_key_coverage`、`expected_vs_actual`（不写 PASS 结论掩盖失败）。

## 4. 冻结（预运行）

### 4.1 共享契约模块 `src/boom_birds/evaluation/latency_plan.py`（freeze 负责）

纯标准库：

```
LATENCY_FREEZE_SCHEMA = 'boom_birds.latency_freeze.v2'
LATENCY_EVAL_VERSION  = 'boom_birds.latency_eval.v1'
build_run_plan(**kwargs) -> dict          # 字段见 3.3 latency_plan；float 统一 round(...,6)；case_ids 排序
build_freeze(...) -> dict                 # 完整冻结（见 4.2）
validate_run_plan(freeze, role, segment_id, config_id, run_plan) -> None
  # 逐字段比较，首个不一致抛 LatencyFreezeError；role='main' 查 main_run_plans[config_id]，
  # role='special' 查 special_segments[segment_id].run_plan
check_freeze_lineage(freeze, now_iso, repo_root) -> None
  # frozen_at 必须可解析且 <= now（禁止倒填/未来时间）；
  # freeze.code_commit 必须等于 `git rev-parse HEAD`；
  # freeze.worktree_state.digest 必须等于当前 `git status --porcelain -- src scripts tests configs`
  # 归一化字符串的 sha256（记录了哪些路径见 4.2）
```
`worktree_state`：`{tracked_paths: ['src','scripts','tests','configs'], status_text_sha256, clean}`；生成时计算，校验时重算。**冻结后修改相关源码/配置必须新建版本并重跑受影响配对，不得混用。**

### 4.2 冻结内容（`configs/scenarios/latency_pair_freeze_v2.json`、`latency_special_freeze_v2.json`）

至少包含：

- `schema_version/status='PRE_RUN_FROZEN'/frozen_at`（真实时间，UTC，禁止覆盖旧文件；生成脚本遇到已存在输出直接失败）；
- `code_commit`（实际 HEAD）、`worktree_state`（4.1）、`evaluation_version`；
- 12 个场景 `case_ids` + `cases_file` + `cases_sha256`；地图 `asset_id/terrain_sha256/preview_sha256/map_config_sha256`；
- A/B 配置 `stop_distance_m`（1.1/1.38）及各自完整 `run_plan`；
- `latency_plan`（obs 150 ms、action 100 ms、TTL 150 ms、max_age 150 ms、allowed_obs_age 300 ms、post-abort 观测窗口）；
- `clock_plan`（camera 偏移 20 ms、漂移 200 ppm、不确定度 5 ms、sync_generation 计划）；
- `evaluation`：监督器阈值（stop/release/prediction horizon/stop speed/observation max age/max wait）、`thresholds`、`expected`（逐 case 预期分类，标注"预期非结论"）；
- `body_envelope`（机体半尺寸来源：`measured_usd_aabb_at_runtime`，运行时测量写入 manifest；冻结中记录计划与容差）；
- `special_segments`：每段 `segment_id/case_ids/run_plan/expected`（见 §5）。

### 4.3 运行入口强制校验（`run_dynamic_eval.py`）

- 传 `--freeze`（v2 schema）时：`check_freeze_lineage`（时间、commit、worktree）+ `validate_run_plan` 全部通过才允许启动；任一不一致 `RuntimeError` 拒绝启动。
- manifest 记录 `freeze.sha256/frozen_at/code_commit`；`frozen_at <= started_at` 必须成立（运行后补写冻结会被拒绝）。
- 旧 schema 冻结（如 map_v2_regression_freeze_v1）走原有校验，不套用新字段（回归兼容）。

## 5. 正式运行分段（串行、独立目录）

主配对（同一 cases 文件、同一延迟/时钟/TTL，仅 stop 不同）：

| 段 | config | stop | cases | 预计 episode |
| --- | --- | --- | --- | --- |
| `latency_formal2_A` | A | 1.1 m | 12 个 `case_ids` | 12 |
| `latency_formal2_B` | B | 1.38 m | 同 12 个 | 12 |

专项（`segment_id` 固定）：

| 段 | 目的 | 用例 | 关键参数 | 预期分类（预冻结） |
| --- | --- | --- | --- | --- |
| `ttl_near` | 近 TTL 接纳 | `dynamic_B_north_0`（巡航 0.56 m/s 制动） | delay 0.10 s、TTL 120 ms、obs 0.15、stop 1.1 | 到达年龄 100 ms < 120 ms 接纳并记录 20 ms 余量；业务预期 STOP_WAIT_RESUME |
| `ttl_over` | 超 TTL 拒绝 | `dynamic_B_north_0` | delay 0.10 → 制动前 stall 到 0.15 s、TTL 150 ms | 制动命令到达年龄 150 ms ≥ TTL → 到达拒绝，未执行；记录旧 setpoint 残余与零目标回退；不宣称实机失效后果 |
| `clock_sync` | sync 代次失效（传输中） | `dynamic_B_north_0` | `--sync-fail-step` 制动前 ~2 tick | 接纳拒绝 `REJECT_SYNC_OR_PX4_BOOT`；在途动作到达拒绝；post-abort 观测旧 setpoint 到期后 NONE |
| `clock_mapping` | 相机时钟映射失效 | `dynamic_B_north_0` | `--obs-mapping-fail-step` | 观测 `CLOCK_MAPPING_UNUSABLE`、监督器 DEGRADED→ABORT；动作因观测过期被拒；post-abort 继续观测 |
| `regression_no_obstacle` | 隔离回归 | 1 个 `map_v2_regression_cases_v1` route | 默认 0 延迟/0 时钟 | 与既有 v2 证据一致 SUCCESS |
| `regression_dynamic` | 隔离回归 | `dynamic_A_south_0` | 默认 0 延迟/0 时钟 | 与既有 v2 证据一致 SUCCESS |

专项"近/超 TTL"与"两个时钟失效"合计 ≥4 段；不足 12 场景的覆盖（静态障碍 C、动态 A/B/D、观测退化 E、速度档 0.7/0.4/0）由主 12 场景 + 专项共同覆盖，不删除验收项。主 A/B 必须同初始状态、同障碍轨迹、同延迟/时钟条件，只改停止阈值。

## 6. 独立核验脚本 `scripts/verify_latency_runs.py`（verify 负责）

纯标准库；输入主 A/B 目录、专项段目录、冻结、运行器前序证据；**从原始 steps/episodes/manifest 重算**，不读 summary 的 PASS 标签作为依据。检查项（至少）：

1. capture/arrival/issued/admitted/executed 时间及所属时钟域；mapping 往返与误差界；`host_now_ns` 与 `time_s` 一致性。
2. 观测年龄点估计/保守上界、动作排队时间、映射可用性与 sync 代次。
3. 重发不续期（`expires-issued == ttl`，全程恒定）；到期拒绝（age ≥ ttl ⇒ `ACTION_EXPIRED`）；sync/epoch 失效；被拒绝动作 id 永不出现在 executed；HOLDING 只在 `now < expires` 且上下文不变时出现，到期后 NONE。
4. 制动起点（首个 STOP 决策）、初始实测速度、停止距离/时间（定义：沿初始速度方向到速度 ≤0.08 m/s 持续 0.5 s），与运行器 `metrics` 独立比对。
5. 中心距离、机体/障碍包络间隙（球保守半径 = max 半尺寸；机体半径来自 manifest 实测 AABB）、相对/接近速度、接触力。
6. episode 连续性（步长/时间单调、无未声明 reset、boundary_count_ok、终止分类唯一）、A/B 配对一致（同 case 集合、延迟/时钟相同、仅 stop 不同）、分母（12/12 + 专项）、episode_id 唯一、产物 hash 与 manifest/freeze 一致、GUI/DirectX/无 headless、冻结先于运行。
7. 专项预期分类核对（不把预期当结论；不一致如实 FAIL 并列出）；post-abort 原始行存在且展示拒绝后旧 setpoint/零目标执行。
8. 输出 JSON：`status PASS/FAIL/INCOMPLETE`、逐项 checks、重算数值范围、失败清单。缺原始字段 → INCOMPLETE（不得默认 PASS）。

## 7. 参数分析（Lead）

`scripts/analyze_latency_envelope.py`（纯标准库）读取正式主/专项核验产物与 `docs/reports/map_eval/brake/evidence/brake_cases_v1.json`（前序正式制动证据）回答：

- stop=1.1/1.38 m 的距离定义：监督器 `clearance` = 障碍中心预测轨迹到"机器人当前位置→当前航点"线段的最小距离（1 s/0.1 s 预测），**不是中心距、不是表面间隙**。
- 扣除机体/障碍包络后的实际间隙；制动起点处的中心距、间隙、相对接近速度、观测年龄、动作延迟。
- 组合判据：`required_clearance ≈ brake_distance(v) + v_self*transport_delay + closing_speed*obs_age + envelope_sum + margin`；区分实测（brake_final4 距离、正式 latency 片段）、推导（公式）、近似（速度-制动距离插值）、未确认（实机/PX4 失效语义）。避免把已含在实测停止距离内的延迟重复计入。
- TTL=150 ms 与 50 ms 控制步长：到达年龄只能落在 0/50/100/150 ms，150 ms 即过期 → 实际可容忍传输延迟 ≤100 ms（2 tick）；给出近/超 TTL 专项证据与适用范围。
- 明确"无人机停止 ≠ 移动障碍停止"；样本最大值不是严格最坏上界，不是实机安全包络。

## 8. 交付物与提交

- 代码：`src/boom_birds/evaluation/{dual_clock,action_transport,latency_plan}.py`、`src/boom_birds/sim/velocity_control.py`（可选字段）、`scripts/{run_dynamic_eval,make_latency_freeze,verify_latency_runs,analyze_latency_envelope}.py`、测试。
- 冻结：`configs/scenarios/latency_pair_freeze_v2.json`、`latency_special_freeze_v2.json`（以及专项 case/expected 配置）。
- 证据：`docs/reports/map_eval/latency/`（summary/episodes/manifest/steps 摘要、hash、核验 JSON、截图；原始 outputs 不入 Git，引用 hash）。
- 报告：`docs/reports/map_eval/MAP_LATENCY_ENVELOPE_REPORT.md`；交接：`docs/reports/HANDOFF_20261102_LATENCY_ENVELOPE.md`。
- 提交：只包含本工作包文件，中文消息，不推送；不纳入用户/上一工作包的 23 个已修改文档与既有 untracked 文件（`latency_pair_freeze_v1.json` 作为探索证据可纳入，标注运行后生成）。
- 收尾：全套 `pytest -q`、`scripts/planning/audit_documents.py`、diff 检查、独立核验、GUI 证据；未完成项如实保留（NOT RUN/INCOMPLETE/UNKNOWN）。

## 9. 写域与任务

| 任务 | 写域 | 说明 |
| --- | --- | --- |
| T1 实现到达门与双时钟 | `src/boom_birds/evaluation/dual_clock.py`、`action_transport.py`、`src/boom_birds/sim/velocity_control.py`、`tests/evaluation/*` | 先失败测试；不改 `run_dynamic_eval.py` |
| T2 冻结与专项契约 | `src/boom_birds/evaluation/latency_plan.py`、`scripts/make_latency_freeze.py`、`configs/scenarios/latency_*.json`（v2/专项/expected）、`tests/evaluation/test_latency_plan.py` | 不改运行器/判据脚本 |
| T3 独立核验 | `scripts/verify_latency_runs.py`、`tests/evaluation/test_verify_latency_runs.py` | 不改运行器/实现 |
| T4 运行器集成 | `scripts/run_dynamic_eval.py` | 仅 Lead |
| T5 正式运行/分析/报告/提交 | outputs、docs、configs 冻结产物、Git | 仅 Lead |

所有成员：不得启动 Isaac（GUI 运行仅 Lead 执行）、不得提交 Git、不得改用户已修改的文档、不得 `--headless`；遇到阻塞在共享任务里记录证据。
