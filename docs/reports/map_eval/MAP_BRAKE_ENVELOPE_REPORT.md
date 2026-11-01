# 制动包络与故障后物理观测报告（2026-11-01）

> **状态：** PASS（仅当前仿真模型的测量证据；不是实机安全包络，不是 PX4 failsafe，不提升 Gate）
> **来源章节：** V2.2 §10.4、§16.6、§17.3、§26.6–26.7；HANDOFF_20261101_V2_EXECUTION.md
> **证据域：** v2 执行链 + 前台 GUI 动力学（DirectX/D3D12）
> **最后核对：** 2026-11-01

## 结论

- 36 个制动 episode 全部在有效零速度 v2 动作后停止：实测初始速度 0.248–0.851 m/s，停止距离 0.185–0.585 m，停止时间 1.25–3.25 s；横向漂移 <0.005 m，未接触地图。
- 8 个故障后物理观测 episode 全部停止，业务结果均为 ABORT；故障后继续观测，未在 ABORT 时截断物理。
- **关键语义：** 动作被拒绝 ≠ 已停止。A/B/C 类旧 setpoint 在 TTL（150 ms）内仍可能被执行，之后 VelocityExecutor 进入无 setpoint 的零目标 hover/hold 降级；D 类撤权/上下文失效使旧 setpoint 立即被拒绝。A/B/C 的故障后距离约等于 D 类 + TTL 残余（0.757 m/s 时差约 0.133 m ≈ v·0.15 s）。
- 参数判断（仅当前模型）：stop=1.1 m 覆盖实测最大停止距离 0.585 m 加 150 ms 旧命令残余约 0.128 m（合计 0.713 m），保留有余量但不构成严格上界；release=1.6 m、预测 1.0 s 可保留，但 1 s 预测不等于完整制动时间，停止阈值仍是主约束。TTL=150 ms 是陈旧动作约束，不应为缩短制动而放大或缩小。
- 无监督器/执行器阈值或逻辑修改，因此未重跑 20+8；只新增测量路径与故障后观测。实验脚本发现并修复了跨 episode executor epoch 泄漏；旧失败目录保留。

## 制动测量

| 指令速度档 | 实测初始速度范围 | 停止距离范围 | 停止时间范围 |
| --- | --- | --- | --- |
| 0.3 m/s | 0.2479 m/s | 0.185–0.187 m | 1.25–3.25 s |
| 0.6 m/s | 0.547 m/s | 0.383–0.390 m | 2.80–3.25 s |
| 0.9 m/s | 0.851 m/s | 0.584–0.595 m | 2.85–3.30 s |

- 覆盖 3 速度×2 航向×3 方向×2 重复=36；初始速度取实测，不取指令值；停止判据速度 ≤0.08 m/s 连续 0.5 s。
- 停止时间较长主要来自零目标 hover/hold 的收敛与保持，不是滑行；停止距离最大约 0.585 m。
- 横向漂移最大约 0.0048 m；最大偏移与停止距离同量级；无接触、无越界。

## 故障后物理行为

| 类型 | .35 m/s 初始 | .76 m/s 初始 | 语义 |
| --- | --- | --- | --- |
| A 无新动作自然过期 | 0.249 m / 1.30 s | 0.516 m / 1.50 s | 旧 setpoint 到 TTL 后降级 |
| B 缓存重发至 TTL 到期 | 0.249 m / 1.30 s | 0.516 m / 1.50 s | 重发不续期；到期后拒绝 |
| C 新动作被拒、旧缓存 | 0.249 m / 1.30 s | 0.516 m / 1.50 s | 新拒绝不执行；旧 setpoint 仍有效至原 expires |
| D 撤权/上下文失效 | 0.182 m / 1.15 s | 0.383 m / 1.35 s | 旧 setpoint 立即无效，进入零目标 hover/hold |

- 所有故障后均停止；A/B/C 与 D 的差值对应旧 setpoint 的 TTL 残余（v·0.15 s）。
- 业务 ABORT 在故障注入时刻；物理观测继续至稳定/碰撞/越界/5 s；没有在 ABORT 时停止仿真。
- 未恢复任务资格；未用零速度动作伪装“撤权后继续发布”。D 类通过提升控制代次使旧 setpoint 被 executor 拒绝。

## 独立核验

verify_brake_runs.py 重算 13 项：36/8 分母、覆盖 18 配置×2、brake 初始速度/停止距离/时间、业务与物理结果分离、v2 接纳与 TTL、故障后降级、A/B/C/D 注入标识、hash/GUI/commit。结果 PASS。

## 参数依据与限制

- 当前模型 stop=1.1 m：实测最大 .585 m + TTL 残余 .128 m = .713 m；保留 .387 m 余量（模型内），但样本只到 .851 m/s，不是严格最坏上界。
- 预测 1.0 s：在 .851 m/s 下前视距离约 .851 m，大于实测制动距离 .585 m；但停止时间可达 3.25 s，预测时域不能替代停止阈值/最大等待。
- release=1.6 m 仍按几何净空余量保留；没有新的释放数据推翻它。
- TTL=150 ms：故障观测验证了“重发不续期”和旧命令残余；TTL 不能由制动距离单独决定，也不能通过放大 TTL 规避拒绝。
- 单时钟仿真不包含真实跨时钟、串口、PX4 延迟；控制/接纳延迟未单独测量（同一 0.05 s tick 发放与执行）。
- 地图仅一个净空区、主动零目标 hover/hold，不是被动滑行或 PX4 failsafe；不能把“业务 ABORT 后停止”写成任一层实机安全保证。

## 证据与 hash（brake/）

| 产物 | SHA-256 |
| --- | --- |
| summary | 156de761fbe51b2595ed8143c968442e8fe2a7979c4034746da373abb8a2c82a |
| episodes | 498ae4ab2388ef55634c1ff0f6cf5d686a22d8699d3a22d321aec18f98813ae7 |
| manifest | e6cb95dcd272045a8283fe213c13f8bb6630dd1efde22bcd9479908362d56d7d |
| 独立核验 | 13daa45d5e8470ec4f3ebb6e012c0d8ed98ea20115ef8500f7c57136bf8ae602 |
| 原始 steps（忽略目录） | e11244c4163e03fcca2400c4fe2d03ff3dc81de48ddacf445aa79a9b9bf969e1 |
| 截图 | brake_s0.3_*_brake_start、brake_s0.9_*_stopped、fault_A/B/D_s0.8_* |

## 精确复现命令（前台 GUI，无 --headless）

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -u scripts/run_brake_eval.py --cases configs/scenarios/brake_cases_v1.json --freeze configs/scenarios/brake_freeze_v1.json --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit ec23997d19eedd5b2e46b8c24aa78a679ac6fb0b --working-tree 'clean at ec23997 plus freeze 7b6acd8' --gpu-driver 'NVIDIA 581.80 (observed)' --output outputs/map_eval/brake_final4
& $py scripts/verify_brake_runs.py --run-dir outputs/map_eval/brake_final4 --freeze configs/scenarios/brake_freeze_v1.json --output docs/reports/map_eval/verify_brake_final.json
& $py -m pytest -q
```

## 失败/重试保留

- brake_final1：GPU 显存分配失败（残留 python 进程），崩溃目录保留。
- brake_final2：D_s0.8 TARGET_UNREACHED；定位为 D 类提升 gate control_epoch 后 executor epoch 未在下一 episode 重置；修复 ca688c4 后 final3/final4 全部停止。旧失败保留。
- final3：通过但故障截图不完整；final4 补齐故障 start/stopped 截图并作为正式证据。

## 未运行/下一工作包

- 未实现 PX4 Sender；未测真实时钟/串口/PX4 延迟；未运行 PPO、真实感知、板端、SITL/HIL/实机；不提升 Gate。
- 下一工作包：多位置/多高度制动、体积/姿态包络、跨时钟与执行延迟注入、真实 PX4 failsafe 语义（需外部资料）。
