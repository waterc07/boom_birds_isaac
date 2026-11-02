# 接触证据退化诊断与受控恢复（2026-11-02）

> **状态：** ASSESSMENT（当前工作包；证据域为仿真 / 最小 GUI 探针 + 受控评价）
> **来源章节：** `docs/reports/HANDOFF_20261102_CLEARANCE_BOUNDARY.md`、`docs/reports/map_eval/MAP_CLEARANCE_BOUNDARY_REPORT.md`、`docs/design/CLEARANCE_GEOMETRY_CONTRACT.md`；历史 `MAP_EVAL_REPORT.md`、`MAP_ROUTES_REPORT.md`、`MAP_DYNAMIC_REPORT.md`、`LAYERED_EVALUATION_REPORT.md`
> **最后核对：** 2026-11-02

## 1. 问题陈述

上一轮边界入口（`ee17a78`）只有 `CONTACT_INFERRED` 球重叠推断；历史地图/动态评价曾记录真实 PhysX 接触力：
- `MAP_EVAL_REPORT.md`：机器人 body 单 prim contact sensor，逐 prim 过滤地图碰撞 prim；墙体 `collision_014` 0.0504 N、地面 `collision_005` 0.0318 N；地图 34 个碰撞 prim 启用 contact reporter。
- `MAP_ROUTES_REPORT.md`：同机制，墙体/地面 4/4 COLLISION。
- `MAP_DYNAMIC_REPORT.md`（`final_dynamic1`，commit `92757f0`）：FOLLOW_ONLY 12 次与 `/World/envs/env_0/Obstacle` 真实接触，0.0231–1.3409 N；sensor 在 robot/body，filter 障碍 root，`replicate_physics=True`。
- `LAYERED_EVALUATION_REPORT.md`：B 类 25/25 碰撞有 PhysX 接触证据（阈值 0.02 N）。

目标不是归因 GPU/驱动/Isaac 不支持，而是逐因素定位差异并恢复可验证接触链。

## 2. 最小复现与逐因素结果（全部前台 GUI，DirectX/D3D12，探针保留）

| 探针 | 场景 | 关键配置 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| probe1 | 场景障碍 + 地图 | 手动 ContactSensor，用机器人 pose 传送 | 障碍与墙均 0；GPU filter 对 obstacle 子 prim 报 unsupported | `outputs/map_eval/contact_probe1` |
| probe2 | 历史地图墙 + 悬停控制 | 地图 spawn 后逐 prim reporter + body/link sensor | **墙接触力 0.042 N**（step 123，`collision_014`） | `contact_probe2` |
| probe3/3b/4 | 运动学障碍穿过悬停机器人 | 传送障碍、body/link sensor、root/mesh filter | 机器人被推开 0.55–0.85 m，但所有 sensor 0；无 filter 的 `net_forces_w` 也 0 | `contact_probe3b`、`contact_probe4` |
| probe5c | 运动学障碍 + 单/多 sensor（无 shape reporter） | `replicate_physics=True` | 仍 0 | `contact_probe5c` |
| probe6 | 障碍穿机器人 + 机器人撞障碍；历史上下文（地图已 spawn、ground 关闭） | `replicate_physics=True`，filter root | 0/0 | `contact_probe6` |
| probe8 | Isaac Sim physics ContactSensor（形变传感器） | 障碍/机器人碰撞体下挂 sensor | `in_contact=false`、force 0，即使机器人被推 | `contact_probe8` |
| probe11 | 同 probe5，但 `replicate_physics=False` + 障碍 shape 级 reporter | `replicate_physics=False` | **真实接触力 0.0081 N**（robot body filter obstacle root，filtered=net） | `contact_probe11` |
| historical_repro1 | 原样运行历史入口 `run_dynamic_eval.py@92757f0`（FOLLOW_ONLY `dynamic_C_south_0`） | 历史源码/配置 | **真实接触力 0.0231 N**（step 454，sensor body filter obstacle root） | `tmp/historical_repro1` |
| controlled runner | 受控 B 墙/障碍（本轮入口） | `replicate_physics=False` + obstacle shape reporter + per-link filtered sensor | 墙 0.156/0.625 N；障碍 0.0276 N（net，未归因） | `outputs/map_eval/contact_*` |

### 2.1 有证据支持的差异解释

1. **历史可测性可复现**：原历史入口在**当前机器/当前 Isaac 版本**下运行仍测得 0.0231 N（`tmp/historical_repro1`），说明不是 GPU/驱动/Isaac 能力问题。
2. **接触 reporter 的覆盖层不同**：`activate_contact_sensors=True`（障碍 spawn）将 `PhysxContactReportAPI` 加在 **obstacle root Xform**；其碰撞 shape `/World/envs/env_0/Obstacle/geometry/mesh` 初始无 API（probe2 inventory）。机器人只与 shape 产生接触，故 shape 无 reporter 时接触报告丢失；历史入口之所以成功，综合复现结果与探针对比，属于历史入口的 contact view 建立时机/对象组合恰好有效（`historical_repro1` 原样可测），而当前边界入口的探针链在 shape/root/replication 组合下未建立有效 contact view。
3. **`replicate_physics=True` 下 post-hoc shape reporter 不生效**：probe6/7（True）与 probe11（False）在相同 shape reporter 下结果相反（0 vs 0.0081 N）。说明在 physics replication 已建立后再给 collider shape 加 reporter，不会进入复制后的 PhysX 场景；需要在复制前配置，或关闭 physics replication 后再加。
4. **接触报告在单进程内仅首个 episode 可靠**：受控 B 第 1 次重复可测（0.0276 N），第 2 次在同一进程内物理推挤仍发生但 net/filtered 均 0；改为**每个 episode 独立进程**后两次均测得 0.0276 N（`contact_B_obstacle_rep0/rep1`）。证据记录为运行入口限制并在正式运行中按独立进程执行重复。
5. **零输出 ≠ 无接触**：probe3b/4 中机器人被明显推开 0.55–0.85 m，而 filtered/net 均 0；因此任何"0 N"都只能说明该通道未覆盖/未更新，必须返回 `UNKNOWN`，不能判 `NO_CONTACT`。受控 C 的 `NO_CONTACT` 仅当 sensor available 且 force 有效为零、无 event 时才成立。

### 2.2 当前入口的恢复方式（本轮已接入）

- `scripts/run_contact_verification.py`：wall/obstacle/clearance/geometry/replay 模式；`replicate_physics=False`；障碍 collider shape 级 `PhysxContactReportAPI`；per-link `ContactSensor` filter obstacle root/wall prim；接触记录用 `boom_birds.contact_evidence.v2`；每步记录 physics substep/窗口；`contact_sensor`、`prim_inventory`、measured `body_envelope`、freeze run_plan 写入 manifest。
- 障碍重复：每个 episode 独立进程（本工作包运行脚本），保留每个进程原始目录并在段目录合并（`merged_from`），不修改原始行。
- 真实测力能力：墙/障碍均可测；障碍当前为 **filtered sensor = 0 但 net_force 可测**，合同标 `CONTACT_FORCE_MEASURED_UNATTRIBUTED`，不伪造 prim 归因；后续若建立 shape 级 filtered 通道，可升级为 ATTRIBUTED。

## 3. 承接的历史报告差异

- 历史 `MAP_EVAL_REPORT` / `MAP_ROUTES` 的接触机制（地图 spawn 后逐碰撞 prim reporter + body sensor 逐 prim filter）**本轮以 probe2 复现**（0.042 N），说明该路径仍可用；当前入口的墙接触采用同一路径。
- 历史 `MAP_DYNAMIC_REPORT` 的障碍接触（kinematic obstacle + root filter + `replicate_physics=True`）在本机原样运行可复现（0.0231 N），因此旧数字本身未被推翻；但其可复现性依赖历史入口的完整上下文，不能把"历史有力"直接当作当前入口的覆盖证明。
- 旧边界报告的 `CONTACT_INFERRED` 保留标签；本轮复核仅对 3 个旧案例新增真实接触证据与适用性说明，不批量改写其余 episode。

## 4. 包络中心发现（详见 `MAP_CONTACT_ENVELOPE_REPORT.md`）

- 运行时测量（collision API prim 集 + 机器人 root AABB，root 系）：half extents `[0.0545422337, 0.0382082667, 0.0135880403]` m，center offset `[5.902e-05, 2.421e-08, 0.014869]` m；因此 `r_origin = || |offset| + half || = 0.072463 m`，旧 `r_legacy = ||half|| = 0.067966 m` 在 offset≠0 时**低估 0.004497 m**。
- 机器人碰撞几何只有 body 碰撞体；螺旋桨/子体在 prim inventory 中无 CollisionAPI（仅视觉），coverage 必须注明未覆盖全姿态/桨叶碰撞几何；AABB 是单关节状态界，不是全姿态三角网格扫掠证明。
- 修正后 clearance/停止需求所用半径需以 `sphere_about_origin` 为准；旧半径分析保留，新增修正分析（`analyze_envelope_correction.json`），旧报告与 hash 不重写。

## 5. 未解决 / 限制

1. 障碍接触当前未取得 per-prim filtered 归因（net force 可测）；需要进一步在障碍 shape 级建立有效的 filtered contact view（可能需在 env 创建前配置 reporter 或自定义 spawn 流程），本轮如实标 `CONTACT_FORCE_MEASURED_UNATTRIBUTED`。
2. 单进程内接触报告仅首 episode 可靠；本工作包用独立进程规避并在段 manifest 记录 `merged_from`。该行为本身是当前接触链的覆盖限制。
3. 没有真实力/冲量的实机标定；冲量层在接触记录中保留接口但本轮未取得可靠 impulse（`impulse.available=false`）。
4. 不启动 PPO/真实感知/PX4/板端/SITL/HIL/实机，不提升 Gate。
