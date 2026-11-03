# dsh_contact_lifecycle：生产包络迁移接口与影响清单（2026-11-02）

> **状态：** PLAN（只读核对，未修改生产接触读取/包络代码，未启动 Isaac）
> **来源：** `docs/reports/map_eval/contact_envelope/CONTACT_REVIEW_CODE_AUDIT_20261102.md` §3、`docs/design/CLEARANCE_GEOMETRY_CONTRACT.md`、`src/boom_birds/sim/body_envelope.py`、`src/boom_birds/evaluation/clearance.py`、`src/boom_birds/evaluation/stop_requirement.py`、`scripts/run_dynamic_eval.py`
> **最后核对：** 2026-11-02

## 1. 现状（生产入口仍是旧包络口径）

`scripts/run_dynamic_eval.py`：

- `measure_body_envelope()`（约 L378–397）只对 `/World/envs/env_0/Robot` 做 `UsdGeom.BBoxCache(default+render)`，取世界 AABB 的 `size/2` 作为 `half_extents_m`；**不记录 AABB 中心偏移**、不区分视觉/碰撞几何、不记录子体覆盖与关节状态。
- L570–579：`robot_radius_conservative = clearance_mod.box_conservative_sphere_radius(half_extents)`；`robot_envelope_payload` 只有 `half_extents_m / measured_prim / source`。
- `clearance.build_robot_envelope()`（L173–187）据 `half_extents` 计算 `radius_m = sqrt(sum(half²))`，`attitude_scope='any_rigid_rotation_about_center'`、`measured_prim`、`limitation` 固定为旧口径。
- `clearance.build_clearance_record` 只用 `robot_envelope_record['radius_m']` 参与 `envelope_gap_sphere_m / path_clearance_gap_sphere_m`（L340–345）。
- `stop_requirement.evaluate_stop_requirement` 的 `robot_radius_m` 是调用方参数（L249），生产入口传入旧 `box_conservative_sphere_radius`（L705–706 同口径）参与 `envelope_sum_m`。
- manifest `envelope_policy`（L1795–1800）固定写 `robot_radius_rule='sqrt(sum(aabb_half_extents^2))'`、`attitude_scope='any_rigid_rotation_about_center'`。
- 实测对比：旧 `r_legacy=||half||=0.0679659 m`；新 `r_origin=|| |offset|+half ||=0.0724634 m`（offset≈[5.9e-5, 2.4e-8, 0.0148685]），旧口径在非零偏移时**低估 0.0044975 m**（见 `analyze_envelope_correction.json`，18 个旧边界 episode 重算）。

## 2. 目标接口（body_envelope.v2 迁移）

| 项 | 旧 | 新 |
| --- | --- | --- |
| 测量对象 | robot root world AABB | 碰撞几何/视觉几何分别枚举（`EnvelopeCoverage`），root 系 half + center offset |
| 球心 | AABB 中心（隐含） | 机器人参考原点（`sphere_about_origin`） |
| 半径规则 | `||half||` | `|| |center_offset| + half ||`（任意绕原点刚体旋转保守） |
| 姿态范围 | “about center” | `any_rigid_rotation_about_reference_origin` + 单关节状态界 |
| 覆盖证据 | 无 | `coverage{source,prim_paths,collision/visual,sub_bodies,limitations}` |
| 记录 | manifest `half_extents_m` | manifest `body_envelope.v2` 完整记录 + episode `envelope_sphere_about_origin_m` |
| 语义版本 | 无 envelope policy 版本 | `envelope_policy='sphere_about_origin.v2'`；clearance/stop 记录引用该 policy 版本 |

## 3. 接口改动清单（方案，不在本轮实施）

### 3.1 `src/boom_birds/sim/body_envelope.py`（已存在，供生产调用）

- 生产直接调用 `body_envelope_from_world_aabb(...)`：输入 world AABB 的 **8 个世界角点**或 world half/center + root world pose，先逆变换到 root 系再求 half/offset；**禁止**“只旋转中心、保留世界 half”的做法。
- 输出 `body_envelope_record(...)`；生产只使用 `sphere_about_origin.radius_m`，`sphere_about_aabb_center` 仅用于旧口径对比，不得冒充生产半径。
- 若碰撞 prim 与视觉 prim 可分别测量：`coverage.source='collision_geometry'|'visual_mesh'|'mixed'`；当前 probed 数据表明机器人碰撞几何只有 body 碰撞体、螺旋桨无 CollisionAPI，必须写 limitations，不得声称全姿态/桨叶覆盖。

### 3.2 `src/boom_birds/evaluation/clearance.py`

- `build_robot_envelope(half_extents_m=None, measured_prim=None, source=None)` 扩展（新版本）：
  - 新增 `center_offset_m`、`radius_m`（显式传入或由 body_envelope 计算）、`envelope_policy_version`、`coverage`、`attitude_scope='any_rigid_rotation_about_reference_origin'`、`limitations`；
  - 新 schema/算法版本（建议 `boom_birds.clearance.v2` 或 `1.1.0` + `envelope_policy` 字段），旧 `boom_birds.clearance.v1` 记录保持可解析；
  - `_resolve_robot_envelope(payload)` 接受新 payload（显式 radius + offset + policy），拒绝“只有 half 却声称 v2”。
- `build_clearance_record` 的 metrics 公式不变（radius 输入语义变化），但 applicability/notes 必须记录 envelope policy 与“非网格扫掠”。

### 3.3 `src/boom_birds/evaluation/stop_requirement.py`

- 输入多一个显式 `robot_radius_source`/`robot_envelope_policy`（或 `robot_envelope` dict），记录 `envelope_sum_m` 来源；schema 升版（建议 `boom_birds.stop_requirement.v2`），旧 v1 保留。
- 生产入口传 `sphere_about_origin.radius_m`；`brake_final4` 模型不变。

### 3.4 `scripts/run_dynamic_eval.py`（生产入口）

- `measure_body_envelope()` 替换为 collision/visual 枚举 + 8 角点逆变换 + `body_envelope_record`；默认 coverage 基于实际测量 prim，不按意图填。
- `robot_envelope_payload` 传显式 radius/offset/policy；`metrics.conservative_envelope` 记录 `sphere_about_origin` 与 legacy 对比（`legacy_radius_m/delta_m`，不得静默替换）。
- manifest `envelope_policy` 写 v2 字段（rule、attitude scope、coverage、limitations、radius、offset、legacy delta）；`body_envelope` 写完整 v2 记录。
- freeze `run_plan` 增加 `envelope_policy_version`、`body_envelope_sha256`（或 radius/offset）字段；旧 freeze v1/v2 不修改，新运行用新 freeze 版本。
- 新运行独立目录；旧 `outputs/map_eval/bnd_boundary_default` 等保留，不得重写；受影响专项（clearance/stop 引用半径的边界/fault/latency 回归）在新 freeze 下重跑，报告里旧/新对照。

### 3.5 独立核验与冻结

- `scripts/verify_clearance_boundary_runs.py` 等检查器：新增 envelope v2 检查（r_origin 重算、coverage/limitations、legacy delta 显式、manifest policy 一致）；旧 v1 冻结仍按 v1 规则核验，不覆盖旧 PASS。
- 分析与报告：`analyze_envelope_correction.json`（已有）升级为新跑次实测 envelope 输入；旧报告/旧 hash 保留；新报告标“半径口径变更，旧数值按旧口径”。

### 3.6 测试（TDD，先失败）

- `tests/evaluation/test_clearance.py`：新 `build_robot_envelope` 接受 offset/radius/policy；拒绝 v2 标签但缺 offset/radius；metrics 使用 r_origin。
- `tests/evaluation/test_stop_requirement.py`：新 schema/半径来源；envelope_sum 使用 r_origin。
- 生产测量单测（可用合成 world AABB + root pose，无需 Isaac）：8 角点逆变换结果、offset 非零、姿态范围、coverage/limitations 校验。
- 端到端：新 freeze + 小 episode GUI 跑，核验器检查 manifest/episode/clearance/stop 四处半径一致。

## 4. 影响清单

| 区域 | 影响 |
| --- | --- |
| 数值 | clearance `envelope_gap_sphere_m`、`path_clearance_gap_sphere_m` 在相同 center/clearance 下减少 0.0044975 m；stop `envelope_sum_m`/required/margin 同量变化（模型支持区间内）；阈值处间隙 1.1→0.727537 m、1.38→1.007537 m |
| 数据 | 所有新运行 manifest/episode/clearance 记录字段变化；旧运行保留旧口径，不可混用比较 |
| 冻结 | 新 freeze 版本（新字段/新 hash）；旧 v1/v2 freeze 与旧 PASS 不重算、不覆盖 |
| 核验 | 核验器新版本/profiles；旧核验器仍可核验旧冻结；新核验不得把 legacy 数据判成 v2 |
| 复现 | 新运行必须重新预冻结、独立目录、GUI；旧边界报告数字标 legacy |
| 契约 | `CLEARANCE_GEOMETRY_CONTRACT.md` 升版为 envelope v2；docs/design 合同引用 |
| 不变量 | 算法（预测路径 clearance 定义）不变；阈值/停止需求模型不变；只改半径输入语义与记录 |

## 5. 迁移顺序与闸门

1. 先完成接触读取修复（Codex）与 lifecycle 定论；本文件不阻塞该修复。
2. 实现 `clearance`/`stop_requirement` 新版本 + 失败测试；旧 API 保留（显式选择 legacy/v2，不做隐式默认切换）。
3. 生产 runner 测量/记录改造；合成/小规模 GUI 验证 8 角点逆变换与 coverage。
4. 新 freeze（新版本字段）→ 受影响专项重跑（至少 1 个 clearance 边界段 + 1 个 brake/stop 段）→ 独立核验。
5. 报告新/旧对照（含旧 hash），更新合同与交接；不提升 Gate。

## 6. 风险与未决

- 测量对象：root AABB 可能包含视觉子几何；若直接当碰撞几何会高估/低估覆盖率。迁移必须按 prim 的 CollisionAPI 实际枚举，并在 coverage 标 mixed/limitations。
- AABB 中心偏移对球心/半径影响已量化（+0.0044975 m），但完整外廓（全姿态、关节运动、桨叶）仍不是网格扫掠证明。
- 视觉 mesh 与碰撞 mesh 差异未测；如需严格保守，应分别记录两类 AABB 并取外包，或明确覆盖声明。
- 旧报告/旧分析不得改写；新报告必须显式写“旧口径 legacy / 新口径 v2”。
- 任何生产代码改动都需新预冻结与独立核验；本轮**不修改**生产接触读取或包络代码，仅输出本方案与影响清单。
