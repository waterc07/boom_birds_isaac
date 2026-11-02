# 交接记录：动作延迟包络正式评价（2026-11-02）

## 分支与提交

- 分支 `codex/bb22-latency-envelope`，未推送远端。
- 工作包代码提交：`0c03281b7594f38e2274799afa1b1ab31896abc2`（feat: 到达延迟门/双时钟/运行器集成/冻结与核验脚本/专项配置；其前一提交 `6ddb14f`；更早基线 `dff8650`）。
- 正式运行使用的代码 commit 固定为 `0c03281`；预冻结记录该 commit 与工作树 digest。
- 文档/冻结/证据提交在运行之后单独提交（不影响运行证据：manifest 记录冻结 sha 与 run-time commit，独立核验按产物世系校验，不依赖当前 HEAD）。

## 完成范围

1. **实现**：`dual_clock.py` 偏移/漂移/不确定度与 `mapping_age()` 保守上界；`action_transport.py` 到达门（TTL/六元组 epochs/sync/owner、旧 setpoint HOLDING 至 expires、拒绝动作永不执行、reset 隔离、原始到达记录）；`velocity_control.VelocitySetpoint` 可选元数据；`run_dynamic_eval.py` 接入相机时钟域、动作真实采集时刻、transport/applied/clock 记录、ABORT 后物理观测、episode 指标重算、机体 USD AABB、v2 预冻结强制校验。
2. **冻结**：`configs/scenarios/latency_pair_freeze_v2.json`、`latency_special_freeze_v2.json`（frozen_at `2026-11-02T05:12:31Z`，commit `0c03281`；生成脚本拒绝覆盖旧文件；运行入口校验 frozen_at≤started_at、git HEAD、工作树 digest、逐字段 run_plan）。
3. **正式运行（前台可见 GUI，DirectX/D3D12，无 headless，串行分段、独立目录）**：
   - A/B 各 12 个预冻结 episode：`outputs/map_eval/latency_formal2_A|B`，各 SUCCESS 6 / ABORT 6 / 其他 0。
   - 专项 4 段：`latency_ttl_near`（SUCCESS）、`latency_ttl_over`（TIMEOUT WALL_TIMEOUT）、`latency_clock_sync`（ABORT V2_REJECT_SYNC_OR_PX4_BOOT）、`latency_clock_mapping`（ABORT V2_REJECT_STALE_OBSERVATION）。
   - 隔离回归 2 段：`latency_regression_no_obstacle`、`latency_regression_dynamic`（均 SUCCESS，默认 0 延迟/0 时钟，transport=DIRECT）。
4. **独立核验**：`scripts/verify_latency_runs.py` 从原始 steps/episodes/manifest 重算，不读 summary；结果 **PASS**（20/20 checks，0 failures，0 missing fields），输出 `docs/reports/map_eval/latency/verify_latency_runs.json`。
5. **参数分析**：`scripts/analyze_latency_envelope.py` → `docs/reports/map_eval/latency/analyze_latency_envelope.json`；结论见 `MAP_LATENCY_ENVELOPE_REPORT.md`。

## 关键语义（必须延续）

- **拒绝 ≠ 停止**：被拒绝动作永不执行；已接纳且在有效期内的旧 setpoint 继续执行（HOLDING）并记录；到期后执行器进入零目标 hold。业务 ABORT ≠ 物理停止；ABORT 后 `--post-abort-observe-s` 继续观测物理。
- **TTL=150 ms + 50 ms tick**：到达年龄量化 0/50/100/150 ms；150 ms 即过期 → 实际可容忍传输延迟 ≤100 ms（本组 100 ms 用满 2/3 TTL）。TTL 只约束陈旧命令，不保证交付；本仿真零目标回退不是 PX4 Offboard-loss failsafe。
- **停止阈值定义**：`clearance` = 障碍预测中心轨迹（1 s/0.1 s）到"机器人当前位置→当前航路点"线段的最小距离；是预测路径净空，不是中心距/表面间隙。独立重放重建 A 配置 B 类触发 1.088–1.096 m（阈值 1.1）、B 配置 1.133–1.362 m（阈值 1.38）。
- **包络**：机体包络取运行时实测 USD AABB 半尺寸 max=0.0545 m；障碍 0.4×0.4×0.6 m → 球半径 0.3 m；阈值处包络后间隙 A≈0.745 m、B≈1.025 m（推导）。
- **时钟**：主运行映射误差上界 25.01→37.07 ms（20 ms 偏移 + 5 ms 不确定度 + 200 ppm 漂移）；观测年龄保守上界最大 0.2766 s；mapping 不可用时观测标 `CLOCK_MAPPING_UNUSABLE` 且动作因年龄不可证被拒。
- **预冻结预期偏差（不修改冻结）**：clock_mapping 预冻结 expected_reason=`OBSERVATION_STALE`，实际 `V2_REJECT_STALE_OBSERVATION`（预冻结同时列有 `admission_reject_reason=REJECT_STALE_OBSERVATION`）；核验 JSON 显式记录 deviation，不当作静默 PASS。

## 验证命令与结果

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -m pytest -q                         # 379 passed
& $py scripts/planning/audit_documents.py  # 结果见本次收尾输出
& $py scripts/verify_latency_runs.py --pair-freeze configs/scenarios/latency_pair_freeze_v2.json --run-a outputs/map_eval/latency_formal2_A --run-b outputs/map_eval/latency_formal2_B --special-freeze configs/scenarios/latency_special_freeze_v2.json --special-run ttl_near=outputs/map_eval/latency_ttl_near --special-run ttl_over=outputs/map_eval/latency_ttl_over --special-run clock_sync=outputs/map_eval/latency_clock_sync --special-run clock_mapping=outputs/map_eval/latency_clock_mapping --regression-run regression_no_obstacle=outputs/map_eval/latency_regression_no_obstacle --regression-run regression_dynamic=outputs/map_eval/latency_regression_dynamic --expected-config configs/scenarios/latency_expected_v1.json --repo-root . --output docs/reports/map_eval/latency/verify_latency_runs.json   # status=PASS exit 0
```

## 证据与可追踪标识

- 报告：`docs/reports/map_eval/MAP_LATENCY_ENVELOPE_REPORT.md`
- 版本化证据：`docs/reports/map_eval/latency/evidence/`（冻结/配置副本、每段 summary/episodes/manifest、steps hash、GUI 日志摘录、截图、核验/分析 JSON、`hashes.json`）
- 截图：`docs/reports/map_eval/latency/screenshots/`（A/B 各 2 张成功场景）
- 原始输出（gitignored，引用 hash）：`outputs/map_eval/latency_formal2_A|B`、`latency_ttl_near|ttl_over|clock_sync|clock_mapping`、`latency_regression_no_obstacle|dynamic`
- 冻结：`configs/scenarios/latency_pair_freeze_v2.json`（sha256 `02480584…`）、`latency_special_freeze_v2.json`（sha256 `c971ad7b…`）
- 无效冻结尝试保留：`docs/reports/map_eval/latency/evidence/invalid_freeze_attempt1/`（frozen_at 05:09:13Z，运行入口按设计拒绝启动，未产生数据）

## 失败/重试/未完成（保留）

- 探索运行（`latency_formal_A/B`、`latency_A1/B1/B2/B3_seg*`、`latency_queue_debug`、`latency_sync_debug`、`latency_clockfail1`、`latency_debug2`）保留，仅作探索证据；旧运行缺新 schema，核验脚本对其输出 INCOMPLETE 而非 PASS。
- 冻结 attempt1 因核验器脚本在冻结后更新使工作树 digest 变化，运行入口 `WORKTREE_STATE_MISMATCH` 拒绝启动（未产生数据）；旧冻结保留后重新生成有效冻结。
- 一次运行在残留 Isaac 进程占用下 `Windows fatal exception: access violation` 中止（未产生数据）；清理本工作包停滞进程后重跑成功。
- 预冻结预期分类偏差（clock_mapping）已记录，不改冻结。
- 未运行：真实跨时钟/串口/PX4/执行器延迟、PX4 Sender/failsafe、PPO、真实感知、板端、SITL/HIL/实机；未提升任何 Gate；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK。

## 下一工作包

1. 高速/近距离接近专项（closing >0.7 m/s、机体 >0.64 m/s）与 TTL/预测时域联合边界。
2. 真实 PX4 Offboard-loss 与在途动作撤回语义（需外部固件资料）。
3. transport jitter/乱序/双队列与多源时钟（相机/PX4/host）失效注入。
4. 体积/姿态扫掠净空、多高度/位置包络；把 supervisor `clearance` 纳入冻结测量字段（当前为独立重放重建）。
5. 用户/上一工作包的 23 个未提交文档修改保持原样、未纳入本工作包提交；后续接手请继续保留。
