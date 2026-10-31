# RMUC2027 多区域与跨区域航点路线评价报告（2026-10-31）

> **状态：** PASS（地图几何/区域/航点路线首版验证；**不是**自主避障、视觉定位或比赛导航验收，不提升任何 Gate）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §8.6、§10.4、§13.2、§15.3、§17、§20.2、§20.11
> **证据域：** 源码审计 + 单元测试 + 动力学仿真（前台 GUI，DirectX/D3D12）
> **地图：** RMUC2027_IsaacSim（terrain.usdc sha256 @f5f55c66…`）；资产原始文件未修改
> **最后核对：** 2026-10-31

## 结论

- 完成地图几何/碰撞专项与 ≥4 个候选区域检查：W/E/S/N 四个空间分离候选区（W 为上一轮原区，E/S/N 在区外）；按多方向、多高度射线判据四个区域采样 cell 全部满足（详见“几何检查”）；选取 W/E/S 作为有效区域，N 记录为候选但未纳入本轮路线合同。
- 形成 2 条跨区域路线（W→E 的 south / north 走廊），每条 4 个合法初始配置；航点、通道、净空余量、停止/超时、失败原因均已落盘冻结。
- 新增最小多航点状态机（WaypointRunner）：到达半径 0.25 m、到达速度 0.2 m/s、中间航点保持 0.2 s、最终航点保持 0.5 s、分段超时 25 s、总超时按案例；有 4 项单元测试。
- 冻结 24 episode 全部以前台 GUI 完成，全部有效（0 INVALID）：
  - 局部到点/悬停（3 区域 ×4 配置）：**SUCCESS 12/12**，平均 4.58 s；
  - 跨区域路线（2 路线 ×4 配置）：**SUCCESS 8/8**，平均 50.17 s（44.55–55.80 s），每条均完成 6 个航点；
  - 真实接触（2 种地图几何 ×2）：**COLLISION 4/4**；墙体 collision_014 力 0.0504 N（step 120），地面 collision_005 力 0.0318 N（step 59）。
- 独立核验 **24 项 PASS**（地图/配置/案例/freeze/产物 hash、边界/计数/时间、区域归属、路线走廊、航点顺序、接触几何多样性、重复确定性、截图、磁盘资产 hash）。
- 路线净空证据与飞行结果**分别报告**：探针未发现 blocked 采样点；飞行 8/8 成功且 0 接触。两者不互相替代。

## 几何与碰撞专项

| 项目 | 实测/记录 |
| --- | --- |
| 视觉/碰撞网格 | 46 视觉 mesh、34 碰撞 mesh（与资产清单一致）；碰撞 purpose=guide、PhysicsCollisionAPI triangle mesh |
| 视觉 bbox | min [−14.00049, −8.00157, −0.300100]，max [14.00050, 8.00157, 3.497683] |
| 碰撞 bbox | min [−14.00250, −8.00407, −0.303500]，max [14.00250, 8.00407, 3.499774] |
| 已知差异 | 碰撞 bbox 比视觉 bbox 外扩约 2.0 mm（x/y）与 2.5 mm（z）；未做三角面级视觉求交，仅作 prim/bbox 独立对照；不能宣称视觉-碰撞完全一致 |
| 多方向/多高度射线 | 每个候选区网格 0.5 m；局部地面以上 +0.4/+1.0/+1.6 m；8 个水平方向 1.5 m + 上方 4 m；判据 ≥0.55 m 水平、≥1.2 m 上方净空 |
| 候选区域 W | x[−10.6,−8.9], y[−2.3,2.3]；40/40 cell 可用；地面 z −0.0587…−0.0027 |
| 候选区域 E | x[7.9,10.6], y[−1.6,1.6]；42/42 cell 可用；地面 z −0.0404…0.1515 |
| 候选区域 S | x[−6.2,−1.8], y[−7.2,−5.7]；36/36 cell 可用；地面 z 0.0130…0.0523 |
| 候选区域 N | x[−6.2,−1.8], y[5.7,7.2]；36/36 cell 可用；地面 z −0.1609…0.0523；未选入本轮 |
| 候选路线 | south/north/center_high/west_south/east_north 全部 0 blocked（south 119、north 115、center 86、west_south 48、east_north 57 采样）；选择 south/north W→E |

**净空限制：** 射线是点/环形采样，不是整机体积或全姿态证明；机体系用半径 0.35 m、通道净空余量 0.5 m 为 PROPOSED；路线只在已声明走廊内使用，不宣称可任意穿行。

## 区域与路线合同

- **有效区域：** W、E、S（范围/地面高度/可用 cell 见上表）；验证依据为 route_probe 的实际 raycast。
- **路线：**
  - south：W(−10,0) → (−10,−4) → (−6,−6.2) → (6,−6.2) → (9.5,−4) → E(9.5,0)，巡航 z=1.0 m；
  - north：W(−10,0) → (−10,3.5) → (−6,5.8) → (5.5,5.8) → (9.5,3.5) → E(9.5,0)，巡航 z=1.0 m。
- 每条路线 4 个配置：起点在 W 区域内变化、终点在 E 区域内变化、起始 yaw 变化；路线中间航点严格等于冻结的 corridor_waypoints（核验项 route_corridor_contract）。
- 仅允许通过有探针证据的走廊；未使用动态规划/在线避障；所有航点离线指定，权限为 ORACLE_MAP / ORACLE_STATE。
- 终点停止：中间航点 hold 0.2 s，最终航点 hold 0.5 s；最终进入半径/速度阈值同局部到点。
## 冻结案例与结果（前台 GUI，24 episode）

| 类别 | 案例 | 次数 | 结果 | 备注 |
| --- | --- | --- | --- | --- |
| 局部到点/悬停 | local_W1…W4 | 4 | SUCCESS 4/4 | W 区域 4 个不同起终点/yaw |
| 局部到点/悬停 | local_E1…E4 | 4 | SUCCESS 4/4 | E 区域 |
| 局部到点/悬停 | local_S1…S4 | 4 | SUCCESS 4/4 | S 区域 |
| 跨区路线 | route_south_R1…R4 | 4 | SUCCESS 4/4 | 52.5 / 48.0 / 55.8 / 50.7 s，均完成 6 航点 |
| 跨区路线 | route_north_R1…R4 | 4 | SUCCESS 4/4 | 47.75 / 52.25 / 44.55 / 49.80 s，均完成 6 航点 |
| 真实接触 | contact_wall14_A | 2 | COLLISION 2/2 | 墙体 collision_014，0.0504 N，step 120 |
| 真实接触 | contact_ground_A | 2 | COLLISION 2/2 | 地面 collision_005，0.0318 N，step 59 |

- 局部平均 4.58 s；路线平均 50.17 s；接触平均 4.53 s。
- 自然路线评价中未观测到碰撞（8/8 成功、0 接触）；这是样本结果，不是安全保证。接触专项独立统计，未注入 collision 标志。
- 所有 episode 接入 EpisodeBoundary；每步计数连续、无 terminated/truncated/未声明 reset；GUI 与物理时间推进由核验脚本检查。
- 失败/重试保留：接触 wall15 实际先撞 collision_014（无法构成独立几何），已替换为地面 contact 并重新冻结；早期 route/contact smoke 目录保留。

## 独立核验

@verify_map_runs.py` 从原始 @episodes.jsonl`/@steps.jsonl`、manifest、freeze、案例文件、本地资产重算，**24 项 PASS**：
- summary 状态/计数、案例重复（local/route 1 次、contact 2 次）；
- 源码 commit、GUI、地图/配置/案例/产物 hash、freeze 文件 hash；
- 步数、边界/计数连续、时间步长；
- 区域归属（起点/终点）、路线走廊合同（中间航点严格相等）、航点索引非递减/最终航点/完成数；
- 接触几何多样性（collision_014 墙体、collision_005 地面）与期望 prim 一致；
- 分母、重复确定性、GUI 截图存在非空、磁盘资产 hash。

结果：[verify_routes_final.json](../verify_routes_final.json)。

## GUI 与可追踪性

- 所有 Isaac 运行（区域/路线探针、24 episode 评价）均以前台可视 GUI 启动，无 --headless；DirectX/D3D12（@--kit_args=--/app/vulkan=false`）。
- 日志含 @Creating window for environment.`；控制台记录每个阶段（地图加载、接触 prim、写入产物）。
- 官方 smoke：上一轮 DirectX GUI 100 步 PASS 记录保留；默认 Vulkan 静默失败仍为未解决项，本轮未重复排查（未阻断 DirectX 路径）。
- 只读观测：Isaac Sim 5.1.0.0、RTX 5080、驱动 581.80、Graphics API D3D12。
- 截图：区域/路线探针总览，局部到点、跨区路线终点、墙体/地面接触，见 [routes](routes) 目录（route_south_*、route_north_*、local_*、contact_* 截图）。

## 证据与 hash（routes/）

| 产物 | SHA-256 |
| --- | --- |
| 评价摘要 | @32b3273dcd06b990634e32173cc7a5377d08fbce3c7350d0fcf2f5bca8bcd098` |
| 逐 episode | @6d648a6513eef8c99ce1d42ed6c7c7613a03a13e53bec91c8b8e128f99bc6f0b` |
| manifest | @4ebe18eb571c9c924c114914cd0fe13b8d9a76e95a0400c4190d0387604cfbb9` |
| freeze v2 | @c76f1263346ecbffe3ada510057b2b6497d233d045f53aa0422bfe891b1f3fed` |
| cases v2 | @882126ae886c11bc05b69596656232c06d6ad59fb7a136d4da88f364c484fef7` |
| 区域/路线探针 | @05010f1f87e37317a0d3101247f155ee76a4757ab95986c437b200b7fd9f0a24` |
| 视觉 mesh 清单 | @39efd3e2ee9b26e141fc136be71ef329de97827e0b7759c578ae6c958c0353e0` |
| 碰撞 mesh 清单 | @610444b753495201c17ed78064aa412d68cb99c814ba61e5cc70c0f938320670` |
| 逐 step（忽略目录） | @outputs/map_eval/final_run3/steps.jsonl` — @4d91c5ac2865a89c9ceb7d12f25794472b8e3973535f605cc7806e7a7d925562` |
| 截图/其他 | 见 [routes/hashes.json](routes/hashes.json) |

## 精确复现命令（前台 GUI，无 --headless）

`powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 区域/路线/几何探针
& $py -u scripts/map_route_probe.py --preview 'E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim\rmuc2027_preview.usda' --output outputs/map_eval/route_probe2 --hold-s 5
# 冻结 24 episode（直接使用冻结 map_cases_v2 / freeze_v2）
& $py -u scripts/run_map_eval.py --mode run --cases configs/scenarios/map_cases_v2.json --freeze configs/scenarios/map_freeze_v2.json --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 680f9b6bfef63f02c77d908a2659e014f571b0aa --working-tree "clean at 680f9b6 plus cases/freeze ddb1c51" --gpu-driver "NVIDIA 581.80 (observed)" --output outputs/map_eval/final_run3
& $py scripts/verify_map_runs.py --run-dir outputs/map_eval/final_run3 --freeze configs/scenarios/map_freeze_v2.json --output docs/reports/map_eval/verify_routes_final.json
& $py -m pytest -q
`

## 限制与未解决

1. 本轮是首版 ORACLE 地图航点路线基线，不是自主避障/视觉定位/比赛导航；路线航点由已知地图离线指定，权限为 ORACLE_MAP/ORACLE_STATE。
2. 净空检查为点/环形射线采样（0.55 m 水平、1.2 m 上方、z±0.25、8 方向 1.5 m），不是整机体积/全姿态证明；0.35 m 机体包络与 0.5 m 余量为 PROPOSED。
3. 视觉-碰撞只做 prim/bbox 独立对照（碰撞 bbox 外扩约 2–2.5 mm），未做三角面级视觉求交；不能宣称完全一致。
4. 候选区域 N 未选入本轮；地图尺寸/地物语义/阵营划分未经规则原文确认，保持未验证。
5. 24 episode 是工作包冻结下限，不替代 V2.2 §20.11 正式样本/场景族要求；未覆盖动态障碍、全方向大样本。
6. 官方 smoke Vulkan 静默失败仍未定位；DirectX GUI 已 PASS，不推断驱动根因。
7. 历史调参依据继续待重验；未运行 PPO/真实感知/板端/SITL/HIL/实机；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；不提升 Gate。
8. 地图资产再分发/商用条款 RULE-CHECK；不能凭仓库 MIT 文件判定地形资产权限。

## 下一工作包

1. 扩展区域/路线到正式样本量，加入动态障碍与自然碰撞统计；覆盖更多起终点/yaw。
2. 视觉-碰撞三角面级一致性（网格求交/最近面距离）专项。
3. 官方 smoke Vulkan 根因定位（保持 GUI，不自动 headless）。
4. 调参候选重建与调参集重跑后再冻结（不使用最终集调参）。