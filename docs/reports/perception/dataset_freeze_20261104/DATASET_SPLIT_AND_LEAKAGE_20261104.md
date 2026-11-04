# 地标数据集分组、泄漏校验与 dev 划分冻结（2026-11-04）

> **状态：** PASS（仅数据准备 / 格式 QA）；dev 划分已冻结 v1（历史）与 v2（保守、训练前最新）；模型效果 NOT RUN；sealed 测试池 NONE；板端 / 导航 / SITL / 实机 N/A
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §20.11.1（测试数据分层，禁止连续视频随机拆帧）、§20.11.3（统计结论边界，高度相关连续帧不得当独立重复）、Phase 6（输入泄漏检查报告交付）
> **证据域：** 文档 + 单元测试 + 数据格式 QA（离线只读解析 outputs/sensor_shadow，未运行 Isaac，未训练，未安装依赖）
> **最后核对：** 2026-11-04

本报告只回答"现有暴露数据能组成什么分组、是否存在跨 split 泄漏、dev 划分能否冻结"。它不构成模型效果、板端部署、导航或任何 BB22 Gate 的验收。

## 0. 结论摘要

- 实际暴露数据是 **13 个 `*_sensor` 目录 / 3002 个 front_rgb 帧 / 2909 个 accepted 帧**，不是数据清单里声称的 4 个数据集。
  2026-11-04 的 `dsh_landmark_data_inventory_20261104.json` 只列了 4 个数据集（1702 帧 / 1648 accepted），**漏列 9 个目录 / 1300 帧 / 1261 accepted**。
- 全部暴露数据只包含 **2 条物理走廊**（南 A、北）加少量 E 区静态视点，因此"新北走廊轨迹族"在现有数据内并不成立：`geo_test_north_0`、`test_north_0`、`lm_pilot_north` 属同一北走廊 family。
- 旧配置有两处与本报告分组规则冲突：
  1. `landmark_data_split_v1.json` 把 `g_geo_north` 放 train、`g_lm_north` 放 val，同一北走廊跨 train/val，是其自身"test 必须是新轨迹族"规则的泄漏；
  2. `landmark_labels_v1.json` 用 route_0(g3) 作 train、route_1/reset_0/reset_1(g4–6) 作 test，把同一南 A 物理族的 reset 重复当独立 test（旧 `landmark_freeze_v4.json` 同样 `split_by_episode=true`）。
- 冻结分两个版本，均 0 error（group 互斥、episode 不跨组、连续帧不跨 split、family 不跨 train/val、帧 sha 无跨组重复）：
  - **v1（历史划分）**：train 5 组 / 1290 帧（1257 accepted），val 5 组 / 605 帧（581 accepted，含 E 静态 test 视点），test 0，excluded 9 组 / 1107 帧（1071）；canonical sha256 `47b535f4…`。
  - **v2（保守，训练前最新）**：E 静态视点簇整簇移入 train，train 7 组 / 1320 帧（1272），val 3 组 / 575 帧（566，仅北走廊 family），test 0，excluded 9 组 / 1107 帧（1071）；canonical sha256 `269d9a65…`。v1→v2 消除了唯一的 `VIEW_CLUSTER_SPLIT` warning（148→147）。
- **现有暴露数据可以形成机制上互斥的 dev train/val**（v2：北走廊整族进 val，train 无北），但只能用于 dev / 选模：
  val 只有 1 条物理走廊，无静态 val 覆盖，每个静态 pose 只有 3 个 accepted 帧。**不满足 final test**；v1 仅保留为历史，不得用于新的训练/选模。
- **当前没有 sealed 池**。标签文件里的 `sealed_test` 只是历史字段；那 49 / 30 帧已被查看和复用，hash 不能把已暴露数据变成 sealed。
- 工具/测试：`pytest -q` 全量 **852 passed**（新增 32 条，先红后绿）；`scripts/verify_landmark_dataset.py` 对 v1/v2 冻结校验均 **PASS**，逐帧 PNG 字节复算 3002/3002 一致，0 缺失、0 不匹配。

## 1. 证据与方法

### 1.1 输入（只读）

- `outputs/sensor_shadow/*_sensor/observations.jsonl`：只取 `sensor_key == 'front_rgb'` 记录，深度记录（`payload.ref` 为空）忽略；帧 id 从 ref 文件名解析为 `<episode>-follow_only_g<generation>_<sequence>.png`。
- 逐帧 `sha256` 取 observation 的 `payload.sha256`；脚本再对本地 PNG 字节重算 sha256 比对（3002/3002 一致）。
- run 级证据取 `outputs/sensor_shadow/<run>/manifest.json` 与 `<run>_sensor/summary.json` 的 hash；渲染版本取 manifest 的 `sensor_shadow.config_sha256`（记录值）并与当前配置文件 hash 对照。
- 标签文件 3 份，逐条 ref 与 observation 的 frame / payload sha 对照。
- 未修改 outputs/ 任何字节；未运行 Isaac、未训练、未安装依赖、未改 `E:\isaac\env_isaaclab`。

### 1.2 工具链

| 文件 | 作用 |
| --- | --- |
| `src/boom_birds/evaluation/landmark_dataset.py` | 帧解析、observations 载入、group/family 校验、连续帧与重复 sha 检测、sealed 规则、标签 hash、canonical freeze hash |
| `scripts/verify_landmark_dataset.py` | `--build` 扫描原始数据写 freeze；默认模式校验 freeze 并输出 JSON 证据 |
| `tests/evaluation/test_landmark_dataset.py` | 32 条回归：分组互斥、连续帧、重复 sha、sealed、family、hash 规范化、缺失/损坏输入、真实 v1/v2 freeze 复验 |
| `configs/perception/landmark_split_freeze_v1.json` | 历史 dev 划分冻结（不再用于新训练）：数据集 hash、family/group 清单、逐帧 sha、split 归属、标签 sha、canonical hash |
| `configs/perception/landmark_split_freeze_v2.json` | **训练前最新 dev 划分**（保守）：E 静态视点簇整簇进 train，val 只保留北走廊 family；记录 v1 canonical hash 与保守化证据 |
| `docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_20261104.json`、`landmark_dataset_verify_v2_20261104.json` | 机器可读校验证据（PASS/FAIL、errors、warnings、stats），分别对应 v1 / v2 |

### 1.3 复现命令（仓库根目录）

```
& 'E:\isaac\env_isaaclab\Scripts\python.exe' -m pytest -q
# 852 passed in 57.75s

# v1（历史）复验
& 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/verify_landmark_dataset.py

# v2（保守、训练前最新）重建 + 复验
& 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/verify_landmark_dataset.py --build --profile conservative --freeze configs/perception/landmark_split_freeze_v2.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v2_20261104.json
& 'E:\isaac\env_isaaclab\Scripts\python.exe' scripts/verify_landmark_dataset.py --freeze configs/perception/landmark_split_freeze_v2.json --output docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_v2_20261104.json
# 两个版本均 {"status": "PASS", ... "frame_total": 3002}
```

`--build` 只在需要重建 freeze 时使用；重建会改变 `generated_at`，但 canonical `freeze_sha256` 不变（该字段不参与哈希）。

## 2. 实际数据清单核查（以现场文件为准）

| 数据集目录 | run mtime | RGB 帧 | accepted | 渲染配置(记录) | inventory 是否列出 | v2 freeze 归属 |
| --- | --- | ---: | ---: | --- | --- | --- |
| formal6_sensor | 2026-11-03 20:49 | 864 | 846 | 06a479621765 | 是 | primary / train |
| lm_pilot_sensor | 2026-11-03 22:32 | 18 | 9 | 06a479621765 | 是 | primary / train |
| lm_independence_sensor | 2026-11-03 22:40 | 613 | 598 | 06a479621765 | 是 | primary / train+val（v2: 静态 test 组改 train） |
| geo_test_sensor | 2026-11-04 00:14 | 207 | 195 | 06a479621765 | 是 | primary / val（北）+ train（v2: 静态组） |
| lm_pilot_north_sensor | 2026-11-03 22:35 | 193 | 190 | 06a479621765 | **否** | val（北 family） |
| debug_all6_sensor | 2026-11-03 20:41 | 864 | 846 | 2ca749f013f4 | **否** | excluded |
| gui_evidence2_sensor | 2026-11-03 20:53 | 213 | 210 | 06a479621765 | **否** | excluded |
| gui_evidence_sensor | 2026-11-03 20:50 | 6 | 3 | 06a479621765 | **否** | excluded |
| debug_static4_sensor | 2026-11-03 20:26 | 6 | 3 | c23e13856b06 | **否** | excluded |
| debug_static5_sensor | 2026-11-03 20:27 | 6 | 3 | c23e13856b06 | **否** | excluded |
| debug_static6_sensor | 2026-11-03 20:28 | 6 | 3 | c23e13856b06 | **否** | excluded |
| debug_static7_sensor | 2026-11-03 20:30 | 6 | 3 | 2ca749f013f4 | **否** | excluded |
| debug_static3_sensor | 2026-11-03 20:25 | 0 | 0 | 无 manifest | **否** | excluded（空采集） |
| **合计** | | **3002** | **2909** | 4 种记录版本 | 4/13 | |

核查发现：

1. **inventory 覆盖不足**：其 `exposure_state.all_listed_runs` 与 `all_current_data_exposed` 只对 4 个数据集成立；实际另有 9 个目录、1300 帧（1261 accepted）未登记。这些数据同样是"已暴露"，如果不显式排除，可能被误当独立训练数据。
2. **渲染版本不止一种**：当前配置文件 `configs/sensors/sensor_shadow_v1.json` 的 sha256 是 `06a479621765...`（与 inventory 记录一致），但 `debug_all6` 记录的是 `2ca749f013f4...`，`debug_static4/5/6` 记录的是 `c23e13856b06...`。旧 debug 运行使用的渲染配置与当前不同，不能与 formal6 混作同一渲染批次。
3. **cases 文件也变过**：`debug_all6` manifest 记录的 cases_sha256 是 `a90d9ad1e5b6...`，当前 `configs/scenarios/sensor_shadow_cases_v1.json` 是 `d6b51c1f9daf...`。debug_all6 的 episode 名/路线与 formal6 相同，但逐帧 sha 全部不同（不同 session + 旧配置），**字节级 sha 去重抓不到这种重复**，必须按 family/session 排除。
4. **debug_static3_sensor 是空采集**：observations.jsonl 为 0 字节（sha256 = 空文件 sha），无 manifest；freeze 中登记为 `empty_capture` 并 excluded，校验时产生 1 条 `EMPTY_CAPTURE` warning，不是可用数据。
5. 原始数据体积：`outputs/sensor_shadow` 共 3122 文件 / 271MB，其中 PNG 约 80.9MB；`/outputs/` 被 `.gitignore` 忽略，不入 Git。

## 3. 分组核查

### 3.1 规则

- **组（group）** = 物理轨迹族 × 采集 session × 渲染版本。
- **族（family）** = 物理走廊 / 视点簇，是泄漏边界：同一 family 的组不得同时出现在 train 与 val/test。
- 同一 episode 的帧永远在同一组，因此连续帧不可能跨 split。
- 同一路线的 reset / 光照/渲染变化算同组；静态近重复画面算同组。

### 3.2 冻结分组表（19 组 / 6 family）

| family | group | split | 帧 / accepted | episode |
| --- | --- | --- | ---: | --- |
| fam_south_A | g_formal6_southA | train | 852 / 840 | sensor_route_0/1、sensor_reset_0/1 |
| fam_static_W_start | g_formal6_staticW | train | 12 / 6 | sensor_static_0/1 |
| fam_static_E_dev | g_lm_pilot_staticE | train | 18 / 9 | pilot_east_center/left/away |
| fam_south_A | g_lm_ind_devSouth | train | 195 / 192 | dev_south_new |
| fam_south_A | g_lm_ind_reverseSouth | train | 213 / 210 | test_reverse_south |
| fam_north | g_lm_ind_north | **val** | 193 / 190 | test_north_0 |
| fam_static_E_test | g_lm_ind_staticEtest | **val** | 12 / 6 | test_static_oblique/away |
| fam_north | g_geo_north | **val** | 189 / 186 | geo_test_north_0 |
| fam_static_E_test | g_geo_staticE | **val** | 18 / 9 | geo_test_static_a/b/c |
| fam_north | g_lm_pilot_north | **val** | 193 / 190 | dynamic_A_north_0 |
| fam_static_W_start | g_debug_all6_staticW | excluded | 12 / 6 | sensor_static_0/1 |
| fam_south_A | g_debug_all6_southA | excluded | 852 / 840 | 6 个 formal episode 重跑 |
| fam_south_A | g_gui_evidence2_route0 | excluded | 213 / 210 | sensor_route_0 重跑 |
| fam_static_W_start | g_gui_evidence_static | excluded | 6 / 3 | sensor_static_0 重跑 |
| fam_static_W_start | g_debug_static4 | excluded | 6 / 3 | sensor_static_0 探针 |
| fam_static_W_start | g_debug_static5 | excluded | 6 / 3 | sensor_static_0 探针 |
| fam_static_W_start | g_debug_static6 | excluded | 6 / 3 | sensor_static_0 探针 |
| fam_static_W_start | g_debug_static7 | excluded | 6 / 3 | sensor_static_0 探针 |
| fam_debug_empty | g_debug_static3_empty | excluded | 0 / 0 | 无 |

### 3.3 物理证据：为什么这些是不同的"族"

来自 `configs/scenarios/sensor_shadow_cases_v1.json`、`landmark_independence_cases_v1.json`、`geometry_test_cases_v1.json`、`map_dynamic_cases_v1.json` 的 waypoints：

- **南 A 走廊**：`sensor_route_0/1/reset_0/1` 与 `dynamic_A_south_0` 的 waypoints 完全相同（[-10.2,0.5] → [-10,-4] → [-6,-6.2] → [6,-6.2] → [9.5,-4] → [9.6,0.5]）。
- `dev_south_new` = `dynamic_A_south_1`：同南走廊，新起点 [-9.4,-1]。
- `test_reverse_south`：南 A 走廊反向（E→W）。
- `test_north_0` = `dynamic_A_north_0`（waypoints 逐点相同）；`lm_pilot_north` 的 case 就是 `dynamic_A_north_0`；`geo_test_north_0` 是北走廊变体（[-9.8,0.8] → [-9.6,3.6] → [-5.8,5.4] → [5.8,5.4] → [9.6,3.2] → [9.7,0.2]）。
- 因此现有暴露数据只有 **2 条物理走廊**（南 / 北）和 E 区若干静态 pose。把 geo 北放 train、lm 北放 val 不是"新族 vs 旧族"，而是同一走廊跨 split。

### 3.4 连续帧核查

- 13 个目录共 31 个 episode，逐 episode 的 sequence 都是 **0..N-1 连续、步长 1**（route 类 0..212，静态 0..5，北 0..188/192），无跳号、无跨 episode 拼接。
- episode → group 为一一映射；**episode 跨组冲突 = 0**。
- 按 observation 实际帧序做相邻帧检查：**跨 split 连续帧违规 = 0**；同 split 内相邻帧换 group 也没有发生。
- 说明：现有数据中"同路线 reset 被随机拆到 train/test"不是由连续帧切割造成，而是旧配置按 episode 实例做 split（见 §5）。

### 3.5 帧 sha 重复核查

- 3002 帧中唯一 payload sha256 有 **2940** 个。
- 31 个重复簇，**全部**是每个 episode 的 warmup 前 3 帧（sequence 0/1/2）字节完全相同；跨 group、跨 split 重复 = **0**。
- 结论：这些重复是同一渲染画面被连续采样 3 次（均 `gate.accepted=false`，reason WARMUP），属于同组内冗余，不构成泄漏；freeze 保留这些帧并标 `accepted=false`，训练消费时应过滤。
- 局限：sha 只能抓字节重复；不同 session 重跑同一轨迹（如 formal6 vs debug_all6、route_0 vs gui_evidence2）不是字节重复，需要 family/session 规则处理。

## 4. dev 划分冻结

### 4.1 冻结内容与规模

| split | v1 组 / 帧（accepted） | v2 组 / 帧（accepted） | 说明 |
| --- | ---: | ---: | --- |
| train | 5 / 1290（1257） | **7 / 1320（1272）** | v2 把 E 静态视点簇整簇移入 train |
| val | 5 / 605（581） | **3 / 575（566）** | v2 val 仅北走廊 family（3 个 session 组） |
| test | 0 / 0 | 0 / 0 | **无 sealed / 无 final test** |
| excluded | 9 / 1107（1071） | 9 / 1107（1071） | 重复 session、debug 探针、空采集 |
| 合计 | 19 / 3002（2909） | 19 / 3002（2909） | 帧集合完全相同，只有 2 个静态组的 split 归属变化 |

两版 freeze 都记录：逐组 `episodes / frame_count / accepted_frame_count / frames[]（frame_id + sha256 + accepted）`；逐数据集 observations / summary / manifest 的 sha256 与 recorded/current 渲染配置 hash；逐标签文件 sha256 与 split 声称；顶层 schema 版本、canonical hash 算法与生成时间。v2 额外记录 `split_profile`（保守化理由与静态 pose 证据）、`supersedes`（v1 路径与 canonical hash）以及 final 池访问边界。

### 4.2 与 `landmark_data_split_v1.json` 的修正

freeze 不照抄旧配置，共 3 处修正，均写入 `references.split_v1.corrections`：

1. **g_geo_north 从 train 改到 val**：与 `test_north_0` 同北走廊，旧配置跨 train/val。
2. **新增 g_lm_pilot_north 到 val**：`outputs/sensor_shadow/lm_pilot_north_sensor` 是已暴露但未登记的北走廊 pilot，必须永不进 train。
3. **为 9 个未登记目录建立 excluded 组**：重复 session / debug 探针 / 空采集不得被静默复用为独立数据。

旧配置的其余 6 个组（formal6_south_A、formal6_static、lm_pilot_static、lm_dev_south、lm_reverse、lm_static_test、geo_static）划分语义与新规则一致，保留。

### 4.3 能否形成独立 train/val？

**机制层：可以。** 独立校验结果：

- group 互斥：每帧只属于 1 组，0 冲突；
- episode 单组：0 冲突；
- 连续帧不跨 split：0 违规；
- family 不跨 train/val：0 泄漏；
- 帧 sha 跨组 / 跨 split：0；
- sealed 组出现在 dev：0（当前无 sealed 组）。

**能力层：只能用于 dev/选模，强度 INCOMPLETE。** 原因：

- 只有 2 条物理走廊。v2 中 val 只含北走廊 family（3 组 / 575 帧 / 566 accepted），train 完全不含北；可用于检验"北走廊是否泛化"，但无法覆盖南走廊的 held-out 视觉域，val 也没有静态视点覆盖。
- E 区静态视点簇（pilot / independent test / geo test）在 v1 中跨 train/val（1 条 `VIEW_CLUSTER_SPLIT` warning）。v2 按保守方案把整簇移入 train，消除该 warning；这不是"为消 warning 造假"，而是有静态机位证据：`geo_test_static_b` 与 `test_static_oblique` 机位差 0.64m / yaw 差 0.05 rad，`geo_test_static_c` 与 `test_static_away` 差 1.22m / yaw 差 0，`geo_test_static_a` 与 `pilot_east_center` 差 0.96m / yaw 差 0.10 rad，属同场景屋顶视点重叠（详见 v2 `split_profile.evidence`）。
- 静态可达样本很小：每个静态 pose 只有 3 个 accepted 帧；E 区静态总计 accepted = 24（v2 全部进 train）。
- 标签覆盖面小：3 份标签共 156 帧（旧 36：24 正 / 23 负；independent79：45 正 / 34 负；geometry30：18 正 / 12 负），相对 3002 帧只是小子集；没有 bbox 的帧仍占多数。
- 上述任何一点都意味着：**当前数据不足以充当 final held-out visual domain**，按 §20.11.3 只能标 INCOMPLETE，不得写成模型泛化结论。

### 4.4 sealed 状态

- `freeze.sealed.present = false`。
- 标签文件中的 `sealed_test` 是历史字段：`landmark_independent_labels_v1.json` 的 49 帧与 `geometry_test_labels_v2.json` 的 30 帧已在开发、诊断和评测中被查看/复用（inventory 的 `sealed_final_pool_remaining = NONE` 亦如此记录）。
- **hash 只能防篡改，不能把已暴露数据变成 sealed**；sealed 只能在 freeze 之后用新轨迹族采集并重新冻结。

### 4.5 v1 → v2（保守变体，Lead 2026-11-04 团队决定）

- 变更：`g_lm_ind_staticEtest`（12 帧 / 6 accepted）与 `g_geo_staticE`（18 帧 / 9 accepted）从 val 移入 train；其余 17 个组的帧集合与 split 不变。family/datasets/labels/frames 字段逐字节相同（校验比对）。
- 规模变化：train 1290→1320 帧（1257→1272 accepted），val 605→575 帧（581→566），test 0，excluded 1107 不变。
- warning 变化：148→147，唯一消除的是 `VIEW_CLUSTER_SPLIT`；剩余 147 = 115 条标签历史 split 声称冲突 + 31 条同组 warmup 重复 sha + 1 条空采集，均非本轮可消除的泄漏方向。
- 两版 canonical hash 都记录：
  - v1（历史，不再用于新训练）：canonical `47b535f4ae1edefac62cf6d6a7b06093d34d7b97b3eb2e2c327ab622d48b6f3c`，文件 `a0fbcd63…`；
  - v2（训练前最新 dev 划分）：canonical `269d9a659db387beee345daff33cf1a3508261d099f548aeb93353b94c33afed`，文件 `5d1d3dbc…`，`split_profile.name=conservative`，`supersedes.canonical_sha256` 指回 v1 的 `47b535f4…`。
- 复验：两版 `validate_freeze` 均 0 error；v2 的 val 组集合被回归测试固定为 `{g_lm_ind_north, g_geo_north, g_lm_pilot_north}` 且 family 全为 `fam_north`。

## 5. 旧配置声称与实况的偏差

| 旧配置 | 声称 | 实况 / 问题 |
| --- | --- | --- |
| `landmark_data_split_v1.json` | 9 组、geo_north 属 train、test 必须是新族 | geo_north 与 lm_north 同北走廊却跨 train/val；未列 lm_pilot_north 与 8 个 debug/evidence 目录 |
| `landmark_labels_v1.json` | 47 帧：train 11 / test 36；test episode = route_1、reset_0/1、static_0/1 | route_0(g3) 与 route_1/reset(g4–6) 是同一南 A 物理族的 repeated reset；36 帧"test"不独立，旧 0.5 presence 结果只是历史 diagnostic |
| `landmark_freeze_v4.json` | `split_by_episode=true`，train route_0 / test 其余 | 与上条同一问题：按 episode 实例 split 同一物理族 |
| `independent_freeze_v3.json` | 49 帧 `sealed_test` | 该 49 帧已被查看/复用，冻结名不等于封存；其中 reverse_south 22 帧现已归 train |
| `geometry_test_freeze_v2.json` | 30 帧 `sealed_test` | 已被查看/复用；现已归 val |
| `dsh_landmark_data_inventory_20261104.json` | `all_current_data_exposed=true`，只列 4 数据集 | 实际 13 个 `*_sensor` 目录，漏列 1300 帧 |

标签 split 声称与新分组的冲突（校验器计数，全部为 warning）：

- `landmark_labels_v1`：36 条 `test` 帧现属 train；
- `landmark_independent_labels_v1`：22 条 `sealed_test`（reverse_south）现属 train，27 条（north + static_test）现属 val；
- `geometry_test_labels_v2`：30 条 `sealed_test` 现属 val；
- 合计 **115 条** `LABEL_SPLIT_CLAIM_CONFLICT`。标签文件本身未改（保留原字节与 sha），冲突作为历史证据记录。

## 6. 访问边界

1. 标注者**可以**查看当前所有帧（包括历史上叫 test/sealed_test 的帧），因为现有数据全部已暴露。
2. 但 test 内容与结果**不得用于模型或阈值开发**：epoch/checkpoint 选择、`tau_det / tau_margin / tau_iou / tau_px / tau_conf`、停训条件只能来自 val；final test 只报告一次，不得回改。
3. **仅凭 hash 不等于 sealed**：hash 记录的是"这份字节没变"，不能证明"没人看过"或"没参与过决策"。
4. 若同一执行者既做标注/QA 又做模型开发，必须如实标注，不能声称盲态独立；本包未做盲复标（该工作属于 annot 任务）。
5. 新 final sealed 池必须在 freeze 之后采集，单独冻结 group/帧/hash/标签，且与 train/val 无 family/session 重叠。
6. **本 freeze 只登记已暴露数据**：final 池的图像与标签将放 ignored 外部目录，仓库只存帧清单 + sha256；同一执行者标注 + 开发时，只能声称"流程隔离 + hash 承诺"，不能声称盲态或统计独立。

## 7. 被 gitignore 的大图与原始产物边界

- `.gitignore` 忽略 `/outputs/`；原始 PNG、observations.jsonl、steps.jsonl、manifest/summary 均不入 Git。本目录原始 `outputs/sensor_shadow` 现为 3122 文件 / 271MB（PNG 80.9MB）。
- v1 / v2 freeze（654KB / 658KB）入 Git，记录：逐帧 payload sha256、每数据集 observations / summary / manifest 的 sha256、记录的渲染配置与 cases hash、标签文件 sha256、canonical freeze hash；v1 保留为历史，v2 为训练前最新。
- 本次校验对 3002 张 PNG 做了字节 sha256 复算：**3002/3002 一致，0 缺失，0 不匹配**（证据 JSON `stats.images_verified`）。
- 复验前提：本地保留 `outputs/sensor_shadow`。若原始目录缺失，只能验证 freeze 内部一致性；raw 是否被改动需要原始文件才能证明。是否需要在外部存储/远端保留带 hash 的原始包，见 §10。
- 大图与 run 目录不作为唯一结论来源；结论以 freeze + 证据 JSON + 本报告的可版本化文字为准。

## 8. 运行与测试证据

- TDD：先提交 `tests/evaluation/test_landmark_dataset.py` 并运行，得到 `ModuleNotFoundError: boom_birds.evaluation.landmark_dataset`；实现后再跑，逐条转绿。v2 的回归测试先要求 val 组集合与 family，再运行。
- 专项测试：`pytest -q tests/evaluation/test_landmark_dataset.py` → **32 passed**（31 条 schema/逻辑测试 + 1 条 v2 保守划分回归；真实数据缺失时相关 2 条自动 skip）。
- 全量测试：`pytest -q` → **852 passed in 57.75s**（退出码 0）。
- 冻结构建 v1：`--build` → PASS，0 error、148 warning（115 标签历史 split 冲突 + 31 同组 warmup 重复 sha + 1 E 静态视点簇跨 split + 1 空采集）。
- 冻结构建 v2：`--build --profile conservative` → PASS，0 error、147 warning（148 − 唯一 `VIEW_CLUSTER_SPLIT`）。
- 冻结复验（不再写 freeze）：v1 / v2 分别 verify → PASS，0 error；freeze 文件字节未变（重复运行 canonical hash 稳定）。
- v1（历史）：`configs/perception/landmark_split_freeze_v1.json`，schema `dsh.landmark_split_freeze.v1`，canonical `47b535f4ae1edefac62cf6d6a7b06093d34d7b97b3eb2e2c327ab622d48b6f3c`，文件 `a0fbcd63c617a29f715c1114d86cec704f3dd44b39bb688dd2f0f9949d9febc9`（生成时间 2026-11-04T10:11:32Z）。
- v2（训练前最新）：`configs/perception/landmark_split_freeze_v2.json`，canonical `269d9a659db387beee345daff33cf1a3508261d099f548aeb93353b94c33afed`，文件 `5d1d3dbcc1d950e73dfd74d4d7c64c2d307aab9786367a0b674f04e163c02407`（生成时间 2026-11-04T10:19:30Z）。
- 证据 JSON：`landmark_dataset_verify_20261104.json`（v1）与 `landmark_dataset_verify_v2_20261104.json`（v2），均 `status=PASS`，包含 errors/warnings/stats 与每数据集计数。

## 9. 对 T5 / T6 的前置结论

**对 T5（final 候选池冻结与封存清单）：**

- 必须采集**至少 3 个当前不存在的物理轨迹族**：例如新走廊、新接近方向、新静态 pose/高度/斜视；不能用现有南/北走廊的重跑、reset 或改名充当新族。
- 原始 accepted 帧会超过 200–400；T5 必须按**固定时间/路径间隔**抽样（例如每 k 个 accepted 帧取 1，规则写清、不用模型分数选择）把池定在 200–400 帧，并覆盖 normal/scale/yaw/遮挡/truncation/目标缺席/相似结构硬负例（HN1–HN6）。
- 新池用同一工具链登记：新 group/family、逐帧 sha、标签 sha、`sealed=true` 且只出现在 `splits.test`，并与既有 family 做不重合校验；仓库只 commit 清单 + hash，图像/标签留 ignored 外部目录；封存后只做一次 final 报告。
- 明确禁止把 lm_pilot_north、debug_all6、gui_evidence* 一类重复 session 当独立数据。

**对 T6（训练/选模）：**

- 只能消费 **v2** freeze 的 train/val；train 用 `accepted=true` 帧并过滤 31 组 warmup 重复帧（它们已标 accepted=false）。
- 选模/threshold 只用 val；v2 val 为"仅北走廊 family"（3 组 575 帧 / 566 accepted），无静态视点覆盖，不能把 val 指标写成 held-out 泛化结论。v1 仅保留为历史，不得用于新训练/选模。
- **不能**把当前任何数据当 final test；模型效果门槛仍为 PROPOSED；本 freeze 只允许写成"机制互斥的 dev 划分（held-out INCOMPLETE）"，**不得写成独立验证通过**；A3（sealed 池）/ A8（样本充分性）仍 INCOMPLETE，需 T5 完成后更新。

**还缺什么：**

1. 新轨迹族的 final 采集（T5）；
2. 盲复标与差异量化（annot）；
3. 静态 pose 独立性与硬负例覆盖（当前每个静态 pose 只有 3 accepted 帧）；
4. 部署/导出证据（ONNX/RKNN/RTX5080）与许可决定（license）；
5. 更大样本的分层统计，避免把 156 帧标签当充分统计。

## 10. 决策来源与遗留事项

**已由 Lead 决定（团队决定，2026-11-04，不需要用户批准）：**

1. **E 区静态视点簇按保守方案处理**：整簇移入 train（v2），val 只保留北走廊 family；v1 保留为历史。依据是本报告 §4.5 的静态机位重叠证据，不是为了消除 warning 而造数据。
2. **9 个未登记目录**：保留原字节并全部 excluded、不参与训练；默认不迁移/不删除。是否迁移存档仍列为用户事项。
3. **raw 不入 Git 的默认处置**：原始数据继续留在 ignored `outputs/`，freeze 只记录清单 + hash。是否做外部备份仍列为用户事项。
4. **freeze 作为 T6 的 A2 证据**：允许，但只能写成"机制互斥的 dev 划分（held-out INCOMPLETE）"，不得写成独立验证通过。

**仍需用户决定（报告不假设已解决）：**

5. **sealed 池标注者与模型开发者是否为同一人**：决定 T5/T6 需要多少盲态证据；若同一人，只能声称"流程隔离 + hash 承诺"。
6. **原始数据是否需要外部备份**：是否在外部存储/远端保留一份带 hash 的 `outputs/sensor_shadow` 原始包，以便他人复验。
7. **9 个未登记目录是否迁移存档**：默认保留原地；若需要长期归档，另行决定位置与流程。
