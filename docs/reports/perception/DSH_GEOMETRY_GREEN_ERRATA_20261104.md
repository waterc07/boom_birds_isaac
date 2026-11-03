# 几何/绿灯消费者指标口径追加勘误（2026-11-04）

> 本文件追加到 `DSH_GEOMETRY_GREEN_20261104.md`；原报告、freeze、verify JSON 和 hash 保留，不覆盖。

## 1. 18 正例 / 9 定位标注 / 3 joint TP

- v2 测试有 **18 个正例**；
- 其中只有 **9 个** 有 bbox + 绿灯火参考点标注（localization 子集）；
- **3 个 joint TP** 全部来自该 9 帧子集（route 3 帧）；
- 因此：
  - **3/9** = localization 子集联合达标率；
  - **3/18** = 全部正例中**已确认达标**的比例/下界；
  - 不能把另外 15 帧全部写成“定位失败”：
    - 5 个正例 presence 未输出（static A 3、static B 2）；
    - 6 个已标注定位正例未 joint 达标（static A 3、static B 3；其中 static B 3 帧并非都产生输出）；
    - 9 个正例没有 bbox/reference 标注，只能计入 presence，不能判定位失败。
- 原报告“joint/全部正例=3/18”作为“确认达标下界”成立；若被读成“3 个成功、15 个失败”则过度解释，本勘误修订如此。

## 2. anchor 误差统计的样本与来源

- v2 的 `.036°` mean / `.006°` median / `.134°` max 来自 **成功检测的 localization 子集**：
  - route `geo_test_north_0` 3 帧；
  - static B `geo_test_static_b` 1 帧（该帧 bbox IoU .266，不计 bbox joint TP）；
  - 共 4 个 detection；joint TP 仅 3。
- route 3 个 reference 点在 v1 中被手工错估，v2 修正时使用图像视觉复核/绿色灯位置；几何 consumer 也使用绿色候选。**标签参考点与算法 anchor 共用绿色视觉来源，不是独立物理测量**。
- 320×240、`fx=160` 条件下 1 px 约 0.358°；`.036°` 约 0.1 px，远低于当前 bbox/keypoint 手工标注可靠性，**不能宣称亚像素实物精度**。
- 这些误差是成功样本误差；不是全部正例覆盖误差。全部正例 joint 覆盖仅 3/18；另有 5 个正例 UNKNOWN。
- 旧 baseline 的 bbox 中心没有物理 anchor，不能与绿灯 anchor 误作同类精度比较；旧报告保留的历史数值只作诊断。

## 3. 低召回、bbox 不准、目标身份不确定

- **低召回/覆盖**：5 个正例无输出（static A 绿灯面积低于开发固定阈值；static B 几何拒绝），UNKNOWN=17（含负例）。
- **bbox 不准**：localization 子集只有 3/9 bbox TP；static B 唯一检测 IoU .266；bbox 来自饱和结构区域，不是物体轮廓的精确框。
- **目标身份不确定**：测试 12 个负例没有 FP，但测试负例规模小；开发期确有相似绿色结构（reverse/north 的多处绿色候选），身份判别并未被大样本验证。
- 这三者是不同问题，不能仅凭 bbox 指标差就推出“必须做分割”。V2.2 当前消费者需要身份/可见性/参考点/图像方位；bbox 是辅助，mask 没有明确下游消费者。

## 4. 适用范围

- 49 帧/30 帧/36 帧均为已暴露数据；不能恢复为 sealed test。
- 本包的新选型、数据规范、训练计划和部署评审不使用新 GUI 采集；不表示模型已训练或感知达标。
