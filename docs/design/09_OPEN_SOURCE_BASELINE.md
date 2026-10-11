# v1.2 开源基线与移植策略

2026-10-11，用户已确定：Isaac Lab主工程、NavRL首个导航/PPO基线参考、DiffPhysDrone轻量视觉与可微训练参考。本文件规定复用边界，当前未下载/安装/运行这些上游作为项目基线。

## 唯一主工程

项目是独立的Isaac Lab任务扩展和轻量运行包，使用成熟PPO实现。不是同时维护NavRL、DiffPhysDrone、VisFly三套可运行系统。NavRL的导航方法参考与其旧依赖解耦；DiffPhysDrone作为独立对照，不能将其加速度动作当成速度发送。

| 组件 | 处理 | 接受条件 |
| --- | --- | --- |
| Isaac Lab四旋翼资产/环境接口 | 基于本机匹配版本扩展 | 官方例与最小场景运行，动力假设记录 |
| PPO算法实现 | 使用当前兼容的一个成熟库 | 能处理所选观测和后续时序策略；锁精确版本 |
| NavRL观测/奖励/课程 | 阅读并择需移植 | 逐字段解释实际来源，基线明确标ORACLE或DEPLOYABLE |
| NavRL网络/推理代码 | 许可允许且输入输出适配时复用 | 独立形状、归一化、动作和导出测试 |
| NavRL旧Isaac环境与ROS部署栈 | 不作为主环境依赖 | 仅确有复现必要时独立隔离，不污染主环境 |
| DiffPhysDrone CNN/GRU思想 | P3模型对照 | 不宣称改变输入后的模型继承论文性能 |
| DiffPhysDrone可微训练 | L9后条件研究 | 原版小例可运行、动力与动作语义匹配、与PPO同预算对照 |
| PX4及MAVLink库 | 成熟飞控与协议 | P5锁定版本/坐标/模式/时效实测 |

## 上游审查产物

P0生成env/manifests/upstream.json：repo URL、commit、tag、检索时间、license文件/适用范围、核心路径、依赖、测试入口、可直接复用/需移植/不采用、风险。公开可见不自动等于许可可复制；无明确许可的部分先仅作为论文和行为参考，需澄清后才能纳入发布代码。

来源：[NavRL README](https://github.com/Zhefan-Xu/NavRL)明确训练基于Isaac Sim 2023.1.0-hotfix.1；[DiffPhysDrone README](https://github.com/HenryHuYu/DiffPhysDrone)说明PyTorch/CUDA测试组合与独立评估资源；[模型](https://github.com/HenryHuYu/DiffPhysDrone/blob/master/model.py)和[训练](https://github.com/HenryHuYu/DiffPhysDrone/blob/master/main_cuda.py)可核输入/动作。仓库现状在P0固定SHA后重新登记，不把README的兼容表述当本机测试。

## 改造顺序

1. 保存可读的原版与版本索引；只做小例或静态审查，不同时跑大训练。
2. 固定速度动作合同，先在当前Isaac Lab空场工作。
3. 引入NavRL相关导航定义，每次移植一个观测/奖励/课程因素，保留简单对照。
4. 改为真实可得观测，重新训练；不得复用不匹配的原权重并称部署成功。
5. 在相同场景比较DiffPhysDrone式小CNN/GRU与当前策略；只有收益足够才升级训练方法。

## 止损规则

若原版环境安装需要替换主机已用Isaac/PyTorch/CUDA，停止主环境修改，先评估是否只需方法移植。一个兼容问题经两条有证据的定位路径仍未解决，就提交阻塞原因与最小替代方案，不连续盲试版本。

如果传感信息不足，先改变观测/使用域；如果控制响应不符，先改执行器/动力模型；只有这两者成立后才用训练算法对照解释性能。移植成功必须写明“方法参考复现”，不得冒称严格复现原论文。
