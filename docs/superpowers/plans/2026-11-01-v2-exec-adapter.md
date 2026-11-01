# v2 执行适配与故障合同计划（2026-11-01）

> **状态：** IN PROGRESS
> **来源章节：** V2.2 §10.4、§16.1–16.8、§17.3、§26.6–26.7、§27.2–27.7、§28.3；HANDOFF_20261101_DYNAMIC_SUPERVISOR.md
> **证据域：** 标准库单元测试 + 仿真动力学（前台 GUI，DirectX/D3D12）
> **Gate：** 不提升 G2.6；不是 PX4 Sender、板端或实机安全

## 目标

1. 建立逐字段 v1→v2 映射、四级上下文/clock/sync/PX4 boot 来源、观测/动作时间与职责边界。
2. 在动态监督器执行前接入 v2 ActionArbiter、ActionEnvelope、所有权和不可续期 TTL；保留 v1 显式对照。
3. 纯软件故障测试 + ≥7 类模拟故障 GUI 集（每类≥2，共≥12）+ 20 动态 + 8 无障碍回归。
4. 独立核验完整关联链，报告/交接/提交；失败保留。

## 设计边界

- v1 路径仍可显式选择；v2 新路径不静默混用；运行 manifest 记录 execution_path。
- 模拟 PX4 boot/session 身份显式标注，仅验证隔离语义。
- 监督器/制导生成新动作；gate 是接纳/所有权过滤层；执行器只接收已接纳动作。
- 拒绝动作不进入 setpoint/执行器；故障 episode 在软件边界中止并记录拒绝原因。
- 等待/保持：每个控制步生成新动作；SEND_CACHED 不续期；reset/epoch/boot/owner 变化清缓存。

## 写域

- src/boom_birds/sim/v2_execution.py、tests/sim/test_v2_execution.py。
- scripts/run_dynamic_eval.py 的 v2 分支、故障注入；scripts/make_v2_freeze.py、verify_v2_execution.py。
- configs/scenarios/map_v2_fault_cases_v1.json、map_v2_regression_cases_v1.json、v2 freeze 文件。
- 报告/交接/证据。

## 验收

- 10 项纯软件故障合同测试；20 动态 +8 回归 +14 故障 GUI（7 类×2）；独立核验完整链；pytest/审计/diff；中文提交，不推送。
