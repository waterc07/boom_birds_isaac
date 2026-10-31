# 评价边界修复与干净基线报告（2026-10-31）

> **状态：** DONE（评价链审计与干净基线；非 Gate 放行）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §8.6、§10.4、§17、§20.2、§20.11
> **证据域：** 源码审计 + 单元测试 + 仿真模型（前台可视 GUI）
> **最后核对：** 2026-10-31

## 结论

- 全入口清单与历史污染审计完成：layered final_run2/final_run3、C 类 legacy 复现为**已确认污染**；历史 velocity/reach 逐 step 记录已检查未发现出生点突变（但旧记录未保存计数/标志，只能算“未发现证据”）；compare 的 tuning/final/faults 只有 episode 级记录，**数据不足，无法判定**，其旧数值统一标为待复核。
- 统一评价边界合同落地：`EpisodeBoundary` 清零随机化计数、记录 reset 快照、逐步校验计数与 terminated/truncated；velocity/reach/compare 全部接入；终止分类使用步前物理状态，绝不使用 auto-reset 后状态；截断/未声明 reset 记 INVALID 并保留原因。
- 干净基线全部以前台可视 GUI 运行（无 --headless）：
  - 官方 smoke：GUI 100 步 PASS（历史记录，未记录 commit/gui_mode 字段；本轮重跑尝试异常，见“失败与重试”）。
  - velocity：PASS（11/11 检查），边界字段干净；方向/组合/停止/过期/reset/KINEMATIC 结果与历史一致。
  - reach：6/6 SUCCESS，状态 INCOMPLETE（smoke，不可当泛化统计）。
  - compare：30 场景 × 2 方法 = 60 episode；比例法 30/30、制动法 30/30；比例法更快（配对均值 +0.118 s 为制动法更慢），排序与历史一致；干净数值替代旧数值。
  - 专项故障：16 episode 全部按预期分类；PhysX 接触 4/4、collision_flag 仅合同路径、timeout 4/4、非法观测 4/4。
  - layered：本轮未改该路径，沿用 final_run4（125 valid，success 100、B 碰撞 25）并用独立核验复核。
- 所有失败/重试目录保留；旧文件与 hash 未覆盖。

## 统一边界合同

| 规则 | 实现 |
| --- | --- |
| 每个 episode 起始 | `EpisodeBoundary.start(seed)`：env.reset + 清零 episode_length_buf/reset_terminated/reset_time_outs |
| 终止/截断主信号 | env.step 返回的 terminated/truncated；同时记录计数与 reset 快照 |
| 静默 reset 检测 | 无 terminated/truncated 时计数不等于 expected → INVALID ENV_UNEXPECTED_RESET；velocity 直接中止并保留 error 文件 |
| 终止状态 | 禁止使用 auto-reset 后状态；用步前物理状态分类 COLLISION / OUT_OF_BOUNDS；可预期任务超时为 TIMEOUT |
| 基础设施错误 | 环境截断/未声明 reset 单列 INVALID 且记录原因，不拼轨迹，不隐藏控制失败 |
| reset 清理 | executor.reset、观测接口新实例、外力注入 begin、故障注入状态、场景实体 reset（各入口既有逻辑） |
| manifest | code_commit、working_tree、GUI 模式、配置/场景 hash、产物 hash；每次运行独立目录 |

## 历史证据适用性审计

| 运行 | 状态 | 证据/限制 |
| --- | --- | --- |
| layered final_run2 | 已确认污染 | 8 个 episode 出生点突变（C/D/E），详见 HISTORICAL_AUDIT.json |
| layered final_run3 | 已确认污染 | 9 个 episode 出生点突变（含 C-021） |
| layered final_run4 | 未发现证据（clean） | 125 场景 no_silent_auto_reset；沿用 |
| velocity_chain/full | 未发现证据 | 旧 CSV 列表列未引用，使用括号感知解析；未保存计数/标志，局限见审计 |
| reach run1/run2 | 未发现证据 | 同上；6/6 成功与干净重跑一致 |
| compare tuning_run1/2 | 数据不足 | 仅 episode 级记录，无法判定 reset；调参依据标为待重验 |
| compare final_run1 | 数据不足 | 无逐 step；旧数值被 clean final_run1 替代 |
| compare faults_run2/4 | 数据不足 | 无逐 step；分类结果与 clean 重跑一致 |
| c_diagnosis legacy | 已确认污染 | 故意复现旧缺陷，3 次 INVALID ENV_TRUNCATED@31 |

“未发现证据”不等于“已证明没有”：旧运行没有记录 episode 计数或 terminated/truncated 字段，检测只能依赖出生位姿/零速度突变这一辅助信号。

## 干净基线结果（前台 GUI）

| 运行 | 关键结果 | 独立核验 |
| --- | --- | --- |
| official smoke | 100 步 PASS；窗口创建日志存在；结果见 evidence/smoke | 结果 status PASS；缺 commit/gui_mode 字段（历史记录限制） |
| velocity | PASS；11 项检查全 true；边界字段全部干净 | verify_baseline_runs PASS |
| reach | 6/6 SUCCESS；status INCOMPLETE（smoke） | verify_baseline_runs PASS |
| compare | 60 episode；比例 30/30，制动 30/30；配对 30 对；比例更快（均值 3.285 vs 3.403 s；Δ=+0.118 s） | verify_guidance_runs PASS（18 项） |
| faults | 16 episode 全部预期分类；接触 4/4 PhysX | verify_guidance_runs PASS（全部检查） |
| layered | 125 valid；success 100、collision 25、其余 0 | verify_layered_runs PASS（25 项） |
## 旧结果与干净基线差异（明确替代关系）

| 指标 | 旧（历史） | 干净重跑 | 处理 |
| --- | --- | --- | --- |
| velocity 各场景位移 | 与干净结果逐项一致（如 forward 0.546 m、left 0.437 m、up 0.202 m、yaw90 0.546 m） | 相同 | 旧结论可用；干净运行作为新证据 |
| reach | run1/run2 均 6/6 SUCCESS | 6/6 SUCCESS | 旧 smoke 结论可用；干净运行替代 |
| compare 比例法 | 30/30，均值 3.47833 s，末距 0.026572 m | 30/30，均值 3.28500 s，末距 0.025865 m | 旧数值被替代 |
| compare 制动法 | 30/30，均值 3.59667 s，末距 0.120785 m | 30/30，均值 3.40333 s，末距 0.118288 m | 旧数值被替代 |
| compare 配对时间差 | +0.118333 s（制动更慢），时间胜 30:0 | +0.118333 s（制动更慢），时间胜 30:0 | 方向与结论不变，绝对时间更新 |
| compare 末距差 | +0.094213 m | +0.092424 m | 数值更新，方向不变 |
| faults | 4 类各 4，全部预期分类 | 相同 | 旧结论可用；干净运行替代 |
| layered | final_run3：C 24/25，总 99/125 | final_run4：C 25/25，总 100/125 | 旧 C 越界被 C 诊断修复替代；final_run4 沿用 |
| tuning | 无逐 step，无法判定 | 未重跑（原候选 A 配置未保留） | 参数选择依据标为**待重验**；当前比较仍使用冻结候选 B，未在最终集调参 |

**调参数据声明：** 历史 tuning_run1 使用的配置 hash 为 `17e8058f…`，与当前/最终配置 `6d1c23a2…` 不同；原候选 A 配置文件未保留，无法在同一源码上重跑原调参集。故原候选选择依据待重验，本轮不声称调参结论已被复核；最终比较仍使用既有冻结参数，未因新结果改动参数或挑选场景。

## GUI 运行方式与证据

- 本轮新增的 Isaac 运行（官方 smoke 历史记录、velocity、reach、compare、faults）全部未使用 `--headless`， AppLauncher 默认创建窗口；日志包含 `Creating window for environment.`。
- 新增 manifest 均记录 `gui_mode: true`、实际 commit 与 working tree；历史 headless 记录保留不改写。
- layered 沿用历史 final_run4（headless），因为该路径本轮未改且已有独立边界修复与核验；按目标第 4 条复用，不重新启动 125 场景。

## 失败与重试（全部保留）

| 目录/日志 | 现象 | 处理 |
| --- | --- | --- |
| outputs/eval_audit/velocity_clean | manifest 写失败 NameError（MANIFEST_SCHEMA_ID） | 保留 error；改代码后重跑 |
| outputs/eval_audit/velocity_clean2 | manifest 缺 started_at | 保留 error；补字段后重跑 clean3 |
| outputs/eval_audit/reach_clean/run1 | 重跑时 manifest 已存在，拒绝覆盖 | 保留 run1；新跑到 run2 |
| logs/eval_audit_smoke_gui2.log / smoke_gui3 尝试 | 启动后无 PASS 标记、结果未写出；原因未确认 | 保留日志；使用先前 GUI 100 步 PASS 记录；列入剩余问题 |
| logs/eval_audit_velocity.log（首次）与 velocity2 | 早期错误 | 保留；正式证据使用 clean3 |

## 独立核验

- verify_guidance_runs.py：compare 18 项检查 PASS；faults 全项 PASS；新增边界字段/无截断/计数连续/时长=步数×0.05/配对场景集一致。
- verify_baseline_runs.py：velocity 与 reach 全部检查 PASS；含边界字段、计数连续、时间步长、终止分类。
- verify_layered_runs.py：final_run4 25 项 PASS；no_silent_auto_reset。
- 所有核验从原始 episodes/CSV/manifest 重算，不依赖 summary 标签。

## 比赛地图资产登记（未集成）

- 路径：`E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim\`
- 入口：`rmuc2027_preview.usda`；场地：`assets/rmuc2027_terrain.usdc`
- 状态：仅登记为后续独立工作包的集成资产；本轮未接入评价或训练，不宣称已使用地图。

## 命令（GUI；无 --headless）

`powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 干净 velocity（clean3）
& $py -u scripts/run_sim_baseline.py --task velocity_step --config configs/vehicles/sim_reference.yaml --scenarios all --code-commit bc169eab335304b0717f99b85568f53ce1423d28 --working-tree "clean at bc169ea except untracked evidence" --device cuda:0 --clone-in-usd --output outputs/eval_audit/velocity_clean3/full.json --csv outputs/eval_audit/velocity_clean3/full.csv
# 干净 reach（run2）
& $py -u scripts/run_sim_baseline.py --task reach --config configs/vehicles/sim_reference.yaml --episodes 6 --timeout-s 20 --goal 1.5,1.0,0.75 --code-commit adefaded8805af80f12e499533cf8932132cb97c --working-tree "clean at adefade except untracked evidence" --device cuda:0 --clone-in-usd --output outputs/eval_audit/reach_clean/run2/reach_summary.json --csv outputs/eval_audit/reach_clean/run2/reach.csv
# 干净 compare + faults（commit 34f9717）
& $py -u scripts/run_sim_baseline.py --task compare --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/final_20261031.json --methods proportional,braking --run-kind final --timeout-s 20 --freeze configs/scenarios/freeze_20261031.json --code-commit 34f9717d2523c810361419daccf5e314e15a0b02 --working-tree "clean at 34f9717 except untracked evidence" --device cuda:0 --clone-in-usd --output outputs/eval_audit/compare_clean/final_run1
& $py -u scripts/run_sim_baseline.py --task compare --config configs/vehicles/sim_reference.yaml --scenario-manifest configs/scenarios/final_20261031.json --methods proportional,braking --run-kind fault --fault collision_flag,collision_contact,timeout,invalid_observation --fault-step 10 --fault-timeout-s 1.5 --scenario-limit 2 --code-commit 34f9717d2523c810361419daccf5e314e15a0b02 --working-tree "clean at 34f9717 except untracked evidence" --device cuda:0 --clone-in-usd --output outputs/eval_audit/faults_clean/run1
# 官方 smoke（历史 GUI 100 步记录）
& $py -u scripts/check_official_quadcopter.py --steps 100 --output outputs/eval_audit/official_smoke_gui/result.json --device cuda:0
# 核验
& $py scripts/verify_baseline_runs.py --velocity-json outputs/eval_audit/velocity_clean3/full.json --velocity-csv outputs/eval_audit/velocity_clean3/full.csv --reach-csv outputs/eval_audit/reach_clean/run2/reach.csv
& $py scripts/verify_guidance_runs.py --run-dir outputs/eval_audit/compare_clean/final_run1
& $py scripts/verify_guidance_runs.py --run-dir outputs/eval_audit/faults_clean/run1
& $py scripts/verify_layered_runs.py --run-dir outputs/layered_eval/final_run4 --freeze configs/scenarios/layered_freeze_20261031.json
`

## 证据与 hash

| 产物 | SHA-256 |
| --- | --- |
| velocity full.json | `31993b0e0f2ef2c6455397abd28226c0945ff223f826a20bb50b6cbf9e7271a0` |
| velocity full.csv | `71c3abc53ee4bbf688d2bcde59ca022dc6d25056e626b4315cf58da20f6eb92a` |
| velocity manifest | `0e43bebd492f0ad3ce61e62a1c021e70a8d9f99d0d7d54d6941858a2c1197a6f` |
| reach summary | `40a2b14a4db23747638225ec2e799d05777fd0ca3d68f79503b9d78fb59119b6` |
| reach csv | `4b8a685e0ed5fa0df689aacb7226271c1f016c192a04d738b30aa6841094c711` |
| reach manifest | `ace153813875450f455b3048395ea018b40f8f94e0a192ba02448e27b14e416c` |
| compare summary | `aa4c938dd3c5966cc92164c979b18de4ab37db4ef6e289754c74a373ebbe7b4b` |
| compare episodes | `b042ba68a3f41172f2b7e32470972326ae9a8300bb29252415b53991173a9a23` |
| compare manifest | `9b3cbab646635341aa7176e89d450510dec2df162161a1b5ebb17b3803287ba0` |
| faults summary | `1af2deb2473177fd7c008147016607e7b1bb5ca6683d89a606867e4b54c6de28` |
| faults episodes | `19a1fd98a3375918a33ab0b0725c3bc9d130bb0e244ed3a481302104d77834d4` |
| faults manifest | `6771094714515225102bc90f5073504ac8d6392149bddeb4041a4991ba4be981` |
| smoke result | `f954bc5726ea123303db3dd59ef9aabbd59fe7d8b782c688a1e321a8bf0eb9e1` |
| layered final_run4 steps | `e4e00d641a0015b4a2927dec67d0a0c1fd2a2666c40d4dbb85f520c5ceb15b66` |

## 剩余限制与下一工作包

1. 官方 smoke 的后续 GUI 重跑在启动后异常无 PASS/结果（日志保留），原因未确认；先前 100 步 GUI PASS 记录仍有效但缺 commit/gui_mode 字段；下一工作包应先定位该 smoke 异常（不改用 headless）。
2. 调参数据只有 episode 级记录且候选 A 配置缺失，原参数选择依据待重验；需要在保留调参集的前提下重建候选配置并重跑，再冻结。
3. compare 历史记录无逐 step，无法证明无 reset；旧数值虽与干净结果方向一致，但以 clean 结果为准。
4. layered 沿用历史 final_run4（headless）；本轮未改该路径，隔离论证见 C 诊断报告；若后续修改共享边界层，需 clean 重跑 125。
5. 比赛地图仅登记，未集成；PPO/板端/SITL/HIL/实机均未运行；规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK；不提升任何 Gate。
