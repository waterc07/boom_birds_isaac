# 交接记录：v2 执行适配、故障验证与动力学回归（2026-11-01）

## 分支与提交

- 分支 codex/bb22-v2-exec-adapter（自 0d669db），未推送远端。
- 358d011 feat: V2ActionGate、10 项纯软件故障合同、动态评价 v2 路径与故障注入、v1 显式对照。
- ecfacbb chore: 冻结 v2 动态 20、故障 14、回归 8 计划。
- 待提交 docs：v2 报告、证据/截图/hash、交接、核验脚本与等待测试。

## 端到端链路

路线制导/监督器 → V2ActionGate（ContractContext 四级上下文 + 模拟 PX4 boot/session + ActionEnvelope/不可续期 TTL）→ ActionArbiter/所有权校验 → VelocitySetpoint（expires 取接纳动作）→ VelocityExecutor → QuadcopterEnv/PhysX → 实测位置/速度。
- v1 路径仍显式可选；manifest 记录 execution_path；无静默混用。
- 拒绝动作不进入 setpoint/执行器；每个控制步生成新动作，SEND_CACHED 不续期。
- 监督器是过滤/降级层，不是第二控制所有者；没有伪造运行期所有权交接；PENDING/ACTIVE 仅合同测试。

## 合同与纯软件验证

- tests/sim/test_v2_execution.py：10 项覆盖到期边界、重发不续期、乱序/重复/回滚、四级上下文、clock/sync、模拟 boot、所有权 pending/revoke、reset、等待新动作、拒绝不执行。
- tests/evaluation/test_supervisor.py 新增等待累计测试：max_wait 为本 episode 累计上限，状态切换/恢复不重置。
- 上一轮 B “等待 28.05 s”是 4 episode 汇总（约 7.0 s/ep），已澄清；无代码缺陷。

## GUI 结果（前台 DirectX/D3D12）

| 运行 | episode | 结果 |
| --- | --- | --- |
| v2 动态正常 | 20 | SUCCESS 8 / ABORT 12 / INVALID 0 |
| v2 无障碍回归 | 8 | SUCCESS 8/8 |
| v2 软件故障 | 14 | ABORT 14/14；7 类×2 |

- v1 supervisor 对照：20 case 结果一致、duration_delta 0.0；差异记录在 verifier notes。
- 故障原因：TTL_EXPIRED、ACTION_EXPIRED、SUPERSEDED、MISSION_EPOCH、SYNC_OR_PX4_BOOT、CLOCK_DOMAIN、CONTROL_EPOCH；拒绝动作 v2_executed=false。
- 独立核验 43 项 PASS。

## 证据

- 报告：docs/reports/map_eval/MAP_V2_EXEC_REPORT.md
- 摘要/证据：docs/reports/map_eval/v2/evidence/
- 核验：docs/reports/map_eval/verify_v2_final.json
- 原始 steps：outputs/map_eval/final_v2_dynamic1、final_v2_fault1、final_v2_regression1（忽略提交）
- GUI 截图：v2/dynamic_A_south_0-supervisor_success.png、dynamic_B_south_0-supervisor_success.png

## 验证与范围

- 全套 pytest、文档审计、本工作包 diff 检查见最终结果。
- 未运行：PPO、真实感知、板端、SITL/HIL、实机；无 PX4 Sender/固件验证；不提升 G2.6/任何 Gate。
- Vulkan 本轮未复核；你提到应已解决，但无独立证据，继续沿用 DirectX，记录不写为已验证。

## 限制与下一工作包

1. 模拟 boot/session 只证明隔离；正常链只用 host_monotonic；跨时钟映射为纯软件合同测试。
2. 故障注入在软件边界并在拒绝后 ABORT；未验证故障下持续恢复路线。
3. 监督器不是独立所有者；未伪造交接；若设计需交接需另立工作包。
4. 下一工作包：真实 PX4 Sender/TIMESYNC/固件掩码（外部资料）、双时钟运行链、所有权交接、制动/TTL 实测标定。
5. AGENTS/PROJECT_PLAN/README 局部状态同步在工作树（含用户修改），未提交。
