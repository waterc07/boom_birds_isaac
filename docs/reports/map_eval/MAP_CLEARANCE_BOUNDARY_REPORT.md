# Clearance 几何语义与停止需求边界专项报告（2026-11-02）

> **状态：** ASSESSMENT（实现覆盖 + 预冻结边界运行 + 独立核验 + 适用范围结论）；仅当前仿真模型证据，不是实机安全包络或 PX4 failsafe，不提升任何 Gate
> **来源章节：** V2.2 §10.4、§16.1–16.3、§16.6、§17.3、§26.6–26.7、§27.3–27.7；`docs/superpowers/plans/2026-11-02-clearance-boundary.md`；`LATENCY_ACCEPTANCE_AUDIT_20261102.md`
> **证据域：** 标准库单元测试 + 前台可视 GUI 仿真动力学（DirectX/D3D12）
> **最后核对：** 2026-11-02

## 1. 结论

- **上一轮验收口径：** `0c03281`（预运行）的 expected alternatives 沿用了 `6ddb14f` 已冻结的 expected 字段，ttl_over 残余形状放宽论证不足、后由 (c) 取代；`e40db26`（运行后）的 7 项修改中 5 项是记录/数据完整性修正、1 项为回归范围修正、1 项为 reason 接受口径扩张。**旧 20/20 PASS 不升级为行为验收**；clock_mapping 的 `OBSERVATION_STALE → V2_REJECT_STALE_OBSERVATION` 偏差登记为"预期规格不足 + 运行后接受扩张"；旧证据与旧冻结保留。详见 `docs/reports/map_eval/latency/LATENCY_ACCEPTANCE_AUDIT_20261102.md`。
- **clearance 合同字段化：** 新增 `boom_birds.clearance.v1`（中心距 / 球包络间隙 / 预测路径净空 / 路径净空扣包络四量严格分离；预测 1.0 s / 0.1 s；world ENU；simulation time base；机器人与障碍包络参数/来源；观测年龄保守界；validity/applicability），生产判定值写入每步原始记录；独立核验器从原始输入重建并与生产值比较（容差 1e-6）。
- **包络保守性修正：** 上一轮分析使用的 `max(AABB half)`（0.0545 m）**不是**旋转保守半径；本轮改为 AABB 半对角线 `sqrt(Σh²)=0.067966 m`（对任意绕质心刚体旋转保守包含该 AABB；单测用随机旋转 8 顶点验证，并给出 max-half 非保守反例）。由此阈值处的球包络间隙修正为：A 配置 1.1−0.067966−0.3=**0.732 m**、候选 1.38 配置 **1.012 m**（推导；上一轮 0.745/1.025 使用非保守半径，按本轮口径作废）。AABB 中心偏移未记录 → 完整外廓保守性仍标**未确认**，球/AABB 近似不是网格扫掠证明。
- **停止需求模型：** `boom_birds.stop_requirement.v1` 基于前序正式 `brake_final4` 实测（3 档 0.248/0.547/0.851 m/s，最大停止距离 0.584659 m）冻结为 `brake_model_v1.json`；区间内分段线性，**区间外禁止外推**（>0.851428 或 <0.248041 → `UNSUPPORTED`，brake/required/margin=null）。模型只支持当前仿真执行器级制动；低速区间以下只作保守说明、超上限一律 UNSUPPORTED。
- **边界专项：** 12 个设计场景 ×2 显式重复 = **24 个预冻结边界 episode** 全部完成；另 2 个上一轮专项复核（clock_mapping / ttl_over）+ 3 个回归。业务结果（边界 24）：ABORT 16、SUCCESS 8；含复核/回归的全部 29 episode：ABORT 18、SUCCESS 10、TIMEOUT 1；物理结果：NO_CONTACT 16、CONTACT_INFERRED 8、CONTACT_MEASURED 0（见 §4/§7 证据域）。
- **场景预期全部满足**（预冻结 expected，逐类）：静态阻塞 4/4 ABORT 无接触；紧触发 2/2 ABORT；路径旁 4/4 SUCCESS 且无 STOP；横穿早 2/2 SUCCESS；横穿晚/延迟不足 6/6 ABORT 且 **CONTACT_INFERRED**；障碍停在前方 2/2 ABORT 无接触；停车后继续接近 2/2 ABORT 且 **首接触晚于停稳**；近/超最高实测速度 2/2 SUCCESS 且制动速度 ≥0.6；INSUFFICIENT_MARGIN 无 SUCCESS。
- **停止不等于避免未来接触（实测/推断）：** 迎面持续接近场景中机器人先停车（speed≤0.08 停稳），障碍继续运动并在停稳后与机器人发生球包络重叠：最小包络间隙 −0.115 m（C_headon_collide）、−0.118 m（B_cross_late/E 段）、−0.067 m（E_action_late）；停车后障碍继续接近 **0.83–0.86 m**。因此"业务 ABORT/停车"不能推出"障碍不再撞来"。
- **超出当前能力（明确不支持）：** `boundary_D_fast_cross` 实测制动速度 **0.992 m/s**，超过制动模型支持上限 0.851428 m/s → 生产记录 `UNSUPPORTED/ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT`（564 步），**不外推为安全结论**；该场景业务 SUCCESS 仅表示本次仿真轨迹通过，不代表超模型速度有安全保证。传输延迟 ≥TTL 的 ttl_over 复核仍为 TIMEOUT、过期动作未执行。
- **上一轮专项复核（新冻结、预声明判据）：** `latency_clock_mapping_recheck` 命中预声明优先路径（observation `CLOCK_MAPPING_UNUSABLE` + admission `REJECT_STALE_OBSERVATION`，业务 ABORT，reason `V2_REJECT_STALE_OBSERVATION`）；`latency_ttl_over_recheck` 满足 (c) 六项（901 被拒 id 与 300 executed id 无交集、首拒绝 age=0.150 s、首拒绝前旧 active 仍在有效期、到期→NONE、零目标回退、TIMEOUT）。旧运行不被改写。
- **独立核验：** **PASS**：`status=PASS`、41/41 checks（data_integrity 10、contract_invariant 14、scenario_expectation 9、performance_boundary 8）、failures=0、deviations=0、missing_fields=0；接触证据模式 `kinematic_inference`（球重叠 >0.02 m，非测力）；clock_mapping 命中预声明路径、ttl_over 满足预声明 (c) 六项；regression 与既有 v2 证据一致。
- **边界：** 单仿真模型/单地图/单机体；ORACLE 障碍观测不是视觉；host 时间基准为 Isaac 仿真时间，camera 为**模拟第二时钟域**，不存在真实多设备时钟/串口/PX4 延迟；接触力传感在本环境不可用，接触以球重叠运动学推断（非测力）；不提升 Gate。

## 2. 现场与证据链

| 类别 | 内容 |
| --- | --- |
| 分支/提交 | `codex/bb22-clearance-boundary`；代码提交 `0546701`（clearance/stop_requirement/边界契约/运行器/核验器/案例/预期/快速车配置）；正式运行 commit `0546701`；旧分支 `codex/bb22-latency-envelope` 的 `9884c19` 等保留 |
| 预运行冻结 | `configs/scenarios/clearance_boundary_freeze_v1.json`（真实 UTC，frozen_at 见冻结文件；9 段、budget 24/2/3/29；运行入口逐段校验 run_plan、HEAD、worktree digest、frozen_at≤started_at） |
| 正式运行 | `outputs/map_eval/bnd_boundary_default`（18）、`bnd_boundary_delay_e1`（2）、`bnd_boundary_delay_e2`（2）、`bnd_boundary_fast`（2）、`bnd_latency_clock_mapping_recheck`（1）、`bnd_latency_ttl_over_recheck`（1）、`bnd_regression_dynamic/no_obstacle/fault`（各 1）；共 29 episode |
| 上一轮证据 | `outputs/map_eval/latency_*` 与 `latency_*freeze_v2.json` 保留，不重写；其层级为 latency 证据，不升级 |
| 调试/校准 | `outputs/map_eval/boundary_smoke1`、`boundary_calibA/B/D/E1/E2`、`calib*` 保留为探索/校准证据，不进入正式分母 |
| 版本化证据 | `docs/reports/map_eval/clearance_boundary/evidence/`（冻结/预期/案例/制动模型/各段 summary/episodes/manifest/steps hash/截图/GUI 摘录/核验与分析 JSON） |

## 3. 合同与实现

### 3.1 clearance 字段（`src/boom_birds/evaluation/clearance.py`，`boom_birds.clearance.v1`）

- 算法：`supervisor_predicted_path_clearance` v1.0.0；min over 预测障碍中心（obs 位置+速度，1.0 s、0.1 s，11 点）到 `[机器人当前中心 → 当前航点中心]` 线段的点-线段距离；world ENU Z-up；simulation time base。
- 字段：`inputs`（机器人中心/速度、目标航点/索引、障碍观测中心/速度、观测年龄点/上界、观测 valid/reason）、`prediction`（11 个预测中心、逐点距离、min_index）、`metrics`（`center_distance_m`、`envelope_gap_sphere_m`、`path_clearance_m`、`path_clearance_gap_sphere_m`）、`envelopes`（robot：`sphere_over_spawn_aabb_half_diagonal`、radius、AABB 半尺寸、来源、`attitude_scope='any_rigid_rotation_about_center'`、限制；obstacle：`sphere_over_case_cuboid`、radius=max(size)/2、来源）、`validity`、`applicability`（SUPPORTED/UNSUPPORTED + reasons + notes）。
- supervisor `_risk` 改为调用该函数（数值等价回归），decision 增加 `clearance_record`；状态机/阈值不变。

### 3.2 停止需求（`stop_requirement.py`，`boom_birds.stop_requirement.v1`）

- `brake_model_v1.json`（`brake_final4.v1`）来源 `docs/reports/map_eval/brake/verify_brake_final.json`（sha256 记录于文件）：点 (0.2480405, 0.186834)、(0.5474249, 0.389777)、(0.8514285, 0.584659)；支持区间 [0.248041, 0.851428] m/s；分段线性；区间外不外推。
- 输入：实测速度、closing speed、观测年龄上界、动作延迟、TTL 剩余、机器人/障碍球半径、阈值、PROPOSED margin=0.2 m。
- 输出：terms（`brake_distance_m`、`transport_reaction_m`、`observation_age_motion_m`、`envelope_sum_m`）、`required_clearance_m`、`margin_to_threshold_m`、`status`、`status_reasons`。`basis='actuation'` 时 brake 距离来自执行器级实测（不含传输延迟），故 `v*action_delay` 单列；若用"触发→停"实测距离则 `basis='trigger'`、reaction=0，禁止重复计延迟。

## 4. 边界运行结果（正式，24 episode）

| 设计类别 | ep | 业务结果 | 物理结果 | 制动实测速度范围 | 停止距离范围 | 最小路径净空 | 最小球包络间隙 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BLOCKED_EXIT（静态远触发） | 4 | ABORT 4 | NO_CONTACT 4 | 0.067 m/s | −0.001–0 m | 0–1.5e-7 m | 4.64–11.86 m | 静态障碍在路径上→早停车、等待超时退出 |
| BLOCKED_EXIT_TIGHT（静态紧触发） | 2 | ABORT 2 | NO_CONTACT 2 | 0.064 m/s | 0.002 m | 1.000 m | 1.62 m | 1 m 航点导致每段停留，触发速度低；紧几何但低速 |
| NO_STOP_EXPECTED（路径旁/远横穿） | 4 | SUCCESS 4 | NO_CONTACT 4 | — | — | 1.50–3.00 m | 1.13–14.53 m | 净空高于阈值→不触发停车 |
| STOP_WAIT_RESUME（横穿早） | 2 | SUCCESS 2 | NO_CONTACT 2 | ~0 m/s | 0 m | 0.015 m | 7.58 m | 远距离早停后等待、恢复 |
| INSUFFICIENT_MARGIN（横穿晚/延迟不足） | 6 | ABORT 6 | CONTACT_INFERRED 6 | ~0 m/s | 0 m | 0–0.022 m | **−0.118…−0.067 m** | 停车后障碍仍进入球包络；首接触晚于停稳 |
| STOP_OBSTACLE_HOLD（迎面障碍停住） | 2 | ABORT 2 | NO_CONTACT 2 | 0.064 m/s | 0.002 m | 1.02 m | 2.02 m | 障碍停在路径上→等待超时退出，无接触 |
| POST_STOP_COLLISION（迎面继续） | 2 | ABORT 2 | CONTACT_INFERRED 2 | **0.613 m/s** | 0.306 m | 0 m | **−0.115 m** | 停稳后接触（首接触 14.85 s，停稳后障碍接近 0.856 m） |
| HIGH_SPEED_STOP（近/超最高实测速度） | 2 | SUCCESS 2 | NO_CONTACT 2 | **0.992 m/s** | 0.522 m | 0.006 m | 4.06 m | 超出模型支持上限→UNSUPPORTED 564 步；不据此声称安全 |

- 覆盖：静态阻塞（远/紧/路径旁）、横穿（早/晚/远）、迎面（停住/继续/远）、近最高速度、延迟不足（obs 0.20/0.18 + action 0.10/0.12）、超模型速度；每设计 2 次显式重复（同参数，不换 seed 冒充独立样本）。
- 业务/物理分离：`business_outcome ∈ {SUCCESS,ABORT,TIMEOUT,INVALID}`，`physical_outcome ∈ {NO_CONTACT,CONTACT_MEASURED,CONTACT_INFERRED,OUT_OF_BOUNDS}`；ABORT 与接触/无接触分别统计。
- 原 stop=1.1 m 为默认阈值；上一轮候选 1.38 m **未在本轮升级为默认**，边界集只运行默认 1.1 m，候选地位保持。

## 5. 停止需求与适用范围（据本轮 + 前序实测）

- **静态阻塞触发位置：** 路径上的静态障碍在航段进入预测线段后 clearance≈0，触发发生在远距离/低速（本组远触发中心距 5+ m、速度 0.067 m/s）；因此 "静态阻塞" 主要证明**路径占用→停车→退出**，不是高速制动能力。真正的高速/紧触发由横穿/迎面场景提供。
- **横穿/迎面停车不等于避免未来接触：** CONTACT_INFERRED 8/24；最小球包络间隙为负（−0.115、−0.118、−0.067 m）。停车后障碍继续运动并把距离继续缩小 0.83–0.86 m（B_cross_late、C_collide、E 段），说明必须同时跟踪"障碍未来运动"，不能以我方停车为安全条件。
- **速度支持上限：** 本轮最大制动实测速度 0.992 m/s（D），超出 `brake_final4` 支持上限 0.851428 m/s；生产记录 564 步 `UNSUPPORTED/ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT`、required/margin=null。**该结果只能说明"超出模型支持、未验证"，不能说明 1.1 m 在 0.99 m/s 下安全或危险。**
- **延迟不足：** obs 0.20 s / action 0.10 s 与 obs 0.18 s / action 0.12 s 段在紧横穿几何下出现包络内接触（首接触 1.05–1.20 s、停稳后），与"剩余间隙不足"预期一致；动作延迟仍在 TTL 内到达（0.10/0.12 <0.15 s），因此不是 TTL 失效，而是**观测年龄+反应距离+几何余量不足**。
- **制动起点/初始速度：** 用首个 STOP 决策行（决策时点）与实测速度，停止距离沿初始速度方向到速度≤0.08 连续 0.5 s；本组最大停止距离 0.522 m @0.992 m/s、0.315 m @0.639、0.306 m @0.613。与 `brake_final4`（0.584659 m @0.851）同量级；样本最大值不是严格上界。
- **包络后间隙：** 阈值处（1.1/1.38）扣半对角线机体球 0.067966 m 与障碍球 0.3 m：A 0.732 m、候选 1.38 1.012 m（推导）。AABB 中心偏移未记录，完整外廓保守性未确认；球/AABB 近似不是网格扫掠证明。
- **TTL/预测时域（承接上一轮）：** TTL=150 ms + 50 ms tick 下可容忍传输 ≤100 ms；1.0 s 预测时域短于实测停止时间（可达 3.3 s），预测时域不能替代停止阈值/最大等待。ttl_over 复核仍为 TIMEOUT、过期动作未执行。

## 6. 上一轮专项复核（新冻结、预声明判据）

| 段 | 结果 | 预声明判据命中 |
| --- | --- | --- |
| latency_clock_mapping_recheck | ABORT `V2_REJECT_STALE_OBSERVATION`，post-abort 60 行 | 命中 expected `acceptable_paths` 优先级 1：observation `CLOCK_MAPPING_UNUSABLE` + admission `REJECT_STALE_OBSERVATION`；未事后扩展集合 |
| latency_ttl_over_recheck | TIMEOUT `WALL_TIMEOUT`，post-abort 60 行 | (c) 六项：901 被拒 id 与 300 executed id 无交集；首拒绝 step 303 age=0.150 s；首拒绝前 300 连续 APPLIED（active expires 15150 ms > host 15100 ms）；到期→NONE；零目标回退；业务 TIMEOUT |

## 7. 证据域与限制（明确）

- **接触：** 本环境 ContactSensor / PhysxContactReportAPI 探针无法记录障碍-机器人接触力（robot 侧/障碍侧/多 link/scene/manual 均失败，而物理推挤可观测）。本轮接触采用**球重叠运动学推断**：球保守半径重叠 >0.02 m 判 `CONTACT_INFERRED`，记录重叠量、命令零、速度、首接触时间；**不是测力证据**，报告与核验 JSON 均显式标注 `contact_evidence_mode='kinematic_inference'`；`CONTACT_MEASURED=0`。
- **时钟：** host 基准 = Isaac 仿真时间；camera 为模拟第二时钟域（偏移 20 ms/漂移 200 ppm/不确定度 5 ms）；无真实跨设备时钟、串口、PX4 延迟。上一轮"模拟双时钟/单时钟仿真证据"按此层次理解。
- **场景：** 单地图南走廊、单机体、ORACLE 观测、运动学障碍；`obstacle-time-clamp` 用于让障碍在 `end_time` 停住（C_stop_short/C_early 等）；该开关仅边界段启用，回归段默认关闭（行为与既有证据一致）。
- **回归：** 仅新增记录/参数化（`--vehicle-config`、`--obstacle-time-clamp`）+ supervisor 等价重构；未改阈值/状态机，因此只跑 3 个代表性回归（动态/无障碍/故障）而非全部旧仿真。回归结果：dynamic/no_obstacle SUCCESS、fault ABORT `V2_REJECT_TTL_EXPIRED`（与既有 v2 证据一致）。
- **未验证：** 真实 PX4/串口/执行器延迟、真实接触力、网格/体积扫掠、真实机体外廓与姿态包络、真实 failsafe、全地图样本；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK。

## 8. 独立核验

- 工具：`scripts/verify_clearance_boundary_runs.py`（纯标准库；从原始 steps/episodes/manifest + 冻结重建；checks 带四类 category；缺字段→INCOMPLETE；偏差不并入 PASS）。
- 输出：`docs/reports/map_eval/clearance_boundary/verify_clearance_boundary.json`。
- 结论：**PASS**：`status=PASS`、41/41 checks（data_integrity 10、contract_invariant 14、scenario_expectation 9、performance_boundary 8）、failures=0、deviations=0、missing_fields=0；接触证据模式 `kinematic_inference`（球重叠 >0.02 m，非测力）；clock_mapping 命中预声明路径、ttl_over 满足预声明 (c) 六项；regression 与既有 v2 证据一致。
- 分类报告：数据完整性 / 合同不变量 / 场景预期 / 性能与能力边界四类分别给出，性能边界包含制动/接近/接触/UNSUPPORTED 统计与适用范围，不与"预期满足"混为一类。

## 9. 证据与 hash

| 产物 | SHA-256 |
| --- | --- |
| `clearance_boundary_freeze_v1.json` | `7c8297e66af19b0e817d25da7d110115d33ee6acc8062a7a0d889e22f35fd8b2` |
| `clearance_boundary_expected_v1.json` | `dc88f5905a13f17aea1c82a35a21465ce30642ef2e1f1b6676983c45c85303aa` |
| `clearance_boundary_cases_v1.json` | `40039748c1bb02ff36aca20cf095d276b9a06b09fb7ac0faf56673c2d984a2c6` |
| `brake_model_v1.json` | `c6a5eeb185896ac0af886ba00aa26205c6f893d2cd30be70b5ea96556770341a` |
| `sim_reference_boundary_fast.yaml` | `7ca440c4e4c083b3ba6460b405800e3ba6ac16d6937fa85648f7b246d3ccaa5b` |
| `boundary_default/summary.json` | `ccfe37f0e26e0dbbc3464077152aa50db29feda748d764f04997f795e58d4a3d` |
| `boundary_default/episodes.jsonl` | `f4656ffe207fced492ae5d5d416913f0961c66aecc7064c48b7c0e629f28fb3a` |
| `boundary_default/manifest.json` | `3bb49b154a8fb00ef427414219723464abca94c2c90eaba14cafd0d665bab8c6` |
| `boundary_default/steps.jsonl (raw, gitignored)` | `cab4e05482b2a75804d7da9e9c50188354233414fb0e5e3a8814ca782646ae12` |
| `boundary_delay_e1/summary.json` | `f45c5afcab26b9ffe2912a5e1aa7a586d37ddeac33262e86a15fcbd31f35b0fe` |
| `boundary_delay_e1/episodes.jsonl` | `76ec965fc8762ab61eac39cf3c7ce0d01755f3e506b930f3230c811f6c4b199a` |
| `boundary_delay_e1/manifest.json` | `8e57a3fba4c9580358df760e59c1d6daa4eddff2de7d51b5846b3b0f80197146` |
| `boundary_delay_e1/steps.jsonl (raw, gitignored)` | `8477989aa457ee017a724cd16c6bec5d0bc6af6e3abf17ca327f8a1809c5d576` |
| `boundary_delay_e2/summary.json` | `463ac19318d6cceb916a62e70c142bece6bdbcd904978265a72e4ef38c4d3c64` |
| `boundary_delay_e2/episodes.jsonl` | `17e75708eb0ba58d6c660596e508bbd997ecf8b52fc908362c1d4645730ce2c4` |
| `boundary_delay_e2/manifest.json` | `36046dc9686d8585e249cd2ea393fd42f5dc09c9a04e5a1f08f315eb19ef895f` |
| `boundary_delay_e2/steps.jsonl (raw, gitignored)` | `cc789387a38fc2760ad7450ea7df49f5232b58ad16192fa8b75308d34a163140` |
| `boundary_fast/summary.json` | `07ca8ef26aaf474afa1bafcd49e2f1cbbf0620bf27466a313c7419f0e6d4239d` |
| `boundary_fast/episodes.jsonl` | `bba9cc38047c932036f5ac14f9073dfc995638ac6b3fdcd6aae3a8b03467aa87` |
| `boundary_fast/manifest.json` | `db377e70242519e74ded86dc1e94c36c86dc9be4d41fbdb786e622d313cfebd3` |
| `boundary_fast/steps.jsonl (raw, gitignored)` | `babe1763bba201b72e37428ff669679ca369ce5152a63177bac1d2b3f7330457` |
| `latency_clock_mapping_recheck/summary.json` | `fe50683b47e85b76b1a160268e0b39b474ec8a352273a135663d51282e330885` |
| `latency_clock_mapping_recheck/episodes.jsonl` | `62860d8460c7f95368156c2665cb27a8781686b06f2e47318cd3a12a34336a71` |
| `latency_clock_mapping_recheck/manifest.json` | `7df09700e8ec63e99dfea1f69df998cb71fbed4ee631ce918c39998c53eeef9d` |
| `latency_clock_mapping_recheck/steps.jsonl (raw, gitignored)` | `d14c2616c87fcf8440a2d05c14dee26a24b79d948202c387a1027634bf1e26b9` |
| `latency_ttl_over_recheck/summary.json` | `13332f4c9ce3d969b16b2baf481aa15064fde7664beff8d647b75b4e64f080fd` |
| `latency_ttl_over_recheck/episodes.jsonl` | `9d4739433b03c651e232afb1f0422c26918be88a21997bc40e7c23e794ad2a3d` |
| `latency_ttl_over_recheck/manifest.json` | `412a5a55ba39eee87244613c37bc0d757ebf425e1483b14208a12f077c030e30` |
| `latency_ttl_over_recheck/steps.jsonl (raw, gitignored)` | `1a202451679d069a731eb70750e47af48243f2a05e0772bd8b7cc8c1a7101b1f` |
| `regression_dynamic/summary.json` | `6ea1e7da60c3909293ee344727f895b3c921e28db66ea05e54410c1173d9242d` |
| `regression_dynamic/episodes.jsonl` | `ce3f74076c72f6de9a78af81926b8d278bb4ff642b888a0c6f0ec2ec3c01c758` |
| `regression_dynamic/manifest.json` | `0876a1ea688a70e82f56b0f5cad6172784135da48980f0f2530434cbbcdcf089` |
| `regression_dynamic/steps.jsonl (raw, gitignored)` | `2c9428e91680ae6b4a4c01540a5e99ce902b3d3af6893e192d5391bf7f3c4da1` |
| `regression_no_obstacle/summary.json` | `b6368d9f72e5e0a59ea8c80dd358ac9a04a3e641c3203076a3ee56cfca2bb369` |
| `regression_no_obstacle/episodes.jsonl` | `77385a8939384cd5cca2a623149ba3c1f6263fc040c010b3c4b35d16d090f177` |
| `regression_no_obstacle/manifest.json` | `8237fc0c62bf15d810e090ed14eb2ca4ede71cbb34d7a8a73f95c670688f07a8` |
| `regression_no_obstacle/steps.jsonl (raw, gitignored)` | `35cf72536dc188cbd3c335b1e4cd5e9787518743a58df807a6047f079b6e61d6` |
| `regression_fault/summary.json` | `cd338a6a8900df93b1b2138512de9b9e859ca3df23866edce6384c1b4b08c0a4` |
| `regression_fault/episodes.jsonl` | `86e6b97dc04d7f4595fc4076edf9fcfc565385eefe3c0b17a6abf17b408625ad` |
| `regression_fault/manifest.json` | `c146e99b3e0338776070674ad5266e8981148d2b35c3925915cc87ff205f8095` |
| `regression_fault/steps.jsonl (raw, gitignored)` | `0d76529e5526088bfb55a7671e75628dc2188eb92d288e256197abdc2e85cbf9` |
| `screenshots/boundary_default_boundary_A_static_offpath_r0-supervisor-boundary_default_success.png` | `9ea0f66ffe65e62cee65ff499a14844fcd479cb090694b0aaa428e3b31379b04` |
| `screenshots/boundary_default_boundary_A_static_offpath_r1-supervisor-boundary_default_success.png` | `c09a49518607bd8df1acf00f437da3ae130b387715785c29f8fbd006bb5806de` |
| `screenshots/boundary_fast_boundary_D_fast_cross_r0-supervisor-boundary_fast_success.png` | `646acc109cc41ddbeefd3c8e584aacb73789fba61bf0ff238d60698ae409d369` |
| `screenshots/boundary_fast_boundary_D_fast_cross_r1-supervisor-boundary_fast_success.png` | `2c90587f168e147d7b28363e273b6ec19e7c5478e869ea346dd21159b8adb266` |
| `verify_clearance_boundary.json` | `fc5abe487f6d628981f1889f1437ef6eca14b1b48111c0602abf3f3fd720a48f` |
| `analyze_clearance_boundary.json` | `816a1ace2b2c67b0fec42fa88a30fc01cbc5f691f2a5b541a7f22d55706aea17` |
| `CLEARANCE_GEOMETRY_CONTRACT.md` | `c666a6b0ed22817a4fe82795a8599b14c26f72fc9506cc76631050c7166bda06` |

## 10. 精确复现命令（前台 GUI，无 --headless）

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 1) 预运行冻结（代码提交后、正式运行前；已存在会拒绝覆盖）
& $py scripts/make_boundary_freeze.py
# 2) 正式 9 段（串行；脚本见 tmp/run_boundary_formal.ps1 的生成逻辑，正式命令以冻结 run_plan 为准）
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/clearance_boundary_cases_v1.json --only-cases <段 case_ids> --methods supervisor --execution-path v2 --segment-id boundary_default --vehicle-config configs/vehicles/sim_reference.yaml --stop-distance-m 1.1 --obstacle-time-clamp --screenshots --obs-delay-s 0.15 --action-delay-s 0.1 --ttl-ms 150 --max-age-ms 150 --allowed-observation-age-ms 300 --post-abort-observe-s 3.0 --clock-offset-ms 20 --clock-drift-ppm 200 --clock-uncertainty-ms 5 --freeze configs/scenarios/clearance_boundary_freeze_v1.json --code-commit <冻结 commit> --kit_args=--/app/vulkan=false --device cuda:0 --output outputs/map_eval/bnd_boundary_default
# 其余段：boundary_delay_e1（obs 0.20/action 0.10）、boundary_delay_e2（0.18/0.12）、boundary_fast（--vehicle-config configs/vehicles/sim_reference_boundary_fast.yaml）、
# latency_clock_mapping_recheck（--obs-mapping-fail-step 280）、latency_ttl_over_recheck（--transport-stall-step 300 --transport-stall-delay-s 0.15）、
# regression_dynamic/no_obstacle/fault（obs 0/action 0/clock 0/allowed 250/ttl 150/max_age 150/stop 1.1/post 0）
# 3) 独立核验与参数分析
& $py scripts/verify_clearance_boundary_runs.py --freeze configs/scenarios/clearance_boundary_freeze_v1.json --run boundary_default=outputs/map_eval/bnd_boundary_default --run boundary_delay_e1=outputs/map_eval/bnd_boundary_delay_e1 --run boundary_delay_e2=outputs/map_eval/bnd_boundary_delay_e2 --run boundary_fast=outputs/map_eval/bnd_boundary_fast --run latency_clock_mapping_recheck=outputs/map_eval/bnd_latency_clock_mapping_recheck --run latency_ttl_over_recheck=outputs/map_eval/bnd_latency_ttl_over_recheck --run regression_dynamic=outputs/map_eval/bnd_regression_dynamic --run regression_no_obstacle=outputs/map_eval/bnd_regression_no_obstacle --run regression_fault=outputs/map_eval/bnd_regression_fault --expected configs/scenarios/clearance_boundary_expected_v1.json --brake-model configs/scenarios/brake_model_v1.json --repo-root . --output docs/reports/map_eval/clearance_boundary/verify_clearance_boundary.json
& $py scripts/analyze_clearance_boundary.py --output docs/reports/map_eval/clearance_boundary/analyze_clearance_boundary.json
& $py -m pytest -q
```

## 11. 失败/重试/未完成（保留）

- 接触力传感尝试（robot/obstacle 双侧、per-link、scene、manual、PhysxContactReportAPI）全部失败或数据不更新；保留探针运行 `outputs/map_eval/calib_probe*`，并据此改用运动学推断（证据域已在核验 JSON 标注）。这同时意味着**旧报告中 contact=0 不能证明无接触**，旧接触类结论需按此限制重读。
- 调试/校准运行（`boundary_smoke1`、`boundary_calibA/B/D/E1/E2`、`calib*`）保留，不进入正式分母。
- 旧 latency 运行/冻结（`outputs/map_eval/latency_*`、`latency_*freeze_v2.json`）保留不改写；上一轮 clock_mapping 预期偏差继续登记。
- 预冻结预期、案例与包络半径口径变更：接触推断、半对角线包络均为**运行前冻结**的内容（expected/freeze/manifest）；运行后未修改冻结或扩张合法结果集合。核验器的字段别名/记录时点适配属于核验器实现修正，需在核验 JSON 中记录，不影响原始记录。
- 未完成/未验证：真实接触力、真实跨设备时钟、真实 PX4/串口/执行器延迟、SITL/HIL/实机、全地图/全姿态外廓扫掠。

## 12. 下一工作包

1. 可在 Isaac 中尝试直接读取 PhysX contact report（`omni.physx` 事件/ContactView）恢复测力证据；若仍不可用，保持运动学推断并扩大重叠判据验证（OBB/多姿态）。
2. 真实 PX4 Offboard-loss/TTL 语义与执行器延迟（需外部固件资料）。
3. 高速/近距离专项扩大（>0.85 m/s、closing>1 m/s、多方向/多高度、体积扫掠净空）。
4. 将 AABB 中心偏移/姿态包络纳入运行时测量与冻结字段；把 clearance `applicability` 支持域与 supervisor 退出策略联立评估。
5. 规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；不提升任何 Gate。
