# 交接记录：RMUC2027 地图动力学评价首版（2026-10-31）

> 2026-11-01 后续补充：官方 smoke 缺少 `sys` 导入的结果写出缺陷已修复；581.80 下前台 Vulkan GUI、CUDA:0、USD 克隆的 100 步已完成，最新复测基于 f0ccfb1 加未提交 import 修复。见 [独立核验摘要](official_gui_smoke/vulkan_current_verification.json)。历史失败保留，但不再将“Vulkan 仍不可运行”作为统一当前结论；本工作包地图动力学结果仍只验收 D3D12。

## 1. 分支与提交

- 工作区 E:\isaac\proj_boom_birds；分支 `codex/bb22-map-eval`（自 `e177eb6`）；未推送远端。
- 本工作包提交：
  - `965e6fa` feat: 地图合同、地图 evaluator/起降阶段机、评价入口、探针、冻结与核验脚本、配置与测试。
  - `c4f6a4d` chore: 冻结 10 episode 案例（3 组到点×2、起降×2、真实接触×2）。
  - 待提交 docs：地图报告、证据/截图、交接、状态同步、核验时间步修正。

## 2. 地图接入标识

- 资产：RMUC2027_IsaacSim；预览 rmuc2027_preview.usda（sha256 b2c15008…），场地 assets/rmuc2027_terrain.usdc（sha256 f5f55c66…）。
- 本地根目录仅在忽略配置 @configs/maps/rmuc2027.local.yaml`；提交配置 @configs/maps/rmuc2027.yaml` 使用相对路径与 hash。
- 单位/轴：米/Z-up/ENU（X 东、Y 北、Z 上），机体 FLU；默认 z=0 地面禁用；地图静态三角网格碰撞。
- 来源：CosmosMount/rmuc2027_mjarena @ ffd1eb7d…；LICENSE MIT；地形再分发/商用条款 RULE-CHECK。原始资产未改写。

## 3. 冻结结果（前台 GUI，DirectX/D3D12）

| 案例 | 结果 | 接触证据 |
| --- | --- | --- |
| reach_A/B/C 各 2 | SUCCESS 6/6（67/74/75 步，终速 <0.014 m/s） | — |
| takeoff_A ×2 | SUCCESS 2/2（161 步，8.05 s；离地→悬停→下降→接地） | 0.0319 N，collision_005，step 160 |
| contact_A ×2 | COLLISION 2/2（121 步，6.05 s） | 0.0504 N，collision_014，step 120 |

- 真实接触来自 PhysX 接触传感器（机器人 body 单 prim filter），非 collision 标志注入；接触 prim 明确。
- 重复运行逐位一致；EpisodeBoundary 每步计数与 terminated/truncated 检查通过。
- 地图探针：112 点 2 m 网格 + 441 点 0.25 m 网格；净空平坦区 x≈−10.5…−9.0、y≈−2.5…2.5；接触墙射线在 z=1.0 命中 collision_014，z=0.8 有通道空隙。
- 核验：verify_map_runs.py 19 项 PASS（hash/边界/时间/阶段/接触/分母/重复/截图/磁盘资产）。
- 截图：map overview、到点、接地、接触，存于 docs/reports/map_eval/screenshots。

## 4. 官方 smoke 与渲染后端

- 默认 Vulkan GUI 的多次尝试在 env 创建后静默结束、无 PASS/结果（历史日志保留）。
- 使用 DirectX（--kit_args=--/app/vulkan=false）GUI 100 步 PASS，记录 code_commit 965e6fa、gui_mode true、Graphics API D3D12；未回退 headless。
- 后续修复与复测：补齐官方脚本的 `sys` 导入，单实例前台 Vulkan GUI 配合 `--clone-in-usd` 已完成 100 步。源码修复、克隆方式及启动条件与部分历史失败不同，不能仅凭这些记录确定后端因果。
- 只读观测：Isaac Sim 5.1.0.0、RTX 5080、驱动 581.80；不声称驱动根因。

## 5. 验证

- 单元测试：地图合同/evaluator 7 项；全套 pytest 见报告（待最终跑）。
- 项目仿真：10 episode 冻结集 PASS；独立核验 PASS；失败/重试（takeoff 初版无接触、contact z=0.8 穿通道、smoke 早期尝试）保留在 outputs/map_eval/ 与 logs/。
- 未运行：PPO、真实感知、板端、SITL/HIL、实机；无 Gate 提升。

## 6. 剩余问题/下一工作包

1. 扩大地图区域与到点/悬停案例至正式样本量，覆盖更多起终点/yaw；加入动态障碍与自然碰撞统计。
2. 地图几何-碰撞一致性专项（薄结构、单面网格、视觉偏差）。
3. 官方 smoke 元数据缺陷已修复且 Vulkan GUI 短例已通过；历史持续挂起与默认 Fabric 路径的全部根因继续保留待查（保持 GUI、单实例、固定源码/参数）。
4. 历史调参依据待重验：重建候选配置+调参集重跑后再冻结，不用最终集调参。
5. 比赛地图规则/资产再分发条款 RULE-CHECK；不宣称地图官方认证。
6. AGENTS/PROJECT_PLAN/README 状态同步在工作树（含用户修改），未提交。

## 7. 复现

见 docs/reports/map_eval/MAP_EVAL_REPORT.md 的 GUI 命令；所有运行目录 outputs/map_eval/，证据副本 docs/reports/map_eval/evidence/。
