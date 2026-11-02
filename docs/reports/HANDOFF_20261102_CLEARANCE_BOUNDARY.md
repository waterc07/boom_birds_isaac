# 交接记录：clearance 几何语义与停止需求边界专项（2026-11-02）

## 分支与提交

- 分支 `codex/bb22-clearance-boundary`（自 `9884c19`），未推送远端。
- 工作包代码提交：`0546701b715e20e35e0208b112debbf1c41c9808`（clearance/stop_requirement/boundary_plan/运行器/核验器/案例/预期/快速车配置/上一轮审计）。
- 正式运行使用代码 commit 固定为 `0546701`；预冻结记录该 commit 与工作树 digest。
- 文档/冻结/证据在运行之后单独提交（不影响运行证据：manifest 记录冻结 sha 与 run-time commit，独立核验按产物世系校验）。

## 完成范围

1. **上一轮验收口径审查**：`docs/reports/map_eval/latency/LATENCY_ACCEPTANCE_AUDIT_20261102.md`。结论：旧 20/20 PASS 不升级为行为验收；`0c03281` alternatives 属预冻结规格沿用、ttl_over 残余形状放宽论证不足由 (c) 取代；`e40db26` 五类数据完整性修正、reason 接受扩张登记为运行后口径变更；clock_mapping 偏差 = 多合法失效路径 + 提交期优先级，预冻结只写次路径，属预期规格不足；ttl_over 独立复核未执行过期动作。旧证据/冻结保留。
2. **clearance 合同字段化**：`src/boom_birds/evaluation/clearance.py`（`boom_birds.clearance.v1`）+ `stop_requirement.py`（`boom_birds.stop_requirement.v1`）+ `configs/scenarios/brake_model_v1.json`；supervisor 等价重构并记录 `clearance_record`；运行器逐步记录 clearance/stop_requirement/contact_evidence；四类几何量分离；包络球改半对角线保守半径；制动模型区间外不外推。
3. **预运行冻结**：`configs/scenarios/clearance_boundary_freeze_v1.json`（9 段；budget 24/2/3/29；真实 UTC/HEAD/worktree digest；运行入口逐段校验）。正式运行前未修改 src/scripts/tests/configs。
4. **正式运行（前台可视 GUI，DirectX/D3D12，无 headless，串行分段独立目录）**：
   - 边界 24 episode：`outputs/map_eval/bnd_boundary_default|boundary_delay_e1|boundary_delay_e2|boundary_fast`。
   - 上一轮专项复核 2：`bnd_latency_clock_mapping_recheck`、`bnd_latency_ttl_over_recheck`（新冻结、预声明判据）。
   - 回归 3：`bnd_regression_dynamic`、`bnd_regression_no_obstacle`、`bnd_regression_fault`。
   - 合计 29 episode；边界 24：ABORT 16 / SUCCESS 8；含复核/回归全部 29：ABORT 18 / SUCCESS 10 / TIMEOUT 1（复核 clock=ABORT、ttl=TIMEOUT；回归 dynamic/no_obstacle=SUCCESS、fault=ABORT，与既有证据一致）。
5. **独立核验**：`scripts/verify_clearance_boundary_runs.py`（四类 checks；从原始记录重建；偏差不并入 PASS），结果见 `docs/reports/map_eval/clearance_boundary/verify_clearance_boundary.json`。
6. **参数分析**：`scripts/analyze_clearance_boundary.py` → `analyze_clearance_boundary.json`；报告 `MAP_CLEARANCE_BOUNDARY_REPORT.md`。

## 关键结论（详见报告）

- clearance 是"预测障碍中心到机器人当前中心→当前航点线段的 1 s 路径净空"，不是中心距/表面间隙；四类量严格分离并逐步记录。
- 保守球半径 = AABB 半对角线 0.067966 m（修正上一轮 max-half 0.0545 非保守口径）；阈值处球包络间隙 A 0.732 m、候选 1.38 为 1.012 m（推导）；AABB 中心偏移未记录 → 完整外廓保守性未确认。
- 停止 ≠ 未来安全：接触推断 8/24 episode，最小球包络间隙 −0.115/−0.118/−0.067 m；停车后障碍继续接近 0.83–0.86 m；业务 ABORT 与物理接触分开记录。
- 超出当前能力：D 段实测 0.992 m/s > 制动模型支持 0.851428 m/s → `UNSUPPORTED/ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT`（564 步，required/margin=null），不外推为安全结论。
- 接触力传感在本环境不可用（多方案探针失败）；接触改为球重叠 ≥0.02 m 运动学推断，显式标注 `kinematic_inference`、非测力；旧报告 contact=0 不能证明无接触。
- 时钟层次：host=Isaac 仿真时间，camera=模拟第二时钟域；无真实多设备/串口/PX4 延迟。
- 上一轮复核：clock_mapping 命中预声明优先路径（admission REJECT_STALE_OBSERVATION + observation CLOCK_MAPPING_UNUSABLE）；ttl_over 满足 (c) 六项（901 被拒与 300 executed 无交集、首拒绝 age 0.150 s、首拒绝前旧 active 有效、到期→NONE、零目标回退、TIMEOUT）。
- 原 stop=1.1 m 保持默认；上一轮候选 1.38 m 未升级、本轮未作为默认运行。

## 验证结果摘要

**PASS**：`status=PASS`、41/41 checks（data_integrity 10、contract_invariant 14、scenario_expectation 9、performance_boundary 8）、failures=0、deviations=0、missing_fields=0；接触证据模式 `kinematic_inference`（球重叠 >0.02 m，非测力）；clock_mapping 命中预声明路径、ttl_over 满足预声明 (c) 六项；regression 与既有 v2 证据一致。

## 验证命令与结果

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -m pytest -q                      # 525 passed（含本工作包 51+38+20+52 等新增测试）
& $py scripts/planning/audit_documents.py
& $py scripts/verify_clearance_boundary_runs.py --freeze configs/scenarios/clearance_boundary_freeze_v1.json --run boundary_default=outputs/map_eval/bnd_boundary_default --run boundary_delay_e1=outputs/map_eval/bnd_boundary_delay_e1 --run boundary_delay_e2=outputs/map_eval/bnd_boundary_delay_e2 --run boundary_fast=outputs/map_eval/bnd_boundary_fast --run latency_clock_mapping_recheck=outputs/map_eval/bnd_latency_clock_mapping_recheck --run latency_ttl_over_recheck=outputs/map_eval/bnd_latency_ttl_over_recheck --run regression_dynamic=outputs/map_eval/bnd_regression_dynamic --run regression_no_obstacle=outputs/map_eval/bnd_regression_no_obstacle --run regression_fault=outputs/map_eval/bnd_regression_fault --expected configs/scenarios/clearance_boundary_expected_v1.json --brake-model configs/scenarios/brake_model_v1.json --repo-root . --output docs/reports/map_eval/clearance_boundary/verify_clearance_boundary.json
& $py scripts/analyze_clearance_boundary.py --output docs/reports/map_eval/clearance_boundary/analyze_clearance_boundary.json
```

## 证据与可追踪标识

- 报告：`docs/reports/map_eval/MAP_CLEARANCE_BOUNDARY_REPORT.md`
- 上一轮审计：`docs/reports/map_eval/latency/LATENCY_ACCEPTANCE_AUDIT_20261102.md`
- 版本化证据：`docs/reports/map_eval/clearance_boundary/evidence/`（冻结/预期/案例/制动模型/快速车配置副本；每段 summary/episodes/manifest/steps hash；截图；核验/分析 JSON；hashes.json）
- 原始输出（gitignored，hash 引用）：`outputs/map_eval/bnd_*`
- 调试/校准保留：`outputs/map_eval/boundary_smoke1`、`boundary_calibA/B/D/E1/E2`、`calib*`、`calib_probe*`
- 旧证据保留：`outputs/map_eval/latency_*`、`configs/scenarios/latency_*freeze_v2.json`

## 失败/重试/未完成（保留）

- 接触力传感不可用（多方案探针失败/不更新）；保留探针运行并改用运动学推断；这是重要证据限制，旧 report 的 contact=0 不能证明无接触。
- 校准/调试运行保留、不进入正式分母；正式 9 段一次通过（exit 0），无正式重试。
- 核验器为适配实际记录发生字段别名/记录时点修正；原始记录未改，偏差在核验 JSON 与报告登记。
- 未运行：真实 PX4/串口/执行器延迟、真实接触力、SITL/HIL/实机、全地图/全姿态外廓扫掠、PPO/真实感知/板端；不提升任何 Gate；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK。

## 下一工作包

1. 直接读取 PhysX contact report 恢复测力证据；否则扩展 OBB/多姿态推断验证。
2. 高速/近距离扩大样本（>0.85 m/s、closing>1 m/s、多高度/多方向、体积扫掠）。
3. 真实 PX4 Offboard-loss/TTL 语义（需外部固件资料）。
4. 把 AABB 中心偏移/姿态包络纳入运行时测量与冻结字段；clearance applicability 与 supervisor 退出策略联立。
5. 用户/上一工作包的未提交文档修改保持原样、未纳入本工作包提交。
