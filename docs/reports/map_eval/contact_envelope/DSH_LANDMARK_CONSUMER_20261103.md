# V2.2 区域/地标导航最小感知消费者（shadow）— 2026-11-03

> **状态：** PASS（软件实现、预冻结评价、独立核验）；**算法效果仅部分达标**（frame recall 0.5，precision 1.0）；不接控制，不提升 Gate。
> **证据域：** 既有单环境模拟传感器 shadow 数据（6 个前台 GUI episode，DirectX/D3D12）离线逐帧评价；不是实机/真实感知。
> **最后核对：** 2026-11-03T21:30+08:00

## 1. 审计结论（上一轮统计与时间）

### 1.1 统计重算

原始 `observations.jsonl`：

```text
total 1728 = rgb 864 + depth 864
valid/accepted 1336 = rgb 846 + depth 490
invalid 392 = rgb WARMUP 18 + depth WARMUP 18 + depth NON_FINITE 356
RUN 1692, WARMUP 36
```

上一报告“864 RGB、490 有效 depth、392 WARMUP/NON_FINITE、1336 accepted”不是互斥分区：864 包含 18 条 RGB WARMUP，490 是有效 depth 而非全部 depth；`864+490+392=1746` 超出的 18 正是 RGB WARMUP。**18 条差异不是丢失数据**。完整勘误见 `DSH_SENSOR_SHADOW_ERRATA_20261103.md`，旧证据不修改。

### 1.2 时间语义

旧 v1 `capture_host_ns` 在 camera update 之后取得，不是曝光时刻；`exposure_uncertainty_ns=physics_dt` 不能证明曝光界；旧 accepted age≈10 ms 是 timestamp uncertainty，不是完整采集延迟。新 v2 记录改为 `capture_time_source=SIM_UPDATE_SAMPLE_TIME`、`exposure_time_status=UNKNOWN`、`capture_interval_ns=250 ms`（先失败测试再修复）；消费者对旧 v1 输入显式归一化并标注 legacy/UNKNOWN，不把主机读取当曝光。v2 证据需新采样才能产生，本轮图像输入来自旧 v1，消费者输出已明确该限制。

## 2. 最小感知任务

**任务：自然固定地标（RoboMaster 中央塔）检测 + 图像方位（image bearing）**。

| 阶段 | 定义 |
| --- | --- |
| 输入 | 仅已声明的 `front_rgb` 观测、其相机内参、静态塔模板；不读取机器人位置/姿态、区域标签、目标世界坐标、未来步骤或评价标签 |
| 算法 | 经典多尺度灰度模板匹配（`cv2.TM_CCOEFF_NORMED`），max over scales；模板来自 **训练 episode route_0** |
| 输出 | `DETECTED` / `NOT_DETECTED` / `UNKNOWN` / `REJECTED`；score（NCC，**不是概率**）、bbox、像素中心、`bearing_rad = atan2(cx-cx0, fx)`；距离 `UNAVAILABLE` |
| 拒绝条件 | 无效载荷、图像缺失/解码失败、内参缺失、重复/旧序号、过期、generation 不符、模板失败 |
| 后续消费者 | 仅在 shadow 中作为**区域/地标候选输入**；不接路线控制；无区域图/坐标前不定位置 |

- 目标为现有地图中的 **RoboMaster 中央塔**自然结构，未添加 AprilTag、合成色块或比赛设施；不使用训练模型。
- 单中心深度不足以支撑任意检测框的距离，故本轮**不输出目标距离**，只输出图像方位。
- 算法版本 `dsh.tower_template.v1`；模板/标签/阈值冻结于 `configs/perception/landmark_freeze_v4.json`。
- 消费者没有 ORACLE/truth 输入；ORACLE 只用于原路线控制和评价标签。

## 3. 数据、标签与评价设计

- 输入：上一轮 `formal6` 6 个预冻结 GUI sensor episode（static×2、route×2、reset×2）的 RGB 观测；离线逐帧复用，不重复 GPU 调参。
- 标签：人工 presence/partial labels，**只用于评价**，文件 `configs/perception/landmark_labels_v1.json`；目标训练/测试按 episode 分离：
  - 训练：route_0（generation 3），11 帧；
  - 测试：route_1/reset_0/reset_1/static_0/static_1，36 帧；
  - 正/负：18/18；部分遮挡/边缘帧标注为 `occluded`（190/195 帧）；
  - 无“随机拆相邻帧”划分；不删除未检测/拒绝帧。
- 阈值 0.55 只用训练帧选择；模板来自训练帧；最终测试在 freeze 后执行。

## 4. 结果（frame / episode）

测试集：

| 指标 | 数值 |
| --- | ---: |
| TP | 9 |
| FP | 0 |
| FN | 9 |
| TN | 18 |
| precision | **1.0** |
| recall | **0.5** |
| rejection rate（test frames） | 0.0 |

- 测试分集：
  - route_1：6 正例中 3 检测，4 负例 0 FP；
  - reset_0：3/6，0 FP；
  - reset_1：3/6，0 FP；
  - static_0/1：0 正例，各 3 负例，0 FP。
- FN 全部来自 **近距离/边缘/遮挡或模板尺度不匹配** 的帧（route_1/reset_0/reset_1 的 seq 190/195/200）；不是把未检测当正确。
- 全 864 条 RGB 输入：42 DETECTED、804 NOT_DETECTED、18 REJECTED（WARMUP）；这 18 条不计入测试指标但保留在拒绝分母。
- 各结果保存 score/bbox/bearing；由于标签仅有 presence、无独立 bbox/bearing 标注，像素/方位误差标 **NOT_AVAILABLE**，不以自评测量冒充误差。
- TP/FN/TN/UNKNOWN 样例：`evidence_20261103_landmark_consumer/`（correct_tp、miss_fn_occluded、miss_fn_scale、negative_tn、template、unknown_reject）。

## 5. reset 与时效合同

- 消费者对 generation 变化执行 gate/cache/sequence 重置；`formal6` 处理 6 个 generation，`consumer_reset_count=6`。
- 测试使用 generation 4/5/6（route_1/reset_0/reset_1）连续处理；旧 generation 不进入当前结果；每个 generation sequence 从 0 重启。
- 输出包含来源 sensor/frame/sequence/payload sha、observation record hash、generation、四级 context、算法/模板/阈值、有效期、score 定义、拒绝原因；`shadow_only=true`、`control_participation=NONE`、`distance.available=false`。
- 旧帧/重复/旧序号/过期/context/generation/无效深度/缺失标定/缺失模板规则在 consumer 和测试中显式处理；新结果不续期旧观测；reset 清空缓存。
- 输入 v1 的 `capture_host` 语义在输出标为 legacy/UNKNOWN；`age` 仅为仿真采样到消费的度量，不是完整采集延迟。

## 6. 预冻结与独立核验

- 源码 commit：`24596a1`（consumer/detector/时间语义）；核验脚本修正 commit `1f8e242`；正式 consumer source freeze `1f8e242`。
- consumer freeze：`configs/perception/landmark_freeze_v4.json`，sha256 `e812a64e07d57f5e6a77319f7a028c66e2cdd6cf4f6defb25be108540042b641`；输入 sensor freeze/hash、源码/config、template hash、labels hash、threshold、scales、split、expected 均记录；label correction 在 final freeze 前完成，未按测试结果调阈值。
- 独立核验 `scripts/verify_landmark_consumer.py` → `dsh_landmark_consumer_verify_20261103.json`：**PASS，24 checks**；重算帧级 TP/FP/FN/TN、precision/recall、拒绝率、episode 分母、输入/output hash、时间语义、generation/reset、shadow/ORACLE 边界、无 truth 引用。
- `pytest -q`：**799 passed**（consumer/detector/time 新增测试）。
- 文档审计：PASS；本工作包 diff 检查通过。
- 不运行新 Isaac GUI：输入是上一轮预冻结 GUI 数据；消费者为离线 CPU 逐帧评价，避免重复 GPU。所有原 GUI 采集均前台 DirectX/D3D12。

## 7. 失败/局限（如实）

- **召回率 0.5**：近距离/边缘/遮挡及尺度变化帧漏检；阈值 0.55 在训练上选定，测试结果没有反向调参；无假阳性。
- 仅一个自然地标（中央塔）和单个模板；无多尺度外观、旋转/光照/遮挡鲁棒性；无像素/方位标签，无法报告检测框误差。
- 不是区域识别、SLAM/VIO、定位或避障；没有区域图/地标数据库/目标语义坐标；不能作为比赛导航能力。
- 距离 `UNAVAILABLE`：单中心深度不能用于任意检测框；若未来输出距离，必须有检测框对应有效深度采样与几何定义。
- 相机参数/安装/曝光仍为 PROPOSED；无真实镜头畸变/标定/硬件时间戳；输入 v1 的 capture 语义已标 UNKNOWN/legacy，完整延迟未测。
- 不接控制；不启动 PPO/真实传感器/PX4 Sender/板端/SITL/HIL/实机；不提升 G2/G3/Gate；规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK。

## 8. 距离区域/地标导航还缺什么

1. 冻结的**地标数据库与区域拓扑**：地标 ID、世界坐标/区域、可见性条件、方向/尺度先验；当前只有单个塔模板，无地图标签。
2. 真实 OV9782 模组/镜头/CSI 参数与内参/畸变标定；相机-机体外参和安装误差。
3. 相机-主机时间戳/曝光可用性；真实延迟测量；将 PROPOSED 相机配置替换为实测。
4. 地标检测鲁棒性（多视角、尺度、遮挡、光照）与独立 bbox/bearing 标注；区域假设/多假设管理。
5. 若需距离，需合法 VL53L8CX/深度采样通道（而非单中心像素）及其标定；本轮不把模拟深度当 ToF。
6. 在上述之前，消费者只能作为 shadow 候选输入，不能进入控制或 Gate。

## 9. 下一步最少实物参数与测量

- OV9782 实际模组型号/镜头 FOV/分辨率/像素格式/CSI lane/帧率/曝光范围/畸变；
- 相机安装基准、光轴与机体坐标变换；相机-IMU/飞控时钟同步；
- 若使用前向距离：VL53L8CX 8×8 接口、zone 布局、更新率、量程/反射率限制与相机视场映射；
- RK3576 CSI/驱动采集管线、时间戳来源、实际端到端延迟；
- 这些实测前，保持 PROPOSED 模拟 shadow 定位，不宣称实机感知/Gate 通过。

## 10. 版本化证据

- `configs/perception/landmark_labels_v1.json`（sha256 `dd8c551d…`）；`tower_template_v1.png`（`e5270003…`）；freeze v4（`e812a64e…`）。
- 核验 JSON：`dsh_landmark_consumer_verify_20261103.json`。
- 证据目录：`docs/reports/map_eval/contact_envelope/evidence_20261103_landmark_consumer/`（samples、metrics、results sample、labels/template、consumer summary、hash）。
- 完整结果：`outputs/perception/landmark_final/results.jsonl`（864 条；gitignored，hash 归档）。
