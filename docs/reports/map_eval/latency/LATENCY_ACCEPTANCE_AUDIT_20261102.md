# 上一轮延迟包络验收口径审查（2026-11-02）

> **状态：** AUDIT（审查结论；不是新验收，不提升旧结果层级）
> **审查对象：** `codex/bb22-latency-envelope` 的 `6ddb14f`、`0c03281`、`e40db26`、`9884c19` 与冻结 `latency_pair_freeze_v2.json` / `latency_special_freeze_v2.json`
> **证据域：** 文档 + 原始运行记录（`outputs/map_eval/latency_*`）+ 独立核验 JSON；无新 Isaac 运行
> **最后核对：** 2026-11-02

## 1. 时间线与证据定位

| 事件 | 本地时间（+08:00） | 证据 |
| --- | --- | --- |
| 代码提交 `6ddb14f`（到达门/双时钟/运行器/核验器/expected 初版） | 2026-11-02 13:09:08 | `git show 6ddb14f` |
| 核验器放宽提交 `0c03281`（运行前） | 13:12:25 | `git show 0c03281` |
| 预运行冻结 v2 生成 | 13:12:31 | `latency_*_freeze_v2.json` 的 `frozen_at` |
| 正式 A/B/专项/回归运行 | 13:13–13:48 | `outputs/map_eval/latency_formal2_*` 等 |
| 运行后核验器修改提交 `e40db26` | 13:57:35 | `git show e40db26` |
| 报告/证据提交 `9884c19` | 13:57:52 | `git log` |

关键事实：`0c03281` 早于冻结与正式运行；`e40db26` 晚于正式运行，**最终 20/20 PASS 使用的核验器包含运行后修改**。旧冻结与旧运行保留，未改写。

## 2. `0c03281`（运行前核验器放宽）逐项审查

| 变更 | 内容 | 合同/预期依据 | 结论 |
| --- | --- | --- | --- |
| expected `alternatives` 继承 | `expected_outcome_alternatives` 从 segment 继承到 case | 该字段在 `6ddb14f`（冻结前）的 `latency_expected_v1.json` 已存在并被冻结写入；不是事后新增 | **预冻结范围内**；但"可接受结果集合"本身没有 V2.2 合同定义，属评价规格，必须在冻结中显式、有界、不可事后扩张 |
| ttl_over 残余证据形状 (a)/(b) | 允许 POST_ABORT 中 applied 非空/HOLDING，或 RUN 到达拒绝行携带旧 active applied | 用"拒绝 ≠ 停止、旧 setpoint 有效期"语义解释 | **论证方向正确但形状假设错误**：单调发布队列下超时到达一定晚于 active 发布，其到达时 active 必已过期；实测 RUN 拒绝行 `applied=None`。该放宽不足以描述实际证据形态（后由 (c) 取代，见 §3） |

`0c03281` 未修改任何运行器行为、冻结内容或原始运行；只修改核验器与测试。

## 3. `e40db26`（运行后修改核验器）逐项分类

| # | 修改 | 类别 | 是否影响行为结论 |
| --- | --- | --- | --- |
| 1 | `phase_summary` 只在 episode 顶层校验、零计数 phase 视为等价 | 数据完整性/记录定义 | 否（计划 §3.2 本来就把 phase_summary 放在 episode 顶层） |
| 2 | `metrics.post_abort` 无窗口允许 null | 数据完整性/记录定义 | 否（无 POST_ABORT 行时本无统计） |
| 3 | `observation_valid = mapping_usable AND raw_dropout_valid`；dropout 行 age 允许 0 占位 | 数据完整性/语义修正 | 否（E 类 dropout 使 raw observation 无效，与 mapping 可用不矛盾） |
| 4 | metrics 改为 RUN(含决策行)+POST_ABORT 全行重算 | 数据完整性/定义对齐 | 否（与运行器记录定义一致） |
| 5 | ttl_over 判据 (c)：拒绝存在且未执行、首次拒绝前旧有效 setpoint、expiry→NONE、零目标回退、业务结果 TIMEOUT/ABORT | **运行后验收判据修改** | **是（判据）；物理事实由原始记录独立复核（§5）** |
| 6 | regression 运行跳过预冻结 expected（只要求既有 v2 证据 SUCCESS 一致） | 验收范围修正 | 否（回归用例不在预冻结 expected 覆盖） |
| 7 | reason 接受 `expected_reason` **或** 任一预冻结 reason 字段（`admission_reject_reason`/`observation_reason`/`inflight_arrival_reject_reason`） | **运行后验收口径扩张** | **是；必须登记偏差并重跑受影响专项** |

结论：第 1–4、6 项是对记录/校验口径的技术修正，不改变行为结论；第 5、7 项属于验收判据在运行后落盘，其中第 7 项有"预冻结 expected 已列 admission 字段"的部分依据，但**接受逻辑是运行后新增**。因此：

> **旧 `20/20 PASS` 是"数据/合同一致 + 在修改后的判据下未发现违约"，不等于"预冻结行为预期全部满足"。旧结果不提升层级。**

## 4. 20 项核验的分类（旧 JSON：`docs/reports/map_eval/latency/verify_latency_runs.json`，sha256 `9e7c7102…`）

| 类别 | 检查项 | 证明范围 |
| --- | --- | --- |
| 数据完整性（6） | `schema_completeness`、`artifact_hashes`、`freeze_lineage`、`gui_evidence`、`episode_continuity`、`denominator_and_episode_ids` | 记录齐全、hash/冻结世系、分母/唯一性、边界连续 |
| 合同不变量（7） | `clock_domain_and_mapping`、`observation_age_and_queueing`、`ttl_no_renewal`、`arrival_expiry_rejection`、`rejection_never_executed`、`hold_until_expiry_then_none`、`applied_record_consistency` | 时钟/年龄/TTL/到达门/执行与旧 setpoint 语义 |
| 设计一致性（2） | `pair_consistency`、`metrics_match_recorded` | A/B 同条件配对、记录指标与重算一致 |
| 场景预期（3） | `expected_classification`、`special_segments`、`post_abort_rows` | 逐场景预期与专项证据形态（依赖修改后判据） |
| 性能/边界（2） | `brake_start_and_stop_metrics`、`geometry_contact_metrics` | 制动起点/距离/时间、中心距/包络/接触（重算，非预期） |

因此旧 PASS 的 15 项属数据/合同/设计一致性，3 项场景预期依赖运行后判据修改，2 项性能指标不构成能力边界验收。

## 5. ttl_over TIMEOUT 独立复核（旧原始记录）

复核脚本直接读 `outputs/map_eval/latency_ttl_over/steps.jsonl`：

- 被拒 action id 集合（含 `rejections_this_step`）901 个，实际 `executed_action_id` 300 个，**交集为空** → 未执行任何过期动作。
- 首次到达拒绝 step 303、reason `ACTION_EXPIRED`、age=0.150 s；此前 step 296–301 连续 300 行 APPLIED（旧有效 setpoint，最后 active `STUDENT-1-0-299`，`expires=15150 ms > host=15100 ms`）；step 302 `NONE/ACTION_EXPIRED`（active 到期）；post-abort 60 行中 57 NONE + 3 REJECTED，**post-abort 无任何 executed**。
- 业务结果 TIMEOUT/WALL_TIMEOUT；物理上执行器在无 setpoint 时进入零目标 hold（仿真专用，不是 PX4 Offstage-loss failsafe）。
- 结论：旧 ttl_over 证据本身支持"拒绝≠执行、旧 setpoint 与过期新动作分开追踪、超 TTL 后回退零目标"，但 (c) 判据文字是运行后落盘，须在新冻结中预声明后重跑。

## 6. clock_mapping expected reason 偏差定性

- 预冻结 expected：`expected_reason='OBSERVATION_STALE'`，同时列 `observation_reason='CLOCK_MAPPING_UNUSABLE'`、`admission_reject_reason='REJECT_STALE_OBSERVATION'`、`supervisor_state='DEGRADED_ABORT'`。
- 实际：step 280 观测 `CLOCK_MAPPING_UNUSABLE`；动作提交被 `REJECT_STALE_OBSERVATION`（运行器的"年龄不可证"保守策略在提交前拒绝）；业务 reason `V2_REJECT_STALE_OBSERVATION`，未等到 supervisor 2 s stale 超时路径。
- 定性：**不是原因码别名，也不是同码不同名**；是"多个合法失效路径 + 提交期优先级"：V2 合同要求不可证新鲜度的动作不得发送，因此 admission 拒绝先发生；supervisor `OBSERVATION_STALE` 是候选的次级路径。预冻结 expected 只把次级路径写成主 reason，属**预期规格不足**，不是运行行为违反合同；但旧 verifier 的接受逻辑（含 admission 字段）是运行后扩张，不能据此声称"预冻结预期已满足"。
- 处理：保留旧证据与偏差；新冻结 `latency_clock_mapping_recheck` 预声明可接受路径集合与优先级，再运行一次；不得修改旧冻结或事后扩集合。

## 7. 时钟层次澄清（修正旧报告表述层次）

- 正常动力学与所有 TTL/队列/停止判据均以 **Isaac 仿真时间**为基准（`time_s`/`host_now_ns` 由 `elapsed=(step+1)*dt` 派生），不存在真实设备时钟。
- `camera_sim` 是**模拟第二时钟域**：计划偏移 20 ms、漂移 200 ppm、不确定度 5 ms，映射误差界 `|offset|+uncertainty+ceil(|drift|·t)`；用于观测年龄保守界与 mapping 失效注入。
- 因此旧报告的"模拟双时钟"指"仿真时间 + 模拟相机时钟域"，旧报告"单时钟仿真证据"指"没有真实跨设备/串口/PX4 延迟"。两者不矛盾；**不得**把它写成真实多设备时钟测试或 PX4 TIMESYNC 证据。新报告将按此层次表述，旧报告保留为历史。

## 8. 审查结论与后续动作

1. 旧结果维持"latency-envelope 仿真证据"层级，不升级为行为验收/更高 Gate；旧冻结与旧核验 JSON 保留、不改写。
2. `0c03281` 的 alternatives 属预冻结规格的沿用，但"可接受结果集合"须显式有界；ttl_over 残余形状放宽（a)/(b）依据不足，由 (c) 取代且必须在预冻结中声明。
3. `e40db26` 中 1–4、6 为技术修正；5、7 为运行后判据变更，必须通过"新冻结 + 受影响专项重跑"补齐预声明证据。
4. clock_mapping 偏差登记为"预期规格不足 + 运行后接受扩张"；ttl_over 物理事实成立但判据需预声明重跑。
5. 新工作包（`codex/bb22-clearance-boundary`）将：字段化 clearance/停止需求；预冻结 12 场景×2 边界专项；重跑 `latency_clock_mapping_recheck` 与 `latency_ttl_over_recheck`；独立核验分四类；仅新增记录不无依据重跑全部旧仿真。
