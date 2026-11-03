# 传感器 shadow 统计与时间语义勘误（2026-11-03）

> 本文件是上一轮 `DSH_SENSOR_SHADOW_20261103.md` 的追加勘误；原报告与原始证据保留，不重写历史事实。

## 1. 重算统计（对象与互斥关系）

原始数据：`outputs/sensor_shadow/formal6_sensor/observations.jsonl`（6 GUI episode；1728 条记录）。

| 口径 | 数值 | 统计对象/关系 |
| --- | ---: | --- |
| 总记录 | 1728 | 864 条 `front_rgb` + 864 条 `front_depth` |
| RGB 记录 | 864 | 全部 RGB 记录（含 18 条 WARMUP） |
| RGB validity/gate 接受 | **846** | 864 − 18 条 RGB WARMUP |
| depth 记录 | 864 | 全部 depth 记录 |
| depth validity/gate 接受 | **490** | 490 条有效 depth |
| depth 无效 | 374 | 18 条 depth WARMUP + 356 条 `NON_FINITE` |
| WARMUP/NON_FINITE 合计 | **392** | 18 RGB WARMUP + 18 depth WARMUP + 356 depth `NON_FINITE` |
| gate 接受总计 | **1336** | 846 RGB + 490 depth |

上一报告写“864 RGB、490 有效 depth、392 WARMUP/NON_FINITE、1336 accepted”，四个数字不是互斥可加的同一分区：864 是 **全部 RGB**（其中 18 条 WARMUP 无效），490 是 **有效 depth**（不是全部 depth），392 是 **全部无效原因计数**；因此 `864 + 490 + 392 = 1746 > 1728` 是口径差异，不是数据丢失。正确关系为：

```text
total 1728 = rgb 864 + depth 864
gate accepted 1336 = rgb_valid 846 + depth_valid 490
invalid 392 = rgb_warmup 18 + depth_warmup 18 + depth_nonfinite 356
phase: RUN 1692, WARMUP 36
```

- 帧级/样本级 gate 接受与物理有效性在本数据中恰好同为 1336，但概念不同：`validity` 是样本物理/载荷有效性，`gate` 是消息顺序/上下文/年龄后的消费者接受；必须分别给出拒绝原因（WARMUP、NON_FINITE 等）。
- 18 条差异的来源：18 条 RGB WARMUP 在 “864 RGB” 中包含，但不在 “846 RGB 接受” 中；旧报告没有把它从 RGB 样本数扣除。

## 2. capture/ready/consume 语义

上一版 v1 记录：

- `capture_sim_ns`：`camera.update` 之后的仿真 `current_time`，准确说是**仿真采样/更新时刻**，不是曝光中心时间；
- `capture_host_ns = time.monotonic_ns()`：在**相机更新之后、读取载荷之前**取得，不是曝光时刻；
- `ready_host_ns`：读取/perceive 后；`consume_host_ns`：记录写出前；
- `ready_sim_ns = consume_sim_ns = capture_sim_ns`：没有独立仿真 ready/consume；
- `exposure_uncertainty_ns = physics_dt_ns`：这是一个物理步的数值，**不能证明曝光时间界**；
- 旧 `gate.age_ns ≈10 ms` 来自 `timestamp_uncertainty_ns = physics_dt`，是仿真采样时刻的不确定量；**不是完整相机捕获到消费者的延迟**，也不是硬件曝光时间。

结论：旧 v1 数据可用于图像/内容评价，但不能把 `capture_host` 或 `exposure_uncertainty_ns` 解释为曝光时刻/完整延迟。新的 v2 记录语义（代码 commit `24596a1`）：

```text
capture_time_source = SIM_UPDATE_SAMPLE_TIME
exposure_time_status = UNKNOWN
capture_interval_ns = policy_dt * sample_period_steps = 250 ms
capture_time_uncertainty_ns = 0 (sim sample time; not exposure)
```

消费者对 v1 输入的归一化明确标为 `SIM_UPDATE_SAMPLE_TIME_LEGACY_V1`、`exposure_time_status=UNKNOWN`，并保留 legacy exposure 数值仅作历史字段；不将其作为真实曝光或完整延迟。若要声称曝光界，必须由渲染器/相机驱动提供真实曝光/帧时间戳；本轮没有该证据。

## 3. 对消费者输入的影响

- 本轮离线消费者只读取 RGB 像素、相机内参、payload hash/sequence/generation 和静态模板；不读取位置真值、标签、目标坐标。
- 图像内容未受时间字段影响；但消费者输出明确 `exposure=UNKNOWN`、`distance=UNAVAILABLE`，并将 age 标明为仿真采样/消费度量而非完整采集延迟。
- 旧报告/证据保留；旧 v1 数据不被伪造成 v2；新消费者输入归一化记录在结果和报告中。
