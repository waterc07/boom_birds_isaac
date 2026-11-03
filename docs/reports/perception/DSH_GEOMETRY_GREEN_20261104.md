# 塔体几何＋绿灯参考点消费者：有界验证与方法去留（shadow，2026-11-04）

> **结论：** 开发条件在已暴露数据上满足，但一次新独立 GUI 测试失败。正式 v2 结果为 presence TP13/FP0/FN5/TN12（P1.000、R0.722），bbox 定位 TP3/9、joint TP3/18（全正例 16.7%），正常静态视角 A 0/3。**决定 C：停止此启发式方法，不进入地标关联 shadow。**
> **证据域：** 4 个新前台 GUI episode + 离线 CPU 开发/测试；无真实传感器/控制/Gate 声明。

## 1. 现场核对与依据

- 分支 `codex/bb22-contact-envelope`；起点 HEAD `4239958`；用户/其他任务修改保留。
- 依据：根因报告/交接/旧报告勘误、freeze v3、labels/templates/results。
- 复核根因结论：
  - B 消融旧模板路径 613 帧状态 0 差异；
  - baseline bbox 中心不可与标签绿灯直接比较；
  - 旧 49 帧已暴露，只可开发/诊断；
  - anchor 精度没有独立验证。
- 本包没有沿用“排除”扩大为所有实现无缺陷；绿光候选/几何规则重新验证。

## 2. 可观测依据与先验

- 当前合成地图中央塔有明显灰色塔体与顶部绿色灯。
- 9 个有参考点标注的目标帧中绿灯可见 8 个；north s181 绿灯不可见/不可标注。
- 其他绿色结构确实存在（如 reverse s83/s103、north s43/s63/s103），颜色/亮度与目标绿灯接近；
  **绿灯不是唯一/规则保证的结构**。因此规则只作为当前资产视觉先验。
- 目标塔体有边缘/灰色结构；几何规则使用绿灯 + 饱和结构区域 + 边缘支持/对称性，但没有把“底宽顶窄/对称”当作已验证比赛规则。
- 方法不读取 truth/标签/目标位置；不输出距离/区域/世界定位。

## 3. 最小实现

`src/boom_birds/evaluation/tower_geometry.py::GreenGeometryDetector`：

1. RGB 绿光候选（G>100、G>1.25R、G>1.15B），形态学合并小碎片；
2. 绿灯邻域饱和结构区域候选（S>70、V>35）作为 bbox；
3. 空间一致性：绿灯位于结构上部、结构尺寸/纵横比、边缘密度、左右边缘支持对称性；
4. 多候选：得分接近时 `AMBIGUOUS_GREEN_CANDIDATES` 拒绝；
5. 输出 bbox、绿灯 anchor、图像 bearing；`score` 为启发式结构分数，**不是概率**；distance `UNAVAILABLE`。

- 开发前条件（`geometry_dev_plan_v2.json`）：至少 2 视角正确目标、presence P/R 门限、bbox/anchor 门限、相似绿色负例拒绝、坐标合成测试；全部 PROPOSED。
- 开发数据：49 已暴露 + 30 旧 development 帧全部作开发，不称独立测试。
- 开发结果（仅开发/诊断）：
  - test-split presence TP26/27、FP0、TN22、FN1（north181 无绿灯），P1.0/R0.963；
  - bbox TP7/9（reverse s201 IoU .285 未达 .3）；anchor TP8/8；known green negatives FP0。
  - 开发条件判定 **PASS**，仅做了一个有界候选尺寸修正 `min_green_area 8→10`（因为 reverse s103 假绿面积9；不是测试调参），其余参数固定。
- 之后冻结 `geometry_test_plan_v1.json`、源码/参数、4 个新 episode 与抽样规则。

## 4. 新独立 GUI 数据

- 4 个 episode（全部前台 GUI/DirectX/D3D12，无 headless）：
  - `geo_test_north_0`：新北侧路线；
  - `geo_test_static_a`：新近距/正视；
  - `geo_test_static_b`：新斜视/边缘；
  - `geo_test_static_c`：目标不存在。
- 全部 `SUCCESS/ROUTE_COMPLETE`；`run.complete.json` 存在、无 error；采集后离线评价。
- 抽样：route every20 + last12；static 全 accepted；共 **30 sealed test frames**（18 正/12 负），localization subset 9。
- 标签 v1 在 opens 后用于正式评价时发现 route 参照点手工估计错误（3 帧），v1 run **保留并标 INVALID_LABEL_REFERENCE**；v2 只修正这 3 个绿灯参考点（图像视觉复核），bbox/算法/参数未改。v2 为新正式评价；v1 指标不作为最终结果。
- freeze v2：`configs/perception/geometry_test_freeze_v2.json`，sha256 `b5897274…`，code commit `8ac5330`；labels v2 冻结后才运行 v2 detection。

## 5. 正式测试结果（v2，有效标签）

测试 frame：30（18 正/12 负）。

| 指标 | 数值 |
| --- | ---: |
| presence TP / FP / FN / TN | **13 / 0 / 5 / 12** |
| presence precision / recall | **1.000 / 0.722** |
| 正例成功输出覆盖率 | 13/18 = 0.722 |
| bbox localization TP（IoU≥0.3） | **3/9** |
| joint TP（bbox+anchor≤5°） | **3/9** |
| joint / 全部正例（联合达标率） | **3/18 = 0.167** |
| UNKNOWN / REJECTED | 17 / 0 |
| anchor error（成功检测） mean / median / max | **0.036° / 0.006° / 0.134°** |
| reference unavailable | 0（本测试参考点均可见） |

### 分 family

| family | 帧/正/负 | presence 检测正例 | 假阳 | bbox TP |
| --- | --- | ---: | ---: | ---: |
| geo_north_test | 21/12/9 | **12/12** | 0 | 3/3（localization 子集） |
| geo_static_a | 3/3/0 | **0/3** | 0 | 0/3 |
| geo_static_b | 3/3/0 | 1/3 | 0 | 0/3（唯一检测 IoU .266） |
| geo_static_c | 3/0/3 | 0 | 0 | — |

- 路线 presence 12/12 且无 FP，但 bbox 只有 3/9、joint 3/18。
- **正常静态 A 完全 UNKNOWN**：该视角绿灯面积 8 px，低于开发后固定的 `min_green_area=10`；这是开发参数在独立视角的泛化失败，不是测试调参。
- 静态 B 多数几何候选被拒/bbox 过小，唯一检测 bbox IoU .266。
- 无 FP，但有 5 个正例无输出；UNKNOWN 未从分母删除。
- 由于成功检测只有 3 个 joint，anchor error 均值 .036° 只是**成功样本**结果，不代表整体方位精度；联合达标率 3/18 才是主结论。

## 6. 开发 vs 测试

| 数据 | presence P/R | bbox TP | anchor TP | joint |
| --- | ---: | ---: | ---: | ---: |
| 开发（已暴露 49 test split） | 1.0 / 0.963 | 7/9 | 8/8 | — |
| 新独立 v2 | 1.0 / **0.722** | **3/9** | 仅检测样本 3 | **3/18** |

- 开发条件满足并不能预测独立视角；差异来自绿灯面积/视角/饱和结构尺度。
- 没有在测试后调整算法/阈值；v2 只是标签参考点修正。

## 7. 方法决策：C 停止此启发式

选择 **C：停止此启发式方法，不进入区域/地标关联 shadow**。

理由：
1. 独立测试 joint 仅 3/18，静态正常视角 0/3；
2. bbox 3/9，低于可跟踪门槛；
3. 无 FP 但 5/18 正例无输出，UNKNOWN 比例高；
4. 继续调整会把 `min_green_area`/bbox 扩张/对称性阈值变成对测试视角的拟合，属于无限启发式叠加；
5. 路线 presence 12/12 只能说明“该路线尾段有绿光候选”，不能支持区域/地标关联。

**没有 NEW test 复用**；本包只进行一次新测试（v1 因标签错误标 INVALID，v2 为修正标签后的有效重跑，算法/参数不变）。

## 8. 下一候选（不本包实现）

若继续，下一候选应是**目标专用分割/实例模型（轻量）**，而不是继续几何阈值堆叠：

- 输入：RGB（当前 320×240）+ intrinsics；不读 truth/pose/labels/目标坐标；
- 数据：3–4 个新独立 GUI 轨迹（不同走廊/高度/偏航），约 200–400 帧；需要目标 mask/bbox/green anchor 标注；
- 计算：CPU 或小型 GPU 推理/训练；明确训练/验证分离与独立 sealed test；不把测试回调参；
- 验证：joint bbox+anchor、失败/UNKNOWN、硬负例、跨视角；若 joint 仍低于预声明门槛，则停止本阶段感知推进。
- 成本粗估：数据采集 1 次 4–6 episode、标注 200–400 帧、离线训练/验证（不在本包启动）。不默认引入大型模型；先做轻量分割/实例方案评审再投入。

## 9. 测试/核验/证据

- 新增单元测试：`tests/evaluation/test_tower_geometry.py`（绿灯+结构检测、纯绿色无结构拒绝）。
- 开发评价脚本：`scripts/evaluate_geometry_dev.py` → `dsh_geometry_dev_eval_20261104.json`。
- 正式运行/核验：`scripts/run_geometry_test.py`、`scripts/verify_geometry_test.py`。
- v2 核验：`docs/reports/perception/dsh_geometry_test_verify_v2_20261104.json`，PASS 17 checks；v1 无效核验保留。
- `pytest -q` 与文档审计见交接。
- 证据：`docs/reports/perception/evidence_20261104_geometry_test/`（正确路线 joint TP、miss/unknown、bbox错误、negative、GUI 截图、中间样本、labels/freeze/plan/verify）。

## 10. 边界

- 保持 shadow；不接控制、不做区域/世界定位/距离结论、不提升 Gate。
- 不启动 PPO/SLAM/VIO/真实相机/PX4/板端/SITL/HIL/实机。
- 绿灯外观仅当前合成资产视觉先验，不是比赛规则保证；硬件参数仍待测。
