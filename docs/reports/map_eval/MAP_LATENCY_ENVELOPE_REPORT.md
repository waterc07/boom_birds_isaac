# 动作延迟包络正式评价报告（2026-11-02）

> **状态：** ASSESSMENT（实现覆盖 + 预冻结正式运行 + 独立核验 + 参数结论）；仅当前仿真模型证据，不是实机安全包络、不是 PX4 failsafe、不提升任何 Gate
> **来源章节：** V2.2 §10.4、§16.1–16.3、§16.6、§17.3、§26.6–26.7、§27.3–27.7；`docs/superpowers/plans/2026-11-02-latency-envelope.md`
> **证据域：** 标准库单元测试 + 前台可视 GUI 仿真动力学（DirectX/D3D12）
> **最后核对：** 2026-11-02

## 1. 结论

- **实现覆盖：** 动作传输到达门（TTL/六元组上下文/所有权/sync 代次到达校验、旧 setpoint 到 `expires` 前继续执行、拒绝动作永不执行、reset/撤权队列隔离）与模拟双时钟（偏移/漂移/映射误差上界，观测年龄取保守上界）已接入 GUI 动力学链；两者仅在 `--action-delay-s > 0` 或时钟参数非 0 时启用，默认路径行为与既有 v2 评价一致（隔离回归 2/2 SUCCESS）。
- **预运行冻结：** 正式证据基于提交 `0c03281b7594f38e2274799afa1b1ab31896abc2` 与 `2026-11-02T05:12:31Z` 生成的 `latency_pair_freeze_v2.json` / `latency_special_freeze_v2.json`；运行入口强制校验 frozen_at ≤ started_at、git HEAD、工作树 digest 与逐字段 run_plan。运行开始后未修改 `src/scripts/tests/configs`。
- **正式运行：** A/B 各 12 个预冻结 episode 完成（合计 24，SUCCESS 6 / ABORT 6，每配置独立目录）；专项 4 段完成（ttl_near SUCCESS；ttl_over TIMEOUT；clock_sync ABORT V2_REJECT_SYNC_OR_PX4_BOOT；clock_mapping ABORT V2_REJECT_STALE_OBSERVATION）；隔离回归 2 段 SUCCESS。失败与重试目录全部保留。
- **距离定义（回答 stop=1.1/1.38 m）：** 阈值作用于监督器的预测**路径净空** `clearance = min_{t∈[0,1s],Δ=0.1s} dist(障碍预测中心, [机器人当前位置→当前航点线段])`，**不是中心距、不是表面间隙**。独立重放重建显示：A 配置 B 类事件触发时 clearance 1.088–1.096 m（阈值 1.1），B 配置 1.133–1.362 m（阈值 1.38），与阈值定义一致；而触发时实测**中心距**为 4.02–11.11 m，说明阈值不可与中心距/间隙混读。
- **包络后实际间隙（推导）：** 阈值处路径净空扣机体/障碍球包络（机体取运行时实测 AABB 半尺寸 max=0.0545 m，障碍 0.4×0.4×0.6 → 0.3 m）后：A 配置 ≈0.745 m，B 配置 ≈1.025 m。实测本组 episode 的最小中心距/间隙分别为 A 3.50/3.14–10.45 m、B 3.77/3.41–10.45 m（障碍多在远处通过或场景提前停车，**不构成高速接近的安全证明**）。
- **参数组合（推导，含实测项）：** 以"STOP 决策触发→停止"的实测停止距离为基准（已含 100 ms 传输延迟，不重复加）：
  `required_clearance ≈ measured_stop_distance + closing_speed × observation_age + body_radius + obstacle_radius`。
  本组最苛刻事件（`v0=0.623–0.625 m/s`，`closing≈0.69–0.70 m/s`，`observation_age_bound=0.228 s`）：A 配置 required≈0.812–0.814 m、余量≈0.286–0.288 m；B 配置 required≈0.818–0.819 m、余量≈0.561–0.562 m。若改用前序 `brake_final4` 执行器级制动距离并显式加 `v0×action_delay`，A 余量≈0.091–0.093 m、B≈0.369–0.370 m。**两种分解都表明观测到的组合支持 1.1/1.38 m 停止；1.38 余量更大；样本只到 v≈0.64 m/s、closing≈0.70 m/s，不是严格最坏上界。**
- **TTL=150 ms 适用性（实测）：** 50 ms 控制步长下到达年龄量化在 0/50/100/150 ms；150 ms 即 `now>=expires` 被拒绝，因此 TTL=150 ms 实际可容忍传输延迟 ≤100 ms。主 A/B 共 17,507 次到达全部 age=0.100 s 被接纳、0 次拒绝；ttl_near（TTL=120 ms）age=0.100 s 余量 20 ms 接纳；ttl_over（制动前 stall 到 0.15 s）900 次 ACTION_EXPIRED 拒绝、被拒制动命令从未执行，旧 active 在 step 296–301 仍有执行、step 302 到期→NONE，首次拒绝后残余距离 0.221 m（速度 0.578→0，TIMEOUT）。**TTL 约束陈旧命令，不保证交付；本仿真的无命令回退是零目标 hold，不是 PX4 Offboard-loss failsafe，不能据此给出实机失效后果。**
- **预测时域 1.0 s：** 前序实测制动时间可达 3.25–3.30 s、停止时间远大于 1 s；1 s 预测只覆盖障碍未来 1 s 轨迹，不能替代停止阈值/最大等待。本组 A/B 场景的停车都在预测与净空阈值内完成，但 C/D/E 类以等待超时/观测退化退出，说明阈值需与退出条件共同评估。
- **停止≠障碍停止（实测）：** B 类停车后障碍仍在运动；停车后障碍中心距继续变化（B_south_1/B_north_0 更近 0.010–0.015 m，B_south_0 更近 0.087 m；振荡障碍 D 距离变化 ±0.015 m）。"无人机已停"不能推出"移动障碍不再撞来"。
- **时钟失效专项：** clock_sync 在 step 300 注入 sync 代次变化 → 当步接纳拒绝 `REJECT_SYNC_OR_PX4_BOOT`，在途旧 sync 动作到达亦被拒绝（age=0.100 s < TTL，证明是传输中失效而非超时）。clock_mapping 在 step 280 使相机时钟映射不可用 → 观测 `CLOCK_MAPPING_UNUSABLE`、动作提交因观测年龄不可证被拒 `REJECT_STALE_OBSERVATION`、业务 ABORT；映射误差上界在主运行中由 25.01 ms 增长到 37.07 ms（20 ms 偏移 + 5 ms 不确定度 + 200 ppm 漂移），观测年龄保守上界最大 0.2766 s。
- **预冻结预期分类偏差（如实记录，不修改冻结）：** clock_mapping 的预冻结 expected 预期 reason 为 `OBSERVATION_STALE`，实际业务 reason 为 `V2_REJECT_STALE_OBSERVATION`（契约在动作提交前拒绝，早于监督器 abort）。该机制也在预冻结 expected 的 `admission_reject_reason='REJECT_STALE_OBSERVATION'` 中列出；**偏差在核验 JSON 与本节明示，不当作 PASS 静默**。
- **验证状态：** 见 §8（独立核验脚本从原始 steps/episodes/manifest 重算，不读取 summary 的 PASS 标签）。独立核验 **PASS**：`status=PASS`、checks 20/20 passed、failures=0、missing_fields=0（`verify_latency_runs.json`，冻结/产物 hash 与世系均校验）。clock_mapping 预期 reason 偏差已显式记录：[{"kind": "expected_reason_deviation", "run": "clock_mapping", "episode_id": "special_stop_north-supervisor-clock_mapping", "expected_reason": "OBSERVATION_STALE", "actual_reason": "V2_REJECT_STALE_OBSERVATION", "matched_field": "admission_reject_reason", "matched_value": "REJECT_STALE_OBSERVATION", "detail": "expected reason OBSERVATION_STALE -> actual V2_REJECT_STALE_OBSERVATION; matched pre-frozen admission_reject_reason=REJECT_STALE_OBSERVATION"}]。
- **边界：** 单仿真模型；无真实跨时钟/串口/PX4/执行器延迟；无 PX4 Sender；未跑 PPO、真实感知、板端、SITL/HIL、实机；不提升 Gate；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK。

## 2. 现场与证据链（探索证据 vs 正式证据）

| 类别 | 目录/文件 | 说明 |
| --- | --- | --- |
| 探索证据（不得升级为正式） | `outputs/map_eval/latency_formal_A|B`、`latency_A1`、`latency_B1/B2/B3_seg*`、`latency_queue_debug`、`latency_sync_debug`、`latency_clockfail1`、`latency_debug2` | 旧 A/B 各 12 运行在 `latency_pair_freeze_v1.json`（`status=FROZEN_AFTER_RUNS_RECORDED`，无 frozen_at）之后生成；仅作探索；旧运行缺少 clock/transport/applied/metrics 字段，核验脚本对其输出 INCOMPLETE 而不是 PASS |
| 预运行冻结（正式） | `configs/scenarios/latency_pair_freeze_v2.json`、`latency_special_freeze_v2.json` | commit `0c03281`，frozen_at `2026-11-02T05:12:31Z`（本地 13:12），运行前生成 |
| 正式运行 | `outputs/map_eval/latency_formal2_A|B`、`latency_ttl_near`、`latency_ttl_over`、`latency_clock_sync`、`latency_clock_mapping`、`latency_regression_no_obstacle`、`latency_regression_dynamic` | 串行分段、每段独立目录；前台可见 GUI（DirectX/D3D12，`--/app/vulkan=false`，未使用 `--headless`） |
| 版本化证据 | `docs/reports/map_eval/latency/evidence/`、`docs/reports/map_eval/latency/screenshots/` | 冻结/配置副本、每段 summary/episodes/manifest 与 steps hash、GUI 日志摘录、截图、核验/分析 JSON |
| 冻结版本迭代（保留） | `docs/reports/map_eval/latency/evidence/invalid_freeze_attempt1/` | 第一次 v2 冻结（`frozen_at 05:09:13Z`）在运行前因核验器脚本更新导致工作树 digest 变化，运行入口按设计拒绝启动（`WORKTREE_STATE_MISMATCH`），未产生任何正式数据；该冻结与拒绝日志按"禁止覆盖旧文件"保留后重新生成有效冻结 |

运行入口拒绝示例（证据）：`outputs/map_eval/latency_formal2_A/summary.error.txt`（首次尝试，stages 仅 `load contract and cases`，异常 `WORKTREE_STATE_MISMATCH`；该目录随后被正式运行覆盖，原始错误文本已复制到 `evidence/invalid_freeze_attempt1/`）。

## 3. 实现与隔离

- `src/boom_birds/evaluation/dual_clock.py`：`SimClock` 偏移/漂移；`SimMapping.map_uncertainty_ns(host_reference_ns)` = `|offset|+uncertainty+ceil(|drift|·1e-6·|t|)`；`mapping_age()` 输出点估计与保守上界，不可用/同步代次不符/窗口外返回 `CLOCK_MAPPING_UNUSABLE` 且年龄为 None（拒绝用零伪装有效）。
- `src/boom_birds/evaluation/action_transport.py`：`DelayedActionQueue` + `DelayedVelocityExecutor` 到达门。到达校验顺序 TTL→六元组 epochs→sync→owner；被拒动作不进入执行器；active setpoint 保留原始 `expires` 并每步复核（到期/撤权/上下文失效→丢弃），撤销/重置清空队列与 active；`last_transport`/`arrivals`/`rejections` 记录原始到达事实。
- `scripts/run_dynamic_eval.py`：相机时钟域与映射年龄上界；动作 header 使用映射后的真实采集时刻（保守取 `mapped−error_bound`；映射不可用时以"年龄不可证"策略拒绝）；`transport`/`applied`/`clock` 每步记录；ABORT 后 `--post-abort-observe-s` 物理观测窗口（拒绝≠停止）；episode 指标从本 episode 原始 steps 重算；机体包络取运行时 USD AABB；manifest/summary 记录 latency/clock/freeze/gui/body envelope；v2 冻结强制校验。
- **隔离依据：** 新语义只在 action delay > 0 或时钟参数非 0 时启用；`--action-delay-s 0` 且时钟 0 时 `transport.status=DIRECT`、观察年龄与既有路径一致。回归 `regression_no_obstacle`（1 个 v2 无障碍 route）与 `regression_dynamic`（`dynamic_A_south_0`）在默认参数下 SUCCESS，与既有 v2 证据一致；共享监督器阈值/逻辑未修改，故未重跑 20+8 昂贵旧集。

## 4. 正式结果

### 4.1 主配对（预冻结 12 场景 × A/B）

| 配置 | episode | SUCCESS | ABORT | TIMEOUT | COLLISION | INVALID | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A（stop=1.1 m） | 12 | 6 | 6 | 0 | 0 | 0 | A/B 类各 3 成功；C/D 等待超时退出；E 观测退化退出 |
| B（stop=1.38 m） | 12 | 6 | 6 | 0 | 0 | 0 | 逐 case 结果与 A 相同；触发时刻/停止距离不同 |

A/B 同场景、同初始状态、同障碍轨迹、同观测/动作延迟（150/100 ms）、同 TTL=150 ms、同时钟计划（偏移 20 ms/漂移 200 ppm/不确定度 5 ms），仅 `stop_distance_m` 不同。episode_id 含 config 后缀（`...-supervisor-A/B`），无重复计数。单位置匹配在 `docs/reports/map_eval/latency/verify_latency_runs.json`（pair_consistency）。

### 4.2 专项段（预冻结）

| 段 | 结果 | 关键原始证据 |
| --- | --- | --- |
| ttl_near（TTL=120 ms，delay=100 ms） | SUCCESS | 1,105 次 APPLIED，arrival_age=0.100 s，TTL 观测 120 ms，余量 20 ms；0 拒绝 |
| ttl_over（制动前 stall 至 150 ms） | TIMEOUT（WALL_TIMEOUT） | 900 次 ACTION_EXPIRED 拒绝（age≈0.150 s）；step 296–301 旧 active 仍执行；step 302 到期→NONE；被拒制动命令从未执行；首次拒绝后残余位移 0.221 m（0.578→0 m/s）；post-abort 60 行 |
| clock_sync（step 300 sync 代次变化） | ABORT `V2_REJECT_SYNC_OR_PX4_BOOT` | 当步接纳拒绝 1 次；在途旧 sync 动作到达拒绝 1 次（age=0.100 s < TTL）；post-abort 60 行，旧 setpoint 到期后 NONE |
| clock_mapping（step 280 映射不可用） | ABORT `V2_REJECT_STALE_OBSERVATION` | 1 行观测 `CLOCK_MAPPING_UNUSABLE`；动作因观测年龄不可证被拒；post-abort 60 行；预冻结 expected reason 偏差见 §1 |
| regression_no_obstacle（默认 0 延迟/0 时钟） | SUCCESS | 与既有 v2 无障碍回归一致；DIRECT 传输 |
| regression_dynamic（`dynamic_A_south_0`，默认参数） | SUCCESS | 与既有 v2 动态证据一致；DIRECT 传输 |

### 4.3 制动/接近几何（独立重算，见 analysis JSON）

| 指标（正式 A/B 触发事件，n=9/配置） | A 配置 | B 配置 |
| --- | --- | --- |
| 触发时实际速度范围 | 0.033–0.639 m/s | 0.073–0.639 m/s |
| 触发时观测年龄保守上界 | 0–0.228 s（E 类观测失效行除外） | 同左 |
| 重放重建 clearance（预测路径净空） | A/B 类 1.088–1.096 m | A/B 类 1.133–1.362 m |
| 触发时中心距（实测） | 4.02–11.11 m | 4.02–11.11 m |
| 触发时包络间隙（实测） | 3.66–10.75 m | 3.66–10.75 m |
| 阈值处包络间隙（推导） | 0.745 m | 1.025 m |
| 实测停止距离（触发→停，含传输） | 0.001–0.315 m | 0.001–0.315 m |
| 实测停止时间 | 0.45–1.30 s | 0.45–1.30 s |
| 实测最小中心距/间隙（全 episode） | 3.50 / 3.14–10.45 m | 3.77 / 3.41–10.45 m |

## 5. 参数分析（回答原目标问题）

### 5.1 stop=1.1/1.38 m 的距离定义与包络间隙

- 定义（源码 `RouteSupervisor._risk`，独立重放交叉验证）：`clearance` 为障碍**预测**中心轨迹（观测位置+观测速度，1.0 s、0.1 s 步长）到"机器人当前位置→当前航路点"线段的最小距离；`risk = clearance < stop_distance_m`。
- 阈值处路径净空扣机体/障碍包络（实测 AABB 半尺寸 max=0.0545 m + 障碍 0.3 m）后的实际间隙：A 0.745 m、B 1.025 m（推导；阈值本身是预测净空，不是表面间隙）。
- **不要混用中心距：** 触发时实测中心距 4–11 m，因为障碍位于路径前方/路径上，`clearance` 可在远距离即小于阈值。历史报告中的"中心点到航段距离"口径与此一致。

### 5.2 观测年龄、动作延迟、相对接近速度与制动需求的组合

- 观测年龄：主 A/B 的 `observation_age_bound` 随漂移由 0.225 s 增到 0.277 s（E 类 0.25–0.277 s）；阈值 1.0/1.38 m 的判定使用该保守上界。
- 动作延迟：固定 100 ms（2 个控制 tick），到达/执行记录显示 age=0.100 s、TTL 余量 50 ms。
- 组合判据（两种分解，避免重复计入已验证延迟）：
  1. **实测基准**（推荐用于本数据）：`required = measured_stop_distance(触发→停，含 100 ms 传输) + closing×age + body_r + obstacle_r`。最苛刻事件 A required≈0.812 m、余量 0.288 m；B required≈0.819 m、余量 0.561 m。
  2. **brake_final4 基准**：`required = brake_distance(v0) + v0×action_delay + closing×age + body_r + obstacle_r`。最苛刻事件 A required≈1.007 m、余量 0.093 m；B≈1.010 m、余量 0.370 m。该基准保守，因为 `brake_final4` 从执行器实际制动起点测量，故显式加传输延迟项。
- 支持停止的组合（本数据）：`v ≤0.64 m/s`、`closing ≤0.70 m/s`、`observation_age ≤0.228 s`、传输 100 ms（TTL 余量 50 ms）→ 两种阈值均满足，1.38 余量更大；C/D 类以"停车等待→超时退出"结束，E 类以观测退化退出（符合预期分类）。
- 应拒绝/退出的组合：路径被静态/慢速障碍持续占用（C/D）→ 停车等待后 `MAX_WAIT_EXCEEDED` 退出；观测丢失/退化（E）→ `DEGRADED→ABORT`；clock_sync/clock_mapping 注入 → 动作在提交/到达被拒 → ABORT；超 TTL 传输（ttl_over）→ 制动命令到达被拒、零目标回退、route 超时。
- 超出当前能力（未确认/不能外推）：传输延迟 ≥TTL（150 ms 且当前 50 ms tick 下有效上限 100 ms）；相对接近速度超过本组最大 ≈0.70 m/s 或机体速度超过 0.64 m/s；制动距离只测到 0.851 m/s；样本最大值不是严格最坏上界，也不是实机安全包络。

### 5.3 TTL=150 ms 与预测时域 1.0 s 的适用范围

- TTL：只约束"命令陈旧性"。在 50 ms tick 下，到达年龄只有 0/50/100/150 ms 四档；150 ms 即过期，所以 **TTL=150 ms 实际可容忍传输延迟 ≤100 ms（2 tick）**，主运行 100 ms 正好用满 2/3 TTL；ttl_near（TTL=120 ms）证明 20 ms 余量可接纳；ttl_over 证明 ≥TTL 的传输会使制动命令被拒。TTL 不限制观测年龄（观测年龄由映射上界与监督器阈值单独判定）。
- 超 TTL 的物理后果本仿真**不能外推**：无 setpoint 时执行器进入零目标 hold（不是 PX4 Offboard-loss failsafe），因此 ttl_over 表现为命令未接纳+回退+route 超时，而不是实机失控/滑行。
- 预测时域 1.0 s：只覆盖障碍未来 1 s；前序 `brake_final4` 实测停止时间 1.25–3.30 s，1 s 预测不能替代停止阈值/最大等待；本组 B 类在触发后 1.25 s 内停稳，但预测时域仍不是保守安全界。

## 6. 停止 ≠ 障碍停止 / 样本边界

- B 类停车后障碍继续运动：实测停车后中心距变化 B_south_1 +0.010 m、B_north_0 +0.010 m、B_south_0 +0.087 m 更近；D 振荡障碍 ±0.015 m；E 静止障碍无移动。**"我方已停"不等于"风险消失"。**
- 本组所有 episode 无接触（contact 0），但这是因为监督器在较远距离（净空阈值）即停车/退出；不能用来说明高速/近距离交叉场景安全。
- 样本量：主 24（12 配对）+ 专项 4 + 回归 2；速度档 0.4/0.7 m/s 障碍、机体 ≤0.64 m/s；无高速接近专项（列入下一工作包）。
- 单仿真模型、单地图、单机体；ORACLE 障碍观测不是视觉；不覆盖真实时钟/串口/PX4 延迟。

## 7. GUI 与可追踪性

- 所有 Isaac 运行均前台可视 GUI：日志含 `Graphics API: D3D12`/`Driver Version 581.80`、窗口/渲染扩展与 `Simulation App Startup Complete`；未出现 `--headless`（`evidence/gui_evidence.json` 每 run 记录匹配行与日志 hash）。
- 截图：A/B 各 2 张成功场景（`screenshots/`），共 4 张；原始截图产物 hash 记录在 `evidence/hashes.json`。
- 代码 commit：正式运行 `0c03281b7594f38e2274799afa1b1ab31896abc2`；冻结/配置/cases/地图/产物 hash 记录在 `evidence/hashes.json` 与 manifest。

## 8. 独立核验

- 脚本：`scripts/verify_latency_runs.py`（纯标准库；不读 summary、重算 raw steps/episodes/manifest；缺字段→INCOMPLETE）。
- 输出：`docs/reports/map_eval/latency/verify_latency_runs.json`。
- 覆盖：20 项检查——raw schema 完整性、时钟域/映射往返与误差界、观测年龄/排队、TTL 不续期、到达过期拒绝、被拒动作永不执行、HOLDING→NONE、applied 一致性、制动起点/停止距离时间、中心距/包络/接近速度、episode 连续性与配对/分母/唯一 id、预期分类、产物 hash、冻结世系、GUI 证据、专项段、post-abort 原始行。
- 结论：`status=PASS`，20/20 checks passed，0 failures，0 missing fields；A/B 12/12 case、pairs 一致（仅 stop 不同）、episode_id 唯一；专项与回归按预冻结段校验；ttl_over 队列时序说明（单调发布队列：超时到达必晚于 active expires，残余只会出现在首次拒绝前的 APPLIED/HOLDING 行，拒绝行 applied=None 为预期形态）已写入 JSON 的 `recomputed.notes.ttl_over_queue_timing`。clock_mapping 的预冻结 expected_reason 偏差记录于 `recomputed.expected_reason_deviations`：[{"kind": "expected_reason_deviation", "run": "clock_mapping", "episode_id": "special_stop_north-supervisor-clock_mapping", "expected_reason": "OBSERVATION_STALE", "actual_reason": "V2_REJECT_STALE_OBSERVATION", "matched_field": "admission_reject_reason", "matched_value": "REJECT_STALE_OBSERVATION", "detail": "expected reason OBSERVATION_STALE -> actual V2_REJECT_STALE_OBSERVATION; matched pre-frozen admission_reject_reason=REJECT_STALE_OBSERVATION"}]

## 9. 证据与 hash（`docs/reports/map_eval/latency/evidence/`）

| 产物 | SHA-256 |
| --- | --- |
| `latency_pair_freeze_v2.json` | `02480584fa0146375843df15ef0ec65a06186c9f726b8a331a959535131da1eb` |
| `latency_special_freeze_v2.json` | `c971ad7b7d1434d9b83db7f6062e81dbdae04cc17f1052faafd5c096cfea35cd` |
| `latency_expected_v1.json` | `589cec7b2bf0e47392837a5f27f0e23b25106fe33889271fe9b5ced2adf0d44d` |
| `latency_special_cases_v1.json` | `717878a70ea1f7ac0ecfbc63167dd23c209b5a67eb4de87e7e0c0a4f93794032` |
| `main_A/summary.json` | `42e142e91a3edd974ed58c434e05fecf65ea47fa0319a81f11d5640ed4043b68` |
| `main_A/episodes.jsonl` | `621c5eadaaacd38dd11b685119c707863b27e68a8665e44db7d32729e2f6a6a9` |
| `main_A/manifest.json` | `e724a83816942bca8f2435a41169f0bb8251b9dcfbae430562fbf6058dd6b6f5` |
| `main_A/steps.jsonl (raw, gitignored)` | `ab26c0486ecb02ba89d80ef7a09562034a46454ef7326023ae92ad37bb305148` |
| `main_B/summary.json` | `4ae5025faead1f650561317068ae8cde0a8e0ce0f1bf85155a528e92d08e4084` |
| `main_B/episodes.jsonl` | `29e34b37cd2870cebd0562894cc48b4159c44c8ab64e73333c5f2682e94775d7` |
| `main_B/manifest.json` | `82b552f0f625b06bc2fc64019fd0a7759e38dee35701a1b6d096288424e26c94` |
| `main_B/steps.jsonl (raw, gitignored)` | `4192d9ca052c5ac7b059826fa7ac42d5b53a38a4bd9d524b128723ec5430ad7c` |
| `ttl_near/summary.json` | `159deb9b2258bd723ce8dd616ba6dad5a62048834686ebabb5d25f5470e3e55f` |
| `ttl_near/episodes.jsonl` | `2e6b2426ebc968457071e3b7641c91bd1c80d25ec25c5c796368090d8b71bb8b` |
| `ttl_near/manifest.json` | `e38525fc565d7e0e4ef2a09663d10eae714d0018ce6fe3e8aba4c3fc5af2921c` |
| `ttl_near/steps.jsonl (raw, gitignored)` | `bf0596079a51c5aee3ab728a43083a384eeb40103dc9c208684d20f5dff628c3` |
| `ttl_over/summary.json` | `60e691855b47b161f143c5cf1d319aa0a84520081c9bb04466e09a13cb0a1565` |
| `ttl_over/episodes.jsonl` | `6a736de11ff6f9e12981917b7bdba2a6dca97032f809089028afef3f4fa34966` |
| `ttl_over/manifest.json` | `bb6b3a69164be9e7d2818fa87f2edc3b58af001105fe452119101557188d246c` |
| `ttl_over/steps.jsonl (raw, gitignored)` | `5ce444c0fef6babd1f6f72a3d76e073d7e8f8ee824c302f369468795422ee1c3` |
| `clock_sync/summary.json` | `d8e8de3845a6985e321449368d3a4f27ae8b966e8495d80f248c848bd3ccfdd6` |
| `clock_sync/episodes.jsonl` | `e67850a361a31911ac89805462bdd3e408f8865248f0ad64f1402272410654c8` |
| `clock_sync/manifest.json` | `45c97dfb616f5b62aacddeb23aeebf9b676708a9cdc46a3e0f382af243aebbb7` |
| `clock_sync/steps.jsonl (raw, gitignored)` | `0ede8c60d3d72985aaec485c8f092eba6943619453447e4772328cad5eb2c092` |
| `clock_mapping/summary.json` | `3c4786d31225df1eda18a3528efdaee5e68cdbe8f13fd56e66fdabdc950f9157` |
| `clock_mapping/episodes.jsonl` | `9c2e4c015c897a67da5c7b6f21eef061b8ed3de62bd424becfda8941948405e3` |
| `clock_mapping/manifest.json` | `20adb61b76d1189e56f7e201f50b5f4afdf8c194f27e4be6d9e6c9dfaa04b243` |
| `clock_mapping/steps.jsonl (raw, gitignored)` | `ca43c6f284770f7546e1a79fe78981fb4a991d762181ff15dcb34f32717878b1` |
| `regression_no_obstacle/summary.json` | `f7ecac6d695f824056ef56d9c58a216ecc3a4d601a442336599f449cfca299d8` |
| `regression_no_obstacle/episodes.jsonl` | `bbc3f7b17a0a2491048c8eb5edfc1286cb98e2fd5efb6aa45864fffa94537b1c` |
| `regression_no_obstacle/manifest.json` | `72a815b722883e6c657bb37746118863b6f90a155c042312f7b086b54b0a2059` |
| `regression_no_obstacle/steps.jsonl (raw, gitignored)` | `aefe1fc488956a6b890d04a116f5e366d33e8ab7e29f28f0082e45647e7b782b` |
| `regression_dynamic/summary.json` | `f9022b086e7cf2d490d1207b014d2b2babf4ad201b9d2b2c72bd7e7b4a4e643d` |
| `regression_dynamic/episodes.jsonl` | `1d867e9dc61a8b41bb8c86461c05456edb046ea7d51389b7f30732c4ad7c47a0` |
| `regression_dynamic/manifest.json` | `456c09e8845667bc28fc3a10d19ac4971de4deadcac26735cf9906f4ce2951fb` |
| `regression_dynamic/steps.jsonl (raw, gitignored)` | `5a1f2b3f711b469310059284259d41dbf04be335a6bd4a79ff04a619bb03e0cf` |
| `screenshots/latency_formal2_A_dynamic_B_north_0-supervisor-A_success.png` | `95455b4216def5c9e6a9c3767a7c8671eb6ef8162807fb2f2f6c2c9730dbb4fd` |
| `screenshots/latency_formal2_A_dynamic_B_south_1-supervisor-A_success.png` | `c1cf184e2d8250b159ee9c87c54ce9caa3e359c6a5affdfdcebca24a5b35464e` |
| `screenshots/latency_formal2_B_dynamic_B_north_0-supervisor-B_success.png` | `e51876789b2eb52aabb48415165094fb000cee1bdb832609460bb1c4f0c6bf7e` |
| `screenshots/latency_formal2_B_dynamic_B_south_1-supervisor-B_success.png` | `de7b86486729258ba1b9a1130d0b21bf80f8822fa9b6a3a0b489e6ca79f418c4` |
| `invalid_freeze_attempt1/latency_pair_freeze_v2.json` | `779e928f014896f81fe871344a9151b1ee6b08ce080c74a6967ba77e4f386df4` |
| `invalid_freeze_attempt1/latency_special_freeze_v2.json` | `41167a599064913120a449b8b38537fe98f0c7610648e6b921f2c9b3b10d2f15` |
| `invalid_freeze_attempt1/summary.error.txt` | `8def7171ef91227df6a7dd54b2734cf453b6c4f16dd0760687199a1b8c2640f0` |
| `verify_latency_runs.json` | `9e7c7102d8b460c2aa2ac57f7829269d4c7eb64ead8317b49d7a49e335e419c1` |
| `analyze_latency_envelope.json` | `4b8c596d9dc10c441b7da5c2f56bbf410767419d2a0c244447f8d47f13598978` |

## 10. 精确复现命令（前台 GUI，无 --headless）

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 1) 预运行冻结（代码提交后、运行前；输出已存在会拒绝覆盖）
& $py scripts/make_latency_freeze.py --output-root configs/scenarios `
  --map-config configs/maps/rmuc2027.yaml --local-config configs/maps/rmuc2027.local.yaml `
  --cases configs/scenarios/map_dynamic_cases_v1.json `
  --special-cases configs/scenarios/latency_special_cases_v1.json `
  --expected configs/scenarios/latency_expected_v1.json `
  --case-ids dynamic_A_south_0,dynamic_A_north_0,dynamic_A_south_1,dynamic_B_south_0,dynamic_B_north_0,dynamic_B_south_1,dynamic_C_south_0,dynamic_C_north_0,dynamic_D_south_0,dynamic_D_north_0,dynamic_E_south_0,dynamic_E_north_0 `
  --stop-a 1.1 --stop-b 1.38 --obs-delay-s 0.15 --action-delay-s 0.10 `
  --ttl-ms 150 --max-age-ms 150 --allowed-observation-age-ms 300 `
  --clock-offset-ms 20 --clock-drift-ppm 200 --clock-uncertainty-ms 5
# 2) 主 A（B 同，改 --config-id B --stop-distance-m 1.38 --output ...B）
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --only-cases <12 ids> --methods supervisor --execution-path v2 --config-id A --stop-distance-m 1.1 --obs-delay-s 0.15 --action-delay-s 0.10 --ttl-ms 150 --max-age-ms 150 --allowed-observation-age-ms 300 --clock-offset-ms 20 --clock-drift-ppm 200 --clock-uncertainty-ms 5 --freeze configs/scenarios/latency_pair_freeze_v2.json --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 0c03281b7594f38e2274799afa1b1ab31896abc2 --output outputs/map_eval/latency_formal2_A
# 3) 专项四段（参数严格对应 latency_special_freeze_v2.json 的 special_segments）
$common = '--cases configs/scenarios/latency_special_cases_v1.json --only-cases special_stop_north --methods supervisor --execution-path v2 --stop-distance-m 1.1 --obs-delay-s 0.15 --action-delay-s 0.10 --max-age-ms 150 --allowed-observation-age-ms 300 --clock-offset-ms 20 --clock-drift-ppm 200 --clock-uncertainty-ms 5 --freeze configs/scenarios/latency_special_freeze_v2.json --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 0c03281b7594f38e2274799afa1b1ab31896abc2'
& $py -u scripts/run_dynamic_eval.py $common --segment-id ttl_near  --ttl-ms 120 --post-abort-observe-s 0   --output outputs/map_eval/latency_ttl_near
& $py -u scripts/run_dynamic_eval.py $common --segment-id ttl_over  --ttl-ms 150 --post-abort-observe-s 3.0 --transport-stall-step 300 --transport-stall-delay-s 0.15 --output outputs/map_eval/latency_ttl_over
& $py -u scripts/run_dynamic_eval.py $common --segment-id clock_sync --ttl-ms 150 --post-abort-observe-s 3.0 --sync-fail-step 300 --output outputs/map_eval/latency_clock_sync
& $py -u scripts/run_dynamic_eval.py $common --segment-id clock_mapping --ttl-ms 150 --post-abort-observe-s 3.0 --obs-mapping-fail-step 280 --output outputs/map_eval/latency_clock_mapping
# 4) 隔离回归（无冻结、默认 0 延迟/0 时钟）
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_v2_regression_cases_v1.json --only-cases v2_reg_route_south_R1 --methods supervisor --execution-path v2 --stop-distance-m 1.1 --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 0c03281b7594f38e2274799afa1b1ab31896abc2 --output outputs/map_eval/latency_regression_no_obstacle
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --only-cases dynamic_A_south_0 --methods supervisor --execution-path v2 --stop-distance-m 1.1 --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 0c03281b7594f38e2274799afa1b1ab31896abc2 --output outputs/map_eval/latency_regression_dynamic
# 5) 独立核验与参数分析
& $py scripts/verify_latency_runs.py --pair-freeze configs/scenarios/latency_pair_freeze_v2.json --run-a outputs/map_eval/latency_formal2_A --run-b outputs/map_eval/latency_formal2_B --special-freeze configs/scenarios/latency_special_freeze_v2.json --special-run ttl_near=outputs/map_eval/latency_ttl_near --special-run ttl_over=outputs/map_eval/latency_ttl_over --special-run clock_sync=outputs/map_eval/latency_clock_sync --special-run clock_mapping=outputs/map_eval/latency_clock_mapping --regression-run regression_no_obstacle=outputs/map_eval/latency_regression_no_obstacle --regression-run regression_dynamic=outputs/map_eval/latency_regression_dynamic --expected-config configs/scenarios/latency_expected_v1.json --repo-root . --output docs/reports/map_eval/latency/verify_latency_runs.json
& $py scripts/analyze_latency_envelope.py --special ttl_near=outputs/map_eval/latency_ttl_near --special ttl_over=outputs/map_eval/latency_ttl_over --special clock_sync=outputs/map_eval/latency_clock_sync --special clock_mapping=outputs/map_eval/latency_clock_mapping --regression regression_no_obstacle=outputs/map_eval/latency_regression_no_obstacle --regression regression_dynamic=outputs/map_eval/latency_regression_dynamic --output docs/reports/map_eval/latency/analyze_latency_envelope.json
& $py -m pytest -q
```

## 11. 失败/重试/未完成（全部保留）

- 探索运行（formal_A/B、A1/B1/B2/B3 分段、queue/sync/clockfail debug）保留，仅作探索证据，不升级为正式。
- 冻结迭代：attempt1（frozen_at 05:09:13Z）因核验器脚本在冻结后更新导致工作树 digest 变化，运行入口按设计拒绝启动（未产生数据），旧冻结保留在 evidence 中；随后重新生成 frozen_at 05:12:31Z 的有效冻结。
- 启动崩溃：一次运行在残留 Isaac 进程占用下以 `Windows fatal exception: access violation` 中止（未产生数据），清理本工作包停滞进程后重跑成功；日志保留。
- 预冻结预期分类偏差：clock_mapping 的 reason 与预冻结 expected 不同（见 §1），已记录在核验 JSON，不修改冻结文件。

## 12. 未运行 / 下一工作包

- 未运行：真实跨时钟/串口/PX4/执行器延迟、PX4 Sender/failsafe、PPO/真实感知/板端/SITL/HIL/实机；未提升任何 Gate。
- 下一工作包：①高速/近距离接近专项（closing >0.7 m/s、机体 >0.64 m/s）；②真实 PX4 Offboard-loss 语义（需外部固件资料）；③transport jitter/乱序/双队列与在途动作撤回；④体积/姿态扫掠净空与多高度/位置包络；⑤把 clearance 阈值纳入冻结测量字段（当前为独立重放重建）。
