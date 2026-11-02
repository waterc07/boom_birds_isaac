# DSH 接触结束新鲜度专项（自然分离 / 重接触）— 2026-11-02

> **状态：** PASS（受控诊断专项；不提升 Gate，不宣称接触链整体完成）
> **证据域：** Isaac Sim 5.1 前台可视 GUI（DirectX/D3D12，无 headless）、单环境受控运动学障碍、独立原始向量核验；不是正式生产 episode
> **最后核对：** 2026-11-02T16:00Z 左右（Asia/Shanghai 2026-11-03 凌晨）

## 1. 结论

- 在同一 episode 内完成 **分离 → 接触 → 持续接触 → 自然分离 → 再次接触** 共 **3 个循环**，无中途 hard reset；机器人只在 **站定保持** 时被写回参考悬停点，自然的接触结束由 **运动学障碍沿连续轨迹离开** 产生，不是传送机器人制造分离。
- 自然分离后 **3/3 循环** 都出现 `filtered/net` 测力回到零：每循环分离阶段在几何间距 `box_separation_m > 0.1 m` 的样本中，最大测得力 **0.0 N**（各 6 个零样本）；随后 **3/3 循环** 均重新建立接触（低幅真实测力约 **0.0125–0.0127 N**，低于 0.02 N，但按真实接触记录，不判无接触）。
- **对照（单独目录，不混称自然分离）**：显式把机器人传送离开的 `robot_teleport_control` 运行中，3 个循环有 **2 个循环** 在几何间距约 2.05 m 处仍返回陈旧 filtered 力 **0.0122–0.0128 N**。这再次说明：**自然运动学分离** 在本受控设置下清除了测力；**显式 teleport** 仍可能返回陈旧力，不能用传送/重置后的零或非零读数推断正常接触结束行为。
- 未发现“自然分离后仍返回陈旧力”的受控证据，因此本轮 **没有** 为接触结束行为修改生产代码；没有手工填零、没有在 episode 中途 hard reset。受控探针的站定保持干预、测力覆盖与原生事件缺口仍是限制（见 §5）。
- 独立核验 `scripts/verify_contact_end_freshness.py`：**PASS**；自然运行所有检查通过，传送对照的陈旧力被独立检测到；原始向量与缓存一致、物理步号单调、握手 generation 1、无中途 reset。

## 2. 受控过程

探针：`scripts/contact_end_freshness_probe.py`，单环境，障碍为受控运动学 cuboid `[0.4,0.4,0.6] m`。

1. 环境创建后完整物理 reset 一次；`DynamicContactSession` 创建 body→障碍 root 的单目标 filtered sensor；障碍置于远端，机器人悬停，**有界零基线握手**（最多 20 步，容差 1e-6 N）成功。
2. 每个循环：
   - 障碍以 0.4 m/s 连续接近；接触由原始 filtered 力 >1e-6 N 或几何重叠触发；
   - 障碍在机器人参考点附近保持（持续接触）`sustain_steps=20`；
   - 障碍以 0.4 m/s **连续离开**（自然分离；机器人不传送、本 episode 不 hard reset）；
   - 障碍再连续返回并重新建立接触（重接触）。
3. 机器人以“站定保持”写回参考悬停点，仅用于保持受控几何；**没有用机器人传送制造分离**。这是诊断干预，已在记录与限制中标明。
4. 另起一次 `--separation-mode robot_teleport`，单独目录记录显式传送对照；不写入自然分离结果。

原始记录（`outputs/dsh_contact_end/natural_obstacle_motion_final2/contact_end_freshness.json`，350 行）逐样本包含：循环/阶段、`physics_step`、`physics_generation`、模拟/主机时间、机器人/障碍世界位置和速度、`center_distance_m`、`box_separation_m`、机器人/障碍半径、球重叠、原始 `filtered_by_target_n`/`net_vectors_n`、读取健康、目标路径与 filter count。

## 3. 结果

自然分离（`obstacle_motion`，最终运行）：

| 循环 | 接触建立 | 持续接触最大测力 | 自然分离后 box>0.1 m 最大测力 | 零样本数 | 重接触 | 重接触最大测力 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 是（66 步接近） | 0.012677 N | **0.0 N** | 6 | 是（18 步） | 0.012262 N |
| 1 | 是（先自然离开 20 步，再 20 步接近） | 0.012603 N | **0.0 N** | 6 | 是（18 步） | 0.012341 N |
| 2 | 是（先自然离开 20 步，再 20 步接近） | 0.012524 N | **0.0 N** | 6 | 是（18 步） | 0.012453 N |

说明：循环 1/2 在开始处先由**运动学障碍连续离开** 20 步（`precycle_separation`，机器人不传送），然后进行完整接近；因此每个循环都有独立的分离基线、接触建立、持续接触、自然分离与重接触。自然分离后测力均回到零。

显式 teleport 对照（`outputs/dsh_contact_end/robot_teleport_control/contact_end_freshness.json`，1076 行，单独目录）：

| 循环 | 分离方式 | 几何间距 >0.1 m 时最大测力 | 零样本 | 备注 |
| --- | --- | --- | --- | --- |
| 0 | 机器人传送到 x=2.0 m | 0.0 N | 30 | 与机器人此前接触状态有关 |
| 1 | 机器人传送 | **0.012781 N** | 0 | 陈旧力；几何间距约 2.05 m |
| 2 | 机器人传送 | **0.012196 N** | 0 | 陈旧力；几何间距约 2.05 m |

原始数据保留，未填零；陈旧样本标为诊断性 `robot_teleport` 对照，不能与自然分离混用。该探针本身不修改生产行为；若将来要在生产入口对“几何与力明显冲突”加 STALE/UNKNOWN 诊断保护，必须先加失败回归，并另行冻结验证。

## 4. 独立核验

- 工具：`scripts/verify_contact_end_freshness.py`（直接读原始 `net/filtered` 向量，用 `contact_raw_audit.audit_row` 重算，不优先信任探针 measure 缓存）。
- 输出：`docs/reports/map_eval/contact_envelope/dsh_contact_end_verify_20261102.json`，**PASS**。
- 检查：自然模式 3/3 循环接触、自然分离后零力、重接触；teleport 对照检测到至少 2 个循环陈旧力；原始向量/缓存一致、物理步号单调、handshake 成功、generation=1、无中途 reset。
- 代表性 GUI 截图：`docs/reports/map_eval/contact_envelope/evidence_20261103/contact_end_sustain.png`（1280×720，持续接触时截取；非空、可查看）。运行日志含前台 GUI/DirectX 启动与关闭记录。

## 5. 限制与未解决问题

1. **站定保持干预**：机器人被写回参考悬停点以保持受控几何；这不是通过传送制造分离，但不同于自由飞行中的自然漂移，不能外推为所有飞行条件下的接触结束行为。
2. **覆盖与事件**：filtered target 仅为障碍 root；负接触覆盖（未发生接触时）仍未验证。原生 contact event/callback 未建立，零事件不能作为无接触证据。零读数只表示本测力通道未测得正力，不能单独证明几何上无接触。
3. **低幅力**：持续/重接触读数约 0.0125–0.0127 N，低于历史 0.02 N 阈值；本轮按真实接触记录，不把它升级为无接触，也不改停止阈值。
4. **范围**：单环境、单一障碍尺寸/速度/材质、单一传感器/单 body；未验证螺旋桨、全姿态 mesh 扫掠、多环境训练 reset；未测原生 impulse/event。
5. **显式 teleport 对照的陈旧力保留为已知限制**，未通过清缓存/填零修复；生产入口当前只在 episode 起点 hard reset，本轮没有在 episode 中途 reset。
6. 本次为诊断探针，不是预冻结生产回归 episode；正式 20 场景回归见 `DSH_DYNAMIC_REGRESSION20_20261102.md`。

## 6. 精确命令

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 自然分离/重接触，GUI；单独目录
& $py -u scripts/contact_end_freshness_probe.py --cycles 3 --separation-mode obstacle_motion --screenshots --output outputs/dsh_contact_end/natural_obstacle_motion_final2 --kit_args=--/app/vulkan=false --device cuda:0
# 显式传送对照，GUI；必须单独目录，不混称自然分离
& $py -u scripts/contact_end_freshness_probe.py --cycles 3 --separation-mode robot_teleport --output outputs/dsh_contact_end/robot_teleport_control --kit_args=--/app/vulkan=false --device cuda:0
# 独立核验
& $py scripts/verify_contact_end_freshness.py --natural outputs/dsh_contact_end/natural_obstacle_motion_final2 --teleport-control outputs/dsh_contact_end/robot_teleport_control --output docs/reports/map_eval/contact_envelope/dsh_contact_end_verify_20261102.json
```

## 7. 版本化摘要

`evidence_20261103/contact_end_freshness_natural.json`、`evidence_20261103/contact_end_freshness_teleport_control.json`、`evidence_20261103/contact_end_sustain.png`、`dsh_contact_end_verify_20261102.json`；完整 hash 见交接与 evidence/hashes.json。
