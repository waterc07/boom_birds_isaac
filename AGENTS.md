# Boom_Birds 仓库协作规则

本文件是后续代理接手项目的操作入口。详细需求、接口与验收以对应设计和实施计划为准；代码、运行证据与文档不一致时，先核查并同步记录，不把规划当成实现。

## 接手顺序与依据

1. 先读 `PROJECT_PLAN.md`、`docs/design/RMUC2027_UAV_V2_2.md` 和 `docs/reports/ROUTE_V2_2_REVIEW_20261031.md`，再查旧架构/目录了解历史。
2. 再读 `docs/superpowers/plans/2026-10-11-p0-p1-foundation.md`、`docs/reports/p0/P0_ENVIRONMENT_REPORT.md`，确认已完成项、限制和下一工作包。
3. 检查 `git status --short`、当前分支和近期提交；保留用户已有修改，不覆盖、不回退无关文件。
4. 实施前阅读对应任务的设计、配置和测试；当前验收依据见 V2.2 正文第 20、26–28 章；旧 `docs/design/08_EVALUATION.md` 仅作历史参考，上游复用依据见 `third_party/NOTICE.md`。

当前采用用户指定 DSH V2.1.0 经验收修订的 V2.2.0，唯一当前设计正文为 `docs/design/RMUC2027_UAV_V2_2.md`，验收及差距见 `docs/reports/ROUTE_V2_2_REVIEW_20261031.md`。它优先于旧 v1.2 总纲、`docs/design/01–09` 及旧实施计划；旧文件只保留历史证据与可复用方法。按新工作包补具体计划，不自动继续旧 Task 4–6。

## 当前状态与延续入口（2026-11-04）

先查 [当前状态索引](docs/reports/CURRENT_STATUS.md) 和最新工作包交接，再使用下方历史记录。单环境动态评价已默认使用 `reference_origin_v2` / `measured_hard_reset`；传感器和地标感知仅 shadow。模板与几何/绿灯候选已按独立测试停止，不进入关联/控制，不自动开始模型训练；下一项为需求、轻量方案、数据和部署可行性评审。真实 PX4 Sender、板端 Student、项目 PPO 和各 Gate 均未完成验收。

## 历史状态与证据索引

截至 2026-10-11，以下为接手基线，后续须以现场检查和最新报告刷新：

- Task 1/W00：已有环境、上游许可、版本与官方最小例证据；选定现有 RSL-RL 5.0.1。环境依赖一致性仍有冲突，详情见 P0 报告；不能宣称 G0 全面通过。
- Task 2/W01：已实现标准库动作、坐标、时效合同及回归测试。
- Task 3–6：旧 Task 3 方法已用于本项目仿真速度执行链；最小到点任务与统一评价入口已实现；项目 PPO 训练和重放仍 NOT RUN。
- 2026-10-31 路线更新：先补新 Phase 0 的规则/实物/固件来源与 Schema 差异；可先实施 BB22:G2.6 纯软件上下文/时钟/动作合同。旧 Task 3 的速度→控制器→力/力矩→实际运动验证方法继续复用；旧 Task 4–6 须先按新 Gate 更新计划。
- 新 Gate 使用 BB22 命名空间，不继承旧 G0/G1 结论。新 Schema、PX4 Sender、控制监督器、恢复控制与板端 Student 均未实现。
- 2026-10-31 BB22:G2.6 软件合同：已新增 `boom_birds.message.v2.0` / `boom_birds.action.v2.0` 标准库合同（四级上下文、时钟映射与 PX4 重启隔离、观测溯源与不可续期 TTL、接纳/重发/乱序拒绝、控制所有权交接、碰撞与 reset 失效），68 条新回归，全套 101 passed；证据见 `docs/reports/g2_6/G2_6_CONTRACTS_REPORT.md`。Gate 整体仍 INCOMPLETE（固件/SITL/HIL/板端/实机均 NOT RUN）。后续同日完成：BB22:G0 来源盘点（`39a7812`，G0 未通过）；仿真速度执行链实测 11/11 检查 PASS（仅仿真模型，`86f0f2f`/`0fb76c3`）；最小到点与统一评价 6 episode smoke 为 INCOMPLETE（`38159ee`/`7e341bc`）。交接见 `docs/reports/HANDOFF_20261031.md`。
- 2026-10-31 分层场景评价：实现 v2 场景合同（A 无障碍/B 静态障碍/C 动态实体/D 观测退化/E 物理扰动）、受控 3×3 配额、PhysX 接触证据、扰动与退化注入；冻结后最终 125 valid episode（每类 25）。A 25/25、B 0/25（25/25 碰撞且有接触证据）、C 24/25、D 25/25、E 3/25（19 越界，控制能力失败保留在分母）。独立核验 24 项 PASS。证据见 `docs/reports/layered_eval/` 与 `docs/reports/HANDOFF_20261031_LAYERED.md`。不是 BB22:G4 放行。
- 2026-10-31 E 类扰动诊断与修复：已证实两项施力实现缺陷（横向力逐策略步累计、基座/整机质心杠杆力矩未补偿），修复后最小回放 3 个原越界案例全部成功且两次重复轨迹一致；冻结 125 场景回归中 E 类 19/25 越界 → 0/25，A/B/C/D 不变；C 类残余 1 个越界另列。证据见 `docs/reports/e_diagnosis/E_DIAGNOSIS_REPORT.md`。
- 2026-10-31 C 类残留越界诊断与修复：确认 QuadcopterEnv 在整环境 reset 时随机化 episode_length_buf，运行器忽略 truncated/静默 auto-reset，导致 C-021 在第 30 步 reset 后被误分类 OUT_OF_BOUNDS；单因素对照与 legacy 3 次重复证实与动态实体/接触/控制器无关。修复（清零 episode 边界、读取 truncated、核验 no_silent_auto_reset）后 C 25/25、A–E 125 clean 回归 success 100/125、0 越界。证据见 `docs/reports/c_diagnosis/C_DIAGNOSIS_REPORT.md`。
- 2026-10-31 评价 episode 边界全入口修复：统一 EpisodeBoundary（清零随机化计数、记录 reset 快照、terminated/truncated 主信号、终止用步前状态），接入 velocity/reach/compare；历史审计确认 layered final_run2/3 污染、velocity/reach 未发现证据但记录不足、compare/tuning 数据不足；以前台 GUI 重建 velocity/reach/compare/faults 干净基线并独立核验。报告见 `docs/reports/eval_audit/CLEAN_BASELINE_REPORT.md`。
- 2026-10-31 RMUC2027 地图动力学入口：通过配置引用 terrain.usdc（禁用默认 z=0 地面），建立米/Z-up/ENU/FLU、bounds、静态三角网格碰撞与接触合同；冻结 10 episode（到点 6、起降 2、真实接触 2）全部完成并通过独立核验；官方 GUI smoke 以 DirectX/D3D12 复跑 PASS。报告见 `docs/reports/map_eval/MAP_EVAL_REPORT.md`。不是完整比赛导航/避障/训练验收，不提升 Gate。
- 2026-10-31 地图多区域与跨区航点：4 个候选区域 GUI 射线核查，选 W/E/S 三区；2 条 W→E 离线航点路线（south/north）；WaypointRunner 中间/最终保持与航点核验；冻结 24 episode（local 12、route 8、接触 4）全部完成，独立核验 24 项 PASS。报告见 `docs/reports/map_eval/MAP_ROUTES_REPORT.md`。仍为 ORACLE 航点路线，不是自主避障/比赛导航，不提升 Gate。
- 2026-11-01 动态障碍监督：运动学障碍 + ORACLE 观测，RouteSupervisor（FOLLOW/BRAKE/HOLD/WAIT/RESUME/DEGRADED/ABORT），20 场景 A–E ×2 方法=40 配对 + 8 无障碍回归；独立核验 25 项 PASS；不是 PX4 监督器/视觉避障/实机安全，不提升 Gate。报告见 `docs/reports/map_eval/MAP_DYNAMIC_REPORT.md`。
- 2026-11-01 v2 执行适配：路线/监督器 → V2ActionGate（四级上下文、模拟 PX4 身份、ActionEnvelope/不可续期 TTL、所有权）→ 执行器 → 实测运动；20 动态 v2 + 8 回归 + 14 软件故障 GUI，独立核验 43 项 PASS；v1 保留显式对照。不是 PX4 Sender/实机安全，不提升 Gate。报告见 `docs/reports/map_eval/MAP_V2_EXEC_REPORT.md`。
- 2026-11-01 制动/故障后观测：36 制动 +8 故障后物理观测（前台 GUI，v2 执行链），实测停止距离 .185–.585 m、时间 1.25–3.25 s；确认“拒绝动作 ≠ 旧 setpoint 立即失效、ABORT ≠ 物理停止”；13 项独立核验 PASS。仅当前模型证据，不提升 Gate。报告见 `docs/reports/map_eval/MAP_BRAKE_ENVELOPE_REPORT.md`。下一项：传统控制基线、失败路径与随机化覆盖；G1/G3/G4 仍被硬件与感知前置阻塞。
- 2026-10-31 传统制导对比与随机化/故障验证：在 `--task compare` 上完成 30 场景 × 2 方法 = 60 episode 配对比较与 4 类专项故障各 4 样本；新制动基线未优于比例法（慢约 0.12 s、最终误差差约 0.09 m），状态 INCOMPLETE（30 场景 < PROPOSED 100，不是 G4 冻结）。证据见 `docs/reports/guidance_baseline/` 与 `docs/reports/HANDOFF_20261031_GUIDANCE.md`。
- 官方任务步进和官方 PPO 短迭代仅证明相应入口可运行，不代表本项目训练、稳定飞行或迁移验收；G1及后续阶段尚未验收。

## 目录与实现边界

- `src/boom_birds/contracts/`：已实现的标准库动作、坐标与时效合同。
- `src/boom_birds/contracts/` 同时存在 v1 历史合同（types/frames/timebase）与 v2 合同（context/action_v2/admission/ownership/lifecycle）；v1→v2 必须走显式迁移，不能只换 schema 标签。
- `tests/contracts/`：对应合同的 pytest 回归测试。
- `scripts/`：环境诊断、文档审计、场景/冻结生成、仿真入口与独立核验；`configs/scenarios/`：随机化场景清单与冻结文件。
- `configs/runtime/`：拟定运行参数，不代表运行系统已实现。
- `env/manifests/`、`env/locks/`：观测版本、上游 SHA 和既有依赖快照；快照不保证环境可干净重建。
- `docs/reports/p0/`：执行证据；`third_party/NOTICE.md`：复用边界。
- `external/`：被忽略的上游参考源码，不能成为项目运行时的隐式依赖。

设计中的其他目录是蓝图，随工作包实际建立，不创建空壳冒充实现。权重、大型资产和实验输出不入 Git；官方 USD 资产按远程引用及 manifest 追踪，不直接打包入库。

## 开发与验证命令

2026-11-02 接入记录（历史，默认已于 11-03 升级）：`run_dynamic_eval.py --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset`，接入真实碰撞几何包络、每集完整物理 reset/分离握手和 filtered force。须使用新的 migration 预冻结，旧冻结不得套用；legacy 默认仅保留历史兼容。当日为 4 集 GUI 接入验证；后续 20 场景、16 集自由飞行阳性和默认等价验证见当前状态索引，仍不是 Gate 放行。命令及证据见 `docs/reports/map_eval/contact_envelope/PRODUCTION_CONTACT_GEOMETRY_MIGRATION_20261102.md`。

用户运行要求（2026-10-31）：后续所有 Isaac 训练、仿真、评价、回放、诊断探针及官方 smoke，均以前台可视形式运行，打开并保留可见的 Isaac GUI 窗口；不得使用 `--headless`、无窗口或隐藏窗口方式运行。长任务也须保持前台可视，可同步保存日志和运行证据。若 GUI 无法正常启动，先排查并报告，不自动回退到 headless；仅用户明确授权时可例外。纯单元测试和文档审计不要求打开 Isaac。历史 headless 运行记录保留为历史证据，不据此继续使用 headless。

在仓库根目录使用 PowerShell 和现有解释器，无需为单元测试安装项目包；pytest 已配置 `src` 导入：

```powershell
$bbPython = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $bbPython -m pytest -q
& $bbPython scripts/planning/audit_documents.py
```

需要刷新环境证据或验证官方任务时再运行：

```powershell
& $bbPython scripts/preflight.py --isaaclab-root E:\isaac\IsaacLab --output env/manifests/host.json
& $bbPython scripts/check_official_quadcopter.py --device cuda:0 --clone-in-usd --steps 100 --output env/manifests/official-quadcopter-usd-smoke.json
```

诊断会覆盖指定记录；刷新时同步报告，保留重要历史失败证据。当前官方例使用 USD 克隆路径；Fabric 克隆问题及证据边界见 P0 报告。项目仿真入口（仿真模型证据，非 SITL/实机）：

```powershell
& $bbPython -u scripts/run_sim_baseline.py --task velocity_step --config configs/vehicles/sim_reference.yaml --scenarios all --device cuda:0 --clone-in-usd --output outputs/sim_velocity_chain/full.json --csv outputs/sim_velocity_chain/full.csv
& $bbPython -u scripts/run_sim_baseline.py --task compare --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/final_20261031.json --methods proportional,braking --run-kind final --timeout-s 20 --freeze configs/scenarios/freeze_20261031.json --device cuda:0 --clone-in-usd --output outputs/guidance_compare/final_run1
& $bbPython scripts/verify_guidance_runs.py --run-dir outputs/guidance_compare/final_run1
& $bbPython -u scripts/run_sim_baseline.py --task layered --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/layered_final_20261031.json --classes all --methods proportional --timeout-s 12 --freeze configs/scenarios/layered_freeze_20261031.json --require-coverage --device cuda:0 --clone-in-usd --output outputs/layered_eval/final_run2
& $bbPython scripts/verify_layered_runs.py --run-dir outputs/layered_eval/final_run2 --freeze configs/scenarios/layered_freeze_20261031.json
```

尚无项目训练或构建 CLI，实施计划中的未来命令须待入口实现后使用。

## 编码与测试

使用 Python 3.11+、四空格缩进、`snake_case` 函数/文件和 `PascalCase` 类型。公共接口加类型注解，变量名标明单位，如 `now_ns`、`velocity_enu_mps`。当前没有配置 formatter 或 linter，不声称已通过不存在的检查。

contracts 仅依赖标准库，不导入 Torch、Isaac 或相机库；sim/learning 与 runtime 保持既定依赖边界。

pytest 文件使用 `test_*.py` 和描述明确的 `test_*` 函数。修改合同行为前先添加失败回归测试，再实现并运行全套测试。覆盖坐标符号、水平向量限幅、非法值、到期边界、时钟域和 mission/origin reset。新增仿真与评价能力按对应计划验证；未配置覆盖率百分比门限。

完成声明须附实际验证命令、结果与限制。单元测试、官方 smoke、本项目仿真、训练及实机证据分别描述，不能互相替代。

## Git 提交与 PR

- **后续所有 Git 提交消息使用中文：标题的描述部分及正文均使用中文。** 保留 `docs:`、`feat:`、`fix:` 等类型前缀，代码标识符、路径和必要技术名词可保留原文。例如：`docs: 完善项目接手规则`、`feat: 实现仿真速度执行器`、`fix: 拒绝过期速度指令`。
- 中文规则适用于普通提交、合并提交、回退提交及 squash 最终消息；不为语言规则改写既有历史。
- 按工作包使用独立分支；按用户 2026-11-04 要求，新建分支不使用 `codex/` 前缀；采用简明的 `feat/`、`fix/` 或 `docs/` 加主题名，当前工作分支为 `feat/v2.2-simulation-perception`。
- 提交前检查 diff 与验证结果，只纳入当前任务文件；不纳入秘密、本机私有配置、大产物和无关修改。
- PR 说明行为变化、计划任务、验证命令/结果及剩余限制，有相关 issue 时关联。阶段交付不自动推送远端或刷写固件。

## 环境、架构与复用约束

保留现有 Isaac 环境；依赖冲突先复现受影响入口并调查，再决定局部调整，不全局升级或复制 venv。不安装 NavRL/DiffPhysDrone 整套旧运行链；采用已选 RSL-RL 后端，不自行实现 PPO 优化器。

V2.2 采用 RK3576、非 VIO 区域导航和地标接力；大规模训练前验证完整代表性 Student 板端可行性。现有 `boom_birds.velocity.v1` 是历史已实现接口，不具备新四级上下文/飞控重启/动作溯源能力，迁移须显式适配、先失败测试，不直接换版本标签。

统一四维归一化动作：水平 FLU 前/左速度、向上速度、逆时针偏航率；运行指令使用 ENU 物理单位，PX4 网关再转 NED。水平速度约束向量模长，不能只逐轴限幅；重发不续期，`now_ns >= valid_until_ns` 即过期。任务/原点 epoch 与时钟域不匹配时拒绝旧动作。

PX4 保留飞控权限；策略不能直接解锁、改模式或改参数。官方推力/力矩动作不能直接当作本项目速度动作；理想赋速度对照须标明 KINEMATIC，不用于迁移验收。无效状态不得用零值伪装有效，零速度也不是所有失效情形下的实机安全保证。

私有路径与秘密放被忽略的本地配置，不新写入可提交配置或报告。复制上游代码前核对许可，记录来源 SHA、文件及修改说明；DiffPhysDrone 代码复制仍被许可澄清阻塞。

## 工作包收尾与交接

完成工作包时同步实施计划勾选项、相关设计/命令与 `docs/reports/` 证据；只有实际执行并满足条件的项目才能取消 NOT RUN 或标记通过。UNKNOWN、PROPOSED 和未通过项须保留明确状态。

交接至少记录：完成范围、验证命令和结果、源码/配置/资产等可追踪标识、未解决问题及下一工作包。报告保存可版本化摘要和外部产物 hash，不把被忽略的日志或 runs 目录作为唯一结论来源。能力或入口变化时同步更新本文件，避免接手指引漂移。


## 单环境动态评价默认升级（2026-11-03）

`scripts/run_dynamic_eval.py` 的单环境评价默认已升级为 `--geometry-policy reference_origin_v2 --contact-mode measured_hard_reset`。历史复现必须显式传 `--geometry-policy legacy --contact-mode legacy_inference`；旧 v1 raw-hash/旧 boundary/latency freeze 在新默认下会被明确拒绝，不自动回退。新 freeze schema v2 记录 hash algorithm、实际生效配置与 default/explicit 来源。只影响该单环境评价入口，不影响训练/多环境/官方 smoke。证据见 `docs/reports/map_eval/contact_envelope/DSH_DYNAMIC_DEFAULT_UPGRADE_20261103.md`。
