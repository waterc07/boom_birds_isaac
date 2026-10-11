# 文件目录与工作区设计

状态：PROPOSED；用户已确定项目根目录。实际已创建的文件以README中的设计交付清单为准，下列业务目录在对应阶段建立。

修订0.2：保留PX4底层，首版速度＋偏航率。新增PX4固件／参数锁、Offboard网关、SITL桥和F0代理模块，详见[接口决策](../decisions/ADR-001_PX4_OFFBOARD.md)。

## 1. 物理目录布局

```text
E:\isaac\
├─ IsaacLab\                       已有官方源码，保留作为现状基线
├─ env_isaaclab\                   已有环境，已有依赖冲突
├─ proj_reach\                    既有其他项目
├─ proj_boom_birds\               本项目：设计、源码、小型配置与测试
├─ envs\
│  ├─ boom_birds_sim\              M0新建：Windows仿真／训练venv
│  └─ boom_birds_runtime\          M8新建：桌面CPU推理验证venv
├─ toolchains\
│  ├─ boom_birds_isaaclab\         M0新建：固定提交的独立源码副本
│  └─ PX4版本索引                  SITL源码宿主在M1确定；Linux源码优先放Linux文件系统
└─ boom_birds_storage\             阶段需要时建立，大文件不进Git
   ├─ assets\                     USD／纹理／大网格与下载资产
   ├─ datasets\                   数据集，按dataset_id不可变存放
   ├─ runs\                       训练与评估运行产物
   ├─ models\                     验证通过的模型包
   └─ cache\                      可再生成缓存，保留策略单独管理
```

不直接复制已有venv：其绝对路径和editable引用可能仍指向旧目录。独立环境通过明确的解释器、包清单和固定源码重新安装；源码副本路径由本地环境配置记录。

Windows下使用短英文运行路径。参考资料可以保留中文名称。环境数据与项目源码位于同一E盘，逻辑隔离不等于备份；正式训练产物需要额外备份位置，未配置前记录备份状态为NOT RUN。

## 2. 最终项目文件树

```text
proj_boom_birds/
├─ README.md
├─ BoomBirds.code-workspace
├─ .gitignore
├─ docs/
│  ├─ design/                       本轮六份设计文档
│  ├─ references/handoff_20261009/  原始交接资料与环境评估快照
│  ├─ decisions/                   ADR-001等：背景、选择、后果、替代方案
│  ├─ experiments/                 每轮实验的问题、比较条件和结论
│  └─ reports/                     已验收的阶段报告与产物索引
├─ configs/
│  ├─ project.yaml                 项目默认值与schema版本
│  ├─ local.example.yaml           本机路径模板，无秘密信息
│  ├─ local.yaml                   本机实际路径，Git忽略
│  ├─ vehicle/                     机体、旋翼、惯量、推力、参数来源
│  ├─ sensors/                     安装外参、采样、噪声、延迟、失效域
│  ├─ control/                     传统目标制导、速度映射与限制
│  ├─ autopilot/                   PX4参数快照、机体配置与F0代理参数
│  ├─ scenes/                      场景布局、机库与目标规格
│  ├─ experiments/                 实验入口：组合配置、算法和种子
│  ├─ evaluation/                  固定测试集manifest和验收配置
│  ├─ mission/                     任务阶段、时间与能源预算
│  └─ rules/                       research与比赛快照约束
├─ env/
│  ├─ baseline-observed.json        现有环境观测，区别于最终锁文件
│  ├─ windows-sim.lock.txt          M0验证后生成的精确依赖锁
│  ├─ windows-runtime.lock.txt      M8桌面CPU环境锁
│  ├─ toolchain.json               Lab提交、Python、Sim、资产版本
│  ├─ px4-toolchain.json           固件提交、target、参数哈希、MAVLink与桥版本
│  └─ environment-report.json      检查命令、结果、设备与时间
├─ source/
│  ├─ boom_birds_core/
│  │  ├─ pyproject.toml
│  │  └─ boom_birds_core/
│  │     ├─ contracts/             schema、坐标、单位和版本迁移
│  │     ├─ math/                  旋转、滤波、数值工具
│  │     ├─ estimation/            状态估计和目标相对估计
│  │     ├─ control/               传统目标制导与速度限制；部署内环属于PX4
│  │     ├─ mission/               状态机、时间与能源管理
│  │     └─ safety/                监督、命令仲裁、回退与事件
│  ├─ boom_birds_lab/
│  │  ├─ pyproject.toml
│  │  ├─ setup.py                  跟随已锁定官方外部扩展模板
│  │  ├─ config/extension.toml     扩展声明，不存实验参数
│  │  └─ boom_birds_lab/
│  │     ├─ assets/                小型资产描述与大文件manifest
│  │     ├─ dynamics/              电机、旋翼、风、能耗与PhysX适配
│  │     ├─ sensors/               采样、相机、光流、IMU与测距模拟
│  │     ├─ observations/          Oracle／E0／E1观测生产器
│  │     ├─ autopilot/             F0受限代理、F1后端与响应比较
│  │     ├─ bridges/px4_sitl/      传感器／执行器桥、时钟与重置同步
│  │     ├─ tasks/
│  │     │  ├─ goal_reach/         第一项学习任务；速度／悬停属飞控基线
│  │     │  ├─ takeoff_land/       M4
│  │     │  ├─ navigation/         M5
│  │     │  ├─ docking/            M6
│  │     │  └─ mission_cycle/      M7
│  │     ├─ training/              SKRL适配、模型、训练状态
│  │     ├─ evaluation/            固定评估、统计、回放和失败归因
│  │     └─ recording/             日志与数据集记录
│  └─ boom_birds_runtime/
│     ├─ pyproject.toml
│     └─ boom_birds_runtime/
│        ├─ policy/                actor加载、归一化、历史与推理
│        ├─ replay/                离线传感器回放
│        └─ adapters/px4/          Offboard单写入者、遥测、时效和模式确认
├─ scripts/
│  ├─ environment/                检查、锁定、资源探针
│  ├─ list_envs.py                 本项目任务清单
│  ├─ baseline.py                 参考控制器评估入口
│  ├─ train.py                    训练入口
│  ├─ evaluate.py                 固定评估入口
│  ├─ play.py                     演示与诊断入口
│  ├─ export.py                   导出actor及完整契约
│  └─ replay.py                   失败回放入口
├─ tests/
│  ├─ unit/                       坐标、混控、状态机、时间戳、配置
│  ├─ contracts/                  字段顺序、动作语义、真值隔离
│  ├─ simulation/                 力学、重置、碰撞、延迟和故障
│  └─ integration/                训练／保存／恢复／导出／重载
└─ manifests/
   ├─ assets.json                 文件路径、大小、哈希、来源、许可
   ├─ datasets.json               数据集版本、分割、标注规则
   └─ models.json                 候选模型索引与证据关联
```

先建立core、lab和M0/M1所需入口；runtime中的PX4网关在M1即用于SITL，actor运行器在M2／M3加入，M8补齐部署导出和资源验证。三包结构是最终边界，不要求第一天把全部目录创建为空文件。

## 3. 配置来源与覆盖顺序

物理／任务参数采用版本化YAML。Isaac Lab所需的Python配置类通过验证过的加载器消费这些配置；禁止在YAML与Python类中维护两份不同的数值默认值。

覆盖优先级：基础配置 → 机体／传感器／场景档案 → 实验组合 → 显式CLI覆盖。本机local.yaml只保存路径和设备选择，不应偷偷改变质量、奖励或验收门限。启动后保存完全展开配置、所有来源文件哈希以及CLI覆盖项；未知字段应报错。

验证包括单位、惯量正定及物理可实现性、机体与旋翼几何、频率整除／异步调度、推力范围、传感器外参及schema兼容性。不得对无效配置静默采用默认值。

## 4. 环境与版本固定

M0先以已运行的Python3.11.9、Sim5.1.0、torch2.7.0+cu128和Lab提交b4c321024792976150ca55fddb26fa34480d974e作为复现候选。该组合不是最终批准版本；依赖冲突解决和短训练验证完成后生成锁文件，保留变更前后差异。

若采用更新正式版本，在独立候选环境重跑M0及已实现任务的回归，通过后才替换项目基线。锁定项至少包括：Lab完整提交、Python、Sim、Torch／CUDA构建、RL库、依赖清单、GPU驱动、OS、资产根与哈希。nvidia-smi显示的CUDA驱动能力不是Torch运行时版本。

仿真脚本先启动AppLauncher，再导入需要Kit的模块；纯core测试和runtime导入不能启动Kit。所有入口显式选择解释器并检查包来源。项目运行不依赖当前终端PATH恰好指向哪个Python。

正式M0入口应提供preflight／smoke／训练短闭环；训练入口接收task、experiment、seed、num_envs、headless、resume等参数。当前这些入口尚不存在，因此工作区不预置指向它们的可点击任务。

## 5. 单次实验产物契约

```text
boom_birds_storage/runs/<UTC时间>_<任务简称>_<seed>_<短提交>_<唯一后缀>/
├─ manifest.json                   run_id、来源、状态、退出码、时间
├─ command.txt                     实际命令；排除凭据
├─ config_resolved.yaml
├─ environment.json                包版本、代码版本、设备、驱动
├─ source.patch                    有未提交变化时的可复现差异
├─ seeds.json                      训练／环境／评估与随机数状态说明
├─ stdout.log
├─ metrics.jsonl                   每阶段／每回合指标
├─ checkpoints/                    latest、best-validation、恢复状态
├─ evaluation/                     固定场景列表、结果、置信区间
├─ failures/                       种子、初态、动作、观测、原因
├─ videos/                         抽样演示；不替代定量指标
└─ report.md
```

manifest至少记录schema_version、code_commit、dirty状态、锁文件哈希、model_hash、task_id、observation_mode、model_fidelity、train_seed、eval_suite_id、attempted／started／completed数量和失败分布。视频与图像开销单独统计；长训练不默认保存每个环境每一帧。

评估冻结归一化和网络参数，resume恢复优化器、scheduler、RNG及观测归一化状态。只恢复权重属于新实验，不应宣称无缝续训。GPU仿真可能非位级确定，复现使用预先声明的指标容差和配置一致性。

## 6. 模型导出包

`actor`权重／可执行格式、observation_schema、action_schema、normalization、history配置、control_limits、模型和配置哈希、支持的任务／传感器档案、评估报告引用。若选择ONNX，必须验证目标算子支持和CPU重载一致性后才作为交付格式；仅文件导出成功不等于部署通过。

桌面CPU与Pi延迟分别报告；完整预算包含采集、传输、估计、预处理、推理、命令传输及飞控接收。PROPOSED策略20Hz、网关50Hz，推理P95<=10ms、观测到命令P95<=40ms；重发不会刷新原始策略命令的有效期。硬件无实测时保持NOT RUN。

## 7. Git、工作区与数据管理

实施M0时初始化本项目独立Git仓库，先保存设计基线；本轮未初始化或提交仓库。主线用于已验收增量，工作分支按阶段／问题命名。只有确有并行实验且需要代码隔离时建立worktree，每个工作区使用独立run目录。

当前`BoomBirds.code-workspace`只打开本项目，避免把旧项目、官方库和运行产物混成一个工作根。需要查看官方源码时可以另开窗口；该约定不是文件权限隔离。M0环境生成后再配置项目默认解释器和运行任务。

Git保存代码、小型配置、测试定义、文档和manifest；大型USD、录像、数据集、checkpoint位于外部storage。下载资产按哈希去重；缓存可重建，但只有确认不被任何manifest引用的运行产物才进入人工清理清单。默认不自动删除实验数据。

PROPOSED资源起点：无图像64环境逐步测到256；视觉8环境逐步测到16，按显存和延迟扩容。E盘当前约322.5GiB可用，设置可用空间低于50GiB的运行前提示；RAM至少留出系统余量，持续记录峰值，避免直接照搬4096环境默认配置。
