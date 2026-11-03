# 地标消费者独立性与 TP/方位定义审计（2026-11-03）

> 证据域：既有 6 个 GUI 传感器 episode + 新独立采集 5 个 GUI episode；纯离线评价。
> 结论：旧 36 帧不能作为独立测试；旧 TP 仅是 presence-level，旧 bearing 未验证。

## 1. 旧数据独立性

### 轨迹/配置

`configs/scenarios/sensor_shadow_cases_v1.json` 中四个非静止 case：

| case | route_id | start | goal | waypoints |
| --- | --- | --- | --- | --- |
| sensor_route_0 | south | `[-10.2,0.5,0.512]` | `[9.6,0.5,0.53]` | 南侧 A 路线 |
| sensor_route_1 | south | 同 | 同 | **完全相同** |
| sensor_reset_0 | south | 同 | 同 | **完全相同** |
| sensor_reset_1 | south | 同 | 同 | **完全相同** |

- **完全重复图像**：旧 846 条 RGB 中按 payload sha256 统计 **0 个重复 hash**。
- **同轨迹重复采集**：四个 route case 的 waypoints 完全相同；generation 4/5/6 与 train generation 3 在同一 seq 的 camera position 差约 0–0.006 m；图像 MAE 约 0.5–8.6（0–255），差异主要来自执行/渲染噪声。**reset_0/reset_1 与 route_0 是同一路线内容，不是独立轨迹。**
- **相近视角/连续帧**：旧测试抽样来自同一南侧路线的后半段连续帧；相邻帧高度相关，不能当独立试验。
- **独立轨迹**：旧 route_0/1/reset_0/reset_1 均不独立；旧 36 帧测试集仅可作开发/历史回归。

详细数字：`docs/reports/perception/dsh_independence_audit_20261103.json`。

### 旧标签/TP 定义修订

旧 `configs/perception/landmark_labels_v1.json`：

- 只有 `present` presence 标签，无 bbox、无参考点、无部分/不可标注分类；
- 旧 TP = 正例帧中消费者状态为 DETECTED，**没有验证 bbox 是否对中央塔**；
- 旧 bearing = `atan2(bbox_center_x - cx0, fx)`，bbox 中心不是固定塔特征；
- 因此：
  - 旧 recall 0.5 仅是 **presence-level、非独立**结果；
  - 旧 TP 不能解释为“正确目标定位”，旧 bearing 不能解释为目标世界方向；
  - 旧结果适用范围修订为历史/开发回归，不能作为新方法的独立测试依据。

## 2. 方位定义审查

- 旧 baseline 使用 bbox 中心：依赖检测框大小/形状，不是塔上重复可标注点；中心漂移会带来约数度到十余度误差。
- 新标签定义 reference point 为**塔顶绿色灯中心**（图像像素），见 `configs/perception/landmark_independent_labels_v1.json`；
- bearing 定义为 **相机光轴到该图像参考点的水平图像角**：`atan2(px_x - cx0, fx)`，单位 rad；不是世界方向、不是水平方位角、不是目标距离。
- 新方法 improvement 2 使用模板 anchor 映射到同一绿色灯参考点；如果某帧绿灯不可见/不可标注，reference 标 `UNAVAILABLE`，不强行补点。
- 内参来自 observation 的 320×240 pinhole 内参 `fx=160, cx0=160`；camera frame 为 `body_flu`/world +X 前向；不把图像 x 方向符号解释为世界北/东。

## 3. 新独立数据与划分

采集计划：`configs/perception/independence_plan_v2.json`（v1 保留；v1 的 every-10 抽样在只查看目标可见性、未看检测结果时发现会漏掉末端接近窗口，因而在标注/测试前升为 v2）。

| family | split | 采样/用途 |
| --- | --- | --- |
| south_new_start | development | 新起点/南侧移动，开发模板/阈值 |
| static_dev_center/left/away | development | pilot 静止视角，开发模板与负例 |
| reverse_south | sealed_test | 东→西反向穿越，新的接近方向 |
| north | sealed_test | 北侧走廊，不同视角与困难负例 |
| static_test_oblique | sealed_test | 东区斜视/边缘正例 |
| static_test_away | sealed_test | 目标不存在/地图结构负例 |

- 路线抽样：every 20th sequence + 最后 12 个 accepted frames；静止：全部 accepted 帧；未按检测分数选帧。
- 新选中帧：**49 sealed test**（27 正、22 负），development 30；测试 family 与开发 family 不相交。
- 新选中帧 exact sha256 重复：**0**；模板只来自 development（pilot static center/left + dev route near）。
- 旧 36 帧不进入新 test；只保留为历史/开发回归。
- 人工标签为代理（agent）像素检查，不是用户专家复核；bbox 近似标注，reference 点由绿灯像素辅助检查；未标注帧不计入 localization TP 分母。

## 4. 结论

1. 旧结果数据集**不独立**；旧 recall 0.5 不能继续作为独立测试指标。
2. 旧 TP 仅是 presence-level；旧 bearing 未经过固定特征验证。
3. 新数据 49 帧是独立于旧路线和新开发轨迹的封存测试集，但样本量小，只能形成限制性结论。
