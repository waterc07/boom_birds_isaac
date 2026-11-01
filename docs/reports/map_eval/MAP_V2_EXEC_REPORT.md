# v2 执行适配、故障验证与动力学回归报告（2026-11-01）

> **状态：** PASS（纯软件合同 + ORACLE 仿真执行链；不是 PX4 Sender、板端或实机安全验收）
> **来源章节：** V2.2 §10.4、§16.1–16.8、§17.3、§26.6–26.7、§27.2–27.7、§28.3
> **证据域：** 标准库单元测试 + 仿真动力学（前台 GUI，DirectX/D3D12）
> **最后核对：** 2026-11-01

## 结论

- 动态监督器执行路径已显式迁移到 v2 上下文 → ActionEnvelope/不可续期 TTL → ActionArbiter/所有权 → 仿真执行器 → 实测运动；v1 仅保留为显式对照，运行 manifest 记录 execution_path。
- 纯软件合同测试 10 项 + 等待语义 1 项；全套 pytest 通过（见下）。
- GUI 结果：
  - 20 个原动态场景以 v2 supervisor 路径运行：SUCCESS 8 / ABORT 12 / COLLISION 0 / INVALID 0；与上一轮 v1 supervisor 逐 case 结果和时长一致（duration_delta 均为 0.0）。
  - 8 个无障碍路线 v2 回归：SUCCESS 8/8，无拒绝、无接触。
  - 14 个软件边界故障 episode（7 类×2）：全部按预期 ABORT，拒绝原因与类型匹配，被拒绝动作未执行。
- 独立核验 43 项 PASS（输出见 verify_v2_final.json）。

## v1→v2 逐字段映射与边界

| v1/旧路径 | v2/新路径 | 说明 |
| --- | --- | --- |
| VelocitySetpoint（前/左/上/偏航率） | VelocityPayload BODY_HEADING_FLU + 4 轴 validity | 物理单位；默认全轴有效；不静默降级 partial-axis |
| 无 provenance 的 setpoint | MessageHeader + ActionEnvelope（observation_id、输入采集区间、issued/expires、max_age、source、digest） | 每次控制步重新生成；SEND_CACHED 不改变 issued/expires |
| 单一 mission/control epoch | system_boot/mission/localization/control/sync/PX4 boot 四级上下文 | 任一级变化拒绝旧动作；reset 清缓存与执行资格 |
| 无所有权检查 | ActionArbiter + OwnershipState/ContractContext.control_owner/pending | 只允许一个发布源；PENDING 期间只允许 pending owner |
| 旧 TTL 仅执行器本地 | 动作 TTL 从 issued 起算并受输入截止裁剪 | 执行 setpoint 的 expires 取自接纳动作；不续期 |
| 直接执行 | 接纳成功后才生成执行命令 | 拒绝动作不进入 setpoint/执行器 |

- 观测：仿真状态在每个控制步作为新鲜观测，observation_id 与 capture 时间写入 header；正常路径观测年龄为 0。跨时钟映射/误差界由纯软件合同测试覆盖，运行路径仅用 host_monotonic，未伪造跨时钟成功。
- 模拟身份：px4_boot_id=100（模拟），system_boot/mission/localization/control/sync 由 V2ExecutionConfig 显式提供；仅证明隔离语义，不读取固件。
- 职责：制导/监督器负责产生新动作；V2ActionGate 负责上下文/接纳/所有权过滤；执行器只执行已接纳 payload；监督器是过滤/降级层，不是第二个控制所有者，因此没有伪造运行期交接。所有权 PENDING/ACTIVE 行为由合同单元测试覆盖。

## 等待时限语义核查

- 上一轮报告中的 B 类“等待 28.05 s”是 4 个 B episode 的汇总（约 7.0 s/episode），不是单 episode。
- 监督器 wait_s 在 WAIT 状态累加，状态切换/恢复不清零；max_wait=8 s 是本 episode 内的累计等待上限，不是“连续阻塞”计时。总墙钟超时独立；航点分段计时在暂停时冻结。
- 新增测试 test_wait_timer_is_cumulative_and_not_reset_by_resume 验证：WAIT→RESUME→再次 WAIT 不会重置等待上限。未发现需要改阈值的缺陷；旧报告保留并澄清，不升级为代码缺陷。

## GUI 结果

| 运行 | episode | 结果 | 说明 |
| --- | --- | --- | --- |
| v2 动态正常路径 | 20 | SUCCESS 8 / ABORT 12 / INVALID 0 | 与 v1 supervisor 逐 case 对照：结果与时长一致 |
| v2 无障碍回归 | 8 | SUCCESS 8/8 | 全部动作 ADMITTED，0 拒绝 |
| v2 软件故障集 | 14 | ABORT 14/14 | 7 类×2，预期拒绝原因，被拒绝动作未执行 |

故障类型与拒绝原因：ttl_expiry→REJECT_TTL_EXPIRED；cache_resend→ACTION_EXPIRED；out_of_order→REJECT_SUPERSEDED；context_reset→REJECT_MISSION_EPOCH；px4_boot_change→REJECT_SYNC_OR_PX4_BOOT；clock_sync_mismatch→REJECT_CLOCK_DOMAIN；ownership_revoke→REJECT_CONTROL_EPOCH。

## 独立核验

verify_v2_execution.py 从原始 steps/episodes/manifest/freeze 重算 43 项：上下文/接纳/执行标识、动作 issued/expires/执行时刻、拒绝动作未执行、v1 对照、故障类型/原因、回归成功、hash/GUI/commit。结果：PASS。

## 证据与 hash（v2/）

| 产物 | SHA-256 |
| --- | --- |
| dynamic summary | 572936665487012e7263c5844a019756fa94244fd0a46f85739d7246e95b1a42 |
| dynamic episodes | 5e1a132ec9b9acd0b6cca9c8d715911c6d480c98a5e2c154f07d9135dd3d8a6b |
| fault summary | 9f90d242975f88146e98dfd4f8baf18e1057319fb556fec464406e802a8016c8 |
| regression summary | f71dd20a6b800ed047520d19d63f94bd9fabd3539933762da6169f749dd39747 |
| 独立核验 | cc19d3e81000ad8f2eba6ce8ddde12dbe028aa6c6192f49ca3ab8c0fd5ecaba3 |
| freeze（dynamic/fault/regression） | 见 v2/evidence 与 hashes.json |
| 原始 steps（忽略目录） | dynamic daffde9e…、fault 3b567fbc…、regression 002fda24…（完整见 hashes.json） |

## 精确复现命令（前台 GUI，无 --headless）

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 20 动态场景，v2 supervisor
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --freeze configs/scenarios/map_v2_freeze_v1.json --methods supervisor --execution-path v2 --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 358d011af77ec936156ff2380efa1868b0e2dadc --output outputs/map_eval/final_v2_dynamic1
# 8 无障碍回归
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_v2_regression_cases_v1.json --freeze configs/scenarios/map_v2_regression_freeze_v1.json --methods supervisor --execution-path v2 --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 358d011af77ec936156ff2380efa1868b0e2dadc --output outputs/map_eval/final_v2_regression1
# 14 故障
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_v2_fault_cases_v1.json --freeze configs/scenarios/map_v2_fault_freeze_v1.json --methods supervisor --execution-path v2 --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 358d011af77ec936156ff2380efa1868b0e2dadc --output outputs/map_eval/final_v2_fault1
& $py scripts/verify_v2_execution.py --dynamic-dir outputs/map_eval/final_v2_dynamic1 --dynamic-freeze configs/scenarios/map_v2_freeze_v1.json --fault-dir outputs/map_eval/final_v2_fault1 --fault-freeze configs/scenarios/map_v2_fault_freeze_v1.json --regression-dir outputs/map_eval/final_v2_regression1 --regression-freeze configs/scenarios/map_v2_regression_freeze_v1.json --output docs/reports/map_eval/verify_v2_final.json
& $py -m pytest -q
```

## 限制与未解决

1. 这是仿真适配层；不是 PX4 Sender，不验证固件掩码/TIMESYNC/serial latency；模拟 boot/session 身份只证明隔离语义。
2. 正常动力学路径只用 host_monotonic；跨时钟/映射异常由纯软件合同测试覆盖，未在运行链注入真实双时钟。
3. 故障注入发生在软件边界，不破坏 PhysX；故障 episode 在拒绝后 ABORT，没有继续路线。
4. 监督器是过滤/降级层，不是独立控制所有者；未伪造运行期交接；PENDING/ACTIVE 仅合同测试。
5. 20+8+14 是工作包样本，不替代正式动态样本或实机安全；未运行 PPO、真实感知、板端、SITL/HIL/实机。
6. 官方 Vulkan 静默失败未在本轮复核；沿用 DirectX。你提到 Vulkan 应已解决，但本轮没有独立证据，不写成已验证。
7. 规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；不提升 G2.6 或任何 Gate。

## 下一工作包

1. 对接真实 PX4 Sender/TIMESYNC/固件掩码（需外部资料，超出本轮）。
2. 运行链双时钟与时钟映射误差注入；动作 TTL/限幅实测标定。
3. 监督器所有权交接运行链（若设计确需独立所有者）；恢复/碰撞生命周期整合。
