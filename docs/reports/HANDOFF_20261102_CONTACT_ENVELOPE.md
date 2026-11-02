# 交接记录：PhysX 接触证据恢复与包络中心修正（2026-11-02）

## 分支与提交

- 分支 `codex/bb22-contact-envelope`（自 `ee17a78`），未推送远端。
- 工作包提交：
  - `ba13c37`：接触合同 v2 / 包络 v2 / 受控接触评价入口 / 冻结契约与生成器 / 独立核验器 / cases+expected（pytest 725 passed）。
  - `be24f6b`：replay 段支持、net-force 回退、重复独立进程。
  - `c50de1f`：replay 未测得真实力时判 UNDECIDABLE（不把脚本化几何重放当作旧推断误报）。
- 预运行冻结：`configs/scenarios/contact_verification_freeze_v2.json`（code_commit `c50de1f`，真实 UTC + worktree digest；6 段 11 episode；budget 2/2/2/2/2/1；replay 引用 `outputs/map_eval/bnd_boundary_default`）。v1 冻结保留为 pilot 记录，不用于正式分母。

## 完成范围

1. **历史/当前接触差异诊断**（`docs/reports/map_eval/contact_envelope/CONTACT_DIAGNOSIS_20261102.md`）：
   - 原样运行历史入口 `run_dynamic_eval.py@92757f0` 在当前环境仍测得 0.0231 N（`tmp/historical_repro1`）→ 不是 GPU/驱动/Isaac 能力问题；
   - 地图墙路径 probe2 复现 0.042 N；
   - 障碍 spawn 的 `activate_contact_sensors` 只覆盖 root，碰撞 shape 初始无 reporter；`replicate_physics=True` 下 post-hoc shape reporter 不进入 PhysX（probe6/7=0），关闭 replication 后 probe11=0.0081 N；
   - 单进程内接触报告仅首个 episode 可靠；B 重复用独立进程后两次均 0.0276 N；
   - 零输出≠无接触：被明显推挤时 filtered/net 仍可为 0 → 必须 UNKNOWN。
2. **分层接触合同**：`src/boom_birds/evaluation/contact_contract.py`（`boom_birds.contact_evidence.v2`），event/force/impulse/geometry/attribution 分层；N 与 N·s 单位、窗口、阈值严格 >0.02 N 且不改写原始值；sensor invalid vs valid zero 可区分；net 不当 per-prim，geometry 不升级为 PhysX。
3. **受控接触评价入口**：`scripts/run_contact_verification.py`（wall/obstacle/clearance/geometry/replay；`replicate_physics=False` + obstacle shape 级 reporter + per-link filtered sensor；每步 contact_record、physics substep、prim inventory、measured body envelope、freeze run_plan 校验；B 重复 `--repeat-index` 独立进程后合并并记录 `merged_from`）。
4. **正式运行（GUI，DirectX/D3D12，无 headless）**：6 段 11 episode：
   - `contact_A_wall` 2/2 `PHYSX_CONTACT_FORCE_MEASURED`（0.1563/0.9406 N，attribution wall prim）；
   - `contact_B_obstacle` 2/2 `CONTACT_FORCE_MEASURED_UNATTRIBUTED`（net 0.0276 N）；
   - `contact_C_clearance` 2/2 `NO_CONTACT`（sensor 有效零；球重叠 −0.078 m）；
   - `contact_D_geometry` 2/2 `GEOMETRY_OVERLAP_ONLY`（overlap 0.022 m；无 event/force）；
   - `replay_contact_inferred` 2 例 UNDECIDABLE（旧 CONTACT_INFERRED；几何重放 overlap 0.122/0.119，无实时力；旧标签保留）；
   - `replay_no_contact` 1 例 CONSISTENT（旧 NO_CONTACT）。
5. **包络中心修正**：half=`[0.0545422337,0.0382082667,0.0135880403]` m，offset=`[5.90e-05,2.42e-08,0.0148685]` m；`r_origin=0.0724634 m`，旧 `r_legacy=0.0679659 m`，delta=0.0044975 m。碰撞几何仅 body；桨叶无 CollisionAPI；coverage/limitations 与 validator 已加；`analyze_envelope_correction.json` 对 18 个旧边界 episode 用 r_origin 重算（阈值处间隙 1.1→0.727537 m、1.38→1.007537 m），旧报告/旧分析保留。
6. **独立核验 PASS**：`scripts/verify_contact_verification_runs.py` 对 6 段 29/29 checks（data_integrity 7、contact_contract 9、envelope_geometry 4、scenario_expectation 5、performance_boundary 4），failures/deviations/missing=0；JSON `docs/reports/map_eval/contact_envelope/verify_contact_verification.json`。
7. **证据**：`docs/reports/map_eval/contact_envelope/`（报告、诊断、evidence/{freeze v2+cases+expected+pilot freeze、runs 原始 summary/episodes/manifest/steps hash、probes、hashes.json}、screenshots/gui_wall_contact.png、gui_logs.txt）。

## 验证命令

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -m pytest -q                         # 725 passed
& $py scripts/planning/audit_documents.py  # PASS
& $py scripts/analyze_envelope_correction.py --output docs/reports/map_eval/contact_envelope/analyze_envelope_correction.json
& $py scripts/verify_contact_verification_runs.py --freeze configs/scenarios/contact_verification_freeze_v2.json --run contact_A_wall=outputs/map_eval/contact_A_wall --run contact_B_obstacle=outputs/map_eval/contact_B_obstacle --run contact_C_clearance=outputs/map_eval/contact_C_clearance --run contact_D_geometry=outputs/map_eval/contact_D_geometry --run replay_contact_inferred=outputs/map_eval/replay_contact_inferred --run replay_no_contact=outputs/map_eval/replay_no_contact --expected configs/scenarios/contact_verification_expected_v1.json --repo-root . --output docs/reports/map_eval/contact_envelope/verify_contact_verification.json
```

## 限制/未完成

- 障碍接触只有 net force（UNATTRIBUTED），无 per-prim filtered 归因；未取得可靠 impulse（`impulse.available=false`）。
- 单进程接触报告仅首个 episode 可靠；B 用独立进程规避并在 manifest 记录，但不能声称任意多 episode 同进程可靠。
- 旧案例 2 个 CONTACT_INFERRED 重放为 UNDECIDABLE（脚本化接触几何重放，非闭环）；不改写未复核 episode。
- 包络：AABB 单关节状态、root AABB、桨叶无碰撞几何、非全姿态网格扫掠；未验证视觉/碰撞 mesh 差异。
- 无真实感知/PX4/板端/SITL/HIL/实机；不提升 Gate；规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK。
- 用户/其他工作包未提交文件保持原样，未纳入本包提交。

## 下一工作包建议

1. 在 env 创建前配置障碍 shape 级 reporter 或自定义 spawn，争取 per-prim filtered 归因与 impulse。
2. 用独立进程/独立 env 重放历史边界 episode 的闭环轨迹（非脚本化几何重放），把 2 个 CONTACT_INFERRED 的 UNDECIDABLE 推进到一致/误报/漏报。
3. 把 measured envelope（含 center offset/coverage）接入 clearance/stop_requirement 生产路径，重跑受影响的正式专项并保留旧 hash。
4. 真实 PX4 Offboard-loss/TTL 语义与执行器延迟（需外部固件资料）。
