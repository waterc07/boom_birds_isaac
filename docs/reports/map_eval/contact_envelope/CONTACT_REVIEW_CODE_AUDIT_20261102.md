# 接触证据链代码复核与修复方案（2026-11-02）

状态：只读源码审计与独立张量复现完成；未修改运行代码，未启动 Isaac，未重跑旧证据，未宣称修复完成。

## 1. 已确认的上层缺陷

### 1.1 filtered force 维度解析错误

本机 Isaac Lab 的 contact_sensor_data.py 明确 force_matrix_w 为 (N,B,M,3)。run_contact_verification.py 的 read_contacts 使用 matrix[0,0].tolist()，结果为 M×3 嵌套列表，随后对每个元素调用 float，M=1 时仍会 TypeError。异常被 except Exception: continue 吞掉。

现有解释器独立复现：输入 shape=(1,1,1,3)，vector=[[0.03,0,0]]，float(vector[0]) 报 TypeError。单目标正确向量索引是 matrix[0,0,0]；多目标应按真实 body/filter 索引分别读取，不可把总绝对值复制为三个坐标。

特别注意：max_force 在异常发生前已经更新，per_prim/target_vectors 却可能仍为空，形成非原子、相互矛盾的结果。因此该缺陷不等于“filtered 必然为零”，但可破坏归因及证据一致性。

### 1.2 L1 与欧氏模长混用

net 和 filtered 均用 abs().sum(-1)，而合同按欧氏模长判断。独立复现 [0.01,0.01,0.01]：L1=0.03 N，L2=0.0173205 N，位于 0.02 N 阈值两侧。旧阈值分类存在受影响可能，必须从原始向量重算；仅有标量时不能精确恢复。

### 1.3 读取失败被编码为有效零

sensor_available 只来自创建阶段；读取异常被吞掉，默认 max_net/max_force=0，随后生成 available=true、event=false、force=0。初始化成功不证明本步读取、更新与过滤覆盖有效。应分开记录 initialized/read_success/updated/coverage，并记录具体异常；读取失败输出 UNKNOWN/null，不能有效零。

### 1.4 event 不是独立 PhysX 事件

运行器 event 由 force>threshold 派生，不能作为与 force 独立的 contact report。应标 force_threshold_inference；若声称真实事件，必须接入实际事件来源。小于阈值不等于不存在物理接触。

## 2. 尚不能定为完整根因的推论

replication、reporter 时机与单进程第二次失效的探针结果值得保留，但必须先修复上述读取与健康度缺陷，再复核。当前 create_sensors 调用私有 _initialize_callback，循环中反复创建 sensor，缺少明确销毁/失效处理。需核查旧 view、事件订阅、时间戳与 reset 生命周期，不直接断言 PhysX 只能首 episode 工作。

建议依次比较：固定 sensor+reset、相同 sensor 强制更新、明确释放旧 view 后重建、整个 scene 重建。每次仅改变一项。记录 body/filter count、解析路径、tensor shape、更新时间和读取错误。

## 3. 包络与重放缺口

run_dynamic_eval.py 仍独立测量整个 robot prim 的 world AABB，并从 half_extents 求半对角线；没有使用新 body_envelope 的 root-frame collision inventory 和中心偏移规则。故诊断已修正，不等于生产 clearance 已迁移。迁移必须检查视觉/碰撞覆盖对象差异，不能简单全局替换常量。

replay 模式选取旧轨迹最大重叠点，重新构造障碍起点并让机器人 hover；这是局部几何探针，不是旧策略闭环回放。要复核旧结果，应重建原初始状态、障碍轨迹、时钟/队列/策略/阈值及 episode 边界，仅更换测量适配；如动力学/控制版本改变，明确属于新版本复现，不能直接判旧记录真伪。

cases_v1 的 geometry_note 写 0.30 m，但实际 y=0.35 m，且不等式自相矛盾。按配置数值核对几何，不以文字说明充当证明。

## 4. 实施顺序与验收

1. 把张量解析与单步健康度独立成小函数；先加失败测试，再修复。覆盖 M=1/M>1、多 body、缺失/异常、非有限值、L1/L2 阈值反例，不允许空字典与非零 filtered 标量并存。
2. 重新分析有原始向量的旧记录；未知保留未知。新 schema/核验版本不得覆盖旧冻结或旧 PASS。
3. 固定单进程三次接触循环，每次含接触前、接触中、离开段。先验证归因和读取健康，再调查 reset/view 生命周期；独立进程仍可保留为临时工作模式，但不得称根因修复。
4. 归因至少区分墙/障碍两个对象，filtered 仅依据真实映射，不凭 net+距离赋予对象身份。可增加一个独立低层 contact event 通道，记录双方 actor/shape 映射；测不到 force 时不伪造 force。
5. NO_CONTACT 改为受限命题：指定对象、时间窗、采样分辨率及经验证的检测覆盖。只有阈值零不能证明严格无接触。几何分离证据和传感器阴性应分别记录。
6. 完成旧案例闭环复现与生产包络迁移，重跑受影响专项；保留版本差异和未确认项。

最小 GUI 验收：同一进程连续三次已知墙接触及三次障碍接触均有实际证据与正确归因，读取错误不会降格为有效零；合法近距离和球重叠反例有独立几何依据；旧两例完成闭环复现或明确证明资料不足；生产包络与记录来源一致。所有 Isaac 运行前台 GUI、DirectX，先预冻结，再运行。

## 5. 协作判断

DS 已实现大量证据工具，但多次把外围诊断与临时绕过作为收尾，读取错误和证据口径未在源头闭环。当前应停止扩大场景，优先关闭本文件列出的确定缺陷。复核方已承担张量维度/L1阈值独立复现与源码追踪，可继续辅助小范围修复和独立验收；PhysX 生命周期问题仍需 GUI 实验证实，不能凭静态审计宣称已解决。
