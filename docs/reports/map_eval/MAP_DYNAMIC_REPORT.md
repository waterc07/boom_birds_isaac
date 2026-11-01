# 动态障碍停止—等待—恢复监督器评价报告（2026-11-01）

> **状态：** PASS（ORACLE 仿真控制监督基线；不是视觉避障、在线重规划、PX4 监督器或实机安全系统）
> **来源章节：** RMUC2027_UAV_V2_2 §10.4、§11.3、§17、§20.2、§20.11；HANDOFF_20261031_MAP_ROUTES.md
> **证据域：** 单元测试 + 动力学仿真（前台 GUI，DirectX/D3D12）
> **地图：** RMUC2027_IsaacSim（terrain sha256 @f5f55c66…`）
> **最后核对：** 2026-11-01

## 结论

- 在 south/north 冻结航点路线上实现**最小停止—等待—恢复监督器**（FOLLOW/BRAKE/HOLD/WAIT/RESUME/DEGRADED/ABORT），仅使用障碍当前位置/速度和有界预测；场景生成器知道未来，监督器不读取未来轨迹/释放时刻。
- 建立 20 个动态场景（A–E 各 4，south/north 均覆盖），每场景配对运行 FOLLOW_ONLY 与 SUPERVISOR，共 **40 episode**；另运行原 8 个无障碍 route episode 回归。
- 结果（全部有效，0 INVALID）：
  - FOLLOW_ONLY：SUCCESS 8、COLLISION 12（A/B 成功；C/D/E 各 4 碰撞）；
  - SUPERVISOR：SUCCESS 8、ABORT 12、**COLLISION 0**（A/B 成功；C/D/E 按合同退出）；
  - B 类出现有证据的停止—等待—恢复（等待合计 28.05 s，RESUME 状态）；C 类在冻结上限 8 s 后 ABORT；D 类状态切换受限、无快速抖动；E 类观测丢失显式 DEGRADED→ABORT。
- 原 8 个无障碍 route 回归：**SUCCESS 8/8**，无接触、无 INVALID。
- 独立核验 **25 项全部 PASS**；失败/重试目录保留；本轮不宣称零碰撞安全保证，只声明模型内监督行为与观测合同。

## 架构边界（必须保留）

- 监督器是**仿真适配层**，不是 V2.2 尚未实现的 PX4 控制监督器；不拥有 PX4 发布权，不绕过 Control Ownership、动作 TTL/epoch、限幅和 reset。
- 执行仍走既有 v1 评价链：比例制导 → VelocitySetpoint（带 TTL/epoch）→ VelocityExecutor → QuadcopterEnv；**未**完成 v2 端到端集成。
- 停止命令是零速度 setpoint（保持当前航点/位置），不重置 episode、不跳过航点、不瞬移、不重新起飞；恢复后继续当前航点。
- 障碍为**运动学刚体**（真实碰撞几何、非车辆动力学）；观测为 ORACLE 真值位置/速度，带延迟/丢失窗口；监督器仅见观测，不见场景脚本未来。

## 动态场景合同

| 类别 | 数量 | 障碍/观测 | 预期 |
| --- | --- | --- | --- |
| A 穿越后离开 | 4（south/north 各2） | 线性横穿，早于到达离开 | 无需停车；FOLLOW_ONLY/监督器均完成 |
| B 临时占据后释放 | 4 | 线性横穿，约在到达时占用走廊 | 减速/等待，净空持续后恢复原路线 |
| C 持续占据 | 4 | 静止在走廊，超出等待上限 | 达到冻结上限后 ABORT，不无限等待 |
| D 阈值附近反复 | 4 | 垂直走廊振荡 ±0.8 m，周期 1.2 s | 迟滞生效，无快速状态抖动 |
| E 观测过期/丢失 | 4 | 物理静止，观测 dropout 8–60 s | 显式 DEGRADED→ABORT；物理实体继续存在 |

- 障碍初始位置不在机体内；未用初始穿模/瞬移制造场景；物理实体在观测丢失期间继续按轨迹存在。
- 轨迹、尺寸 (0.4,0.4,0.6 m)、观测延迟/dropout 均写入案例文件；reset 后障碍位姿、路线时钟、观测队列按案例重新建立。
- 探索阶段：B 类先以 max_wait=5 s 调试，实测等待约 7.2 s 才净空，导致 ABORT；据此将 max_wait 调整为 8 s 并重新冻结（调试证据保留在 dynamic_smoke10/11）。该值是 PROPOSED，不是安全阈值。

## 监督器合同（PROPOSED）

| 参数 | 值 | 说明 |
| --- | --- | --- |
| stop / release 距离 | 1.1 m / 1.6 m | 预测障碍到机器人当前航段最近距离；迟滞 |
| 预测时域/步长 | 1.0 s / 0.1 s | 只用观测位置+速度线性外推 |
| 观测年龄上限 | 0.3 s | 超龄/无效显式降级 |
| 最大 stale | 2.0 s | 超时 ABORT |
| 最大等待 | 8.0 s | WAIT 超时 ABORT；总墙钟超时独立 |
| 最小保持 / 释放保持 / 恢复保持 | 0.5 / 0.5 / 0.3 s | BRAKE→HOLD→WAIT；恢复需持续净空 |
| 停止判定速度 | 0.12 m/s | BRAKE→HOLD |
| 分段/总计时 | 暂停时航点分段时钟冻结；总墙钟继续 | 不能靠等待重置超时 |

- 距离是**中心点到航段**的几何量，不是机体表面间隙；未做三角面级/体积扫掠。

## 配对结果（40 episode，前台 GUI）

| 类别 | FOLLOW_ONLY | SUPERVISOR | 监督器等待合计 | 监督器状态切换合计 |
| --- | --- | --- | --- | --- |
| A 穿越后离开 | SUCCESS 4/4 | SUCCESS 4/4 | 0.00 s | 0 |
| B 临时占据后释放 | SUCCESS 4/4 | SUCCESS 4/4 | 28.05 s | 20 |
| C 持续占据 | COLLISION 4/4 | **ABORT 4/4**（MAX_WAIT_EXCEEDED） | 34.60 s | 16 |
| D 阈值附近反复 | COLLISION 4/4 | **ABORT 4/4**（MAX_WAIT_EXCEEDED） | 34.60 s | 16 |
| E 观测丢失 | COLLISION 4/4 | **ABORT 4/4**（OBSERVATION_STALE） | 7.80 s | 8 |
| **总计** | **SUCCESS 8 / COLLISION 12 / 0 ABORT** | **SUCCESS 8 / ABORT 12 / 0 COLLISION** | 105.05 s | 60 |

- FOLLOW_ONLY 的 12 次碰撞均为与 `/World/envs/env_0/Obstacle` 的真实物理接触，接触力 0.0231–1.3409 N；未注入 collision 标志。
- B 类监督器出现 BRAKE/HOLD/WAIT/RESUME 并完成路线；A 类无停车；C 类在 8 s 上限后 ABORT；D 类状态切换合计 16（4 场景）且无快速抖动；E 类 DEGRADED→ABORT，物理障碍继续存在。
- ABORT 单独分类，不计入路线成功，也不从有效分母移除；40 个 episode 均有效（INVALID=0）。
- 中心点最小距离 0.222 m（全配对范围 0.222–10.686 m）；这是**中心点距离**，不是机体表面间隙；接触力/对象单独记录。
- 原 8 个无障碍 route 回归：**SUCCESS 8/8**，0 接触、0 超时、0 INVALID。

## 独立核验

`verify_dynamic_runs.py` 从原始 steps/episodes、manifest、freeze、案例与本地资产重算，**25 项全部 PASS**：
- 场景/方法分母（20×2=40）、A–E 各 4、south/north 覆盖、配对完整性；
- 地图/案例/配置/产物 hash、源码 commit、GUI/D3D12；
- 步数与仿真时间、EpisodeBoundary/计数连续、无未声明 reset；
- 障碍实际位姿与脚本轨迹一致、观测有效性与年龄、监督器状态/切换次数；
- 接触对象与力、成功/碰撞/超时/越界/ABORT 分类；
- 预定义行为 A（无停车）、B（等待+RESUME）、C（ABORT）、D（切换≤8）、E（DEGRADED+ABORT）；
- 8 个回归 route 全成功。

结果：[verify_dynamic_final.json](verify_dynamic_final.json)。

## GUI 与可追踪性

- 所有 Isaac 运行均以前台可视 GUI 启动，无 --headless；DirectX/D3D12（`--kit_args=--/app/vulkan=false`），日志含窗口创建。
- 截图：A/B 监督器成功场景（[A_south](dynamic/dynamic_A_south_0-supervisor_success.png)、[B_south](dynamic/dynamic_B_south_0-supervisor_success.png)）；停车/等待/退出的原始状态在 step 记录中，截图只展示成功终点，不替代原始证据。
- 官方 smoke：上一轮 DirectX GUI 100 步 PASS 记录保留；默认 Vulkan 静默失败仍未解决，本轮未重复排查（未阻断 DirectX 路径）。
- 只读观测：Isaac Sim 5.1.0.0、RTX 5080、驱动 581.80、Graphics API D3D12。

## 证据与 hash（dynamic/）

| 产物 | SHA-256 |
| --- | --- |
| summary | `5fa7fab860fbdebf1cbd52003219fcf8f540472f79ceda760ad64579715dcbfc` |
| episodes | `c15e2b8db1534a4f3dfc6059eae41f232efb53f25e07ec57829eafac066ccacd` |
| manifest | `08673e0ad3928aacb800b43dbcb6c995d0d6d044595eb2eff6939a9edef51ceb` |
| freeze | `8332d8954c464bf6f614e3b361d7e56140e88df73008882dcd5e6c53e03a1643` |
| cases | `0f3799050282eb10fb40e2401856769142a3d43432f51ac0efad36ea5f5397d0` |
| 独立核验 | `e049d2741ea03df98b39ed79784d44a69fe1ce2a0d8e6c4e0bfabec194dce684` |
| 回归摘要 | `c14ff69b2d63ef8a75705dbd8ceb736717b319f8bc94fd28121a8915a1c419ec` |
| steps（忽略目录） | `outputs/map_eval/final_dynamic1/steps.jsonl` — `a60148fda68cbd6db41f270097ee45aeb7a4756ecb38882b10614bef7f600906` |
| 回归 steps（忽略目录） | `outputs/map_eval/final_regression1/steps.jsonl` — `563345976d2efd634c8adbf7e9a62491a11052fd42c9f65dabc9adc4acd6eabf` |

## 精确复现命令（前台 GUI，无 --headless）

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 冻结 40 配对动态场景
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --freeze configs/scenarios/map_dynamic_freeze_v1.json --methods follow_only,supervisor --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 92757f01680f3c9ecd879cc6f6eecb1750634e5e --working-tree "clean at 92757f0 plus freeze 6d4e336" --gpu-driver "NVIDIA 581.80 (observed)" --output outputs/map_eval/final_dynamic1
# 原 8 个无障碍 route 回归（既有地图评价链，FOLLOW_ONLY）
& $py -u scripts/run_map_eval.py --mode run --cases configs/scenarios/map_cases_v2.json --only-cases route_south_R1,route_south_R2,route_south_R3,route_south_R4,route_north_R1,route_north_R2,route_north_R3,route_north_R4 --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 92757f01680f3c9ecd879cc6f6eecb1750634e5e --output outputs/map_eval/final_regression1
& $py scripts/verify_dynamic_runs.py --run-dir outputs/map_eval/final_dynamic1 --freeze configs/scenarios/map_dynamic_freeze_v1.json --regression-dir outputs/map_eval/final_regression1 --output docs/reports/map_eval/verify_dynamic_final.json
& $py -m pytest -q
```

## 限制与未解决

1. 监督器是仿真适配层，不是 PX4 控制监督器；未完成 v2 端到端、Control Ownership/真实动作 TTL 集成；不能据此宣称实机安全。
2. 障碍为运动学刚体（真实碰撞几何，不模拟车辆动力学）；观测为 ORACLE 位置/速度+延迟/dropout，不是视觉检测；不读取未来，但场景生成器拥有未来。
3. 20 场景/40 episode 是工作包下限，不替代 V2.2 §20.11 正式动态样本；A/B 的 FOLLOW_ONLY 未发生碰撞（实际相对位置记录），不能据此证明无危险。
4. 距离为障碍中心到机器人当前航段的几何量，不是机体表面间隙；未做体积扫掠/三角面级一致性；采样间隔 0.05 s，可能漏掉更短接近。
5. D 类全部 ABORT，仅证明迟滞/无快速抖动，不证明可通过；E 类在观测丢失下主动退出，物理实体继续存在。
6. 官方 smoke Vulkan 未解决；历史调参依据待重验；制动参数未重建/未调参；不提升 Gate。
7. 未运行 PPO、真实感知、板端、SITL/HIL、实机；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK。
8. 动态场景使用已验证 south/north 走廊，不替代全地图几何证明；三角面级视觉-碰撞一致性仍未完成。

## 下一工作包

1. 扩展到更多动态场景/路线与正式样本量；加入真实感知输入（非 ORACLE）与观测时延统计。
2. 体积/扫掠净空与多步预测对比；制动距离实测标定，替换 PROPOSED 阈值。
3. v2 控制监督器/所有权/TTL 接口对接（仍在仿真，不宣称实机）。
4. Vulkan 根因、调参候选重建；地图几何面级一致性专项。
