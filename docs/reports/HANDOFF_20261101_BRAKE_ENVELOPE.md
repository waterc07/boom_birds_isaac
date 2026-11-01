# 交接记录：制动包络与故障后物理观测（2026-11-01）

## 分支与提交

- 分支 codex/bb22-brake-envelope（自 add86ed），未推送远端。
- 444f36f feat: 制动/故障后观测实验、36+8 案例、冻结脚本。
- dff670b、51c5001、7b6acd8 chore: 冻结/更新 commit（含截图捕获）。
- ca688c4 fix: 每 episode 按新 gate 重置 executor.control_epoch；前一次 D_s0.8 失败保留。
- 待提交 docs: 报告、证据、截图、hash、交接、独立核验。

## 结果

- 36 制动：实测初始速度 0.248–0.851 m/s，停止距离 0.185–0.585 m，停止时间 1.25–3.25 s；横向漂移 <0.005 m；无接触。
- 8 故障后观测：A/B/C/D ×2 全部业务 ABORT、物理 STOPPED；A/B/C 旧 setpoint 到 TTL 后降级，D 立即失效；.757 m/s 时差约 0.133 m（≈v·150 ms）。
- 独立核验 13 项 PASS；36/8 分母、覆盖、指标重算、v2 接纳/TTL、故障后降级、hash/GUI 全通过。

## 关键语义

- 拒绝动作不进入执行器 ≠ 旧 setpoint 立即失效；旧 setpoint 在其 expires 前仍可能被执行，之后 executor 进入零目标 hover/hold。业务 ABORT ≠ 物理停止。
- D 类撤权/上下文失效通过 executor control epoch 使旧 setpoint 立即拒绝；没有用零速度动作伪装撤权后继续发布。
- TTL=150 ms 是陈旧动作约束；故障残余距离与 TTL 一致，不能通过放大 TTL 规避拒绝。

## 参数判断（仅当前模型）

- stop=1.1 m：最大实测 .585 m + 150 ms 残余 .128 m = .713 m，模型内余量 .387 m；不是严格最坏上界。
- 预测 1.0 s：前视 .851 m（在 .851 m/s）大于制动距离，但停止时间可到 3.25 s；不能替代停止阈值/最大等待。
- release=1.6 m 保留；无新释放数据。

## 证据

- 报告：docs/reports/map_eval/MAP_BRAKE_ENVELOPE_REPORT.md
- 摘要/证据：docs/reports/map_eval/brake/evidence/
- 核验：docs/reports/map_eval/verify_brake_final.json
- 原始：outputs/map_eval/brake_final4（正式）；brake_final1/2/3 保留失败与重试。
- GUI：brake start/stopped、fault_A/B/D start/stopped 截图。

## 未运行/边界

- 单时钟仿真；未测真实跨时钟/串口/PX4/执行器延迟；无 PX4 Sender；未跑 PPO/真实感知/板端/SITL/HIL/实机；不提升 Gate。
- 主动零目标 hover/hold 不是被动滑行或实机 failsafe；不能写成任一层实机安全。
- 下一工作包：多位置/高度/姿态包络、体积净空、时钟/延迟注入、真实 PX4 failsafe（需外部资料）。
- AGENTS/PROJECT_PLAN/README 局部状态同步在工作树（含用户修改），未提交。
