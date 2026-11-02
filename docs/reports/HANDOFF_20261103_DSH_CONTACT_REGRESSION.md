# 交接：DSH 接触结束新鲜度 + 20 动态场景回归（2026-11-03）

## 状态

- **接触结束专项：PASS（受控诊断）。** 同 episode 3 个循环：分离→接触→持续→自然分离→重接触；自然分离后 3/3 循环测力归零；显式 robot teleport 对照在 2/3 循环仍返回陈旧力（单独目录）。
- **20 动态场景预冻结回归：PASS（新模式 opt-in）。** 20/20 SUPERVISOR、无 INVALID、业务/原因/时长与旧 v2 supervisor 完全一致；物理结果全 UNKNOWN，未伪标无接触/推断接触。
- **独立核验：** 20 场景 27 checks PASS；迁移 13,149 行 PASS；原始向量 13,149 行 0 errors；`pytest -q` 772 passed；文档审计 PASS。
- **默认模式：不升级。** 20 集没有阳性实测接触；原生 event/impulse、负接触覆盖、实机噪声、多环境 reset 未解决；保留 legacy 默认，新模式仅显式 opt-in 评价。
- **Goal 状态：** 本工作包内任务已实现并验证；仍有下文“未解决问题”，不将整个接触链/Gate 标为完成。未提升任何 Gate，未运行 PPO/真实感知/PX4 Sender/板端/SITL/HIL/实机。
- **Git：** 未推送远端；不执行 `git add .`，只对本工作包已审查文件做中文提交（见 §7）。Codex/用户未提交修改保留。
- **范围：** 单环境、前台 GUI/DirectX/D3D12、串行独立目录；未改驱动/全局渲染；不扩大正式比赛样本。

## 1. 本轮产物

| 类别 | 路径 |
| --- | --- |
| 接触结束探针 | `scripts/contact_end_freshness_probe.py` |
| 接触结束独立核验 | `scripts/verify_contact_end_freshness.py` |
| 20 场景独立核验 | `scripts/verify_dynamic_regression20.py` |
| 原始向量核验扩展 | `scripts/verify_contact_raw_samples.py`（新增生产嵌套 measurement 路径） |
| 接触结束报告 | `docs/reports/map_eval/contact_envelope/DSH_CONTACT_END_FRESHNESS_20261102.md` |
| 20 场景报告 | `docs/reports/map_eval/contact_envelope/DSH_DYNAMIC_REGRESSION20_20261102.md` |
| 预期参考 | `configs/scenarios/contact_production_migration_20_expected_v1.json` |
| 正式预冻结 v2 | `configs/scenarios/contact_production_migration_20_v2.json` |
| pilot 预冻结 v1 | `configs/scenarios/contact_production_migration_20_v1.json`（pilot 停止，不作为验收） |
| 20 集运行 | `outputs/map_eval/production_contact_migration/regression20`（steps 为 gitignored 原始证据） |
| 接触结束运行 | `outputs/dsh_contact_end/natural_obstacle_motion_final`、`robot_teleport_control` |
| 核验 JSON | `dsh_contact_end_verify_20261102.json`、`dsh_dynamic_regression20_verify_20261102.json`、`..._migration_verify_...json`、`..._raw_audit_...json`（均在 `docs/reports/map_eval/contact_envelope/`） |
| 版本化证据/hash | `docs/reports/map_eval/contact_envelope/evidence_20261103/`（含 `hashes.json`） |
| GUI 证据 | 接触结束持续接触截图、20 集成功集截图；均有效非空 PNG；完整日志另存 |

## 2. 接触结束结果（详见专项报告）

- 自然模式：3/3 循环接触、持续、自然分离、重接触；自然分离后几何间距 >0.1 m 时最大测力 **0.0 N**（每循环 6 个零样本）；重接触测力约 0.0122–0.0127 N（低于 0.02 N，仍按真实接触保留，不判无接触）。
- teleport 对照：单独目录，2/3 循环在几何间距约 2.05 m 仍返回陈旧 filtered 力 0.0122–0.0128 N；保留原始数据、不填零、未中途 hard reset。
- 机器人站定保持仅用于受控几何；自然分离由运动学障碍连续离开产生，不是机器人传送。原生 callback 未建立，零事件不能证明无接触。
- 独立核验 PASS（原始向量重算、步号单调、generation 1、握手成功、无中途 reset）。

## 3. 20 场景回归结果（详见报告）

- 20/20 SUPERVISOR；generation 1–20，20 次分离零握手成功；RUN 内无硬 reset。
- 业务：SUCCESS 8（A/B）/ ABORT 12（C/D `MAX_WAIT_EXCEEDED` 8、E `OBSERVATION_STALE` 4）；COLLISION/TIMEOUT/OUT_OF_BOUNDS/INVALID = 0。
- 物理：20 UNKNOWN；`contact_max_force_n=0`；没有 NO_CONTACT/CONTACT_INFERRED/CONTACT_MEASURED 伪标签；旧 v2 supervisor 同为零接触。
- 与旧 v2 supervisor：逐场景 outcome/reason 差异 0；duration/wait 最大差 0；未删场景/未改阈值。
- 几何：真实 CollisionAPI 网格 + root-frame 偏移；body radius 0.0722841624 m；障碍 `[0.4,0.4,0.6]` 半对角线 0.4123105626 m；clearance v2，12,989 个有观测行核对，160 个 observation-dropout 行保持 UNKNOWN/不适用；停止阈值 1.1 未改。
- 独立核验：20 场景 PASS（27 checks）、迁移 PASS（13,149 行）、raw PASS（13,149 行，0 errors）；GUI 8 张成功集截图有效。
- **未解决：** 20 集没有实测接触阳性；两个旧 CONTACT_INFERRED 历史案例不在本矩阵、未重跑，保持“物理真值未确认”；本轮未跑 FOLLOW_ONLY 配对（无受影响场景差异）。

## 4. 失败/重试记录

1. 接触结束探针首版机器人漂移/接触未建立；改为受控站定保持并加深接触偏移后，3 循环完成。原始失败运行 `outputs/dsh_contact_end/natural_obstacle_motion_v2/v3` 保留。
2. 20 集 pilot 使用未含预期参考的 v1 冻结；发现后停止，保留 `regression20_pilot_v1`，正式结果只在 expected+v2 冻结后运行。
3. 核验工具失败与修正：freeze config 逻辑键当路径、局部变量 shadowing、observation-dropout 非适用 clearance 口径、raw 核验生产嵌套行扩展；均为核验口径修正，不是运行数据/生产合同放宽；完整失败 JSON/日志保留。
4. 未发现需要修改生产接触行为的自然分离陈旧证据；显式 teleport 陈旧力保留为已知限制，未用清缓存/填零包装修复。

## 5. 独立核验与测试

- `scripts/verify_dynamic_regression20.py`：PASS，27 checks，0 differences，0 expected failures。
- `scripts/verify_dynamic_migration.py`：PASS，13,149 rows，20 episodes。
- `scripts/verify_contact_raw_samples.py`：PASS，13,149 rows，0 errors；旧 final3 复核 PASS 3,050 rows。
- `pytest -q`：**772 passed**。
- `python scripts/planning/audit_documents.py`：PASS；`planning_audit.json` 运行前后 hash 不变。
- 未将“核验工具 PASS”等同于所有物理条件满足；核验范围与生产行为限制见报告。

## 6. 精确命令

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
# 接触结束（自然，GUI）
& $py -u scripts/contact_end_freshness_probe.py --cycles 3 --separation-mode obstacle_motion --screenshots --output outputs/dsh_contact_end/natural_obstacle_motion_final --kit_args=--/app/vulkan=false --device cuda:0
# 传送对照（单独目录，GUI）
& $py -u scripts/contact_end_freshness_probe.py --cycles 3 --separation-mode robot_teleport --output outputs/dsh_contact_end/robot_teleport_control --kit_args=--/app/vulkan=false --device cuda:0
& $py scripts/verify_contact_end_freshness.py --natural outputs/dsh_contact_end/natural_obstacle_motion_final --teleport-control outputs/dsh_contact_end/robot_teleport_control --output docs/reports/map_eval/contact_envelope/dsh_contact_end_verify_20261102.json
# 20 集预冻结运行（正式；先冻结 expected/v2）
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/map_dynamic_cases_v1.json --methods supervisor --execution-path v2 --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --screenshots --device cuda:0 --gpu-driver 'NVIDIA 581.80 (observed)' --kit_args=--/app/vulkan=false --freeze configs/scenarios/contact_production_migration_20_v2.json --output outputs/map_eval/production_contact_migration/regression20
# 独立核验
& $py scripts/verify_dynamic_regression20.py --run outputs/map_eval/production_contact_migration/regression20 --freeze configs/scenarios/contact_production_migration_20_v2.json --expected configs/scenarios/contact_production_migration_20_expected_v1.json --old-run outputs/map_eval/final_v2_dynamic1 --repo-root . --output docs/reports/map_eval/contact_envelope/dsh_dynamic_regression20_verify_20261102.json
& $py scripts/verify_dynamic_migration.py --run outputs/map_eval/production_contact_migration/regression20 --freeze configs/scenarios/contact_production_migration_20_v2.json --output docs/reports/map_eval/contact_envelope/dsh_dynamic_regression20_migration_verify_20261102.json
& $py scripts/verify_contact_raw_samples.py --run outputs/map_eval/production_contact_migration/regression20 --output docs/reports/map_eval/contact_envelope/dsh_dynamic_regression20_raw_audit_20261102.json
& $py -m pytest -q
```

## 7. 版本化摘要 / Git

- 正式冻结 sha256 `049d7a6c9ede4f1d83ff29e0b7aded6bc2e65688839d50ce3360cf2c5e982411`；预期 sha256 `f3502baa535a714aeb7ad56b300d099a84ccfae94041f519e2b377308894c4b3`；20 集 `steps.jsonl` sha256 `f2b7c507…`。
- 完整 hash 清单：`docs/reports/map_eval/contact_envelope/evidence_20261103/hashes.json`。
- 旧 `contact_production_migration_v3.json`（`86335031…`）与旧 v2/final3 结果未改。
- 本轮新代码/配置/报告按文件显式加入 Git，中文提交，不推送；**不执行 `git add .`**。Codex 改动 `scripts/run_dynamic_eval.py`、`src/boom_birds/evaluation/clearance.py` 等保持未提交，不在本工作包提交范围内。冻结 v2 的源码 hash 描述的是当前工作树（含 Codex 未提交改动），不能声称这些源码已在旧 HEAD 提交中。

## 8. 未解决问题 / 下一步

1. 接触结束：原生 event/impulse、负接触覆盖、自由飞行（非站定保持）、其他障碍尺寸/速度、多环境 reset 未验证；teleport 陈旧力是已知观测，不做清缓存式“修复”。
2. 20 场景：全 UNKNOWN，需要真正进入可测接触的场景/方法补样本；FOLLOW_ONLY 配对只在出现受影响场景时做；不得删场景/改阈值制造一致。
3. 旧两个 CONTACT_INFERRED：保持物理真值未确认，不重复单例追求一致；新模式结果只能是新测量。
4. 升级默认条件：需阳性实测样本、负覆盖、原生事件、实机/多环境证据；当前仅 opt-in 评价模式。
5. Gate/PX4/规则/BOM/真实感知/SITL/HIL/实机均未被本轮提升或验证。
