# RMUC2027 地图动力学评价报告（2026-10-31）

> **状态：** PASS（地图集成与首版动力学证据；**不是**完整比赛导航/避障/训练验收，不提升任何 Gate）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §8.6、§10.4、§13.2、§15.3、§17、§20.2、§20.11
> **证据域：** 源码审计 + 单元测试 + 动力学仿真（前台可视 GUI，DirectX/D3D12）
> **地图资产：** @E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim`（原始资产未修改；本地路径仅在忽略配置）
> **最后核对：** 2026-10-31

## 结论

- RMUC2027 场地通过**配置引用**接入项目动力学评价：使用 @assets/rmuc2027_terrain.usdc`，禁用官方环境默认的 z=0 平面，保留场地原始高度（最低点约 −0.301 m）；未复制大资产进 Git，未改写原始资产。
- 地图合同已落盘：米、Z-up、世界 X 东/Y 北/Z 上，机体 FLU；地形为静态三角网格碰撞（friction 0.8、restitution 0）；地图 bounds 与探针地面高度写入配置；地图/配置/案例/freeze 均有 hash。
- 冻结 10 episode（前台 GUI）：3 组到点 ×2 = 6，全部 SUCCESS；起飞—悬停—下降—接地 ×2，全部 LANDED（地面接触力约 0.032 N，prim collision_005）；真实地图接触 ×2，全部 COLLISION（接触力约 0.050 N，prim collision_014）。重复运行结果逐位一致。
- 独立核验 PASS（19 项）：地图/配置/案例/freeze hash、步数与仿真时间、EpisodeBoundary/无未声明 reset、起降阶段、真实接触 prim/力、分母与产物完整性、GUI 与截图。
- 官方 GUI smoke 已用 DirectX/D3D12 复跑 PASS（100 步）；此前 Vulkan 后端的 GUI 尝试静默失败，现明确为**渲染后端相关**，未回退 headless，未声称驱动根因。

## 地图与坐标合同

| 项目 | 值 |
| --- | --- |
| 资产 ID | rmuc2027-isaacsim-20261028 |
| 预览入口 | rmuc2027_preview.usda（sha256 b2c15008…） |
| 场地 | assets/rmuc2027_terrain.usdc（sha256 f5f55c66…） |
| 单位/轴 | 米；Z-up；X 东/Y 北/Z 上；机体 FLU |
| 地图 bounds | min [−14.0005, −8.0016, −0.3010]，max [14.0005, 8.0016, 3.4977] |
| 碰撞 | PhysicsCollisionAPI static triangle mesh，approximation=none，无 RigidBody；摩擦 0.8、恢复 0 |
| 默认地面 | 运行时禁用 /World/ground；不填平低处 |
| 来源 | CosmosMount/rmuc2027_mjarena @ ffd1eb7d…；source/LICENSE（MIT）；地形再分发/商用条款 RULE-CHECK |
| 接触配置 | 机器人 body 单 prim contact sensor，逐 prim 过滤（collision_005 地面、collision_014 墙）；地图 34 个碰撞 prim 启用 contact reporter |

## 选点与净空核查

- GUI 射线探针：112 个 2 m 网格点；地面 z 中位数 0.031 m，最低 −0.195 m，最高 2.668 m；34 个平坦净空点。
- 细网格（0.25 m）在 x∈[−13,−8]、y∈[−2,3] 共 441 点；地面 z ∈ [−0.071, 1.261]；选定净空平坦区 x≈−10.5…−9.0、y≈−2.5…2.5，地面 z≈−0.05…0。
- 到点/起降点：(−10.0, 0.0) 地面 z≈−0.001；接触路线 (−4,0,1.0) 沿 +x；射线在 z=1.0 命中 collision_014（x≈−0.39），z=0.8 存在通道空隙（因此选择 z=1.0）。
- 碰撞几何与可见几何对应关系仅抽样核对；未做全场地薄结构/单面网格穷举。

## 冻结案例与结果（前台 GUI）

| 案例 | 类型 | 次数 | 结果 | 接触 |
| --- | --- | --- | --- | --- |
| reach_A | 到点（−10,−1.5→−10,0） | 2 | SUCCESS 2/2，67 步 / 3.35 s | — |
| reach_B | 到点（−9.5,1.5→−9.5,−0.25） | 2 | SUCCESS 2/2，74 步 / 3.70 s | — |
| reach_C | 到点（−10.5,1.75→−9.25,0.5，不同 yaw） | 2 | SUCCESS 2/2，75 步 / 3.75 s | — |
| takeoff_A | 起飞—悬停—下降—接地（−10,0） | 2 | SUCCESS 2/2，161 步 / 8.05 s | 0.0319 N，collision_005，step 160 |
| contact_A | 真实地图墙接触（−4,0,1.0 沿 +x） | 2 | COLLISION 2/2，121 步 / 6.05 s | 0.0504 N，collision_014，step 120 |

- 到点终态误差：A 0.032 m、B 0.033 m、C 0.027 m；终速 <0.014 m/s。
- 起降：实际离地爬升到悬停高度 1.225 m、悬停 1.0 s、受控下降、接地并低速停住；起始 z 0.029 m 为地面附近（阈值 PROPOSED，不宣称实机安全）。
- 接触：未使用 collision 标志注入；每一步由 PhysX 接触传感器读力，接触 prim 由单 prim filter 明确记录；碰撞前飞行在净空走廊内。
- 重复运行逐位一致（deterministic），核验脚本比较终态差 <1e-9。
## 实现要点

- 地图合同：[map_contract.py](<../../src/boom_birds/sim/map_contract.py>)（hash 校验、本地路径、bounds、案例 schema）；地图 evaluator：[map_eval.py](<../../src/boom_birds/evaluation/map_eval.py>)（地图边界/floor/接触优先级，起降阶段机）。
- 评价入口：[run_map_eval.py](<../../scripts/run_map_eval.py>)：创建 QuadcopterEnv 后禁用 /World/ground、引用 terrain.usdc、启用 34 个地图碰撞 prim 的 contact reporter、机器人 body 单 prim 接触传感器（地面/墙分别过滤）、EpisodeBoundary、地图专用 done（关闭 z<0.1 自动死亡，边界由 evaluator 判定）、比例控制器与冻结案例、GUI 截图。
- 冻结：[map_freeze_v1.json](<../../configs/scenarios/map_freeze_v1.json>)（10 episode、地图/配置/案例 hash、阈值、源码 commit）；核对：[verify_map_runs.py](<../../scripts/verify_map_runs.py>)。
- 探针：map_probe/map_site_probe/map_wall_probe（GUI 射线检查、截图），仅诊断，不替代动力学证据。

## 渲染/GUI 与官方 smoke

- 所有本轮 Isaac 运行均以前台可视 GUI 启动，无 --headless；日志含 @Creating window for environment.`。
- 地图/评价运行使用 DirectX 后端（@--kit_args=--/app/vulkan=false`）；只读观测：Isaac Sim 5.1.0.0、GPU NVIDIA RTX 5080、驱动 581.80、Graphics API D3D12。
- 官方 smoke：DirectX GUI 100 步 PASS（[result.json](evidence/official_smoke_directx.json)，code_commit 965e6fa、gui_mode true、Graphics API D3D12）。此前默认 Vulkan 的多次 GUI 尝试在环境创建后静默结束、无 PASS/结果（日志保留），**未改用 headless**；现确认与渲染后端相关，未声称驱动根因，也不改写历史 headless 记录。
- 历史调参依据仍标为**待重验**（上轮审计：tuning 只有 episode 级记录、候选 A 配置未保留）；本轮使用既有比例参考控制器，不重建候选、不声称历史调参有效。

## 独立核验

@verify_map_runs.py` 从原始 @episodes.jsonl`/@steps.jsonl`、manifest、freeze、本地资产重算：19 项全部 PASS——summary 状态/计数、案例重复、commit/gui_mode、地图/配置/案例 hash、产物 hash、步数、EpisodeBoundary/无截断/计数连续、时间步长、起降阶段与接触规则、分母、重复确定性、截图、磁盘资产 hash。
核验结果：[verify_final.json](<verify_final.json>)。

## 证据与 hash

| 产物 | 位置/hash |
| --- | --- |
| 评价摘要 | [evidence/summary.json](evidence/summary.json) — @abf1eba68e463980c4c4d14a0bf62ecf6c7c88da2d826a828e7e1375f5a019f1` |
| 逐 episode | [evidence/episodes.jsonl](evidence/episodes.jsonl) — @9f182d5235752c64970ee25088616957077afdddde8cf0d26d6c66ee71467d21` |
| manifest | [evidence/manifest.json](evidence/manifest.json) — @69215c9a3d152544dce9572ff8bfe8ec97cb341877aa1e8a7cc97a962cd55a13` |
| 逐 step（忽略目录） | @outputs/map_eval/final_run1/steps.jsonl` — @e62ecc5b921a91d53efc917c9a239540bac44be28255ccd0f058b48fbb4533f3` |
| freeze | [evidence/map_freeze_v1.json](evidence/map_freeze_v1.json) — @a5c40eb3d7c05f51554099661337b0d0cfc68ff91154f8f79564f856416c5b41` |
| cases | [evidence/map_cases_v1.json](evidence/map_cases_v1.json) — @a8bc5ce96da7a2f7774e4d76b6e1d625b384e7e50908344013e9ecde4b976275` |
| 地图配置副本 | [evidence/rmuc2027.yaml](evidence/rmuc2027.yaml) — @e6f7bc777986e82059181b198aee8d4ed73cf6a50e8491988b124616d0de0e15` |
| 地图探针 | [evidence/map_probe.json](evidence/map_probe.json) — @a355e02d76d8290843136461df5eb8417afc15456f89941b35c7025f511deec4` |
| 官方 smoke | [evidence/official_smoke_directx.json](evidence/official_smoke_directx.json) — @c607270d29bf31e120012b3dd561e4c512b315181dddabf3cf6f4bccf0e27653` |
| GUI 截图（地图全景） | [screenshots/map_probe_overview.png](screenshots/map_probe_overview.png) |
| GUI 截图（到点/接地/接触） | [reach_A](screenshots/reach_A-r0_goal.png)、[takeoff_A](screenshots/takeoff_A-r0_landed.png)、[contact_A](screenshots/contact_A-r0_contact.png) |
| 独立核验 | [verify_final.json](verify_final.json) — @420cd3ad3dc1918fdf798449b3029484646cc76e64841c40e96a7c5cfc73a125` |

## 精确复现命令（前台 GUI，无 --headless）

`powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 地图探针（GUI 射线/截图）
& $py -u scripts/map_probe.py --preview 'E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim\rmuc2027_preview.usda' --terrain 'E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim\assets\rmuc2027_terrain.usdc' --output outputs/map_eval/probe3 --grid-step-m 2.0
# 冻结地图动力学评价（DirectX GUI）
& $py -u scripts/run_map_eval.py --mode run --freeze configs/scenarios/map_freeze_v1.json --screenshots --kit_args=--/app/vulkan=false --device cuda:0 --code-commit 965e6fafa3228480f854ebf08b4d6378e2183764 --working-tree "clean at 965e6fa plus freeze c4f6a4d" --gpu-driver "NVIDIA 581.80 (observed)" --output outputs/map_eval/final_run1
& $py scripts/verify_map_runs.py --run-dir outputs/map_eval/final_run1 --freeze configs/scenarios/map_freeze_v1.json --output docs/reports/map_eval/verify_final.json
# 官方 smoke（DirectX GUI）
& $py -u scripts/check_official_quadcopter.py --steps 100 --output outputs/map_eval/official_smoke_directx/result.json --kit_args=--/app/vulkan=false --code-commit 965e6fafa3228480f854ebf08b4d6378e2183764 --device cuda:0
& $py -m pytest -q
`

## 限制与未解决

1. 本轮是**首版地图动力学验证**，不是完整比赛导航/避障/训练；到点路径为预先核查净空的局部路径，比例控制器没有避障能力。
2. 接触案例为受控前飞撞墙，用于验证地图真实碰撞与接触证据；不是自然导航失败统计。
3. 10 episode 为本工作包冻结下限，不替代 V2.2 §20.11 正式样本/场景族要求；未做多地图区域、动态障碍、多 yaw 全方向大样本。
4. 地图几何/碰撞只在抽样区域核对；薄结构、单面网格、视觉-碰撞偏差未穷举。
5. 起降阈值（离地/接地速度等）为 PROPOSED，不宣称实机安全。
6. 官方 smoke 的 Vulkan 后端静默失败仍未定位；DirectX GUI 已 PASS；不得据此推断驱动根因。
7. 历史调参依据待重验；未运行 PPO、真实感知、板端、SITL/HIL、实机；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；不提升任何 Gate。
8. 比赛地图权重/再分发条款仍需 RULE-CHECK，不能仅凭仓库 MIT 文件判定地形资产权限。

## 下一工作包

1. 扩展地图区域与到点/悬停案例到正式样本量，覆盖更多起终点和 yaw；加入动态障碍与真实碰撞统计。
2. 地图几何-碰撞一致性专项（薄结构/单面网格/视觉偏差）。
3. 官方 smoke Vulkan 根因定位（保持 GUI，不自动 headless）。
4. 调参候选重建与调参集重跑后再冻结（不使用最终比较集调参）。
