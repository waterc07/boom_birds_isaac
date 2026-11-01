# 交接记录：动态障碍停止—等待—恢复监督器（2026-11-01）

## 分支与提交

- 分支 codex/bb22-dynamic-supervisor（自 c2e32a3），未推送远端。
- 92757f0 feat: 动态障碍合同、RouteSupervisor、配对评价入口、冻结/核验脚本、7 项测试。
- 6d4e336 chore: 冻结 A–E 20 场景 ×2 方法=40 episode。
- 待提交 docs：动态报告、证据/截图/hash、交接、核验终止 ABORT 记录修正、状态同步。

## 架构边界

- 监督器为仿真适配层，不是 PX4 控制监督器；沿用 v1 评价链（比例制导 → VelocitySetpoint TTL/epoch → VelocityExecutor → QuadcopterEnv），未完成 v2 端到端/所有权/TTL 集成。
- 停止 = 零速度 setpoint；不重置 episode/航点/位置/超时；恢复继续当前航点；ABORT 终态。
- 障碍为运动学刚体（0.4×0.4×0.6 m、真实碰撞几何，非车辆动力学）；观测 ORACLE 真值位置/速度，带延迟/dropout；监督器只读观测，不读未来脚本。

## 场景与冻结

- 20 场景：A 穿越离开、B 临时占据、C 持续占据、D 振荡、E 观测丢失，各 4；south/north 均覆盖。
- 冻结：configs/scenarios/map_dynamic_cases_v1.json、map_dynamic_freeze_v1.json。
- 监督阈值（PROPOSED）：stop 1.1 / release 1.6 m、horizon 1.0 s、obs age 0.3 s、max stale 2 s、max wait 8 s、hold 0.5 s、release hold 0.5 s、resume hold 0.3 s。
- B 类调试在 max_wait=5 s 时等待约 7.2 s 才净空导致 ABORT；改为 8 s 后重新冻结。dynamic_smoke10/11 保留。

## 最终结果（40 配对 + 8 回归，前台 GUI）

| 类别 | FOLLOW_ONLY | SUPERVISOR |
| --- | --- | --- |
| A | SUCCESS 4/4 | SUCCESS 4/4（无停车） |
| B | SUCCESS 4/4 | SUCCESS 4/4（等待 28.05 s、RESUME） |
| C | COLLISION 4/4 | ABORT 4/4（MAX_WAIT_EXCEEDED） |
| D | COLLISION 4/4 | ABORT 4/4（MAX_WAIT_EXCEEDED，切换受限） |
| E | COLLISION 4/4 | ABORT 4/4（OBSERVATION_STALE） |
| 总计 | 8 SUCCESS / 12 COLLISION | 8 SUCCESS / 12 ABORT / 0 COLLISION |

- 12 次 FOLLOW_ONLY 碰撞均为 /World/envs/env_0/Obstacle 真实接触，力 0.0231–1.3409 N；未注入 collision 标志。
- 中心点最小距离 0.222 m（0.222–10.686 m），不是表面间隙。
- 原 8 个无障碍 route 回归：SUCCESS 8/8、0 接触。
- 独立核验 25 项 PASS（分母/配对、hash、边界/计时、障碍轨迹、观测合同、状态切换、接触、预期行为 A–E、回归）。

## 证据

- 报告：docs/reports/map_eval/MAP_DYNAMIC_REPORT.md
- 摘要：docs/reports/map_eval/dynamic/evidence/summary.json
- 核验：docs/reports/map_eval/verify_dynamic_final.json（25 项 PASS）
- 原始 steps：outputs/map_eval/final_dynamic1/steps.jsonl（忽略提交）；回归 outputs/map_eval/final_regression1。
- GUI 截图：dynamic_A_south_0 / dynamic_B_south_0 supervisor 成功终点；等待/退出状态在 step 记录中。
- 失败/重试：outputs/map_eval/dynamic_smoke1…13（含 RigidPrim 崩溃、场景配置失败、max_wait=5 的 B ABORT）保留。

## 验证

- 单元测试：动态障碍 2 + 监督器 5；全套 pytest 250 passed。
- 文档审计/本工作包 diff 检查：见最终结果。
- 未运行：PPO、真实感知、板端、SITL/HIL、实机；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；不提升 Gate。
- 官方 smoke：DirectX GUI 100 步 PASS 记录保留；Vulkan 静默失败未解决（本轮未重复）。

## 限制与下一工作包

1. ORACLE 观测/运动学障碍，不是视觉感知或实机安全；未做体积扫掠，中心距离不等于表面间隙。
2. A/B FOLLOW_ONLY 未碰撞，仅记录实际相对位置，不证明安全；D 类全部 ABORT 只证明迟滞/无抖动。
3. 40 episode 不替代正式动态样本；未覆盖多障碍、动态起降、全地图。
4. 下一工作包：更多场景/真实感知、体积净空与制动标定、v2 监督/所有权/TTL 对接、Vulkan 根因、调参重建、地图面级一致性。
5. AGENTS/PROJECT_PLAN/README 局部状态同步在工作树（含用户修改），未提交。
