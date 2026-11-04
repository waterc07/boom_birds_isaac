# 盲标/比较证据放大图（固定子目录）

本目录只保留报告真正引用的少量放大证据（原生 320×240 帧局部放大、带原生像素网格）。

| 文件 | 说明 |
| --- | --- |
| z2_3_geo_test_static_a-follow_only_g2_3.png | geo_static_a g2_3 绿灯 16× 放大：小目标（bbox 78×75 px、绿灯面积 10–12 px）参考点读取，对应报告 §5.3 (1) |
| z2_9_test_reverse_south-follow_only_g2_201.png | reverse_south 201 绿灯 16× 放大：近距大目标、右缘截断；report §5.1 |
| z2_12_test_north_0-follow_only_g3_181.png | north 181 头部 16× 放大：**绿灯不可见**（只见头部边缘/蓝色灯带），"目标存在但参考点不可见"表达力证据，报告 §8.1 |
| z2_18_geo_test_static_c-follow_only_g4_3.png | static_c (160,130) 局部 16×：目标缺席帧内的暗绿色小点（1–2 px 达颜色阈值），报告 §4.3/§8.1 相似结构歧义 |
| z2_19_geo_test_static_c-follow_only_g4_3.png | static_c 右侧深灰柱状结构 16×：另一竞争结构，报告 §4.3/§8.1 |
| q_177top.png | geo_north g1_177 头部右上缘 14×：确认头部在帧右缘被截断，报告 §4.2 |
| sc_obj1.png | static_c 远端约 6×25 px 带绿色顶端锥形结构 20×：**HN1 已有证据**（旧数据），报告 §8.1 与 T6 报告继承 |
| sc_obj2.png | static_c 右侧约 20×40 px 深灰柱状结构 16×：HN1 竞争结构，报告 §8.1 |

说明：以上均为分析用放大图（最近邻/网格标注），不是模型输入，也不是检测器输出；原始帧仍在 `outputs/`（gitignored），未修改。
