# 交接记录：地图多区域与跨区域航点路线（2026-10-31）

## 1. 分支与提交

- 工作区 E:\isaac\proj_boom_birds；分支 `codex/bb22-map-routes`（自 `f0ccfb1`）；未推送远端。
- 本工作包提交：
  - `680f9b6` feat: 地图案例 schema v2（区域/路线/航点/接触 prim）、WaypointRunner 与测试、地图评价入口支持 local_reach/route、冻结/核验扩展、区域/路线/几何探针。
  - `ddb1c51` fix: 接触专项改为墙体 collision_014 与地面 collision_005 两类几何；重新冻结 v2 案例。
  - 待提交 docs：MAP_ROUTES_REPORT、证据/截图/hash、交接、状态同步、核验走廊检查。

## 2. 资产与合同

- 资产同上一工作包：RMUC2027_IsaacSim；terrain sha256 f5f55c66…；本地路径仅忽略配置。
- 4 个候选区域（W/E/S/N）均以 GUI 多方向/多高度射线检查；选 W/E/S 为有效区域，N 记录但未选入。
- 2 条跨区域路线 south/north（W→E），每条 4 配置；中间航点严格等于冻结 corridor_waypoints；离线指定，ORACLE_MAP/ORACLE_STATE。
- 几何：46 视觉/34 碰撞 mesh；碰撞 bbox 比视觉外扩约 2.0–2.5 mm；仅 prim/bbox 独立对照，未做三角面级视觉求交。

## 3. 冻结结果（24 episode，前台 GUI，DirectX/D3D12）

| 类别 | 结果 |
| --- | --- |
| local_reach（W/E/S ×4） | SUCCESS 12/12，平均 4.58 s |
| route（south/north ×4） | SUCCESS 8/8，平均 50.17 s（44.55–55.80 s），每条约 6 航点 |
| contact | COLLISION 4/4：墙体 collision_014 0.0504 N step 120；地面 collision_005 0.0318 N step 59 |

- 自然路线 0 观察到碰撞；不代表安全保证。接触专项独立统计，非注入 collision 标志。
- EpisodeBoundary：每步计数连续、无 terminated/truncated/未声明 reset。
- 独立核验 24 项 PASS（hash、区域归属、路线走廊、航点顺序、接触几何、分母、重复、截图、磁盘资产）。
- 失败/重试保留：wall15 实际先撞 collision_014，改为地面接触；早期 smoke/调试目录保留。

## 4. GUI 与官方 smoke

- 所有 Isaac 运行前台 GUI，DirectX/D3D12（--kit_args=--/app/vulkan=false）；日志含 Creating window。
- 官方 smoke：上一轮 DirectX GUI 100 步 PASS；默认 Vulkan 静默失败未解决，未重复排查；不推断驱动根因。
- 只读观测：Isaac 5.1.0.0、RTX 5080、驱动 581.80。

## 5. 验证

- 单元测试：WaypointRunner 4 项 + 地图合同 7 项；全套 pytest 见最终报告（243）。
- 项目仿真：24 episode 冻结集完成、独立核验 PASS。
- 未运行：PPO、真实感知、板端、SITL/HIL、实机；不提升 Gate。

## 6. 限制与下一工作包

1. 路线净空为点/环形射线采样，不是整机体积/全姿态证明；0.35 m 包络、0.5 m 余量为 PROPOSED。
2. 视觉-碰撞仅 bbox/prim 对照，未三角面级求交。
3. 24 episode 不替代 V2.2 §20.11 正式样本/场景族；未覆盖动态障碍。
4. 官方 smoke Vulkan 未解决；历史调参依据待重验；规则/BOM/PX4 RULE-CHECK。
5. 下一工作包：扩样本/动态障碍；视觉-碰撞面级一致性；Vulkan 根因；调参重建。
6. AGENTS/PROJECT_PLAN/README 部分状态同步在工作树（含用户修改），未提交。

## 7. 复现

见 docs/reports/map_eval/MAP_ROUTES_REPORT.md；运行在 outputs/map_eval/final_run3，证据在 docs/reports/map_eval/routes/。
