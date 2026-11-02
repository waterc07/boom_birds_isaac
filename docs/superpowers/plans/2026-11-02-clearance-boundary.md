# Clearance 几何语义与停止需求边界专项计划（2026-11-02）

> **状态：** BASELINE（本轮工作包执行计划；不是验收结论）
> **来源章节：** V2.2 §10.4、§16.1–16.3、§16.6、§17.3、§26.6–26.7、§27.3–27.7；`MAP_LATENCY_ENVELOPE_REPORT.md`、`HANDOFF_20261102_LATENCY_ENVELOPE.md`、`verify_latency_runs.json`、`analyze_latency_envelope.json`
> **证据域：** 标准库单元测试 + 前台可视 GUI 仿真动力学（DirectX/D3D12）
> **最后核对：** 2026-11-02

## 0. 目标

1. 审查上一轮判据放宽/预期偏差，区分文档、核验口径与真实未满足预期；不把旧 PASS 当行为验收。
2. 把 clearance 几何语义、包络、预测、有效性、停止需求、适用范围固化为可校验接口（代码 + 文档合同），生产判定值与独立重建值分离。
3. 预冻结 ≥12 场景 ×2 重复（≥24 episode）边界专项，覆盖静态阻塞内外、横穿时机、持续接近、近最高实测速度、延迟致剩余间隙不足、超模型输入。
4. 独立核验分四类报告：数据完整性、合同不变量、场景预期、性能与能力边界。
5. 回归、pytest、文档审计、diff、报告、证据、hash、交接、中文提交（不推送）；不提升 Gate。

分支：`codex/bb22-clearance-boundary`（自 `9884c19`）。用户既有 23 个已修改文档 + 10 个上一工作包 untracked 文件保留、不纳入提交。

## 1. 上一轮验收口径审查（Lead，先于新正式运行完成）

输出 `docs/reports/map_eval/latency/LATENCY_ACCEPTANCE_AUDIT_20261102.md`，须包含：

- 时间线证据：`6ddb14f 13:09:08`（代码）→ `0c03281 13:12:25`（verifier 放宽）→ 冻结 `13:12:31` → 正式运行 `13:13–13:48` → `e40db26 13:57:35`（运行后 verifier 修改）。
- `0c03281` 变更逐项：预运行 verifier 放宽（ttl_over 残余形态 (a)/(b)、expected alternatives 继承）。判断合同依据：alternatives 在 `6ddb14f` 的 expected 文件已存在（预冻结）；残余形态放宽是否有队列语义依据；(a)/(b) 后被 (c) 取代。
- 运行后 verifier 修改（`e40db26`）逐项分类：数据完整性/记录定义修正（phase_summary 位置与零计数、post_abort 可空、dropout 有效性、metrics 全行重算）vs 验收口径扩张（reason 接受 expected/admission/observation/inflight 字段、regression 豁免 expected）。结论：**旧 20/20 PASS 不能等同行为验收**；clock_mapping 的 reason 偏差与 ttl_over 的 (c) 放宽须在新冻结中以预声明判据重跑。
- clock_mapping 偏差定性：原因码别名 / 多合法拒绝条件优先级 / 未满足预冻结预期。当前证据倾向"多合法路径且预冻结只写主路径"：实际 admission 拒绝 `REJECT_STALE_OBSERVATION` 先于 supervisor stale abort；预冻结 expected 同时列有 admission 字段但 verifier 原只读主 reason。登记为**预期规格不足 + 事后接受扩展**，保留旧证据；新冻结显式声明可接受路径与优先级后再跑。
- ttl_over 独立复核：被拒 action id 集合与 executed id 集合无交集（901 vs 300），首次拒绝 step 303 age=0.150，旧有效 active 只出现在 296–301（expires 15150ms > host 15100ms），step 302 到期→NONE，post-abort 60 行无 executed。结论：未执行过期动作；旧 setpoint 与过期新动作分开记录；TIMEOUT 属预期失效边界。
- 20 项核验分类表（数据完整性 / 合同不变量 / 场景预期 / 性能边界），说明各项证明范围。
- 时钟层次澄清：正常动力学以 Isaac **仿真时间** 为基准；camera/PX4 域是**模拟第二时钟**（计划偏移/漂移/不确定度），不存在真实多设备时钟、串口或 PX4 延迟；旧报告"模拟双时钟/单时钟仿真证据"表述按此层次在新报告中修正，旧报告保留为历史。
- 结论：旧结果维持"latency 证据"层级，不升级；受影响专项以新冻结版本重跑。

## 2. Clearance 字段化合同（代码 `src/boom_birds/evaluation/clearance.py`）

纯标准库；`CLEARANCE_SCHEMA_VERSION='boom_birds.clearance.v1'`；算法 `id='supervisor_predicted_path_clearance'`, `version='1.0.0'`；单位 m；坐标系 world ENU Z-up；时间基准 simulation_time_s；预测 1.0 s / 0.1 s（11 点）。

```json
{
  "schema_version": "boom_birds.clearance.v1",
  "algorithm": {"id": "supervisor_predicted_path_clearance", "version": "1.0.0",
                 "units": "m", "frame": "world_ENU_Z_up", "time_base": "simulation_time_s",
                 "prediction_horizon_s": 1.0, "prediction_step_s": 0.1,
                 "definition": "min point-to-segment distance from predicted obstacle centers to [robot_center_now -> current_waypoint_center]"},
  "inputs": {"robot_center_world_m": [..], "robot_velocity_world_mps": [..],
              "target_waypoint_world_m": [..], "waypoint_index": 0,
              "obstacle_observed_center_world_m": [..], "obstacle_observed_velocity_world_mps": [..],
              "observation_age_point_s": 0.2, "observation_age_bound_s": 0.228,
              "observation_valid": true, "observation_reason": "ACCEPT"},
  "prediction": {"obstacle_predicted_centers_world_m": [[..] x 11],
                  "point_distances_m": [.. x 11], "min_index": 0},
  "metrics": {"center_distance_m": 4.25, "envelope_gap_sphere_m": 3.88,
               "path_clearance_m": 1.09, "path_clearance_gap_sphere_m": 0.72},
  "envelopes": {"robot": {"kind": "sphere_over_spawn_aabb_half_diagonal",
                            "radius_m": 0.0677, "aabb_half_extents_m": [0.0545,0.0382,0.0136],
                            "measured_prim": "/World/envs/env_0/Robot",
                            "source": "measured_usd_aabb_at_runtime",
                            "attitude_scope": "any_rigid_rotation_about_center",
                            "limitation": "AABB approximation; not a triangle-mesh sweep"},
                 "obstacle": {"kind": "sphere_over_case_cuboid", "radius_m": 0.3, "size_m": [0.4,0.4,0.6],
                               "source": "case_obstacle_size"}},
  "validity": {"valid": true, "reasons": []},
  "applicability": {"status": "SUPPORTED|UNSUPPORTED", "reasons": [],
                     "notes": ["path clearance is not center distance or surface gap"]}
}
```

- `box_conservative_sphere_radius(half_extents_m)` = `sqrt(sum(h_i^2))`（半对角线，对任意绕质心刚体旋转保守包含该 AABB；测试用 8 顶点随机旋转验证；**不得**再用 max-half-extent 作为保守半径）。AABB 本身是 spawn 姿态对资产的保守界；球/AABB 近似不是网格扫掠证明。
- `point_to_segment_distance`、`predict_obstacle_positions`、`predicted_path_clearance`（与 supervisor 现算法逐位一致）；supervisor `_risk` 改为调用该函数，行为不变（用现有测试 + 输入样本数值等价回归）。
- `RouteSupervisor.update` 的 decision 增加 `clearance_record`（结构如上，`validity` 由 observation valid/target 决定）；`clearance_m` 保留（生产判定值）。
- 一个字段只承载一种量：中心距 `center_distance_m`、表面/球包络间隙 `envelope_gap_sphere_m`、预测路径净空 `path_clearance_m`、路径净空扣包络 `path_clearance_gap_sphere_m`，不得互相替代。

## 3. 停止需求模型（`src/boom_birds/evaluation/stop_requirement.py`）

- `STOP_REQUIREMENT_SCHEMA_VERSION='boom_birds.stop_requirement.v1'`；制动模型版本 `brake_final4.v1`，来源 `docs/reports/map_eval/brake/verify_brake_final.json`（实测 36 点，速度 0.248/0.547/0.851 三档），冻结到 `configs/scenarios/brake_model_v1.json`（点、支持区间、插值规则、provenance hash、只许区间内分段线性、**区间外不外推**）。
- 输入：实测机器人速度、closing/relative speed、观测年龄保守界、动作延迟、动作 TTL 剩余、机体/障碍球半径、当前 stop 阈值、`proposed_margin_m`（PROPOSED，默认 0.2 m，仅规划余量不是已验证安全余量）。
- 输出：`brake_distance_m`、`transport_reaction_m = v*action_delay`、`observation_age_motion_m = closing*age`、`envelope_sum_m`、`required_clearance_m = 前三项 + envelope_sum`、`margin_to_threshold_m = threshold - required - proposed_margin`、`status ∈ {SUPPORTED, UNSUPPORTED}`、`status_reasons`（如 `ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT`、`OBSERVATION_AGE_UNKNOWN`、`ACTION_TTL_EXPIRED_BEFORE_ARRIVAL`、`CLOSING_SPEED_NOT_MODELLED` 仅标记不阻断、`PREDICTION_HORIZON_SHORTER_THAN_STOP_TIME` 标记）。
- 禁止：超模型速度外推；把中心距当路径净空；把已含传输延迟的实测停止距离再次加延迟（生产记录用执行器级 brake_model，故 `v*action_delay` 单列；若分析用"触发→停"实测距离，则不再加 reaction，须在记录中给出 `basis` 字段）。

## 4. 运行器集成（Lead 负责 `scripts/run_dynamic_eval.py`）

- 新增 `--vehicle-config <path>`（默认 `configs/vehicles/sim_reference.yaml`；manifest 记录 hash）。
- 每步（supervisor 路径）记录 `clearance`（生产记录，来自 supervisor decision 的 `clearance_record`）与 `stop_requirement`（运行器按实测速度/obs age/action delay/TTL/envelope/threshold 计算），manifest 记录 clearance/stop_requirement schema、算法版本、brake model hash、包络策略。
- episode metrics 增加：`min_path_clearance_m`、`min_path_clearance_gap_sphere_m`、`min_center_distance_m`、`min_envelope_gap_sphere_m`、`conservative_envelope`（半径/来源/姿态范围）、`stop_requirement_extremes`（最小 margin、UNSUPPORTED 步数/原因）、`post_abort` 物理结果、`business_outcome`/`physical_outcome` 分离字段。
- 运行器冻结校验：新 schema `boom_birds.clearance_boundary_freeze.v1`（`boundary_plan.validate_run_plan/check_freeze_lineage`），旧 latency schema 保持兼容；frozen_at≤started_at、git HEAD、工作树 digest、逐字段 run_plan（含 vehicle_config hash、cases hash、expected hash、brake model hash）。
- 不改监督器阈值/状态机/执行器语义；仅新增记录与 `--vehicle-config`。若发现确定几何/判定缺陷才做有失败回归的最小修复（本轮预期不改）。

## 5. 场景与冻结（12 场景 ×2 重复=24 GUI episode）

案例文件由 Lead 校准后写入 `configs/scenarios/clearance_boundary_cases_v1.json`；场景 id（重复用 `_r0/_r1`，同参数显式重复，不换 seed）：

| id | 类型 | 设计 | 预期类别（运行前冻结） |
| --- | --- | --- | --- |
| `boundary_A_static_far_r{0,1}` | 静态阻塞·早触发 | 长航段走廊，障碍在路径上，远距离即触发 STOP，margin 大，等待后退出 | BLOCKED_EXIT（ABORT/TIMEOUT；无接触） |
| `boundary_A_static_tight_r{0,1}` | 静态阻塞·紧触发 | 短航段（~1 m 间距）使触发发生在阈值附近（v≈0.6），margin 小，等待后退出 | BLOCKED_EXIT_TIGHT |
| `boundary_A_static_offpath_r{0,1}` | 静态·路径旁 | 障碍偏离走廊 1.5 m，路径净空>阈值，不触发停车 | NO_STOP_EXPECTED（SUCCESS） |
| `boundary_B_cross_early_r{0,1}` | 横穿·早 | 障碍在机器人到达前 ~1.5–2 s 穿越 | STOP_WAIT_RESUME（SUCCESS） |
| `boundary_B_cross_late_r{0,1}` | 横穿·晚 | 障碍与机器人同时到达交叉点（剩余间隙不足） | INSUFFICIENT_MARGIN（COLLISION 或 ABORT/TIMEOUT，登记物理结果） |
| `boundary_B_cross_far_r{0,1}` | 横穿·很远 | 障碍横穿点远在预测/触发之外 | NO_STOP_EXPECTED（SUCCESS） |
| `boundary_C_headon_stop_short_r{0,1}` | 迎面·障碍停住 | 障碍沿走廊朝向机器人，停止后机器人停车等待，障碍停在前方 | STOP_OBSTACLE_HOLD（ABORT/TIMEOUT；无接触或极小间隙） |
| `boundary_C_headon_collide_r{0,1}` | 迎面·继续驶来 | 障碍不停，机器人停车后障碍仍继续接近 → 停车后接触 | POST_STOP_COLLISION（接触发生在业务停止之后；物理结果单列） |
| `boundary_C_headon_early_r{0,1}` | 迎面·远距离 | 迎面障碍远距离即触发停车，margin 大 | BLOCKED_EXIT（无接触） |
| `boundary_D_fast_cross_r{0,1}` | 近最高实测速度 | 快速车配置（max 0.9），长直走廊，横穿障碍在对向触发时 v≈0.8–0.85 | HIGH_SPEED_STOP（SUCCESS 或 TIGHT_EXIT；记录实际速度，若>0.851 标 UNSUPPORTED） |
| `boundary_E_delay_insufficient_r{0,1}` | 延迟·间隙不足 | 横穿时机紧 + obs 200 ms/action 100 ms，反应距离超过剩余间隙 | INSUFFICIENT_MARGIN（COLLISION 或 late ABORT；物理结果单列） |
| `boundary_E_action_late_r{0,1}` | 延迟·动作迟到 | obs 180 ms/action 120 ms（TTL 150 内到达）紧横穿 | INSUFFICIENT_MARGIN（同上） |

- 车辆配置：默认 `configs/vehicles/sim_reference.yaml`（max_horizontal 0.6，**保持默认**；1.38 m 仍是候选，不升级）；快速段 `configs/vehicles/sim_reference_boundary_fast.yaml`（max_horizontal 0.9，其他不变，PROPOSED）。
- 观测/动作延迟：默认 obs 150 ms/action 100 ms；E 段按表；TTL 150 ms；allowed obs age 300 ms；时钟 20 ms/200 ppm/5 ms（与上一轮一致）。
- 业务/物理结果分离；`post_abort_observe_s=3.0`（所有边界段）保留停机后物理观测；不得为继续观测恢复任务资格；auto-reset 后状态不得拼入同一轨迹。
- 专项段（新冻结、显式预声明判据）：
  - `latency_clock_mapping_recheck`：同上一轮 clock_mapping，但 expected 明确声明"可接受路径集合与优先级"：`{admission_reject_reason:'REJECT_STALE_OBSERVATION', observation_reason:'CLOCK_MAPPING_UNUSABLE'}` 或 supervisor `OBSERVATION_STALE`；verifier 要求实际命中声明集合之一并记录命中的路径与优先级，不得事后扩展集合。
  - `latency_ttl_over_recheck`：同上一轮 ttl_over（stall 0.15），expected 预声明 (c) 判据：先拒绝后无执行、旧有效 setpoint 在首次拒绝前、expiry→NONE、零目标回退、业务结果 TIMEOUT/ABORT 之一。
  - 回归：`regression_dynamic`（`dynamic_A_south_0`）、`regression_no_obstacle`（`v2_reg_route_south_R1`）、`regression_fault`（`fault_ttl_expiry_0`）默认参数，验证监督/执行行为未变。
- 冻结文件：`configs/scenarios/clearance_boundary_freeze_v1.json`（单文件多 segment：`boundary_default`、`boundary_fast`、`latency_clock_mapping_recheck`、`latency_ttl_over_recheck`、`regression_dynamic`、`regression_no_obstacle`、`regression_fault`）。生成脚本不覆盖旧文件、真实 UTC 时间、实际 HEAD；运行入口逐段校验。

## 6. 独立核验（`scripts/verify_clearance_boundary_runs.py`，纯标准库）

从原始 steps/episodes/manifest + 冻结重算，失败→INCOMPLETE，不读 summary 结论。每项 check 带 `category ∈ {data_integrity, contract_invariant, scenario_expectation, performance_boundary}`：

1. **数据完整性**：字段 schema、hash、episode 唯一/分母、步长时间单调、GUI/DirectX、冻结先于运行、manifest 与磁盘一致。
2. **合同不变量**：clearance 生产值 = 独立重建值（容差 1e-6）；预测位置数/时域一致；包络半径 = 半对角线规则且 AABB 来源一致；中心距/球间隙/路径净空互不混用；观测年龄界、TTL/不续期、到达拒绝、被拒动作永不执行、旧 setpoint 合法残留→NONE；stop_requirement 项与状态（SUPPORTED/UNSUPPORTED）可重算，区间外不外推。
3. **场景预期**：逐场景对照预冻结 expected 类别/可接受结果集合/必须条件（如 must_not: SUCCESS 于 INSUFFICIENT_MARGIN；collision 必须发生在业务停止之后等），偏差单独列出（不并入 PASS）。
4. **性能与边界**：制动起点/初始实测速度/停止距离与时间、接近/相对运动、接触时刻与力、停车后障碍接近量、业务 vs 物理结果、UNSUPPORTED 输入统计与原因、支持范围外推禁止的证据。
5. 输出 JSON：`status`、`checks[category]`、`recomputed`、`failures`、`deviations`、`unsupported`、`performance`、`freeze`；存在偏差时不得把场景预期标 PASS。

## 7. 运行与分段（Lead，前台 GUI，串行）

1. 调试案例：先用 2–4 个单 episode 调试运行校准触发时机/航点/障碍起点（独立 debug 目录，不作正式证据）。
2. 正式：`boundary_default`（A/B/C/E 共 10 场景 ×2 =20 episode）→ `boundary_fast`（D 2 场景 ×2=4）→ `latency_clock_mapping_recheck`、`latency_ttl_over_recheck` → 3 个 regression。每段独立目录、独立日志/exit marker；检查窗口、stages、物理步进、error、完成标记、产物；保留失败/重试；只清理确认属于本工作包且停滞的进程。
3. 至少 24 个预冻结边界 episode；真实失败/不支持状态保留。

## 8. 交付与提交

- 代码：`clearance.py`、`stop_requirement.py`、`supervisor.py` 重构（行为等价）、`boundary_plan.py`、`run_dynamic_eval.py` 集成、`make_boundary_freeze.py`、`verify_clearance_boundary_runs.py`、`analyze_clearance_boundary.py`、测试。
- 配置：`brake_model_v1.json`、`clearance_boundary_cases_v1.json`、`clearance_boundary_expected_v1.json`、快速车配置、`clearance_boundary_freeze_v1.json`。
- 文档：上一轮审查 `LATENCY_ACCEPTANCE_AUDIT_20261102.md`；clearance 合同（本计划 §2/§3 + `docs/design/CLEARANCE_GEOMETRY_CONTRACT.md` 简短合同，标注 PROPOSED/实测边界）；报告 `MAP_CLEARANCE_BOUNDARY_REPORT.md`；交接 `HANDOFF_20261102_CLEARANCE_BOUNDARY.md`；证据 `docs/reports/map_eval/clearance_boundary/evidence/`、截图。
- 提交：只含本工作包文件；中文消息；不推送；用户既有修改保持未提交。全套 pytest、`scripts/planning/audit_documents.py`、diff 检查、独立核验通过后才标记 Goal complete。

## 9. 写域

| 任务 | 写域 | 说明 |
| --- | --- | --- |
| U1 clearance/停止需求实现 | `src/boom_birds/evaluation/clearance.py`、`stop_requirement.py`、`supervisor.py`、`configs/scenarios/brake_model_v1.json`、`tests/evaluation/test_clearance.py`、`test_stop_requirement.py`、`test_supervisor.py` | 先失败测试；supervisor 行为数值等价 |
| U2 边界契约/冻结 | `src/boom_birds/evaluation/boundary_plan.py`、`scripts/make_boundary_freeze.py`、`configs/vehicles/sim_reference_boundary_fast.yaml`、`configs/scenarios/clearance_boundary_expected_v1.json`、`tests/evaluation/test_boundary_plan.py` | 不改运行器/核验器；冻结正式生成由 Lead 在提交后执行 |
| U3 独立核验 | `scripts/verify_clearance_boundary_runs.py`、`tests/evaluation/test_verify_clearance_boundary.py` | 不改实现/运行器/冻结 |
| U4 运行器集成与案例校准 | `scripts/run_dynamic_eval.py`、`configs/scenarios/clearance_boundary_cases_v1.json` | 仅 Lead |
| U5 审计/运行/报告/提交 | docs、outputs、冻结产物、Git | 仅 Lead |
