# BB22:G2.6 软件合同实施报告

> **状态：** INCOMPLETE（纯软件合同层已通过；板端/固件复检 NOT RUN）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §10.4、§16.1–16.8、§17.3、§26.6–26.7、§27.2–27.7、§28.3
> **证据域：** 单元测试（标准库合同）；不含 SITL/HIL/台架/实飞
> **最后核对：** 2026-10-31

## 结论

- 新增 `boom_birds.message.v2.0` / `boom_birds.action.v2.0` 标准库合同，覆盖 V2.2 要求的四级上下文、时钟域与同步代际、PX4 独立重启隔离、观测溯源与不可续期 TTL、动作接纳/合法重发/乱序与回滚拒绝、控制所有权交接，以及碰撞/重置/重启后的旧消息、动作与隐藏状态失效。
- 既有 `boom_birds.velocity.v1` 保持原行为不变并保留全部回归测试；v1→v2 迁移必须显式传入轴有效性与观测溯源，不允许只替换 schema 标签。
- 契约验证：`python -m pytest -q` → **101 passed，exit 0**（v1 33 条 + v2 68 条）；`scripts/planning/audit_documents.py` → **exit 0，PASS**。
- **Gate 判定：`BB22:G2.6` = INCOMPLETE。** 原因是 §28.3 要求 G2.6 在板端集成后复检，而固件掩码、MAVLink 链路、板端运行均未执行。软件合同层可单独引用本节证据，不得据此声明 G2.6 或 G1/G4/G5 通过。

## 实现清单（写入 `src/boom_birds/contracts/`）

| 模块 | 对应条款 | 已实现行为 |
| --- | --- | --- |
| `versions.py` | §27.1 | message/action schema id、坐标帧、单位、兼容集合 |
| `reasons.py` | §27.2–27.4 | 稳定接受/拒绝原因码；每个拒绝项有明确字符串 |
| `context.py` | §16.1–16.3、§27.2 | `MessageHeader`、`ContractContext`、`EstimatorState`、`ClockMapping`；@validate_message@ 按 §27.2 顺序返回原因码；跨时钟年龄取含误差界的最坏值，未知即拒绝 |
| `action_v2.py` | §10.4、§16.6、§16.3.2 | `VelocityPayload`（物理单位 + 4 轴 validity + FLU/Up 帧）、`ActionEnvelope`（observation_id、输入采集区间、最早安全截止、issued/expires、max_age、source、digest/identity）；`expires = min(issued+ttl, earliest_input_safe_deadline)`；BODY_HEADING_FLU→LOCAL_NED 变换；`from_velocity_v1` 显式迁移 |
| `admission.py` | §16.6、§17.3、§27.3–27.4 | `validate_action` 按 §27.3 顺序（epoch/时钟/PX4 boot/TTL/输入截止/观测年龄/所有权/有限性/帧/轴/估计/限幅）；`ActionArbiter` 锁内提交序号与缓存；重发不续期、过期即撤销并标 `ACTION_EXPIRED`；`LatestValidActionQueue` 只保留最新有效动作 |
| `ownership.py` | §16.8、§26.7 | PENDING/ACTIVE 交接；交接确认必须改变 control_epoch；超时保留原所有者；PX4 failsafe 后无外部发布者；交接记录字段按 §26.7 |
| `lifecycle.py` | §16.3.1、§16.4、§16.3.2、§17.6 | `EpochManager` 原子处理 impact / localization reset / mission reset / PX4 单独重启 / Companion 重启；队列按代际清理；GRU 隐状态与 previous action 代际门；推理结果按 epoch/代际/quarantine/年龄拒绝；`ImpactEvent` 不确定区间 quarantine |

配置：`configs/runtime/schema_v2.yaml`（schema/frame/unit 常量，TTL/年龄/垂直完整性为 PROPOSED 初值；1479/1511 标注 PROPOSED + 未固件验证）。

## 关键合同决定与理由

1. **过期边界**：`issued_at <= now < expires_at`，`now >= expires_at` 一律拒绝；Sender 重发沿用原 expires，不刷新 issued。
2. **序号与重发**：序号按 `(system_boot_id, control_epoch, source)` 严格递增；重发同一动作返回 `ACCEPT_RESEND` 且不递增、不作为新接纳；同序号不同内容拒绝；低于当前缓存序号的旧动作按“已被替换”拒绝，防止缓存回滚。
3. **PENDING 期间发布权**：本工作包测试暴露并修正了初版缺陷——旧所有者与 pending 所有者被同时放行。现按 §16.4/§16.8 只允许 pending owner 的经校验预发送动作通过；`NONE` 与 `PX4_CONFIGURED_FAILSAFE` 状态下不允许任何外部发布。
4. **partial-axis 默认拒绝**：1479 全轴组合之外，1511 仍是 PROVISIONAL；`axis_validity` 不全为真时默认拒绝，不自动降级发送忽略垂直速度的消息。
5. **垂直控制完整性**：正常速度动作默认要求 `z_velocity_valid` + `thrust_source_valid` + `height_valid` + `yaw_valid`（§10.4.3、§26.7 的保守解释）。该默认是 PROPOSED 策略，需在固件/实机验证后冻结。
6. **PX4 单独重启**：新 `px4_boot_id` 触发时间映射作废、sync generation 递增、sync 失效、localization/control epoch 递增、动作与在途推理作废、控制权交安全监督器，并要求重新确认 PX4 模式与健康状态后才允许恢复发布。
7. **不可续期 TTL 的起点**：TTL 从 issued 起算并被最早安全输入截止裁剪，避免“慢推理后重新起算”使旧观测产出新鲜动作。

## 验证记录

| 实际执行 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/contracts/test_v2_*.py -q`（RED，实现前） | exit 2，3 个模块 ImportError | `docs/reports/g2_6/contracts-v2-red.log` |
| `python -m pytest -q`（GREEN） | **101 passed in 0.38s，exit 0** | `docs/reports/g2_6/contracts-v2-green.log` |
| `python scripts/planning/audit_documents.py` | exit 0，status PASS | 控制台输出；审计文件为既有入口 |
| 标准库隔离检查（子进程 import 全部合同模块） | 无 torch/isaaclab/isaacsim/numpy/cv2 | `tests/contracts/test_action_contract.py` |

源码提交：`c730c75a0cef5cbadf398b0bc746a2dccc12df1b`（分支 `codex/bb22-g2-6-contracts`）。用户既有 V2.2 文档修订仍未提交，按现场规则原样保留，未纳入本工作包提交。

## 未验证与 NOT RUN

- PX4 固件 tag/commit、参数导出、`SET_POSITION_TARGET_LOCAL_NED` 实际掩码与 validity 映射：**NOT RUN**（无固件证据）。
- MAVLink Sender、`time_boot_ms` wrap-safe 映射、串口排队与在途延迟：**NOT RUN**（未实现 Sender）。
- `SENSOR_INTERFACE.md` 级传感器协议与 `SENSOR_INTERFACE` 消息字段：**NOT RUN**（仅有通用 `SensorMessage` 语义，未定义具体协议）。
- 完整恢复控制器状态机（§8.4–8.6 各恢复阶段的指令生成与退出条件）：**NOT RUN**；本包只实现所有权、失效与拒绝骨架。
- SITL/HIL/台架/实飞与板端复检：**NOT RUN**。
- TTL、加速度/jerk 限幅、最大安全陈旧时间的数值冻结：**PROPOSED，未冻结**（§27.5 要求先测量再冻结）。

## 已知限制

- `EstimatorState` 是归一化布尔集合，未绑定具体固件消息；真实映射必须按 §16.9 单独取证。
- 合同层不发送任何 MAVLink 消息，也不能证明 PX4 会拒绝陈旧包或按掩码执行。
- 时钟映射只实现“显式提供且代际有效”的最坏年龄；TIMESYNC 机制本体未实现。

## 下一工作包

按依赖与返工成本，下一项为**仿真动力学执行链**（复用旧 Task 3 方法）：归一化动作 → 坐标/时效检查 → 外环控制器 → 推力/机体力矩 → PhysX → 实测运动，先验证前/左/上/偏航符号、组合动作、停止、过期、reset 与不同 yaw。前置：无新增硬件；需要 Isaac Lab 现有环境与官方四旋翼资产。验收：仿真证据域，不允许标为 SITL/实机通过。
