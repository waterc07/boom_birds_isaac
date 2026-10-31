# Phase 0 来源与 Schema 差异盘点（2026-10-31）

> **状态：** BASELINE（盘点结论；不改变任何 LOCKED/TBD，不产生 PASS）
> **来源章节：** [RMUC2027_UAV_V2_2.md](../../design/RMUC2027_UAV_V2_2.md) §2、§4、§10.4、§16、§19、§20、§24、§26–28
> **证据域：** 文档 / 官方网页 / 仓库文件 / 未验证（逐条标注）
> **最后核对：** 2026-10-31
> **盘点对象：** `E:\isaac\proj_boom_birds`；盘点开始 HEAD `d01e156`，撰写时 HEAD `533708e`（盘点期间 BB22:G2.6 提交 c730c75、533708e）；V2.2 文档修订仍未提交
> **执行边界：** 只读盘点；Web 检索/抓取日期均为 2026-10-31；未运行 pytest/SITL/HIL/训练/固件；未安装依赖；未改 V2.2 正文、src、tests、configs；未执行 git add/commit

本报告对应共享任务 `task-1`（BB22:G0 新 Phase 0 来源与 Schema 差异盘点），是 [BB22:G2.6 合同实施计划](../../superpowers/plans/2026-10-31-bb22-g2-6-contracts.md) 的输入。机器可读差异见 [phase0_schema_diff.json](phase0_schema_diff.json)。

## 结论摘要

- 规则来源：RMUC 2027 正式规则手册、机器人制作规范手册、官方答疑原文均未取得。官方规则中心页面只返回页面框架/标题（已访问 URL 与日期见 A.1），因此全部规则数值（4Wh、300Wh、触点充电、飞行期可见光通信、10s 悬停、紧急停桨等）保持 **RULE-CHECK**，本报告不写条款号、不写 PASS。
- 官方场地图纸公告的页面标题与描述可读，提到“基于 RMUC&RMUL 2027 比赛规则手册 V1.0.0 制作”，可作为“规则手册 V1.0.0 存在”的官方网页证据；但手册正文与图纸本身未取得。
- BOM 层面仓库里只有型号级记录（V2.2 §4 与 planning 文档），没有铭牌照片、采购单据、称重、推力台或功耗数据；电池化学体系/铭牌电压未确认，4Wh 上限只有 0.01Wh 余量的情形必须取得合规确认。
- PX4 侧只有用户确认的“1.17、无 GPS、有光流、无磁力计、定高与 MAVLink 通信”，没有实机固件 tag/commit、参数导出、状态消息有效性映射与日志；上游 `v1.17.0` 候选 commit 只是历史检索记录，不能当作已刷写固件。
- Schema 侧：v1 `boom_birds.velocity.v1` 为 9 个字段的单层数据类；V2.2 要求 MessageHeader 17 字段、ActionEnvelope 16 字段、NormalVelocityAction 24 字段。逐字段对照得到 38 条差异，其中 28 项 v1 缺失、9 项改名/语义变化、1 项规范内部重复定义。
- 迁移不能只换 schema 标签：§10.4 的 `axis_validity`、`observation_id`、`input_capture_interval_ns`、`earliest_input_safe_deadline_ns`，§16.3 的 `system_boot_id`/`px4_boot_id`/`localization_epoch`/`control_epoch`/`sync_generation`/`quarantine`，以及 §16.6 的序号与身份语义，都必须显式补参；缺省、补 0、补当前时刻一律拒绝（MIG-01…MIG-12）。
- JSON 校验：使用 `E:\isaac\env_isaaclab\Scripts\python.exe` 执行 json.load，输出 JSON_OK、EXIT=0（2026-10-31）。
- 并发工作包：BB22:G2.6 已在盘点期间提交 v2 合同实现与证据（101 passed，自评 INCOMPLETE）；本报告不重复验收，也不把它当作 G0 或飞行能力证据。
- 结论：BB22:G0 仍未通过；本报告只把“缺口”变得可追踪，不把任何 UNKNOWN/PROPOSED/RULE-CHECK 写成 PASS。

## 0. 范围、方法与证据域

证据域按四级标注，表格中每行都带标签：

- 【文档】仓库内文档：V2.2 正文、验收报告、p0 报告、planning/decisions 文档。
- 【官方网页】2026-10-31 用 web_fetch 实际抓取的官方站点或官方仓库源码；取得程度（正文/仅标题/仅框架）逐条注明。
- 【仓库文件】仓库内代码、配置、证据文件，可 diff、可复核。
- 【未验证】只有转述、工程推断，或本次未能取得可复核证据。

规则类结论的硬约束：只从官方原文得出；如果只拿到页面框架/标题，就记录“已访问 URL + 日期 + RULE-CHECK”，不编条款号、不用第三方整理页代替原文。

**快照与并发说明：** 盘点开始时 `src/boom_birds/contracts` 只有 v1 三个模块。盘点期间 BB22:G2.6 工作包以测试先行方式落地并提交：`c730c75` 实现 v2 合同（versions/reasons/context/action_v2/admission/ownership/lifecycle），`533708e` 提交证据报告，自评 101 passed、Gate 仍为 INCOMPLETE。本报告仍以 v1 为“迁移前”基线做 Schema 逐字段差异（任务要求），不重复验收 G2.6 实现；v2 实现与测试状态以 [G2.6 报告](../g2_6/G2_6_CONTRACTS_REPORT.md) 为准，两者写域不重叠（本报告只写本文件与 JSON）。

**本次实际执行摘要：**

| 动作 | 对象 | 结果 |
| --- | --- | --- |
| read 工具读取 | AGENTS.md、PROJECT_PLAN.md、ROUTE_V2_2_REVIEW_20261031.md、P0 报告、UPSTREAM_REVIEW、NOTICE、V2.2 §2/§4/§10.4/§16/§19/§20/§24/§26–28、v1 合同源码、v1 测试、runtime 配置 | 成功 |
| 只读检索 | git status/HEAD、env/manifests、docs/planning、docs/decisions、docs/superpowers/plans | 成功 |
| web_fetch | 16 条证据 URL（RoboMaster、PX4 文档与源码、MAVLink、Rockchip、OVT、ST、MicoAir、GitHub Release；另有若干复抓/重定向尝试未单列） | 多数 200；部分仅取得标题/框架，逐条记录 |
| 写入 | docs/reports/p0/PHASE0_SOURCE_INVENTORY_20261031.md、docs/reports/p0/phase0_schema_diff.json | 仅这两个文件 |
| JSON 校验 | 项目解释器 json.load（UTF-8） | JSON_OK，exit 0 |
| 未执行 | pytest、SITL/HIL、训练、固件读写、依赖安装、git 提交 | NOT RUN（按任务约束） |

## A. 规则来源状态表

### A.1 官方来源可得性（检索日期 2026-10-31）

| 来源 | 官方入口 URL | 本次取得程度 | 版本/条款定位 | 证据域 | 结论标签 |
| --- | --- | --- | --- | --- | --- |
| RMUC 2027 比赛规则手册 | https://bbs.robomaster.com/wiki/20204847/1969149?source=7 | HTTP 200，但只返回页面框架与站点标题（title=RoboMaster 社区），无手册正文/附件链接 | 无法定位章节与条款号 | 官方网页（仅框架）+ 文档（V2.2 转述） | RULE-CHECK |
| RMUC 2027 机器人制作规范手册 | 官方规则中心内入口（同上 wiki 目录），本次未取得直属可用 URL | 未取得 | 无法定位 | 未验证 | RULE-CHECK |
| 官方规则答疑原文（轻流公开答疑面板） | 无公开直达链接；第三方检索入口 https://birdiebot.org/rules/（只作检索入口，不作原文） | 未取得原文；V2.2 §2.2 表中的口径来自项目此前整理，转载记录见 docs/planning/07_SOURCE_REGISTER.md | 无 Official Q&A ID/日期 | 文档（转述）+ 未验证 | RULE-CHECK |
| RMUC 2027 场地图纸/可移动道具开源公告 | https://bbs.robomaster.com/article/1970956 | HTTP 200；可读到 SSR 标题“RMU 2027场地图纸&可移动道具开源”与页面描述“以下开源图纸基于RMUC&RMUL 2027比赛规则手册V1.0.0制作”；图纸/附件本体未下载 | 仅能证明“规则手册 V1.0.0 存在”和公告标题，不含条款 | 官方网页（部分：标题+描述） | RULE-CHECK（条款）/ 文档（图纸基于 V1.0.0） |
| RoboMaster 官网 RMUC 2027 赛季页 | https://www.robomaster.com/zh-CN/robo/rm?type=rm-process | HTTP 200，正文可读：2027 赛季介绍、报名时间（2026-10-20 至 2026-10-27）、区域赛/总决赛时间、“规则/资料中心：https://bbs.robomaster.com/wiki/20204847” | 赛季级信息，无技术条款 | 官方网页（正文） | 文档（赛季事实） |
| 规则文件目录页 | https://bbs.robomaster.com/wiki/20204847/809871?source=7 | HTTP 200，仅页面框架（title=RoboMaster 社区），无文件列表正文 | 无法定位 | 官方网页（仅框架） | RULE-CHECK |
| 本地 2026 规则/制作规范 PDF（v1.3.0） | docs/references/field_research_20261009/（仓库文件） | 已存在（历史证据），与 2027 无关 | 2026 版本，不可代替 2027 | 仓库文件（历史） | HISTORICAL |
| RMUC 2027 场地图纸（STEP/预览） | 无 2027 官方图纸本体；仅有第三方转换的 Isaac 预览包（CosmosMount/rmuc2027_mjarena） | 预览已本地验证，但来源为第三方仓库，且报告声明不代表正式赛场 | 非官方原始图纸 | 仓库文件（第三方资产） | HISTORICAL / 不用于规则判定 |

**对规则的直接结论：** 官方规则中心与答疑原文在本次工具条件下不可取得正文。任何“4Wh/300Wh/触点充电/飞行期可见光通信/10s 悬停/紧急停桨/桨叶全包围/30s 续航”的数值或口径，只能引用 V2.2 的转述（文档），并保持 RULE-CHECK；冻结前必须补齐官方手册版本、条款号、答疑 ID、日期与链接。**不得把本报告表格当作规则依据。**

### A.2 当前掌握口径与 RULE-CHECK 缺口

以下“当前口径”一栏全部来自 V2.2 §2.2/§2.3 的项目整理，不是本次核验的官方原文；因此全部行保持 RULE-CHECK。

| 编号 | 规则主题 | 当前掌握口径（项目转述） | 对设计影响 | 关闭所需证据 |
| --- | --- | --- | --- | --- |
| RUL-CHK-01 | 空中机器人运行方式 | 全自动 | 不设计比赛用人工遥控运行模式 | 规则原文条款 + 版本 |
| RUL-CHK-02 | 持续悬停 | 单台至少 10s 悬停要求 | V0 独立悬停验收依据 | 制作规范/规则原文 |
| RUL-CHK-03 | 桨叶保护 | 机体外沿全包围、桨叶不外露，柔性材料要求 | 机械结构与 G0.5 | 制作规范原文 |
| RUL-CHK-04 | 紧急停桨 | 独立遥控器/接收机 + 安全员 | 独立于 RK3576 的安全链路 | 规则原文 + 实物 |
| RUL-CHK-05 | 单机供能 | 4Wh 供电总容量按电池标称电压计算 | 电池选型与合规 | 答疑原文 ID + 日期 |
| RUL-CHK-06 | 赛中换电 | 允许更换无人机电池 | 机库保留换电路径 | 答疑原文 |
| RUL-CHK-07 | 机库供能总量 | 机库最大供电总容量 300Wh，电池与累计充入计入 | 能源台账 | 答疑原文 |
| RUL-CHK-08 | 触点充电 | 允许机库通过触点充电，需符合机库电源管理接口要求 | 充电与数据触点分开设计 | 答疑原文 |
| RUL-CHK-09 | 机库内通信 | 允许有线/近场/可见光等规则允许方式 | 本项目选物理触点有线 | 规则原文 |
| RUL-CHK-10 | 飞行期间与机库通信 | 当前口径为可见光通信；普通 Wi-Fi/蓝牙/UWB 不允许 | 不假设飞行期有普通 RF 链路 | 答疑原文 |
| RUL-CHK-11 | 与其他机器人通信 | 受机库中继与可见光通信边界约束 | 优先机载缓存、返库同步 | 规则原文 |
| RUL-CHK-12 | 攻击方式 | 通过空中机器人冲击造成伤害 | 任务规划只考虑允许交互 | 规则原文 |
| RUL-CHK-13 | 遮挡引导灯/目标 | 允许相应遮挡，但造成道具故障可能判罚 | 接触检测与退出判据 | 答疑原文 |
| RUL-CHK-14 | 正常降落后再次起飞 | 允许在系统正常且未被罚下时再次起飞 | 多架次流程输入 | 答疑原文 |
| RUL-CHK-15 | 续航时长 | 2026-08-14 亮点材料曾写“至多 30s”；公开答疑称当前手册无该限制（均为转述） | 不写软件硬限制；用 4Wh+任务能耗+返库余量预算 | 规则原文 + 答疑原文 |

### A.3 关闭规则缺口的操作步骤（建议按序）

1. 用有权限的账号登录官方论坛规则中心（入口 https://bbs.robomaster.com/wiki/20204847），下载 RMUC 2027 规则手册、机器人制作规范手册的 PDF 与官方答疑导出件；归档到 `docs/references/rules_2027/`，记录文件名、版本、发布日期、SHA-256、下载日期。
2. 按 V2.2 §24.5 模板逐条登记：Rule ID、Manual Version、Section、Official Q&A ID、Official Answer Date、Original URL、Interpretation、Affected Hardware、Affected Software、Compliance Test、Last Verified、Owner。
3. 每条规则结论必须能指到“PDF 页码 + 条款号”或“答疑 ID + 原文截图”，否则继续 RULE-CHECK。
4. 规则更新后重跑需求追踪；规则与答疑冲突时以赛事组织方最新明确口径为准（V2.2 资料优先级）。
5. 未闭合前禁止把规则数值写进验收门槛或 PASS 依据。

## B. 实物/硬件 BOM 核对

状态分类只有三档：**【已有仓库证据】**、**【需要用户提供铭牌/照片】**、**【未知】**。厂商/官方网页只能证明芯片或产品页存在，不能证明手里的模组就是该配置，因此单独标注“仅芯片/产品页级证据”。**仓库未提供的数值一律留 UNKNOWN 或标为缺失，禁止用厂商典型值或工程估计填入 BOM。**

表中型号/数量来自【已有仓库证据】的型号级记录，但除“型号清单”一行外，没有一项具备实物铭牌、称重或实测证据，因此主标签取更严格的【需要用户提供铭牌/照片】或【未知】。

| 项目 | 基线（AGENTS §2 / V2.2） | 仓库证据 | 官方/厂商页面证据 | 状态分类 | 补齐动作 |
| --- | --- | --- | --- | --- | --- |
| 型号清单（V2.2 §4 BOM 基线） | 飞控/ESC/电机/桨/电池型号与数量已写入基线表 | V2.2 §4.1、§4.2；PROJECT_PLAN；planning 01 | 部分厂商页可达（标题级） | 【已有仓库证据】（仅型号/数量级，不构成实物核对） | 仍需逐项实物铭牌核对；补齐后升级为实测证据 |
| 机载计算 | RK3576（核心板/载板型号待定），LOCKED | V2.2 §4.1；PROJECT_PLAN；planning 01/10 | Rockchip 官方 RK3576 页：4×A72+4×A53 ≤2.2GHz、6TOPS NPU、LPDDR4/4x/5、PCIe/USB3/SATA/GMAC/CAN FD 等（2026-10-31 抓取正文） | 【未知】：板卡型号/BSP/revision 未提供 | 提供核心板+载板型号、照片、BSP 版本、CSI/USB/UART 资源表 |
| 飞控 | MicoAir743V2-AIO + PX4，BASELINE | V2.2 §4.1；ADR-001；planning 01 | MicoAir 官方产品页可达（标题 MicoAir743v2-AIO-45A），历史登记有 10g/5V2A/无板载磁力计口径 | 【需要用户提供铭牌/照片】：实板 revision、称重、BEC 带载未验 | 拍板卡正反面丝印；称重；记录 revision |
| ESC | AIO 45A 版本，BASELINE | V2.2 §4.1 | 与飞控同板（产品页标题级） | 【需要用户提供铭牌/照片】：四路持续/峰值电流、协议支持未验 | 记录丝印与 DShot600 实测 |
| 电机 | T-Motor M1103 8000KV ×4，LOCKED | V2.2 §4.1；planning 01 | 无本次厂商页抓取 | 【需要用户提供铭牌/照片】：批次、重量、推力曲线 | 铭牌照片 + 推力台数据（G0.5） |
| 桨叶 | Gemfan 2216S-3 ×4，LOCKED | V2.2 §4.1 | 无本次厂商页抓取 | 【需要用户提供铭牌/照片】：型号/螺距确认、动平衡 | 照片 + 称重 + 动平衡/推力台 |
| 电池 | 3S 350mAh LiHV（铭牌 11.4V 标称/满充 4.35V/cell/3.99Wh），PURCHASED + RULE-CHECK | V2.2 §2.2.1、§5；PROJECT_PLAN | 无官方电池厂商证据；仅 V2.2 转述 | 【需要用户提供铭牌/照片】：型号、化学体系、C 倍率、质量、满充电压、采购凭证 | 铭牌正反面照片 + 称重 + 内阻/放电记录；确认 LiHV 后按 3.99Wh 复算 |
| 前视相机 | OV9782 彩色全局快门，PROVISIONAL | V2.2 §4.2.1 | OVT 官方产品页可达（title=OV9782）；属性需以数据手册为准 | 【需要用户提供铭牌/照片】：模组型号、镜头、FOV、MIPI lane/帧率/像素格式 | 模组型号与镜头参数 + 实测帧率/曝光/丢帧 |
| 下视相机 | OV9281 灰度全局快门，PROVISIONAL | V2.2 §4.2.2 | OVT 官方产品页可达（title=OV9281） | 【需要用户提供铭牌/照片】：同上，另含灰度格式 | 模组型号与镜头 + 驱动验证 |
| 下视光流/测距 | MTF-02P，PROVISIONAL | V2.2 §4.2.3 12 项接口清单 | MicoAir 官方产品页可达（title=MTF-02P Optical&Range Sensor） | 【需要用户提供铭牌/照片】：UART 电平/协议/单位/质量字段/时间戳 | 按 §4.2.3 清单实测并归档手册页 |
| 前视测距 | VL53L8CX 8×8 多区 ToF，PROVISIONAL | V2.2 §4.2.4 | ST 官方产品页可达（title=VL53L8CX） | 【需要用户提供铭牌/照片】：模组总线（I2C/SPI）、地址、电压、最大稳定更新率 | 模组手册 + 实测更新率/无效 Zone |
| 机库停靠通信 | 物理触点有线；协议 TBD | V2.2 §6 | 无 | 【未知】：触点定义、电气参数、协议 | 机库接口定义 + 触点电阻/数据完整性台架 |
| 紧急停桨链路 | 独立遥控器/接收机 + 安全员，RULE-CHECK | V2.2 §2.2 | 无 | 【需要用户提供铭牌/照片】：接收机型号与接线 | 实物型号 + 独立链路验证 |
| 桨保/机架/紧固件 | 全包围四旋翼，BASELINE | V2.2 §4.1 | 无 | 【未知】：材料、质量、外廓、重心 | CAD/称重/外廓测量 |
| 稳压/配电/线束 | 未冻结 | 无 | 无 | 【未知】：拓扑、峰值能力、压降、效率 | 原理图 + 带载实测 |
| 整机质量/推力/功耗 | 未闭合；160g 仅历史参考 | planning 01（历史） | 无 | 【未知】 | 逐件称重 + 推力台 + 功率计（BB22:G0.5） |

### B.1 电池能量复算（按 V2.2 §2.2.1 的候选口径，不构成合规结论）

变量：3S × 350mAh = 0.35Ah。普通 LiPo 按 3.7V/cell，LiHV 按 3.8V/cell：

- LiPo：`V_nom = 3 × 3.7 = 11.1V`，`E_nom = 11.1 × 0.35 = 3.885Wh`。
- LiHV：`V_nom = 3 × 3.8 = 11.4V`，`E_nom = 11.4 × 0.35 = 3.99Wh`。
- 若上限确为 4Wh，则 LiHV 方案余量仅 **0.01Wh**；这不是“通过”，而是必须在最终检录前取得官方明确合规确认（RULE-CHECK）。
- 满充 4.35V/cell 不得直接用于“按标称电压”计算；实际可用能量还要扣除放电深度、线损、稳压损耗与返库余量。
- 机内所有电池都必须计入总供电容量；不得用额外小电池绕开限制；电容组/超级电容不得默认加入（V2.2 §2.2.1）。

**结论：** 电池化学体系与铭牌电压未确认前，只能并列给出 3.885Wh/3.99Wh 两种口径；任何“符合 4Wh”表述都是 UNKNOWN/RULE-CHECK。

## C. PX4 固件与参数

### C.1 已知证据（逐项标证据域）

| 项目 | 已知内容 | 证据域 | 状态 |
| --- | --- | --- | --- |
| 飞控硬件 | MicoAir743V2-AIO；V2.2 §4.1 标 BASELINE | 文档 + 官方网页（厂商页标题级） | BASELINE（实板 revision 未验） |
| 固件家族/版本 | 用户确认 PX4 1.17；无 GPS、有光流、无磁力计；已实现定高飞行与上位机 MAVLink 通信 | 文档（用户确认转述，见 docs/planning/10、01、09、ADR-001） | 文档级证据；无日志、无参数、无 tag/commit |
| 实机固件 tag/commit | **UNKNOWN**。仓库只有上游候选记录：v1.17.0 tag 候选 commit `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`（2026-10-09 git ls-remote，非实机固件） | 文档（历史记录）+ 官方网页（Release 页标题可读） | UNKNOWN（实机）/ 文档（候选上游） |
| 参数导出 | 无参数文件、无参数快照 | 未验证 | UNKNOWN |
| 状态消息与有效性映射 | V2.2 §16.9 要求列出实际固件可获取的消息、估计健康位、时间戳、reset counter 与逐轴有效性；仓库无映射记录 | 文档（要求）+ 未验证（实际） | UNKNOWN |
| Offboard 接口要求 | PX4 官方：2Hz proof-of-life、进入前需提前发送 >1s、低于 2Hz 后按 COM_OF_LOSS_T 超时并执行 COM_OBL_RC_ACT | 官方网页（PX4 v1.16 Offboard 页 200；语义经 PX4 User Guide markdown 复核） | 官方文档级；实机行为未验 |
| LOCAL_NED 接收逻辑 | PX4 v1.16.0 mavlink_receiver.cpp：LOCAL_NED 分支按 type_mask 逐字段选择，忽略字段置 NaN；BODY_NED 分支按 yaw 旋转 | 官方网页（PX4 官方仓库源码，抓取时截断但相关函数段落可读） | 源码级；未在实机/SITL 验证 |
| MAVLink 字段与 type_mask | MAVLink common 页面可达，但正文因页面体积未完整提取；1479（全轴速度+yaw-rate）与 1511（忽略 vz）是按位定义计算的候选掩码 | 官方网页（页面标题级）+ 文档（V2.2 §10.4.1 推导） | PROVISIONAL（候选合同） |
| 失效参数 | COM_OF_LOSS_T、COM_OBL_RC_ACT、COM_POSCTL_NAVL、COM_RC_IN_MODE 等名称来自 PX4 官方文档；实际取值 UNKNOWN | 官方网页 + 文档 | UNKNOWN（取值） |

### C.2 缺失项与获取方法（建议直接形成证据包）

| 缺失项 | 影响 | 如何取得（待实机验证的命令/路径） | 归档要求 |
| --- | --- | --- | --- |
| 实机固件 tag/commit | 无法建立固件版本矩阵；无法复现 SITL/HIL 与实机差异 | PX4 控制台执行 `ver all`（命令名以实际固件 shell 为准）；QGC MAVLink Console / Analyze；飞控启动 banner 与日志（ulog）中的版本串；若是自定义构建，记录 `git describe --always --dirty` 与编译参数 | 固件二进制（.px4/.bin）+ SHA-256 + 版本串截图 + 构建日志 |
| 参数全量导出 | TTL、failsafe、EKF2 行为不可复现；无法做失效矩阵 | QGC 参数导出（菜单名以实际 QGC 版本为准）或 PX4 shell 参数 dump；至少单独记录 COM_OF_LOSS_T、COM_OBL_RC_ACT、COM_POSCTL_NAVL、COM_RC_IN_MODE 与 EKF2_* 关键项 | 参数文件 + 导出日期 + 固件版本 + SHA-256 |
| v_xy_valid/v_z_valid 等有效性映射 | 无法执行“估计无效即拒绝动作”的合同；零值伪装风险 | 用 MAVLink Inspector 列实际可用消息（ODOMETRY、ESTIMATOR_STATUS、LOCAL_POSITION_NED、ATTITUDE 等）；核对 reset counter/quality/frame 字段；对照实际固件源码；做断流、遮挡、强光、低纹理故障注入 | 消息清单 + 字段映射表 + 故障注入记录（含拒绝动作日志） |
| type_mask 1479/1511 实机接受与失效行为 | 垂直控制完整性与“忽略 vz 自动放行”均不能确认 | SITL/HIL 注入两种掩码，记录 PX4 模式、目标回显（若固件支持）、速度响应、失效行为；再上受控实机低速 | SITL/HIL 日志 + 实机记录 + 结论标签（未过则 NOT RUN） |
| PX4 failsafe 参数与行为 | Offboard Loss/Position Loss/Kill Switch 无法写入 G8 放行证据 | 参数快照 + 故障注入矩阵（链路中断、估计失效、超时），按 V2.2 §17.4/§28.5 记录实际模式 | 故障注入矩阵 + 参数快照 + 飞控日志 |

### C.3 状态有效性与控制权限（合同要求，未实现）

- V2.2 §16.9 明确：`v_xy_valid`/`v_z_valid` 是**项目内部归一化状态名**，不是标准 MAVLink 速度消息原生字段。必须先列出实际固件可获取的消息、估计健康位、时间戳、重置计数与逐轴有效性映射；仅有有限速度数值不能置为有效，未获得可信映射时标 UNKNOWN 并拒绝相应动作。
- V2.2 §26.6 控制权限最低条件：正常水平速度 = ATTITUDE_VALID + ANGULAR_RATE_VALID + XY_VELOCITY_VALID；正常垂直速度加 Z_VELOCITY_VALID；正常偏航角速度 = ATTITUDE_VALID + ANGULAR_RATE_VALID；碰撞后各分支另有推力源/高度/视觉条件。**这些状态当前均无实机映射证据。**
- 结论：C 节所有“取得/验证”项都是待办，不得把 PX4 1.17 的用户确认扩写成速度 Offboard、validity 映射或 failsafe 已验证。

## D. Schema 差异（v1 → V2.2 Action Schema v2.0）

对照对象：`src/boom_birds/contracts` 的 `boom_birds.velocity.v1` ↔ V2.2 §16.3 MessageHeader、§16.6 ActionEnvelope、§10.4 NormalVelocityAction。机器可读版本见 [phase0_schema_diff.json](phase0_schema_diff.json)。

**证据域：** 以下逐字段内容中，v2 要求来自【文档】（V2.2 条文），v1 现状来自【仓库文件】（`src/boom_birds/contracts`、`configs/runtime/default.yaml`）。v2 实现已于盘点期间由 G2.6 提交（【仓库文件】，见 [G2.6 报告](../g2_6/G2_6_CONTRACTS_REPORT.md)），但其固件/板端状态仍是【未验证】/NOT RUN；本报告只描述迁移要求，不重复验收该实现。

### D.1 v1 快照（仓库文件）

| 字段 | 类型 | 语义 | 证据 |
| --- | --- | --- | --- |
| velocity_enu_mps | tuple[float,float,float] | ENU 三轴速度（已由 yaw 旋转后的中间表示） | src/boom_birds/contracts/types.py L30 |
| yaw_rate_rad_s | float | ENU 逆时针偏航率，发 NED 前取负 | types.py L31; frames.py L49-50 |
| created_ns | int | 动作创建时刻（发送方不得刷新） | types.py L32 |
| valid_until_ns | int | 到期时刻，now >= valid_until_ns 即拒绝 | types.py L33; timebase.py L33 |
| mission_epoch | int | 任务/架次级 epoch | types.py L34 |
| source | str ('policy') | 动作来源（单一字符串） | types.py L35 |
| origin_epoch | int | 原点重置代际（v1 自定义） | types.py L36 |
| clock_id | str ('host_monotonic') | 时钟域名（字符串） | types.py L37 |
| schema_id | str ('boom_birds.velocity.v1') | 版本标签（类默认值） | types.py L5, L38 |

模块常量：`SCHEMA_ID = "boom_birds.velocity.v1"`（`types.py` L5）。v1 的关键特征：单一 `mission_epoch` + 自定义 `origin_epoch`；字符串 `clock_id`；载荷存 **ENU 中间表示**；无 header、无序号、无观测溯源、无逐轴有效性、无 quarantine。v1 的 33 条回归测试证明的是这些既有行为，不代表 v2。

### D.2 MessageHeader（§16.3）逐字段对照

| 字段 | 类型 | v2 要求/说明 | v1 是否存在 | 迁移动作 |
| --- | --- | --- | --- | --- |
| system_boot_id | uint64 | Companion 进程/系统启动标识 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| px4_boot_id | uint64 | PX4 单独重启必须更换并作废旧映射 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| clock_id | uint64 | 有版本的时钟域标识（v1 为字符串，迁移需注册表） | 部分存在（str，无域注册表/代际/误差界） | 字段名保留但语义不足：新增域注册表/代际/误差界；缺失即拒绝，禁止默认 0 |
| mission_epoch | uint64 | 单架次 | 存在（仅此一项） | 字段保留，但必须与 system/localization/control 三级上下文联合校验；单独 mission_epoch 不足以放行 |
| localization_epoch | uint64 | 碰撞/定位重置递增 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| control_epoch | uint64 | 控制所有权交接递增 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| sequence_id | uint64 | 序号（动作侧按 boot_id/control_epoch/source 严格递增） | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| capture_timestamp_ns | uint64 | 采集时刻；年龄判断基准 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| receive_timestamp_ns | uint64 | 接收时刻 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| publish_timestamp_ns | uint64 | 发布时刻 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| source_id | uint32 | 消息源标识 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| schema_version | uint32 | 与 v1 字符串 schema_id 类型不一致 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| sync_generation | uint64 | 跨设备时间映射代际 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| timestamp_uncertainty_ns | uint64 | 误差界；年龄取最坏值 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| sync_valid | bool | 同步质量是否可信 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| quarantine | bool | 碰撞不确定区间内的数据隔离标记 | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |
| valid | bool | 消息级有效性（不得以 0 伪装有效） | 缺失 | 新增并纳入消费端逐项校验；v1 无对应字段，缺省/补 0 一律拒绝 |

### D.3 ActionEnvelope（§16.6）逐字段对照

| 字段 | 类型 | v2 要求/说明 | v1 是否存在 | 迁移动作 |
| --- | --- | --- | --- | --- |
| header | MessageHeader | 承载 §16.3 header，含 clock_id/px4_boot_id/sync_generation | 缺失（v1 无 header 结构） | 新增；缺失即拒绝 |
| observation_id | id | 动作溯源到观测 | 缺失 | 新增；缺失即拒绝 |
| input_capture_interval_ns | [start,end] | 输入采集时间范围 | 缺失 | 新增；缺失即拒绝 |
| earliest_input_safe_deadline_ns | uint64 | 由输入年龄+误差界推导的最早安全截止 | 缺失 | 新增；缺失即拒绝 |
| action_id | id | 动作身份，重发必须完全一致 | 缺失 | 新增；缺失即拒绝 |
| action_type | enum | 例如 BODY_VELOCITY | 缺失 | 新增；缺失即拒绝 |
| coordinate_frame | enum | 例如 COMPOSITE_BODY_HEADING_FLU_WORLD_UP | 缺失 | 新增；缺失即拒绝 |
| units | 声明 | 物理单位 m/s、rad/s，禁止归一化混用 | 缺失 | 新增；缺失即拒绝 |
| issued_at_monotonic_ns | uint64 | 与 expires 同一单调域 | 部分对应 `created_ns` | 保留等价语义但改名/改公式/改枚举；不得只换标签 |
| expires_at_monotonic_ns | uint64 | = min(issued+ttl, earliest_input_safe_deadline) | 部分对应 `valid_until_ns`（公式不同） | 保留等价语义但改名/改公式/改枚举；不得只换标签 |
| max_age_ms | number | 最大允许年龄（与 TTL 分离） | 缺失 | 新增；缺失即拒绝 |
| sequence_id | uint64 | ADMIT_NEW 严格递增；SEND_CACHED 不递增 | 缺失 | 新增；缺失即拒绝 |
| source | enum(STUDENT/RECOVERY/SAFETY) | 控制所有权来源 | 部分对应 `source`（枚举不同） | 保留等价语义但改名/改公式/改枚举；不得只换标签 |
| policy_version | 版本 | 模型/策略版本 | 缺失 | 新增；缺失即拒绝 |
| payload | object | 具体动作载荷 | 缺失 | 新增；缺失即拒绝 |
| validity_mask | mask | 载荷有效性（不替代逐轴 validity） | 缺失 | 新增；缺失即拒绝 |

### D.4 NormalVelocityAction（§10.4）逐字段对照

| 字段 | 类型 | v2 要求/说明 | v1 是否存在 | 迁移动作 |
| --- | --- | --- | --- | --- |
| schema_version | str '2.0'（示例） | 与 header.schema_version(uint32) 类型不一致，需统一 | 部分对应 `schema_id`（str） | 语义/类型/坐标系不一致：显式适配并写回归测试，禁止只改字段名 |
| action_type | enum 'BODY_VELOCITY' | 动作类型 | 缺失 | 新增；缺失即拒绝 |
| clock_id | uint64 | 与 header 重复定义 | 部分存在（str→uint64） | 语义/类型/坐标系不一致：显式适配并写回归测试，禁止只改字段名 |
| px4_boot_id | uint64 | 与 header 重复定义 | 缺失 | 新增；缺失即拒绝 |
| sync_generation | uint64 | 与 header 重复定义 | 缺失 | 新增；缺失即拒绝 |
| observation_id | id | 与 envelope 重复定义 | 缺失 | 新增；缺失即拒绝 |
| input_capture_interval_ns | range | 与 envelope 重复定义 | 缺失 | 新增；缺失即拒绝 |
| earliest_input_safe_deadline_ns | uint64 | 与 envelope 重复定义 | 缺失 | 新增；缺失即拒绝 |
| frame | enum 'COMPOSITE_BODY_HEADING_FLU_WORLD_UP' | v1 无；显式声明 vx/vy 随航向、vz 世界 Up | 缺失 | 新增；缺失即拒绝 |
| component_frames | object{vx_forward,vy_left,vz_up,yaw_rate_ccw_world} | 逐分量坐标系声明 | 缺失 | 新增；缺失即拒绝 |
| vx_forward_mps | float | 水平前向速度（BODY_HEADING_FLU） | 部分（v1 存 ENU，需再旋转） | 语义/类型/坐标系不一致：显式适配并写回归测试，禁止只改字段名 |
| vy_left_mps | float | 水平左向速度 | 部分（同上） | 语义/类型/坐标系不一致：显式适配并写回归测试，禁止只改字段名 |
| vz_up_mps | float | 世界 Up 速度 | 部分（v1 为 ENU up） | 语义/类型/坐标系不一致：显式适配并写回归测试，禁止只改字段名 |
| yaw_rate_ccw_world_radps | float | 绕世界 Up 逆时针偏航率 | 存在（`yaw_rate_rad_s`） | 改名并显式声明坐标系；到 NED 取负号，需 SITL 单测覆盖正负方向 |
| axis_validity | object{vx,vy,vz,yaw_rate} | 逐轴有效性；v1 完全缺失 | 缺失 | 新增；缺失即拒绝 |
| system_boot_id | uint64 | 与 header 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| mission_epoch | uint64 | 与 header 重复定义 | 存在 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| localization_epoch | uint64 | 与 header 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| control_epoch | uint64 | 与 header 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| sequence_id | uint64 | 与 header/envelope 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| issued_at_monotonic_ns | uint64 | 与 envelope 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| expires_at_monotonic_ns | uint64 | 与 envelope 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| policy_version | 版本 | 与 envelope 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |
| source | enum | 与 envelope 重复定义 | 缺失 | 与 header/envelope 重复定义：先确定唯一权威来源，见 D.6 第 9 条 |

### D.5 v1 字段去向（关键映射）

| v1 字段 | v2 对应 | 变化类型 | 严重度 | 迁移动作 |
| --- | --- | --- | --- | --- |
| velocity_enu_mps | frame + component_frames + vx_forward_mps/vy_left_mps/vz_up_mps | split_reframe | critical | v2 载荷改存 BODY_HEADING_FLU 物理速度；ENU 仅作为 v1 中间表示保留在旧适配层；禁止对 v2 载荷再次 yaw 旋转（防止二次旋转） |
| yaw_rate_rad_s | yaw_rate_ccw_world_radps + component_frames.yaw_rate_ccw_world | rename_semantics_declared | medium | 重命名并显式声明坐标系；到 NED 仍取负号，需 SITL 单测覆盖正负方向 |
| created_ns | issued_at_monotonic_ns | rename | low | 同义重命名；Sender 不得刷新 issued_at，重发必须沿用原值 |
| valid_until_ns | expires_at_monotonic_ns + max_age_ms + earliest_input_safe_deadline_ns | semantic_change | critical | 到期不再固定为 created+ttl，必须取 min(issued+action_ttl, earliest_input_safe_deadline)；边界仍为 now >= expires 拒绝 |
| mission_epoch | mission_epoch（保留）+ system_boot_id/localization_epoch/control_epoch | extends_to_quartet | critical | 从单 epoch 扩展为四级上下文；消费者必须逐项校验，不得只校验 mission_epoch |
| source | source ∈ {STUDENT, RECOVERY, SAFETY} + header.source_id | enum_change | medium | v1 'policy' 映射为 STUDENT 且必须显式赋值；所有权与 source 必须一致（§16.8） |
| origin_epoch | localization_epoch + control_epoch | split | critical | v1 origin_epoch 语义拆分为定位代际与控制代际；迁移需在 ADR 中记录映射，禁止继续用单一 origin_epoch 代替两者 |
| clock_id | clock_id(uint64) + sync_generation + timestamp_uncertainty_ns + sync_valid | type_change_split | critical | v1 字符串时钟域名改为版本化 uint64 时钟域注册表；新增映射代际与误差界；跨域比较前必须验证映射有效，无法证明年龄则拒绝 |
| schema_id | header.schema_version(uint32) + §27.1 兼容矩阵 | type_change | medium | 'boom_birds.velocity.v1' 常量不得改为 v2 标签；新增独立 v2 schema 标识与 schema_version 数值，旧对象显式转换 |

### D.6 语义级差异：不是改字段名能解决的

1. **TTL 起点与截止**：v1 `valid_until_ns = created_ns + ttl_ns`；V2.2 要求 `expires_at = min(issued_at + action_ttl, earliest_input_safe_deadline)`，后者由各必需输入的采集时刻、最大允许年龄和时钟误差界决定。否则慢推理会生成“新鲜动作”（§16.6）。
2. **四级上下文**：v1 只有 `mission_epoch` 与自定义 `origin_epoch`；v2 要求 `system_boot_id`、`mission_epoch`、`localization_epoch`、`control_epoch` 加 `px4_boot_id`，消费者逐项校验（§16.2/§27.2）。
3. **时钟域**：v1 `clock_id` 是字符串，只能表达“同一域/不同域”；v2 要求版本化 `clock_id`（uint64）+ `sync_generation` + `timestamp_uncertainty_ns` + `sync_valid`，且年龄取包含误差界的最坏值（§16.3.2）。
4. **动作身份与重发**：v1 没有 `sequence_id`/`action_id`，无法区分 ADMIT_NEW 与 SEND_CACHED；v2 要求新接纳严格递增、缓存重发完全一致且不续期（§16.6 TTL 规则 5、§27.3）。
5. **逐轴有效性**：v1 只有消息级 `command_is_valid`；v2 要求 `axis_validity{vx,vy,vz,yaw_rate}`，`v_xy_valid=false` 拒绝水平速度，`v_z_valid=false` 拒绝整个正常速度动作（1511 默认拒绝），不得用 0 伪装有效（§10.4.2/§10.4.3/§26.6）。
6. **坐标系与二次旋转**：v1 `decode_action` 已把 4D 归一化动作旋转成 ENU；v2 载荷要求 BODY_HEADING_FLU 物理单位并带 `frame`/`component_frames`，ENU 只能作为旧适配层中间表示。迁移若沿用 v1 的旋转结果会二次旋转（§10.4.1）。
7. **quarantine**：v1 无隔离概念；v2 要求碰撞不确定区间的图像/状态隔离并被消费端以 `REJECT_QUARANTINE` 拒绝（§16.3.1/§27.2）。
8. **日志与版本矩阵**：v1 无日志字段合同；v2 要求每次发布/拒绝记录 §27.7 全字段（含 reject_reason、实际 MAVLink message ID），并按 §27.1 声明 Schema/Producer/Consumer/Firmware/Model/Map 版本。
9. **规范内部冲突（必须先登记再实现）**：§10.4 的 `NormalVelocityAction` 同时携带与 `MessageHeader`/`ActionEnvelope` 重复的上下文、时间、序号、来源字段；且 §10.4 示例 `schema_version: "2.0"`（字符串）与 §16.3 `schema_version: uint32` 类型不一致。实现前必须确定唯一权威来源（建议 header 唯一持有上下文）并在 `SPEC_DISCREPANCIES`/决策记录中登记，禁止两处各自赋值。

### D.7 显式迁移要求（合同级，缺一不可）

| 编号 | 要求 | 依据 | 验证方式（尚未运行） |
| --- | --- | --- | --- |
| MIG-01 | 新增独立 v2 模块与 schema 标识，不修改 v1 行为；v1 33 条回归测试必须继续通过 | §25, §27.1 | 全新 schema id + schema_version；v1 文件不改语义 |
| MIG-02 | v1→v2 转换必须显式传参：system_boot_id、px4_boot_id、localization_epoch、control_epoch、clock_id(clock domain registry)、sync_generation、observation_id、input_capture_interval_ns、earliest_input_safe_deadline_ns、axis_validity、sequence_id | §16.3, §16.6, §10.4 | 缺任一项即拒绝转换，禁止用 0/当前时刻/默认字符串补齐 |
| MIG-03 | 轴有效性不得从速度数值推断：v_xy_valid=false 拒绝水平速度；v_z_valid=false 拒绝整个正常速度动作，1511 默认拒绝 | §10.4.2, §10.4.3 | 单元测试覆盖四轴组合与 default-deny |
| MIG-04 | TTL 语义改为 expires_at = min(issued_at + action_ttl, earliest_input_safe_deadline_ns)，Sender 不得刷新 issued_at | §16.6, §27.5 | 边界测试 now>=expires；慢推理场景测试 |
| MIG-05 | 序号与重发：ADMIT_NEW 严格递增；SEND_CACHED 要求 action_id/payload 摘要/源时间/上下文完全一致且仍为当前缓存动作，不递增、不续期 | §16.6 规则 5, §27.3 | 乱序/复用/回滚缓存拒绝测试 |
| MIG-06 | 时钟域：字符串 clock_id 改为版本化 uint64 域 + sync_generation + 误差界；跨域比较需有效映射，否则拒绝并标 UNKNOWN | §16.1, §16.3.2 | 不同类型/域不匹配测试；最坏年龄计算测试 |
| MIG-07 | 坐标系单向链：策略 4D 归一化 → v2 载荷(BODY_HEADING_FLU 物理单位) → PX4 Adapter(LOCAL_NED, 有效 yaw) ；禁止二次旋转与在 v2 载荷重做 ENU 中间层 | §10.4.1, §10.4.2, §26.3 | 四航向、vz 符号、yaw-rate 符号 SITL 单测计划（未运行） |
| MIG-08 | Epoch：origin_epoch 拆分为 localization_epoch + control_epoch；任何交接必须递增 control_epoch（含 PENDING→ACTIVE 过程） | §16.2, §16.4, §16.8 | 交接期间动作到达测试；旧 owner 发包拒绝测试 |
| MIG-09 | PX4 单独重启：生成新 px4_boot_id、作废时间映射/状态缓存/在途动作与推理，递增 epoch 并退出正常控制 | §16.3.2 | boot_id 变化拒绝对应动作；与 Companion 重启区分测试 |
| MIG-10 | 日志最小字段按 §27.7 输出，含 reject_reason 与实际 MAVLink message ID；不得只记录成功发送 | §27.7 | 日志字段 schema 测试（未实现） |
| MIG-11 | 版本矩阵：Schema/Producer/Consumer/Firmware/Model/Map 版本声明，不兼容拒绝启动或显式降级 | §27.1 | 启动检查测试（未实现） |
| MIG-12 | 规范歧义登记：NormalVelocityAction 与 Header/Envelope 的上下文重复、schema_version 字符串 vs uint32，先登记再实现 | §10.4 vs §16.3/§16.6 | SPEC_DISCREPANCIES 条目 + 决策记录 |

### D.8 机器可读 JSON 与校验结果

文件：[phase0_schema_diff.json](phase0_schema_diff.json)。结构：`schema_diff_id`、`snapshot`、`schema_ids`、`v1_fields`、`v2_structures`（MessageHeader/ActionEnvelope/NormalVelocityAction）、`field_diffs`、`migration_requirements`、`gaps`、`evidence_index`、`not_verified`、`summary`。

| 统计项 | 数值 |
| --- | --- |
| v1 字段数 | 9 |
| MessageHeader 字段数（§16.3） | 17 |
| ActionEnvelope 字段数（§16.6） | 16 |
| NormalVelocityAction 字段数（§10.4） | 24 |
| 字段级差异条目 | 38 |
| 其中 v1 缺失 | 28 |
| 其中改名/语义变化 | 9 |
| 其中规范重复定义 | 1 |
| 迁移要求条数 | 12 |
| 缺口条数 | 25 |

**校验命令与结果（2026-10-31 实际执行）：**

```powershell
& 'E:\isaac\env_isaaclab\Scripts\python.exe' -c "import json;json.load(open(r'E:\isaac\proj_boom_birds\docs\reports\p0\phase0_schema_diff.json',encoding='utf-8'));print('JSON_OK')"
```

结果：`JSON_OK`，退出码 **0**（项目解释器；Python 3.11.9 见 P0 报告；未安装新依赖）。

注意：JSON 只是差异索引，不替代规范正文；若与 §10.4/§16 冲突，以正文为准，并把冲突登记为规范缺口，不得两边并存。

## E. 最小缺口表（需要用户或实物才能补齐）

按类别分组，编号与 JSON `gaps` 数组一致。标签沿用 LOCKED/BASELINE/PROVISIONAL/TBD/UNKNOWN/RULE-CHECK/NOT RUN/未验证，不使用 PASS。

### E.1 规则来源

| ID | 条目 | 当前状态 | 证据域 | 标签 | 补齐方式 | 负责 |
| --- | --- | --- | --- | --- | --- | --- |
| GAP-R01 | RMUC 2027 正式比赛规则手册原文（版本、条款号、PDF/SHA256） | 未取得：规则中心页面仅返回框架/标题 | 文档 + 官方网页 | RULE-CHECK | 用户登录官方论坛下载并归档；按 §24.5 记录 Rule ID/Manual Version/Section/URL/日期 | 用户 |
| GAP-R02 | RMUC 2027 机器人制作规范手册原文 | 未取得 | 文档 + 官方网页 | RULE-CHECK | 同上；至少归档尺寸/重量/桨保/电池相关条款页 | 用户 |
| GAP-R03 | 官方规则答疑原文（轻流面板 ID/日期/链接） | 未取得；仅有第三方索引与 V2.2 转述口径 | 文档 | RULE-CHECK | 逐条导出答疑原文截图/链接，补 Official Q&A ID 与日期 | 用户 |
| GAP-R04 | 4Wh 单机供电容量口径与电池计算方式 | V2.2 §2.2 转述；官方原文未取得 | 文档 | RULE-CHECK | 规则原文条款 + 官方答疑原文双证据；再结合铭牌复算 | 用户/规则 |
| GAP-R05 | 机库 300Wh 台账、触点充电许可、飞行期间可见光通信 | V2.2 转述；官方原文未取得 | 文档 | RULE-CHECK | 规则手册/制作规范对应章节 + 答疑原文 | 用户/规则 |
| GAP-R06 | 10s 悬停、紧急停桨接收机与安全员、桨叶全包围/柔性要求 | V2.2 §2.2 转述；官方原文未取得 | 文档 | RULE-CHECK | 规则原文；另需接收机实物与安全员流程 | 用户/规则 |

### E.2 实物/硬件

| ID | 条目 | 当前状态 | 证据域 | 标签 | 补齐方式 | 负责 |
| --- | --- | --- | --- | --- | --- | --- |
| GAP-H01 | 电池铭牌照片/型号/C 倍率/质量/满充电压/化学体系 | 无照片、无采购单据、无称重 | 仓库文件（仅型号记录）+ 未验证 | RULE-CHECK | 提供铭牌正反面照片与称重记录；确认为 LiHV 后按 11.4V×0.35Ah=3.99Wh 复算 | 用户 |
| GAP-H02 | RK3576 核心板/载板型号、BSP、CSI/USB/串口资源 | 锁定 RK3576，但板卡型号待定 | 文档 | TBD | 提供板卡型号/照片/BSP 版本；补 CSI lane 与 NPU 运行记录 | 用户 |
| GAP-H03 | MicoAir743V2-AIO 实板 revision、称重、BEC 带载 | 仅厂商页面（10g/5V2A 口径，来自历史登记） | 仓库文件 + 官方网页 | BASELINE | 实板称重与照片；记录 revision 丝印 | 用户 |
| GAP-H04 | OV9782/OV9281 模组型号、镜头、FOV、lane 数、帧率、像素格式 | 仅有芯片级属性；模组/镜头待确认 | 官方网页 + 文档 | PROVISIONAL | 提供模组型号与镜头参数；实测帧率/曝光/丢帧 | 用户 |
| GAP-H05 | MTF-02P 接口/电平/协议/时间戳/质量字段/安装倾角 | 厂商页面存在；具体接口未验证 | 官方网页 + 文档 | PROVISIONAL | 按 §4.2.3 12 项接口清单实测；附手册页 | 用户 |
| GAP-H06 | VL53L8CX 模组总线、地址、电压、最大稳定更新率、Zone 布局 | 芯片级资料；模组待定 | 官方网页 + 文档 | PROVISIONAL | 模组手册 + 实测更新率/无效 Zone 统计 | 用户 |
| GAP-H07 | 整机重量闭合、推力台数据、功耗曲线（BB22:G0.5） | 无实测；160g 仅参考 | 文档 | UNKNOWN | 逐件称重+推力台+功率计，形成 G0.5 报告 | 用户/团队 |
| GAP-H08 | 紧急停桨遥控器/接收机型号与独立链路 | 仅规则口径，无实物记录 | 文档 | RULE-CHECK | 提供接收机型号与接线；验证独立于 RK3576 | 用户 |
| GAP-H09 | 机库触点接口与 DockLink 协议 | 物理方式 LOCKED；协议 TBD | 文档 | TBD | 提供机库接口定义；先做触点电阻/数据完整性台架 | 用户/团队 |

### E.3 PX4 固件与参数

| ID | 条目 | 当前状态 | 证据域 | 标签 | 补齐方式 | 负责 |
| --- | --- | --- | --- | --- | --- | --- |
| GAP-F01 | 实际刷写 PX4 固件 tag/commit | 仅有用户确认 1.17；无 tag/commit/构建 SHA | 文档（用户确认转述） | UNKNOWN | PX4 控制台 `ver all`（待验证命令）或 QGC MAVLink Console 输出；自定义构建需 build SHA；归档 .px4/.bin + SHA256 | 用户 |
| GAP-F02 | PX4 参数全量导出与冻结参数表 | 无参数文件 | 未验证 | UNKNOWN | QGC 参数导出或 PX4 shell 参数 dump；至少含 COM_OF_LOSS_T/COM_OBL_RC_ACT/COM_POSCTL_NAVL/COM_RC_IN_MODE/EKF2_* | 用户 |
| GAP-F03 | v_xy_valid/v_z_valid 等有效性映射到实际固件消息/健康位 | V2.2 §16.9 要求；仓库无映射记录 | 文档 + 未验证 | UNKNOWN | 列出实际可用消息（ODOMETRY/ESTIMATOR_STATUS/LOCAL_POSITION_NED 等）、reset counter、time stamp；做故障注入 | 团队 |
| GAP-F04 | type_mask 1479/1511 在实际固件接收路径的接受与失效行为 | 仅在 PX4 v1.16.0 源码核对 LOCAL_NED 分支；未做实机/SITL | 官方网页（源码）+ 未验证 | PROVISIONAL | SITL/HIL 注入 1479/1511，记录模式、推力来源、失效行为 | 团队 |
| GAP-F05 | PX4 失效参数与模式行为（Offboard Loss / Position Loss / Kill Switch） | 仅有官方文档口径；无实机记录 | 官方网页 + 文档 | UNKNOWN | 故障注入矩阵 + 参数快照；按 §17.4/§28.5 | 团队 |

### E.4 Schema/规范

| ID | 条目 | 当前状态 | 证据域 | 标签 | 补齐方式 | 负责 |
| --- | --- | --- | --- | --- | --- | --- |
| GAP-S01 | v2 合同实现（MessageHeader/ActionEnvelope/NormalVelocityAction/仲裁/所有权/Epoch） | 已由 G2.6 提交（c730c75，自评 101 passed）；本报告未复跑其测试，Gate 自评 INCOMPLETE | 仓库文件 + 文档（G2.6 报告） | IN PROGRESS | 复核 G2.6 报告与测试证据；按 §28.3 完成板端/固件复检后才可重评 Gate | 团队 |
| GAP-S02 | 上下文/时间字段唯一权威来源（action 与 header 重复） | V2.2 §10.4 与 §16.3/§16.6 重复定义 | 文档 | TBD | SPEC_DISCREPANCIES 登记 + 决策记录后统一 | 团队 |
| GAP-S03 | schema_version 类型冲突（§10.4 字符串 '2.0' vs §16.3 uint32） | 文档内部不一致 | 文档 | TBD | 规范修订或实现侧统一映射；登记后禁止两边并存 | 团队 |
| GAP-S04 | MAVLink common 字段正文未完整提取（页面体积） | 页面可达但正文未取得 | 官方网页（部分） | 未验证 | 以 MAVLink common.xml 或本地 pymavlink 方言核对 type_mask/字段单位；记录版本 | 团队 |
| GAP-S05 | v1 origin_epoch 到 localization/control 的语义映射决策 | v1 自定义字段，v2 无对应单字段 | 文档 | TBD | ADR 记录映射与失效条件 | 团队 |

### E.5 最小放行前置集（建议排序，不是已完成）

| 目标 | 必须先闭合的缺口 | 说明 |
| --- | --- | --- |
| BB22:G0（规则/需求/硬件边界/接口记录） | R01–R06、H01、H02、S02、S03 | 规则原文与答疑原文是 G0 的硬前提；电池铭牌与板卡型号决定后续 BOM/供电/接口 |
| BB22:G2.6（纯软件合同） | S05（S01 已由 G2.6 提交但未复跑） | 软件合同层已有提交证据且自评 INCOMPLETE；不得据此声称固件掩码/validity 已验证 |
| BB22:G1（飞控基础） | F01–F05、H03–H06 | 固件 tag/commit、参数导出、validity 映射、type_mask 实机行为缺一不可 |
| BB22:G0.5（重量/推进/供电门） | H07 | 需要称重、推力台、功率计实测，不能用厂商口径代替 |
| BB22:G11（机库） | H09 | 触点电气与协议台架先行 |

## F. 本次执行记录、限制与未验证项

### F.1 实际执行

- 读取（read 工具）：`AGENTS.md`、`PROJECT_PLAN.md`、`docs/reports/ROUTE_V2_2_REVIEW_20261031.md`、`docs/reports/p0/P0_ENVIRONMENT_REPORT.md`、`docs/reports/p0/UPSTREAM_REVIEW.md`、`third_party/NOTICE.md`、`docs/design/RMUC2027_UAV_V2_2.md` 第 2、4、10.4、16、19、20、24、26–28 章、`src/boom_birds/contracts/{types,frames,timebase}.py`、`tests/contracts/*.py`、`configs/runtime/default.yaml`，以及 `docs/planning/`、`docs/decisions/` 相关记录。
- 只读检查：`git status`、`git log`、`env/manifests`、`docs/superpowers/plans`。
- Web：检索/抓取 16 个 URL；检索日期 2026-10-31；取得程度逐条见 A.1 与 G。
- 写入：仅 `docs/reports/p0/PHASE0_SOURCE_INVENTORY_20261031.md` 与 `docs/reports/p0/phase0_schema_diff.json`；未改其它文件；未 git add/commit。
- JSON 校验：`json.load(..., encoding="utf-8")` → JSON_OK，exit 0。
- 未执行：pytest、SITL/HIL、训练、固件读写、依赖安装、文档审计脚本。

### F.2 未能取得的官方来源（明确列出，不替代）

| 来源 | 访问 URL（2026-10-31） | 取得程度 | 后续取得方式 |
| --- | --- | --- | --- |
| RMUC 2027 规则手册 | https://bbs.robomaster.com/wiki/20204847/1969149?source=7 | 仅页面框架（title=RoboMaster 社区） | 登录官方论坛下载 PDF，归档并记 SHA-256 |
| 规则文件目录 | https://bbs.robomaster.com/wiki/20204847/809871?source=7 | 仅页面框架 | 同上 |
| 机器人制作规范手册（2027） | 规则中心内入口，未取得直属 URL | 未取得 | 同上 |
| 官方答疑原文 | 无公开直达链接 | 未取得 | 导出轻流面板原文（ID/日期/截图） |
| 场地图纸本体 | https://bbs.robomaster.com/article/1970956 | 仅标题+描述（提到规则手册 V1.0.0） | 下载官方 STEP/图纸并记版本与 SHA-256 |
| MAVLink common 字段正文 | https://mavlink.io/en/messages/common.html | 页面 200，正文因体积未完整提取 | 用 common.xml 对应版本或 pymavlink 方言核对字段/掩码并记录版本 |
| OVT/ST/MicoAir 产品页正文 | 见 G | 多数仅取得标题级（页面 200） | 以数据手册/模组说明书补齐模组级参数 |

### F.3 未验证项（不得写成 PASS）

- PX4 实际刷写固件的 tag/commit、参数导出、状态消息有效性映射：UNKNOWN（仅用户确认 1.17）
- type_mask 1479/1511 在实际固件/SITL 的接受与失效行为：PROVISIONAL，未测试
- RMUC 2027 规则手册/制作规范/答疑原文：RULE-CHECK，未取得
- 电池铭牌、化学体系、C 倍率、质量、4Wh 合规：RULE-CHECK/UNKNOWN
- 所有传感器模组的接口、帧率、标定：PROVISIONAL
- 整机重量、推力、功耗、温度：UNKNOWN（BB22:G0.5 未验收）
- v2 合同实现：已由 G2.6 提交（c730c75/533708e），但本报告未复跑其测试；其 Gate 自评 INCOMPLETE，见 [G2.6 报告](../g2_6/G2_6_CONTRACTS_REPORT.md)

## G. 参考来源（URL + 检索日期 2026-10-31）

下表与本报告正文、[phase0_schema_diff.json](phase0_schema_diff.json) 的 `evidence_index` 一致。抓取工具为 web_fetch；取得程度是本次实际结果，不代表页面永久有效。

| ID | 类型 | 来源/说明 | URL | 日期 |
| --- | --- | --- | --- | --- |
| EV-01 | 仓库文件 | src/boom_birds/contracts/types.py / frames.py / timebase.py（v1 合同） | （仓库内文件） | 2026-10-31 |
| EV-02 | 仓库文件 | tests/contracts/test_action_contract.py / test_timebase.py（v1 33 条回归来源） | （仓库内文件） | 2026-10-31 |
| EV-03 | 仓库文件 | configs/runtime/default.yaml（PROPOSED 仿真初值） | （仓库内文件） | 2026-10-31 |
| EV-04 | 文档 | docs/design/RMUC2027_UAV_V2_2.md §2/§4/§10.4/§16/§19/§20/§24/§26–28 | （仓库内文件） | 2026-10-31 |
| EV-05 | 文档 | docs/reports/ROUTE_V2_2_REVIEW_20261031.md（V2.2 验收与限制） | （仓库内文件） | 2026-10-31 |
| EV-06 | 文档 | docs/reports/p0/P0_ENVIRONMENT_REPORT.md / UPSTREAM_REVIEW.md / third_party/NOTICE.md | （仓库内文件） | 2026-10-31 |
| EV-07 | 文档 | docs/planning/10_CURRENT_FACTS_AND_ANALYSIS_20261011.md、01_INPUTS_AND_GATES.md、07_SOURCE_REGISTER.md、09_TARGET_TEAM_AND_INTERCEPTION.md（用户确认/历史模型） | （仓库内文件） | 2026-10-31 |
| EV-08 | 文档 | docs/decisions/ADR-001_PX4_OFFBOARD.md（速度接口与 20Hz/50Hz/150ms PROPOSED） | （仓库内文件） | 2026-10-31 |
| EV-09 | 官方网页 | https://www.robomaster.com/zh-CN/robo/rm?type=rm-process（2027 赛季页，含规则/资料中心入口） | https://www.robomaster.com/zh-CN/robo/rm?type=rm-process | 2026-10-31 |
| EV-10 | 官方网页 | https://bbs.robomaster.com/wiki/20204847/1969149?source=7（规则中心页面；仅框架/标题） | https://bbs.robomaster.com/wiki/20204847/1969149?source=7 | 2026-10-31 |
| EV-11 | 官方网页 | https://bbs.robomaster.com/wiki/20204847/809871?source=7（规则文件目录；仅框架/标题） | https://bbs.robomaster.com/wiki/20204847/809871?source=7 | 2026-10-31 |
| EV-12 | 官方网页 | https://bbs.robomaster.com/article/1970956（RMU 2027 场地图纸公告；SSR 标题+描述提到规则手册 V1.0.0） | https://bbs.robomaster.com/article/1970956 | 2026-10-31 |
| EV-13 | 官方网页 | https://docs.px4.io/v1.16/en/flight_modes/offboard（Offboard 模式页，标题可读） | https://docs.px4.io/v1.16/en/flight_modes/offboard | 2026-10-31 |
| EV-14 | 官方网页 | https://raw.githubusercontent.com/PX4/PX4-user_guide/main/en/flight_modes/offboard.md（2Hz、>1s、COM_OF_LOSS_T、COM_OBL_RC_ACT、支持消息组合） | https://raw.githubusercontent.com/PX4/PX4-user_guide/main/en/flight_modes/offboard.md | 2026-10-31 |
| EV-15 | 官方网页 | https://raw.githubusercontent.com/PX4/PX4-Autopilot/v1.16.0/src/modules/mavlink/mavlink_receiver.cpp（LOCAL_NED type_mask→trajectory_setpoint，忽略字段置 NaN） | https://raw.githubusercontent.com/PX4/PX4-Autopilot/v1.16.0/src/modules/mavlink/mavlink_receiver.cpp | 2026-10-31 |
| EV-16 | 官方网页 | https://docs.px4.io/v1.16/zh/config/safety（Safety 配置页，标题可读） | https://docs.px4.io/v1.16/zh/config/safety | 2026-10-31 |
| EV-17 | 官方网页 | https://mavlink.io/en/messages/common.html（页面可达，标题可读；正文因体积未完整提取） | https://mavlink.io/en/messages/common.html | 2026-10-31 |
| EV-18 | 官方网页 | https://mavlink.io/en/services/offboard_control.html（Offboard Control Protocol；消息清单可读） | https://mavlink.io/en/services/offboard_control.html | 2026-10-31 |
| EV-19 | 官方网页 | https://github.com/PX4/PX4-Autopilot/releases/tag/v1.17.0（标题为 v1.17.0 Stable Release） | https://github.com/PX4/PX4-Autopilot/releases/tag/v1.17.0 | 2026-10-31 |
| EV-20 | 官方网页 | http://www.rock-chips.com/a/en/products/RK35_Series/2024/1212/2033.html（RK3576：4×A72+4×A53 ≤2.2GHz、6TOPS NPU、LPDDR4/4x/5） | http://www.rock-chips.com/a/en/products/RK35_Series/2024/1212/2033.html | 2026-10-31 |
| EV-21 | 官方网页 | https://github.com/airockchip/rknn-toolkit2（官方工具链 README：支持 RK3576 Series；最新 v2.5.0） | https://github.com/airockchip/rknn-toolkit2 | 2026-10-31 |
| EV-22 | 官方网页 | https://www.ovt.com/products/ov9782/ 与 https://www.ovt.com/products/ov9281/（OVT 官方产品页，标题可读） | https://www.ovt.com/products/ov9782/ | 2026-10-31 |
| EV-23 | 官方网页 | https://www.st.com/en/imaging-and-photonics-solutions/vl53l8cx.html（ST 官方产品页，标题可读） | https://www.st.com/en/imaging-and-photonics-solutions/vl53l8cx.html | 2026-10-31 |
| EV-24 | 官方网页 | https://micoair.com/optical_range_sensor_mtf-02p/ 与 https://micoair.com/flightcontroller_micoair743v2_aio_45a/（厂商产品页，标题可读） | https://micoair.com/optical_range_sensor_mtf-02p/ | 2026-10-31 |
| EV-25 | 文档+仓库文件 | docs/reports/g2_6/G2_6_CONTRACTS_REPORT.md 与提交 c730c75/533708e（G2.6 v2 合同实现与证据；自评 INCOMPLETE） | （仓库内文件） | 2026-10-31 |

**报告自检（对照 V2.2 与仓库 AGENTS.md）：** 结论未与基线表冲突；未把未实测数值写成已达成；未引入旧口径（Pi 5、3S300、VIO 主定位、30s 硬限制等）；规则结论全部 RULE-CHECK；Schema 差异与迁移要求可追溯到 §10.4/§16/§27；本报告不构成任何 Gate 的 PASS 证据。

---

撰写：phase0-scout（受 lead 委托，共享任务 task-1）。本报告为 BB22:G2.6 与后续硬件工作的输入，不是验收结论。
