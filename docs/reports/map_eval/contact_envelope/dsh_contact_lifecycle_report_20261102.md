# dsh_contact_lifecycle：单进程多 episode 接触读取生命周期独立诊断（2026-11-02）

> **状态：** DIAGNOSTIC（独立只读探针；未修改 `scripts/run_contact_verification.py`、`src/boom_birds/evaluation/contact_readout.py`、测试、冻结或核验器；未 commit）
> **来源：** `docs/reports/map_eval/contact_envelope/CONTACT_REVIEW_CODE_AUDIT_20261102.md`、`docs/reports/HANDOFF_20261102_CONTACT_ENVELOPE.md`、`docs/reports/map_eval/contact_envelope/MAP_CONTACT_ENVELOPE_REPORT.md`
> **证据域：** 前台可视 GUI（Isaac Sim 5.1.0，DirectX/D3D12，无 headless）下的独立诊断探针；无真实感知/PX4/板端/SITL/HIL/实机
> **最后核对：** 2026-11-02

## 0. 本轮边界

- 与 Codex 并行：Codex 负责 `scripts/run_contact_verification.py`、`src/boom_birds/evaluation/contact_readout.py`、`tests/evaluation/test_contact_readout.py`（接触读取错误、张量维度、模长、单步健康状态）。本报告**不修改、不提交、不回退**这些文件；不切分支/worktree，不做仓库级 git add/commit。
- 本报告所有探针为 `tmp/dsh_contact_lifecycle_*`，输出在 `outputs/dsh_contact_lifecycle/`，配置/报告使用 `dsh_contact_lifecycle` 前缀；未读取 Codex 未完成入口作为正式证据。
- 旧 filtered 结果受已复现的张量索引/L1/L2 缺陷影响，**不能**直接用于证明生命周期根因；本探针直接读取原始 `force_matrix_w/net_forces_w` 张量并按欧氏模长（L2）计算，保留原始向量、异常、时间戳、对象映射。

## 1. 独立复现的读取缺陷（与审计一致）

探针在每一步读原始张量，并同时记录旧解析方式的结果：

- `force_matrix_w` 实际 shape 为 `[1, 1, 1, 3]`（env=1、body=1、filter=1、xyz）；`net_forces_w` shape `[1,1,3]`。
- 旧读取方式 `matrix[0,0].tolist()` 得到 `M×3`（此处 `[[x,y,z]]`），再 `float(...)` 抛
  `TypeError: float() argument must be a string or a real number, not 'list'`；该异常在旧入口被 `except Exception: continue` 吞掉，导致 `max_force` 已更新但 `per_prim/target_vectors` 为空（非原子矛盾结果）。本探针在每个 episode 的每一步都保留该 `buggy_float_error`（证据字段），并同时记录正确向量 `matrix[0,0,0]`。
- L1/L2：本探针同时记录 `force_matrix_l1_n`（`abs().sum(-1)`）与 `force_matrix_l2_n`（`norm`）；本组接触向量恰好沿单轴，L1=L2；审计给出的 `[0.01,0.01,0.01]` 阈值两侧反例属于独立算术复现，本轮运行数据未出现该方向组合，不能把旧阈值分类当成已验证。
- 读取健康：在正确解析下，所有 episode 的 `read_ok` = 200/200（通用探针）或 300/300（墙探针），传感器 `filter_count=1`、`body_names=['body']`、`sensor_timestamp/timestamp_last_update` 每步推进、无 `exception`。**因此后述力为零不是"读取抛异常"造成的，而是传感器输出本身为零或物理接触未覆盖。**

## 2. 探针与变体（每次只改一个因素）

场景 A（运动学障碍穿过悬停机器人，复现旧入口配置）：`replicate_physics=False`，机器人 body 单 sensor，filter 障碍 root；可选对障碍碰撞 shape 应用 `PhysxContactReportAPI`；3 episode 连续，200 步/集。

| 变体 | 每集非零 filtered 步数（ep0/ep1/ep2） | max L2 (N) | 说明 |
| --- | --- | --- | --- |
| fixed（固定 sensor，无 reset） | 4 / 2 / 0 | 0.185 / 0.222 / 0 | 同一 sensor/view（view id 不变） |
| fixed root-only（不对 shape 加 reporter） | 0 / 1 / 1 | 0 / 0.127 / 0.005 | 证明 shape reporter **不是唯一必要条件** |
| env_reset（同 sensor，env.reset） | 4 / 3 / 0 | 0.185 / 0.033 / 0 | reset 不恢复第 3 集 |
| sensor_reset（同 sensor，sensor.reset） | 4 / 1 / 0 | 0.185 / 0.024 / 0 | 与 fixed 相同，reset 数据缓冲无效 |
| view_rebuild（每集重建 ContactSensor/view） | 4 / 2 / 0 | 0.185 / 0.222 / 0 | 新 view id 仍不恢复第 3 集 |
| reapply_reporter（每集重加 shape reporter） | 4 / 0 / 0 | 0.185 / 0 / 0 | 重加 reporter 也不恢复 |
| scene_rebuild（env.close + 新 env，同进程） | — | — | 在 `env.close()` 后重建时进程挂起（日志止于新 app 初始化），只能 kill；同进程 scene 重建不可用（失败保留） |

关键限定：

- 该场景的 box 分离量（中心坐标 + 已知 half extents，轴对齐近似）只在 -0.004…0 m 的**边缘接触**附近；机器人被障碍推走，接触几何逐集变化。因此"力为零"既可能是接触报告生命周期问题，也可能是**接触本身只是擦碰/几何变化**；不能直接用零输出来证明"无接触"，也不能把跨集下降单独归因为 sensor/view 生命周期。
- `fixed root-only` 在 ep1/ep2 有非零力（0.127/0.005 N）→ **不能说 reporter 必须加在 shape**；shape reporter 只影响覆盖，不能解释全部零输出。
- 所有变体都没有读取异常；`view_rebuild` 的新 view 仍复现同样的跨集下降 → 单纯重建 view 不是修复。

场景 B（墙接触，持续推墙；用于把"接触"从边缘状态变为持续状态）：

- 地图 `collision_014`（碰撞 prim 带 `PhysxContactReportAPI`），机器人 body sensor filter 墙 prim；每集从 x=-4 以 0.6 m/s 前飞并持续推墙 300 步。
- 首轮（无高度保持）结果：ep0 接触窗口 190 步中 153 步有 filtered 力（max 0.434 N）；ep1 180 步（max 0.352 N）；**ep2 0 步**，但日志显示 ep2 机器人末态 z=0.28、x=+0.46 → 机器人已下沉并从墙体下方间隙穿过，**ep2 没有墙接触**，零力是几何事实而非传感器失效。
- 据此加"高度保持"变体（每步 z 偏离 1.0 m >0.02 时只修正 z 并清速度；其余不变），重跑 fixed/env_reset/view_rebuild（结果见 §3）。

> 场景 B 的详细表格在 `outputs/dsh_contact_lifecycle/wall_alt_*/wall_lifecycle_probe.json`，原始每步行记录包含 robot 位姿、力 L1/L2 原始向量、shape、view id、timestamps、异常。

## 3. 最终结论（静态障碍持续接触是决定性对照）

### 3.1 静态障碍持续接触探针（场景 C，决定性）

场景：kinematic 静态 cuboid（0.6×0.6×0.6，位于 (0,0,1)），机器人从 (-2,0,1) 以 0.4 m/s 前飞并持续推障碍；body 单 sensor，filter 障碍 root；对障碍 collider shape 应用 `PhysxContactReportAPI`；每集 200 步，高度保持；3 集连续。

| 变体 | ep0 真实接触窗口 | ep1 | ep2 |
| --- | --- | --- | --- |
| fixed（固定 sensor，无 reset） | step86 起 115 步 net=filtered，max 0.01651 N | **step1 起 robot x=-2.0（距障碍 2 m）即报 0.015616 N**，持续到 step85；step86 真实接触后 max 0.02186 N | step1 起 0.015621 N，同样持续到 step85；真实接触 max 0.02194 N |
| env_reset（env.reset） | 同上 | 同上（0.015616 N，step1–85） | 同上（0.015648 N） |
| sensor_reset（sensor.reset） | 同上 | 同上（0.015616 N） | 同上（0.015621 N） |
| view_rebuild（每集新建 ContactSensor/view） | 同上 | **新 view id 仍报相同 0.015616 N**（step1，robot 距障碍 2 m） | 新 view id 仍报 0.015621 N |
| late_view_rebuild（先远离 step 一次再新建 view） | 同上 | 仍报 0.015616 N（step1） | 仍报 0.015565 N（step1） |

所有变体 `read_ok=200/200`、`filter_count=1`、`body_names=['body']`、`force_matrix shape=[1,1,1,3]`、`sensor_timestamp/timestamp_last_update` 每步推进、无读取异常；`net_forces_l2` 与 filtered `force_matrix_l2` 在该对象对上相等（attribution 映射本身没有丢失）。

**结论：** 这不是"第 2 集开始读不到力"的简单失效，而是——上一集结束时最后的接触力（0.0156 N）**在新一集机器人已被传送/重置到 2 m 外后仍被 PhysX contact report 保留并逐 step 返回**，直到新一次真实接触发生才被更新。该陈旧值：
- 不是 Python 读取/解析错误（正确索引下 `read_ok` 全真、时间戳推进）；
- 不是 sensor 对象 view 生命周期（新建 view、late rebuild 都返回相同陈旧值）；
- 不是 `env.reset`/`sensor.reset` 能清除（两者都不清除）；
- 不是 filter 映射丢失（filter_count/body/filtered=net 均正常，陈旧值仍指向上一接触对象对）。

**同进程可重复性：** 同一进程内连续 episode 的接触读数**不可作为独立接触证据**；首集（无历史接触）干净，后续集可能携带上一集陈旧力。独立进程第一集无历史接触 → 推测/既有证据表明可避免该陈旧值，但这只是**规避**，不是根因修复，不能写成修复。

### 3.2 其他场景的限定

- 墙场景（collision_014，薄墙/存在通道空隙）三集重复时，ep2 曾出现机器人下降后从墙下穿过（z=0.28）或从几何开口通过；高度保持后仍存在墙穿越/偏航导致接触窗口不连续。该场景用于确认"零输出可能只是没有墙接触"，**不作为** lifecycle 根因证据。
- 运动学移动障碍场景接触为边缘擦碰（box 分离仅 −0.004…0 m），机器人被推走、接触几何逐集变化；非零 steps 4/2/0 等下降不能单独归因于 sensor 生命周期。root-only（不对 shape 加 reporter）在部分集也得到 0.127 N → **不能预设 reporter 必须加在 shape**；repoter 覆盖问题与 lifecycle 陈旧问题需分开记录。
- 旧入口 filtered 结果受 `matrix[0,0]` TypeError 与 L1/L2 混用影响，**不能直接用于证明 lifecycle 根因**；本探针正确读取后才发现上述陈旧力现象。旧报告"单进程仅首 episode 可靠"的表述应修订为"上一轮测试的几何/读取缺陷与 contact report 陈旧状态共同造成；独立进程是规避，不是根因"。

### 3.3 最小修复建议（有证据支持，待 Codex 合并后验证）

1. **读取层**：`force_matrix_w[env, body, filter, :]` 正确索引；模长用 `norm(...)`（L2）；每步分开记录 `initialized/read_success/updated/coverage`、shape、原始向量、异常；读取失败 → `UNKNOWN/null`，不能有效零。
2. **陈旧检测（必须）**：记录物体几何分离（距离/box separation）。若 contact force/net 非零但机器人-对象分离明显超过阈值 → 标 `STALE_CONTACT_REPORT` / `UNKNOWN`，既不当作接触也不当作无接触；直到看到与几何一致的接触建立/清除事件。
3. **episode 边界握手**：每集开始先把机器人和对象置于已知分离位姿并 step，直到 net/filtered 为 0 才允许开始测量；若一直非零（如本探针）→ 本集标 UNKNOWN，不得作为证据。不要用"独立进程"掩盖问题；独立进程只作临时工作模式。
4. **更低层证据源**：使用带 actor/shape 映射与时间戳的 contact event/raw contact data 通道，区分"事件存在但力未更新"与"陈旧缓存"；force 不可用时不伪造。
5. **验收矩阵**：同进程连续 3 次静态/墙接触，每次要求（a）分离时 force=0，（b）真实接触时 force 连续/可归因，（c）读取健康/异常/陈旧标记完整；再加 2 个旧案例闭环复现（测量适配版本）。

## 4. 两个旧 CONTACT_INFERRED 案例的闭环重放准备

- 产物：`configs/scenarios/dsh_contact_lifecycle_replay_plan_v1.json`（只读生成，未运行旧案例）。
- 已核对并 hash 一致：旧 freeze `clearance_boundary_freeze_v1.json`、cases、expected、vehicle config、brake model、旧 `episodes.jsonl/steps.jsonl` 均与旧 manifest 记录一致（`artifacts.*.matches_manifest=true`）；源码 commit `0546701` 本地可用，旧 `run_dynamic_eval.py` 可从 git 只读提取（不得 checkout/改写共享工作树）。
- 可严格恢复的部分：case 初始位姿/航点/`timeout_s`、障碍公式（start+velocity·t，end_time clamp）、观测/动作延迟、TTL/max_age/allowed_age、时钟偏移/漂移/不确定度、注入故障步（均为 -1）、supervisor/waypoint/V2 gate/executor（由源码 commit 固定）、`EpisodeBoundary.start(seed=case.seed or 9000)`、`env._get_dones` override、每集不 reset、`max_steps=ceil(timeout/0.05)`。
- 缺失/不可保证项（已写入计划）：Isaac/IsaacLab/PyTorch/CUDA 版本未记录；GPU driver 仅为 `NOT RECORDED`；env origin 未记录；boundary seed 默认值由源码固定但未逐集记录；PhysX/CUDA 非确定性未表征，不能承诺位级复现；旧运行无 contact sensor（旧标签是几何推断），重放必须只增加"测量适配"而不能重写控制/障碍/时钟/边界；旧两例的逐集截图未保存。
- 结论：**控制/障碍/时钟/队列/边界可严格配置恢复**；**测量与数值复现只能标"新版本复现/测量适配"**，不能直接判旧记录真伪。结合 §3 的陈旧 contact report 证据：旧边界运行虽无 contact sensor，但任何新测量重放都必须在每集开始做"分离时 force=0"的健康握手；若同进程无法保证，只能用独立进程作临时模式并明确标注，不能把该结果当成严格同配置闭环复现。

## 5. 包络迁移方案（只输出，不改代码）

见 `docs/reports/map_eval/contact_envelope/dsh_contact_lifecycle_envelope_migration_plan_20261102.md`：现状旧口径、目标 `body_envelope.v2`（root 系 half+offset、`sphere_about_origin`、coverage/limitations）、`clearance`/`stop_requirement` 版本化接口、runner 测量/记录改造、freeze/核验/测试与影响清单。本轮未修改生产接触读取或包络代码。

## 6. 证据文件

- 运动学障碍探针：`outputs/dsh_contact_lifecycle/{fixed_root_only,fixed_shape,env_reset_shape,sensor_reset,view_rebuild,reapply_reporter}_rep_false/`（第一轮）与 `*_refined/`（完整逐步行记录）。
- 墙探针：`outputs/dsh_contact_lifecycle/wall_{fixed,env_reset,view_rebuild}_refined/`（无高度保持，含 ep2 下沉证据）与 `wall_alt_*`（高度保持）。
- **静态障碍决定性探针**：`outputs/dsh_contact_lifecycle/static_{fixed,env_reset,sensor_reset,view_rebuild,late_view_rebuild}_refined/wall_lifecycle_probe.json`（每集 200 步行记录，含 robot/obstacle 位姿、raw matrix/net、shape、view id、timestamps、read health、异常与陈旧力）。
- 日志与退出码：`logs/dsh_lifecycle_*.log/.exit`、`logs/dsh_wall_*.log/.exit`；探针脚本 `tmp/dsh_contact_lifecycle_*.py`。
- 重放计划：`configs/scenarios/dsh_contact_lifecycle_replay_plan_v1.json`。
- GUI 证据：`docs/reports/map_eval/contact_envelope/screenshots/dsh_contact_lifecycle_static_gui.png`（本轮静态障碍探针的前台 Isaac Sim 5.1 窗口，DirectX；截图同时可见 Codex 在编辑 `contact_readout.py`，本报告未使用该未完成入口）。

## 7. 未完成/待 Codex 合并后复核

- 高度保持墙场景的 fixed/env_reset/view_rebuild 三组结果需补入 §3 后再给最终"同进程可重复性"结论。
- Codex 的 `contact_readout.py`/测试合并后，本探针需改用它读取（只作为测量适配）重跑同矩阵，确认读取缺陷修复后 lifecycle 结论是否变化。
- 同进程 scene 重建不可用（挂起）已记录为失败探针；不在本轮强行重试。
- 未提交、未改冻结/核验/生产入口；等待 Codex 合并检查与用户决定下一步 GUI 验收。
