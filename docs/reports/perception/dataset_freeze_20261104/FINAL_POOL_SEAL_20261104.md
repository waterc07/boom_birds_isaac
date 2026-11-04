# 地标 final 候选池冻结与封存清单（T5，2026-11-04）

> **状态：** PASS（仅 final 池清单 / hash / 分组 / 互斥校验的 QA）；模型效果 NOT RUN；A3/A8 训练准入 INCOMPLETE；板端 / 导航 / SITL / 实机 N/A
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §20.11.1（测试数据分层，禁止连续视频随机拆帧）、§20.11.3（统计结论边界）、Phase 6（输入泄漏检查报告交付）；configs/perception/landmark_training_plan_v2.json 的 A3（sealed final pool）与 A8（样本充分性）
> **证据域：** 文档 + 单元测试 + 数据格式 QA + 仿真采集产物清单（Isaac Sim 5.1 可见前台 GUI 采集产物，本 T5 未重新运行 Isaac、未训练、未安装依赖）
> **最后核对：** 2026-11-04

本报告只回答"T1 final 候选池能否作为封存 test 池冻结、清单/hash/分组是否自洽、与 dev 数据是否互斥、条件覆盖到什么程度"。封存清单 PASS 不等于模型效果、板端、导航或 A3/A8 通过。

## 0. 结论摘要

- T1 采集产物最终冻结：**297 个 front_rgb 帧（6 个 episode × 3 WARMUP + 279 accepted）**。
  - 独立复算 **accepted = 279**（不是 297；297 是含 18 个 WARMUP 的总 RGB 帧数）。逐族 111 / 76 / 23 / 28 / 38 / 3。
  - 279 个 accepted 帧 payload sha256 **全部唯一**；297 帧整体唯一 sha 285（6 个重复簇均为每 episode 前 3 帧 warmup，accepted=false）。
- **未触发抽样**：279 accepted ≤ 400，按固定规则 **N=1 全部纳入**；备用规则（超过 400 时按每族 sequence 升序取 k=ceil(total/400) 每第 k 帧）已写入清单但未执行。Lead 交接预期"原始 accepted 会超过 400"与实况不符，以本次独立复算为准；capture 报告 §1/§5 也给出 279。
- 封存清单：`configs/perception/landmark_final_pool_seal_v1.json`
  - schema `dsh.landmark_split_freeze.v1` + `pool_kind=FINAL_SEALED_TEST`，6 family → 6 group，全部 `split=test`、`sealed=true`，train/val/excluded 为空。
  - canonical sha256 `cedbbc7e1cd455f022d5f7c5f7f7925f046d9eebeb2581ca789ee25f7ce81007`；文件 sha256 `c852f0e520ffe608a1b7fc9db3e6e4c2d18aa4761a16700a4214a59e7708af02`。
- 校验证据：`docs/reports/perception/dataset_freeze_20261104/landmark_final_pool_verify_20261104.json`，**status=PASS，0 error，6 warning**（6 条均为同组 warmup 重复 sha）；逐帧 PNG 字节复算 297/297 一致。
- 与 dev freeze v2 互斥：family / group / dataset root 重合 = 0；与 dev 3002 帧（2940 唯一 sha）**跨 run 帧 sha 重合 = 0**（比 capture 只查 4 个 run/1702 帧更广）。
- 条件覆盖：6 个新族、279 accepted；距离 **1.458–8.367 m**；偏航 sweep ±24.7°、edge −40.1…−28.6°；**右缘截断 26/28 accepted 帧**；**目标不存在 41 帧**（similar_negative 38 + side_negative 3）；**HN1 verified 相似结构 = 0（缺失）**；场景结构遮挡未构造。
- `lmf_similar_negative_0` 的真实情况是"目标在相机身后 + 中央场地结构在画面内 + 15/38 accepted 帧出现 ≤3 px 绿色假线索"，**不是已验证相似结构**；不能写成 HN1 已覆盖。
- 与既有族：**0 个 waypoint 序列相同**；但起点位姿接近（`lmf_edge_0` vs `pilot_east_center` 0.30 m / yaw 差 0.60 rad；`lmf_similar_negative_0` vs `pilot_east_away` 0.54 m / 同 yaw）。这是必须向 T6 明示的邻接关系，**起点接近不等于轨迹同一**。
- **A3 = INCOMPLETE**（完整语义标签尚未生产，T6 试点标注 PENDING）；**A8 = INCOMPLETE**（无 HN1、无遮挡、仅 41 个目标缺席 accepted 帧、远距绿灯 0–1 px）。封存完整性 PASS 与 A3/A8 判定分开报告。

## 1. 输入与现场（provenance）

| 项 | 值 | 来源 |
| --- | --- | --- |
| run | `outputs/sensor_shadow/lm_final_candidate_20261104` | run manifest |
| sensor run | `outputs/sensor_shadow/lm_final_candidate_20261104_sensor`（observations.jsonl + 297 PNG） | 目录 |
| 完成状态 | `run.complete.json` status=PASS / completed=true / summary_error_file=false / finished_at 2026-11-04T18:17:54+08:00 | run.complete |
| episode | 6/6 SUCCESS（sweep/backoff/near/edge/similar_negative/side_negative），0 collision / 0 timeout / 0 invalid | run summary |
| case manifest | `configs/scenarios/landmark_final_cases_v1.json`，sha256 `43645338b71c5e446f875dc3d19874978ce67d82de7a72fff99cb735177b2aaa` | seal provenance |
| 分支 / HEAD | `feat/v2.2-simulation-perception` / `43fee3e02de57840e54297e8595924e2f213d722` | run manifest |
| GUI / 渲染 / 驱动 | gui_mode=true；DirectX/D3D12（`--/app/vulkan=false`）；NVIDIA 581.80（RTX 5080） | manifest + 截图 |
| GUI 证据文件 | `_evidence/desktop_full_run.png`、`_evidence/window_check/desktop_full_run_view.png`、`_evidence/desktop_smoke_run_1815.png`、`_evidence/desktop_smoke_run_1815_view.png`（sha 均入 seal provenance） | _evidence/ |
| T1 报告 | `docs/reports/perception/capture_20261104/CAPTURE_20261104.md`，seal 生成时 **PRESENT**，sha256 `7d6db809c416c850979167e86a84216bdbb4bc69b5997ce97c12104198045dd5` | seal provenance |

**T1 报告 provenance 现状（如实记录）**：Lead 交接 T5 时（约 18:24 前）T1 报告尚未落盘；本 seal 生成时（2026-11-04T10:26:46Z = 18:26:46+08）该报告已落盘。seal 按实际记录 `PRESENT + sha256`；若报告后续被修改，重新 verify 会报 `T1_REPORT_SHA_MISMATCH`。

seal 的 `provenance.files` 共 23 项（run manifest / run summary / episodes / run.complete / gui.log / gui.exit / GUI 截图 / frame_conditions / overlap_check / duplicate_hash_check / observations / sensor summary / case 清单 / 相机配置 / capture 报告与证据 / dev freeze v2），构建与复验均逐文件核对 sha256，全部存在且一致。

## 2. 独立复算（不抄 capture 数字）

规则：`sensor_key=front_rgb`，accepted = `gate.accepted AND validity.valid AND phase==RUN`；每 episode 另有 3 帧 WARMUP（accepted=false）。

| 族 / case | RGB 帧 | accepted（复算） | 唯一 sha | 说明 |
| --- | ---: | ---: | ---: | --- |
| lmf_sweep | 114 | 111 | 111 | 6 帧 WARMUP 中 3 帧同 sha，另 3 帧在 accepted 前 |
| lmf_backoff | 79 | 76 | 76 | 同上 |
| lmf_near | 26 | 23 | 23 | 同上 |
| lmf_edge | 31 | 28 | 28 | 同上 |
| lmf_similar_negative | 41 | 38 | 38 | 同上 |
| lmf_side_negative | 6 | 3 | 3 | 同上 |
| **合计** | **297** | **279** | **279** | 297 帧整体唯一 sha 285（6 个 warmup 重复簇 ×3 帧） |

- 逐帧 PNG 字节 sha256 复算：297/297 一致，0 缺失、0 不匹配（builder 与 verifier 都做）。
- 与 2026-11-04 数据清单/Lead 预沟通口径的差异（均以实际复算为准，报告中保留差异记录）：
  - "297 accepted" → 实际 **279 accepted**（297 是含 18 个 WARMUP 的总帧数；capture 报告 §1/§5 亦为 279）。
  - "目标不存在 44 帧" → 实际 **41 个 accepted 负例帧**（similar_negative 38 + side_negative 3）；其余 6 帧是这两个 episode 的 WARMUP，不在 accepted 池内。
  - "6 帧 ≤3px 绿光假线索" → 实际 `lmf_similar_negative_0` 中 **15/38 accepted 帧**有 1–3 px 绿光（9×1px、3×2px、3×3px），其余 23 帧为 0；`lmf_side_negative_0` 全 0。本 seal 记录 15，不沿用 6。
  - "截断 26–28 帧" → 实际 `lmf_edge_0` **26/28 accepted 帧** `truncated_right=true`（不是 26–28 的区间）；绿灯本身仍在画面内（u 246–294）。
  - "偏航 ±25°" → `lmf_sweep_0` 为 −22.8°…+24.7°；`lmf_edge_0` 更大（−40.1°…−28.6°），两者都记录。
- 跨 run 帧 sha：dev freeze v2 覆盖 **13 个目录 / 3002 帧（2940 唯一 sha）**；本池 285 唯一 sha 与其交集 = **0**（capture 只查了 formal6/lm_pilot/lm_independence/geo_test 4 个 run/1702 帧，本 seal 校验范围更广）。

## 3. 抽样规则

- 原始 RGB 297、accepted 279；**279 ≤ 400 → 不抽样**，固定规则 **N=1 保留全部 accepted 帧**。
- 备用规则（本次未触发，仅记录）：若未来重采/合并后 accepted > 400，按每族 accepted 帧 sequence 升序，取 `k = ceil(total_accepted / 400)`，从第一个 accepted 帧起每第 k 帧取 1；只依赖时间/序号顺序，**不使用模型分数、不使用随机数**。
- 18 个 WARMUP 帧仍列在 seal 的 `frames[]` 中（`accepted=false`），训练/评估必须过滤；它们解释了 6 条 `DUPLICATE_SHA_WITHIN_GROUP` warning。

## 4. 封存清单结构

字段（`landmark_final_pool_seal_v1.json`）：

- 顶层：`schema_version / grouping_protocol / freeze_id / pool_kind / status / generated_at / hash_algorithm / sampling / condition_coverage / family_independence / pool_adequacy / provenance / dev_freeze_reference / cross_checks / annotation_status / datasets / families / groups / splits / sealed / labels / access_boundary / raw_data_boundary / notes / freeze_sha256`。
- 6 个 group（= 6 family × 1 session × 1 渲染版本），每个 group 记录 `group_id / family_id / dataset / session / case_id / render_version / episodes / split=test / sealed=true / frame_count / accepted_frame_count / frames[]（frame_id + sha256 + accepted）`。
- `splits = {train: [], val: [], test: [6 groups], excluded: []}`；`sealed.present=true` 且 `sealed.groups=6`。
- `labels = {}`；完整语义标签 **PENDING**（见 §6 与 `annotation_status`）。
- hash：canonical `cedbbc7e1cd455f022d5f7c5f7f7925f046d9eebeb2581ca789ee25f7ce81007`，文件 `c852f0e520ffe608a1b7fc9db3e6e4c2d18aa4761a16700a4214a59e7708af02`，88,426 bytes。
- 与 dev freeze v2 的关系：`dev_freeze_reference.canonical_sha256 = 269d9a659db387beee345daff33cf1a3508261d099f548aeb93353b94c33afed`；`cross_checks` 记录 family/group/dataset root 交集均为空、跨 run sha 交集 0。

## 5. 条件覆盖矩阵（"≥3 新族、200–400 帧、条件覆盖"）

规模：**6 个新轨迹族 / 279 accepted 帧**，满足 ≥3 族与 200–400 帧；0 个 waypoint 序列与既有 18 个 case 相同。

| 族 | accepted | 距离 m | 相对方位 | 绿光 px | 截断 | 覆盖条件 |
| --- | ---: | --- | --- | --- | ---: | --- |
| lmf_sweep | 111 | 2.83–5.52 | −22.8°…+24.7° | 1–15 | 0 | normal / 尺度 / 侧向 |
| lmf_backoff | 76 | 2.06–8.37 | −3.9°…+11.0° | 0–23 | 0 | 尺度（近→远）/ 高度变化 |
| lmf_near | 23 | 1.46–1.78 | −11.7°…+13.1° | 26–41 | 0 | 近距尺度 / 近距出框 |
| lmf_edge | 28 | 2.51–3.23 | −40.1°…−28.6° | 15–28 | 26 | 偏航侧向 / 右缘截断 |
| lmf_similar_negative | 38 | 3.64–6.42 | 目标在身后 | 0–3（15 帧 >0） | 0 | 目标不存在 + 小绿点假线索 |
| lmf_side_negative | 3 | 2.07 | −110.8°（FOV 外） | 0 | 0 | 目标出视场 |

条件矩阵（seal `condition_coverage.condition_matrix`，条件来源为 capture `frame_conditions.json`；其帧集合与本次独立复算的 279 accepted 帧逐个核对一致）：

| 条件 | 族 | 帧数 / 证据 | 状态 |
| --- | --- | --- | --- |
| normal / 目标在画面内 | lmf_sweep | 111 accepted | 有 |
| 尺度 / 距离 | lmf_near + lmf_backoff + lmf_sweep | 1.458–8.367 m | 有 |
| 偏航 / 侧向 | lmf_sweep + lmf_edge | −40.07°…+24.73° | 有 |
| 截断（右缘） | lmf_edge | 26/28 accepted | 有（仅右缘；无左缘） |
| 目标不存在 | similar_negative + side_negative | 41 accepted | 有（视线级/出 FOV） |
| 相似结构 HN1 | similar_negative | **verified = 0** | **缺失**：只有"目标缺席 + ≤3px 绿点"，无结构级相似标签 |
| 场景结构遮挡 | — | 0 | **未构造** |
| 近距出框 | lmf_near | 23，塔体充满画面/底座出下边界 | 有（不等同横向截断） |
| 远景小目标 | lmf_backoff | 至 8.37 m，绿光 0–1 px | 有，但参考点可能 UNAVAILABLE |

**必须如实写明的边界**：
- `lmf_similar_negative_0` 不是"已验证相似结构"：目标在相机身后（相对方位约 ±180°），画面中央是中央场地结构；绿光检测只有 0–3 px 的孤立噪声级像素（15/38 accepted 帧 >0）。它只能算"目标不存在 + 少量绿色假线索"的负例，**HN1（相似结构困难负例）仍缺失**。
- 未构造"墙/物体挡在相机与塔之间"的遮挡；现有截断只是画面右缘几何越界，近距出框只是塔体充满画面。
- 远景（>约 7 m）绿灯 0–1 px，T6 标注应允许 reference UNAVAILABLE，不得把未标注帧一律当失败。

## 6. 与 dev freeze v2 的不重合校验

| 检查 | 结果 |
| --- | --- |
| family id 交集 | 0（seal 使用 `lmf_*`，dev freeze 使用 `fam_*`） |
| group id 交集 | 0（seal 使用 `g_lmf_*`，dev 使用 `g_formal6_*/g_lm_*/g_geo_*` 等） |
| dataset root 交集 | 0（seal 只用 `lm_final_candidate_20261104_sensor`） |
| 跨 run 帧 sha 交集 | 0（seal 285 唯一 sha vs dev 2940 唯一 sha） |
| 图像字节复算 | 297/297 一致 |
| waypoint 序列 | 0 个与既有 18 个 case 相同 |
| 起点位姿最近距离 | sweep 0.412 m（geo_test_static_c，yaw 差 π）、backoff 0.45 m（test_static_away，π）、near 0.702 m（π）、edge 0.30 m（pilot_east_center，差 0.60 rad）、similar_negative 0.539 m（pilot_east_away，同 yaw）、side_negative 0.481 m（test_reverse_south，差 1.571 rad） |

- 起点接近但 waypoint 序列不同是**事实**，seal 的 `family_independence` 与 capture `overlap_check.json` 都记录；轨迹族定义使用完整路径而非起点，本池全部走 E 区侧扫/中场后退/近距巡逻/边缘偏航/中场负例，**没有复用 south/north corridor 路线**。
- 视觉邻接：最接近的图像对（similar_negative vs pilot_east_away）像素 mean abs diff ≥ 7.69/255，edge vs pilot_east_center ≈ 12.5/255；不是字节重复、也不是近重复画面，但这是全池中最接近 dev 的两族，T6 报告必须继续标注该邻接关系。
- 与 capture 的差异：capture 只对 4 个 run 做 sha 交集；本 seal 对 dev v2 全部 13 个目录/3002 帧做校验，交集仍为 0。

## 7. 访问边界与封存局限

1. 本池只作为 **test**：`splits.test` 6 组、`sealed=true`；train/val/excluded 为空。
2. final test 只报告一次；test 内容/结果不得用于模型选择、阈值（`tau_det/tau_margin/tau_iou/tau_px/tau_conf`）或停训条件。
3. **hash + 流程记录不等于第三方独立封存**：seal 能证明"清单内字节未变、分组/hash 自洽"，不能证明"没人提前看过"或"标注者与开发者互相独立"。
4. 同一执行者既标注又开发时，只能声称 **流程隔离 + hash 承诺**；盲态或统计独立无法由 hash 证明。
5. 完整语义标签 **尚未生产**（`annotation_status.status=PENDING`，`full_semantic_labels=NOT_PRODUCED`）。T6 试点标注计划路径（ignored，不入库）：`outputs/perception/landmark_final_annotations_20261104/labels_v1.json`；仓库只登记路径，标签与 sha 在 T6 完成后回填。
6. 原始 297 PNG 与 observations 在 ignored `outputs/`；seal 逐帧记录 frame_id + payload sha256，便于在原始目录存在时复验。
7. 本池是**仿真**产物：合成 RMUC2027 资产、SIM_RENDER_RGB 模拟针孔相机（320×240/90°FOV/PROPOSED），不是 OV9782 实物、不是真实光照/运动模糊/曝光。

## 8. 复现与证据

```
# 构建 seal（重写清单 + 校验，canonical hash 不含 generated_at）
& 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/verify_landmark_dataset.py --build-final-pool

# 只校验（不写 seal）
& 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/verify_landmark_dataset.py --final-pool

# 同时可指定额外 dev freeze 做互斥校验
& 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/verify_landmark_dataset.py --final-pool --cross-run-freezes configs/perception/landmark_split_freeze_v1.json,configs/perception/landmark_split_freeze_v2.json
```

- 校验结果：`status=PASS`、0 error、6 warning（全部为同组 warmup 重复 sha）；帧总数 297、accepted 279、test 组 6、sealed 组 6。
- 证据 JSON：`docs/reports/perception/dataset_freeze_20261104/landmark_final_pool_verify_20261104.json`（含 errors/warnings/stats/cross_checks/condition aggregate/admission）。
- 全量回归：`pytest -q` → **872 passed in 48.02s**（含 T4 dataset 测试；本 T5 扩展复用同一 module/script，未改 dev freeze 语义）。
- dev freeze v2 复验仍 PASS（canonical `269d9a65…`），本 T5 未改 v2 字节。

## 9. 对 A3 / A8 的结论

| 准入项 | 判定 | 证据 / 缺口 |
| --- | --- | --- |
| A3 sealed final pool（≥3 新族、200–400 帧、冻结 group/list/label/hash） | **INCOMPLETE** | 6 新族 / 279 accepted / 清单+hash 已冻结；但**完整语义标签 PENDING**，A3 的 label/hash 部分未完成 |
| A8 样本充分性 | **INCOMPLETE** | 41 目标缺席帧、HN1 verified=0、无遮挡、远景绿灯 0–1 px；不足以支持 false-match ≤0.5% 或分层统计 |
| 封存完整性（manifest/hash/分组/互斥） | **PASS** | 本报告 §4–§6；0 error |

- 封存完整性 PASS 只说明清单可复验，**不能**升级 A3/A8，也不是模型/导航/板端证据。
- T6 应基于本 seal 清单做分层试点标注（建议每族抽 24–36 帧，覆盖 normal/尺度/近距/截断/目标不存在），标注完成后回填 `annotation_status` 与标签 sha，再重跑 verify；只有标签完整后才可能把 A3 改为 PASS。

## 10. 遗留问题与需用户决定

1. **完整语义标签尚未生产**：T6 试点标注完成前，A3 保持 INCOMPLETE；是否接受"先试点 24–36 帧、再决定全量标注"的节奏。
2. **HN1 相似结构负例缺失**：是否需要在下一轮采集中专门构造"塔被场景结构遮挡/相似结构在画面内"的负例；当前 `lmf_similar_negative_0` 不能替代。
3. **盲态独立封存**：标注者与开发者若为同一执行者，只能声称流程隔离 + hash 承诺；是否需要第三方/独立人员复核由用户决定。
4. **raw 外部备份**：原始 297 PNG 与 observations 仅在 ignored `outputs/`；是否需要在外部存储保留带 hash 的原始包以便他人复验。
5. **A3/A8 口径**：本报告按 training plan v2 的 admission gates 标 INCOMPLETE；若 Lead 要把"清单冻结 PASS"与"A3 INCOMPLETE"分开对外表述，以本报告 §9 为准。
