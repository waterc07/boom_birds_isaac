# 动态评价生产入口：接触与几何迁移（2026-11-02）

状态：显式新模式完成实现、4 个预冻结 GUI episode 与独立核验；不是接触链/全场景总体验收，不提升 Gate。保留 legacy 默认，避免静默改变旧复现命令。未创建 Goal、未切分支、未提交或推送 Git，用户和 DSH 既有修改保留。

## 1. 本轮完成与审查依据

沿用 [DSH 最小矩阵交接](../../HANDOFF_20261102_DSH_CONTACT_LIFECYCLE.md) 和 [Codex 读取修复](CONTACT_READOUT_FIX_HANDOFF_20261102.md)。重新运行 DSH verifier：77 项 PASS；另新增独立 raw-vector 审计，直接从 `net_vectors_n` 和 `filtered_by_target_n` 重算 1,023 行，验证运行器 measure/episode 最大值缓存、握手零和产物 hash，0 错误。后者不信任原 verifier 的 `raw_measure` 缓存优先路径。

审计限制：记录一致性不是证明所有 PhysX 数据都新鲜；本轮在单环境中用完整物理 reset 和有限零基线握手约束 episode 起点。没有建立原生 event/impulse 通道，也不声称任意接触结束后的低层缓存行为均已解决。

## 2. 新入口与兼容

`scripts/run_dynamic_eval.py` 新增显式模式：

- `--contact-mode measured_hard_reset`：每 episode 完整物理 reset，创建单 body→障碍 root filtered sensor；建立分离零基线，记录 generation、物理步号、原始读取及异常。
- `--geometry-policy reference_origin_v2`：测量真实 CollisionAPI 几何，计算 root-frame AABB、中心偏移和绕机器人参考原点的球；障碍使用 cuboid 半对角线球。
- `--write-migration-freeze <新文件>`：在创建 Isaac GUI 前写预冻结；已存在文件拒绝覆盖。
- 新模式使用 `boom_birds.dynamic_migration_freeze.v1`，验证真实 Git HEAD、所有 `src/**/*.py` 与 runner 的源文件 hash、配置 hash、运行参数和真实冻结时间。旧冻结不得套入新模式。

`legacy` / `legacy_inference` 保留原始公式与路径，仅用于历史兼容，不将其宣传为已经修正的默认路径。新模式仍运行原 v2 gate、TTL、所有权及动力学控制器；没有新增 PX4 Sender 或实机 failsafe。

完整 reset 只在测量 episode 开始前使用，后续 `EpisodeBoundary` 重新初始化策略 episode 计数。分离握手使用初始化控制器，不属于策略任务动作。握手完成后正式任务从声明初始配置开始；gate/队列/控制器重新初始化。未知测量不伪装有效零，零力不升级为 NO_CONTACT。

## 3. 新查明的几何来源问题

旧接触入口列出了 collision prim，但实际用 `BBoxCache(default, render).ComputeWorldBound(robot_root)` 计算整个 root 的 bbox，再把 coverage 写成 collision_geometry。这不能证明输入是碰撞几何专属边界。该旧 source 声明过强，保留原记录和 hash，不再据此宣称已完成碰撞专属包络迁移。

新测量直接读取碰撞 mesh points（或全 purpose bound），按 prim→world→reference 变换计算。该资产的碰撞 mesh 是 proxy/guide 用途，旧 default/render 查询该 prim 返回空界。新路径不回退到视觉 bbox 冒充碰撞几何。

| 项目 | 新运行测量/规则 |
| --- | --- |
| collision prim | `/World/envs/env_0/Robot/body/body_collision/geometry` |
| root 系 half extents | `[0.0500000007, 0.0500000007, 0.0149999997]` m |
| root 系中心偏移 | `[0,0,0]` m |
| 机器人参考原点球半径 | 0.0722841624 m |
| 障碍尺寸 | `[0.4,0.4,0.6]` m，运行前核对各 case 与同一 spawn 一致 |
| 障碍半对角线球半径 | 0.4123105626 m |
| 两球半径和 | 0.4845947250 m |

旧障碍 `max(size)/2=0.3 m` 连固定姿态 cuboid 的角点也不覆盖；本轮明确保留为 legacy 公式，不再称其为任意姿态保守球。

若只把停止阈值作路径距离的几何扣除，1.1/1.38 m 对应的 gap 约为 0.615405/0.895405 m。这不是制动安全余量；相对运动、时延和制动需求还须单独计入。此前使用不同包络来源的 margin 结论不能直接继承。

测量只覆盖当前模型的碰撞 body、固定关节状态与 authored USD 几何；没有建立螺旋桨机械扫掠、PhysX 接触 offset 外扩或真实机体安全包络，不宣称全姿态 mesh sweep。

## 4. 预冻结 GUI 结果

最终冻结：[contact_production_migration_v3.json](../../../../configs/scenarios/contact_production_migration_v3.json)。运行目录 `outputs/map_eval/production_contact_migration/final3`，前台 GUI、DirectX/D3D12、cuda:0。四集物理 generation 依次 1–4，握手各 1 步，新模式正式运行开始后未再次执行完整 reset。

| 案例/方法 | 业务结果 | 物理证据 | 时长 |
| --- | --- | --- | --- |
| A / FOLLOW_ONLY | SUCCESS | UNKNOWN，未观测到 filtered force | 52.50 s |
| A / SUPERVISOR | SUCCESS | UNKNOWN，未观测到 filtered force | 52.50 s |
| C / FOLLOW_ONLY | COLLISION | filtered force=0.0130532 N，归因障碍 root | 22.75 s |
| C / SUPERVISOR | ABORT / MAX_WAIT_EXCEEDED | UNKNOWN，未观测到 filtered force | 24.70 s |

低于旧 0.02 N 阈值的真实 filtered 信号不再被丢弃。该模式使用 1e-6 N 的 PROPOSED 读取噪声容差区分测力与数值零，未声称已完成实机噪声标定。几何重叠独立保留，不自动升级为物理碰撞。

独立核验从 3,050 行记录重算测力、包络、gap、generation/握手及物理结果，核对预冻结、源文件与产物 hash，PASS、0 raw errors。它验证指定记录与合同一致，不证明负接触覆盖或所有运行条件安全。无接触读数仍为 UNKNOWN。

## 5. 实际验证与失败记录

- 全套 `pytest -q`：772 passed，exit 0，76.02 s；包含新增 raw-cache 篡改、live tuple/list、几何来源接口、配置/源码冻结与有限握手回归。
- 文档审计 PASS，原用户 `planning_audit.json` 执行后按原字节恢复。
- 新入口及模块语法检查、当前工作包空白检查通过。
- 只读 GPU 观测：RTX 5080、driver 581.80；这是本轮机器观测，未更改驱动。
- 截图是有效地图 viewport 图像，人工查看确认地图可见；没有用它证明细小无人机的具体位置。GUI 创建与运行另由窗口日志和物理记录支持。

失败保留：pilot1 碰撞 prim default/render bbox 为空；final2 live dataclass tuple 被只接受 JSON list 的新审计函数误拒绝。均有 error 文件，新冻结未覆盖旧版本。第二项经新增失败回归修复后，final3 运行通过。Kit 两次失败仍返回 exit 0，所以不能只凭 shell 退出码认定成功。

## 6. 精确命令

```powershell
$bbPython = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 重新运行时用新输出目录；当前 source 与 v3 freeze 必须保持一致。
& $bbPython -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --only-cases dynamic_A_south_0,dynamic_C_south_0 --methods follow_only,supervisor --execution-path v2 --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --screenshots --device cuda:0 --kit_args=--/app/vulkan=false --output outputs/map_eval/production_contact_migration/new_run --freeze configs/scenarios/contact_production_migration_v3.json
& $bbPython scripts/verify_dynamic_migration.py --run outputs/map_eval/production_contact_migration/final3 --freeze configs/scenarios/contact_production_migration_v3.json --output outputs/map_eval/production_contact_migration/verify_repeat.json
& $bbPython scripts/verify_contact_raw_samples.py --run outputs/dsh_contact_lifecycle/formal_contact_S_static3 --run outputs/dsh_contact_lifecycle/formal_contact_W_wall3 --output outputs/map_eval/production_contact_migration/raw_audit_repeat.json
& $bbPython -m pytest -q
```

源码变化后，应使用同一运行参数和新文件名传 `--write-migration-freeze` 生成新预冻结，而非修改 v3 时间或 hash。全部新模式尚为未提交工作树实现；Git HEAD 只是基线标识，真实执行源码由冻结 source_hashes 描述，不冒称代码已入该 commit。

## 7. 旧案例和下一步

两个旧 CONTACT_INFERRED 标签维持“历史几何推断，物理真值未确认”。缺少完整旧环境和连续运行上下文，单例结果不能推翻或证明旧标签；停止重复单例来追求一致。今后若重测，明确是新模式/新冻结下的新测量，不能改写旧事实。

下一步优先在该显式新模式做 20 个动态场景的有限回归、以及接触结束后数据是否陈旧的专项；需要时追加几何冲突标 UNKNOWN 的诊断保护，不能通过填零制造健康。随后再决定是否升级默认模式。当前只验证 4 集，不宣称已回归所有动态/故障场景。

未解决：完整负接触覆盖、原生 event/impulse、任意接触结束后的缓存新鲜度、多环境训练 reset、全部地图/姿态体积覆盖。未运行 PPO/真实感知/PX4 Sender/板端/SITL/HIL/实机，规则/BOM/PX4 保持原未验证状态，不提升任何 Gate。

## 8. 版本化证据

[独立核验](production_migration/verify_final3.json)、[DSH 矩阵复核](production_migration/dsh_matrix_recheck.json)、[独立原始向量审计](production_migration/raw_vector_audit.json)、[摘要与选定原始样本](production_migration/evidence)、[hash 清单](production_migration/hashes.json)。完整 steps 仍位于忽略输出目录，hash 已归档；版本化摘要不以该目录作为唯一结论来源。
