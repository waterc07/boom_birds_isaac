# 许可待决项与导出路径证据清单（YOLOv8n-pose / YOLOX-Nano / RKNN，2026-11-04）

> **状态：** EVIDENCE_ONLY（证据到此为止；许可与模型路线决策待用户，不替用户认定接受 AGPL）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §7/§11.1/§13（学习侧与证据边界，间接）；LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §4 准入项 A1/A5（许可决策、版本/硬件/导出证据）
> **证据域：** 官方网页与 License 原文 + 本机只读环境查询；文档/证据清单，**不是**模型效果、不是板端、不是导航验收
> **最后核对：** 2026-11-04

本文件只回答“官方原文与现场事实是什么、哪些仍需解释、哪些必须由用户决策”。它不构成法律意见，不构成许可接受动作，也不构成训练/部署放行。**未实测项标 UNKNOWN/TBD，未决解释标【未确认解释】。**

---

## 0. 结论摘要（先读这一段）

1. **主候选 YOLOv8n-pose 的代码/权重许可已由原文确证为 AGPL-3.0**：Ultralytics 仓库 v8.2.0 tag 的 LICENSE 与 FSF 官方 AGPL-3.0 文本**逐字节一致**（同为 34523 字节，sha256 同为 0d96a4ff…abcb0），官方 README 明确“AGPL-3.0 + Enterprise 双许可”【来源陈述】。
2. **三件事仍是未决解释，不能由本文或代理代替用户裁定**：AGPL §13 网络交互义务的触发范围；自训练权重/导出 ONNX 是否构成“based on the Program”（衍生作品）；闭源分发时的义务边界。【未确认解释｜PENDING_USER_DECISION】→ PD-001/002/003。
3. **拟用版本 ultralytics==8.2.0 有官方发布信息**：PyPI 上传时间 2024-04-17T04:38:42，License 字段 AGPL-3.0，requires_python >=3.8，依赖 torch>=1.8.0，export extra 含 onnx>=1.12.0；Python 3.8–3.12 分类器【来源陈述】。
4. **官方 docs/代码支持 pose 任务与自定义关键点数**：v8.2.0 docs 给出 kpt_shape: [17, 3] 与“自定义数据集”指引，动物姿态示例为 12 关键点；v8.2.0 代码从 data yaml 读取 kpt_shape 并构造 PoseModel(data_kpt_shape=...)，因此 **1 关键点在代码路径上合法**（是否“好用/可导出可量化”另论）【来源陈述】。
5. **ONNX 导出有官方命令**：yolo export model=path/to/best.pt format=onnx，参数含 imgsz/half/dynamic/simplify/opset；官方 docs 未给 pose 专门限制；RKNN Model Zoo 的 yolov8n-pose.onnx 资产说明官方生态中 pose→ONNX 已被实际使用。**我们的自定义 1 关键点 ONNX 尚未导出过 → UNKNOWN**。
6. **备选 YOLOX-Nano 的代码许可为 Apache-2.0（原文确证）**；yolox_nano.pth 权重公开可下载（0.1.1rc0），但**权重自身许可声明与 COCO 数据集条款未在可检索原文中确证** → 未确认；**只作备选，绝不自动切换**（PD-005）。
7. **RKNN Model Zoo 存在 yolov8_pose 示例并声明支持 RK3576**；示例 README 给出 convert.py 命令，Model Zoo 基准表 RK3576 @single_core 对 yolov8n-pose 标 75.0 FPS（INT8，官方示例，非我们的模型）。**注意：RKNN-Toolkit2 不是 Apache-2.0，而是 Rockchip 专有的 “RKNN SDK License”**（本清单新增事实）。自定义 1-keypoint 的 RKNN 导出/量化/板端延迟 = **UNKNOWN**，并有代码级理由（PD-008）。
8. **RTX 5080 本机只读事实**：驱动 581.80（nvidia-smi 报 CUDA Version 13.0，为驱动支持的最高 API）、显存 16303 MiB、compute capability **12.0（sm_120）**；已装 torch 2.7.0+cu128，torch.cuda.get_arch_list() **包含 sm_120**；PyTorch 官方 cu128 索引存在 torch-2.7.0+cu128-cp311-cp311-win_amd64.whl（2025-04-22 上传）【来源陈述+本机事实】。
9. **但 ultralytics 8.2.0（2024-04）与 torch 2.7（2025-04）的组合没有官方兼容性声明**；本机 torch.load 签名默认 weights_only=True，而 8.2.0 早于该默认值生效期 → 必须隔离环境实测后才可称“可用”（安装/训练/导出在本任务被禁止，PD-009）。【未确认解释】
10. **不得把 RKNN 官方示例指标写成我们的模型效果、板端验收或导航能力**：75.0 FPS 是 Model Zoo 对 yolov8n-pose 的**官方示例基准（RK3576 单核、INT8、640×640、仅推理，不含前后处理）**；我们没有 RK3576 板卡、没有自定义模型、没有板端测量。使用边界见 §9。

---

## 1. 核查方法与现场

### 1.1 现场状态（2026-11-04）

- 仓库：E:\isaac\proj_boom_birds；分支 feat/v2.2-simulation-perception；HEAD 43fee3e02de57840e54297e8595924e2f213d722（2026-11-04 01:01:40 +0800，docs(perception): 完成地标任务定义、选型、标注样例与训练实验包）。
- 核查时 git status --short 出现 **其他并行 teammate 的未跟踪新文件**（configs/perception/landmark_training_plan_v2.json、docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md、docs/reports/perception/annotation_verify_20261104/、docs/superpowers/plans/2026-11-04-landmark-training-admission.md、tests/evaluation/test_landmark_dataset.py）。这些**不是本任务产出**，本任务未修改/未删除它们。
- 本任务只写 docs/reports/perception/license_evidence_20261104/；未改 outputs/、未改其他人的文件、未 commit/push。

### 1.2 做了与没做（硬约束自证）

| 项目 | 状态 |
| --- | --- |
| 安装训练依赖 / 升级包 | **未做**（本机 pip 只执行了 pip list 只读查询） |
| 下载模型权重 | **未做**（仅访问网页/原始文本） |
| 启动训练 / 模型加载 / 前向 / 导出 | **未做** |
| 修改 E:\isaac\env_isaaclab | **未做** |
| 运行 Isaac（含 headless） | **未做**（本任务不需要 Isaac；无 GUI 运行） |
| 只读环境查询 | 做了：python -c 读 torch/CUDA/包、nvidia-smi、pip list、文件搜索 |
| 官方网页/许可证原文 | 做了：Ultralytics/YOLOX/RKNN/PyTorch/GNU 官方页面与 raw 文件，抓取时间 2026-11-04 |

### 1.3 证据域与样本量口径

- 【来源陈述】= 官方项目/组织自己的原文陈述；样本量 = 抓取的官方页面/文件数（本文每条注明 N=1 或 N=2）。
- 【项目决策】= 本项目已做出的选择（如“主候选/备选/不选分割”“不自动切换”），来源是仓库配置而非外部原文。
- 【未确认解释】= 需法律/技术评审才能落地的解释；本文不替用户裁定，状态一律 PENDING 或 UNKNOWN。
- 本机事实 = **单机 1 次只读查询**（E:\isaac\env_isaaclab\Scripts\python.exe，Python 3.11.9，Windows 10.0.28120）；不是多机统计结论。

---

## 2. 主候选：Ultralytics YOLOv8n-pose

### 2.1 LICENSE 原文（AGPL-3.0）

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-01 | Ultralytics 仓库 **v8.2.0 tag** 的 LICENSE 是 GNU AGPL v3（2007-11-19）全文，且与 FSF 官方 AGPL-3.0 文本逐字节一致 | 【来源陈述】 | EVIDENCED | 官方文件 2 份（Ultralytics v8.2.0 LICENSE + gnu.org agpl-3.0.txt），N=2；sha256 相同 |

**原文摘录（Ultralytics v8.2.0 LICENSE，第 1–2 行）**

~~~text
                    GNU AFFERO GENERAL PUBLIC LICENSE
                       Version 3, 19 November 2007
~~~

- 出处：<https://github.com/ultralytics/ultralytics/blob/v8.2.0/LICENSE>（raw：<https://raw.githubusercontent.com/ultralytics/ultralytics/v8.2.0/LICENSE>）
- 对照：<https://www.gnu.org/licenses/agpl-3.0.txt>
- 核查计算结果：两份文本均 len=34523、sha256=0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0，规范化后字符串相等。
- 说明：main 分支 LICENSE 同为 AGPL-3.0（另抓 1 份，N=1）；版本 pin 以 v8.2.0 tag 为准。

### 2.2 官方 licensing 说明（AGPL + 商业许可双轨）

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-02 | 官方 README 声明两种许可：AGPL-3.0 开源许可；商业场景可购买 Enterprise License “bypassing the open-source requirements of AGPL-3.0” | 【来源陈述】 | EVIDENCED | 官方 README v8.2.0，N=1 |

**原文摘录（v8.2.0 README.md，License 段，约 L269–L274）**

~~~text
- **AGPL-3.0 License**: This OSI-approved open-source license is ideal for students and enthusiasts,
  promoting open collaboration and knowledge sharing. See the LICENSE file for more details.
- **Enterprise License**: Designed for commercial use, this license permits seamless integration of
  Ultralytics software and AI models into commercial goods and services, bypassing the open-source
  requirements of AGPL-3.0. ... reach out through Ultralytics Licensing.
~~~

- 出处：<https://github.com/ultralytics/ultralytics/blob/v8.2.0/README.md#L269-L274>
- 商业许可入口：<https://ultralytics.com/license>（README 引用；本任务未提交任何许可申请，也未取得任何商业许可）

### 2.3 AGPL §13、衍生作品、权重归属：**未决解释**（不得替用户认定）

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-03 | AGPL §13 只在“修改了 Program 且该版本支持通过网络远程交互”时，对远程交互用户提供 Corresponding Source；条文本身**没有**直接规定机载推理或权重地位 | 【来源陈述】 | EVIDENCED（条文）/ UNKNOWN（适用性） | gnu.org AGPL-3.0 原文，N=1 |
| E-04 | AGPL 的“covered work”=未修改的 Program 或“based on the Program”的作品；“modified version”的定义基于复制/改编 | 【来源陈述】 | EVIDENCED（定义）/ UNKNOWN（权重是否落入） | 同上，N=1 |
| E-05 | AGPL 明示“运行 covered work 的输出，只有在该输出本身构成 covered work 时才受本许可约束” | 【来源陈述】 | EVIDENCED（条文）/ UNKNOWN（我们的权重是否构成） | 同上，N=1 |
| E-06 | “Corresponding Source”包含生成、安装、运行（可执行作品）所需全部源码，以及作品被特意要求依赖的共享库/动态链接子程序源码 | 【来源陈述】 | EVIDENCED（定义） | 同上，N=1 |

**原文摘录（§13，gnu.org AGPL-3.0 文本）**

~~~text
Notwithstanding any other provision of this License, if you modify the Program, your modified version
must prominently offer all users interacting with it remotely through a computer network (if your
version supports such interaction) an opportunity to receive the Corresponding Source of your version
by providing access to the Corresponding Source from a network server at no charge ...
~~~

**原文摘录（§0 定义 / §2 输出条款）**

~~~text
To "modify" a work means to copy from or adapt all or part of the work in a fashion requiring copyright
permission ... The resulting work is called a "modified version" ... or a work "based on" the earlier work.
A "covered work" means either the unmodified Program or a work based on the Program.

The output from running a covered work is covered by this License only if the output, given its content,
constitutes a covered work.
~~~

- 出处：<https://www.gnu.org/licenses/agpl-3.0.txt>；条文结构可对照 <https://www.gnu.org/licenses/agpl-3.0.html>

**未决解释（必须由用户/法务裁定，本文不做结论）**

1. **权重衍生性**：用 Ultralytics 代码与 yolov8n-pose.pt 预训练权重训练出的自定义权重、以及导出的 ONNX，是否属于 “based on the Program” 的 covered work？§2 输出条款把判断条件回指“输出本身是否构成 covered work”，形成解释空间；不同司法辖区/律师意见可能不同。
2. **§13 触发范围**：本项目目标形态是 **RK3576 机载推理**（不对外提供网络服务）；是否还会存在地面站/日志回传等“remote network interaction”形态、是否“modify 了 Program”，都会改变 §13 义务。**部署形态尚未冻结 → UNKNOWN**。
3. **闭源分发**：若未来需分发含 YOLO 代码/权重/ONNX 的产品镜像，AGPL 的传染范围（是否要求整机软件开源、是否可用进程隔离规避）属法律解释，**不得由工程侧自行认定**。
4. **商业许可**：Ultralytics Enterprise License 是否覆盖“自训练权重 + 导出 ONNX + 板端部署”，需以商业许可条款原文为准；本任务未取得条款原文（公开页面仅说明可绕过 AGPL 开源要求）→ **UNKNOWN**。

### 2.4 拟用版本 ultralytics==8.2.0 的官方发布信息

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-07 | PyPI ultralytics 8.2.0：上传 2024-04-17T04:38:42，License 字段 AGPL-3.0，requires_python >=3.8，依赖 torch>=1.8.0、torchvision>=0.9.0；export extra 含 onnx>=1.12.0；分类器含 Python 3.8–3.12 | 【来源陈述】 | EVIDENCED | PyPI JSON 元数据，N=1 |

- 出处：<https://pypi.org/pypi/ultralytics/8.2.0/json>、<https://pypi.org/project/ultralytics/8.2.0/>
- 含义：8.2.0 对 torch **只有下限没有上限**；“装了新 torch 就能用”不是官方承诺，见 §2.7。
- 项目侧拟用 pin 见 configs/perception/landmark_model_selection_v1.json（ultralytics==8.2.0 为 proposed isolated-env pin），属于【项目决策｜PROPOSED】，不是官方要求。

### 2.5 官方 docs 对 pose 与自定义关键点（kpt_shape）的支持证据

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-08 | v8.2.0 官方文档承认 pose 任务，模型命名 -pose 后缀，示例 yolov8n-pose.pt，训练 CLI yolo pose train data=... model=yolov8n-pose.pt | 【来源陈述】 | EVIDENCED | v8.2.0 docs，N=1 |
| E-09 | v8.2.0 数据格式文档用 kpt_shape: [17, 3] 表达“关键点数量, 维度（2=x,y 或 3=x,y,visible）”，并说明对称关键点可选 flip_idx；另有 12 关键点动物姿态示例；文档给出“使用自己的数据集”指引 | 【来源陈述】 | EVIDENCED | v8.2.0 docs，N=1 |
| E-10 | v8.2.0 代码从 data yaml 读取 kpt_shape：缺失或维度非法会抛错；PoseTrainer 把 data["kpt_shape"] 传入 PoseModel(data_kpt_shape=...)；PoseModel 用其覆盖 model yaml 的 kpt_shape | 【来源陈述】 | EVIDENCED（代码路径） | v8.2.0 源码，N=3 文件 |
| E-11 | 预训练 17 关键点姿态头**不会**迁到 1 关键点新头：BaseModel.load() 用 intersect_dicts 只保留“同名且同 shape”的权重 | 【来源陈述】 | EVIDENCED（代码） | v8.2.0 源码，N=2 文件 |

**原文摘录（v8.2.0 docs/en/datasets/pose/index.md，约 L50–L52、L63、L114、L122）**

~~~text
# Keypoints
kpt_shape: [17, 3]  # number of keypoints, number of dims (2 for x,y or 3 for x,y,visible)
flip_idx: [0, 2, 1, ...]
...
(Optional) if the points are symmetric then need flip_idx ...
...
- **Keypoints**: 12 keypoints.        # 动物姿态示例（Tiger）
...
If you have your own dataset and would like to use it for training pose estimation models ... ensure
that it follows the format specified above ...
~~~

**原文摘录（v8.2.0 ultralytics/data/dataset.py，约 L80–L85）**

~~~python
nkpt, ndim = self.data.get("kpt_shape", (0, 0))
if self.use_keypoints and (nkpt <= 0 or ndim not in {2, 3}):
    raise ValueError("'kpt_shape' in data.yaml missing or incorrect. Should be a list with [number of "
                     "keypoints, number of dims (2 for x,y or 3 for x,y,visible)], i.e. 'kpt_shape: [17, 3]'")
~~~

**原文摘录（v8.2.0 ultralytics/models/yolo/pose/train.py 约 L40–L49；ultralytics/nn/tasks.py 约 L377–L384、L240–L253）**

~~~python
model = PoseModel(cfg, ch=3, nc=self.data["nc"], data_kpt_shape=self.data["kpt_shape"], verbose=verbose)
...
if any(data_kpt_shape) and list(data_kpt_shape) != list(cfg["kpt_shape"]):
    LOGGER.info(f"Overriding model.yaml kpt_shape={cfg['kpt_shape']} with kpt_shape={data_kpt_shape}")
    cfg["kpt_shape"] = data_kpt_shape
...
def intersect_dicts(da, db, exclude=()):
    return {k: v for k, v in da.items() if k in db and ... and v.shape == db[k].shape}
~~~

- 出处：
  - <https://github.com/ultralytics/ultralytics/blob/v8.2.0/docs/en/datasets/pose/index.md>
  - <https://github.com/ultralytics/ultralytics/blob/v8.2.0/docs/en/tasks/pose.md>
  - <https://github.com/ultralytics/ultralytics/blob/v8.2.0/ultralytics/data/dataset.py#L80-L85>
  - <https://github.com/ultralytics/ultralytics/blob/v8.2.0/ultralytics/models/yolo/pose/train.py#L40-L49>
  - <https://github.com/ultralytics/ultralytics/blob/v8.2.0/ultralytics/nn/tasks.py#L240-L253>
  - <https://github.com/ultralytics/ultralytics/blob/v8.2.0/ultralytics/utils/torch_utils.py>
- 判读边界：这些证据只说明 **API/数据格式层面允许 nkpt=1**；不说明 640 输入下 4–10 px 绿光可学、不说明精度、不说明 RKNN 可转换。项目 yaml 已按 kpt_shape: [1, 3] 写为计划（configs/perception/landmark_yolo_pose_v1.yaml，【项目决策｜PLANNED】）。

### 2.6 export 到 ONNX 的官方命令与限制

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-12 | v8.2.0 官方 export 文档给出 ONNX 导出命令与参数 imgsz/half/dynamic/simplify/opset；opset 默认 None 时“使用最新支持的 opset” | 【来源陈述】 | EVIDENCED | v8.2.0 docs，N=1 |
| E-13 | 官方未在 export 文档中声明 pose 任务的额外限制；ONNX 是通用导出格式；导出依赖 onnx 包（PyPI export extra onnx>=1.12.0） | 【来源陈述】 | EVIDENCED（文档事实）/ 局限未列举 | v8.2.0 docs + PyPI 元数据，N=2 |
| E-14 | 官方生态中 pose→ONNX 已被实际使用：RKNN Model Zoo 直接提供 yolov8n-pose.onnx 资产与转换示例 | 【来源陈述】 | EVIDENCED（存在性） | RKNN README/示例，N=1 |

**原文摘录（v8.2.0 docs/en/modes/export.md，约 L69、L79–L87、L101–L103）**

~~~bash
yolo export model=yolov8n.pt format=onnx  # export official model
yolo export model=path/to/best.pt format=onnx  # export custom trained model
~~~

~~~text
| simplify | bool | False | Simplifies the model graph for ONNX exports ...
| opset    | int  | None  | Specifies the ONNX opset version ... If not set, uses the latest supported version.
...
| ONNX | onnx | yolov8n.onnx | ✅ | imgsz, half, dynamic, simplify, opset |
~~~

（摘录自官方表格，去除了链接与 Markdown 反引号；“✅”列为官方原文的 metadata 支持标记。）

- 出处：<https://github.com/ultralytics/ultralytics/blob/v8.2.0/docs/en/modes/export.md>
- 限制/边界（如实记录）：
  1. 官方文档**没有**给出“自定义 kpt_shape 导出的 ONNX 输出布局与下游运行时兼容性”说明；我们只能依据代码与 RKNN demo 反推，属【未确认解释】。
  2. opset 未固定；“使用最新支持 opset”意味着不同 ultralytics/onnx 版本可能产出不同 opset → 复现性风险，**导出时必须显式固定 opset**（项目计划写 opset18 为 PROPOSED）。
  3. 导出/量化后的 **RKNN 算子支持与精度**没有任何官方保证（见 §4）。
  4. 我们的自定义 1-keypoint ONNX **从未导出过**（无 ultralytics、无权重、未安装）→ **UNKNOWN，不是 PASS**。

### 2.7 ultralytics 8.2.0 × torch 2.7 兼容性：未验证组合（重要）

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-15 | 本机 torch 2.7.0 的 torch.load 签名默认 weights_only=True（inspect.signature 显示 weights_only=None，文档签名显示 weights_only=True），即 2.6 起的安全默认已生效 | 本机只读事实 | EVIDENCED | 本机查询，N=1 |
| E-16 | ultralytics 8.2.0 发布于 2024-04，早于 torch 2.6/2.7 的 weights_only 默认变更；PyPI 上 8.2.0 只有 torch>=1.8.0 下限，无上限、无 2.7 兼容声明 | 【来源陈述】+ 时间线推断 | EVIDENCED（事实）/ UNKNOWN（兼容性） | PyPI 元数据 + PyTorch 2.6 行为，N=2 |
| E-17 | Ultralytics 后续才加入可选的 ULTRALYTICS_SAFE_LOAD 安全加载开关（PR #24829），说明“torch 新默认 + 旧加载逻辑”确实需要专门处理 | 【来源陈述】 | EVIDENCED（存在该 PR） | 官方 PR 页面，N=1 |

- 出处：<https://pypi.org/pypi/ultralytics/8.2.0/json>；<https://github.com/ultralytics/ultralytics/pull/24829>
- 结论：**“8.2.0 能在 torch 2.7.0+cu128 上训练/加载/导出”没有任何官方声明，本任务也未实测**（安装被禁止）→ **UNKNOWN**，必须在隔离环境做最小 smoke（加载 yolov8n-pose.pt、1 张图 forward、1 epoch 微型训练、onnx export）后才可升级为“已验证”。对应待决项 PD-009。

---

## 3. 备选：YOLOX-Nano（只作备选，不得自动切换）

### 3.1 LICENSE 原文（Apache-2.0）

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-18 | YOLOX 仓库 LICENSE 是 Apache License 2.0 全文，附录版权行 “Copyright (c) 2021-2022 Megvii Inc.” | 【来源陈述】 | EVIDENCED | 官方文件，N=1；sha256=0ec3668d…9088，len=11371 |

**原文摘录（LICENSE 首段 + 附录）**

~~~text
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/
...
   Copyright (c) 2021-2022 Megvii Inc. All rights reserved.
   Licensed under the Apache License, Version 2.0 ...
~~~

- 出处：<https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE>（raw：<https://raw.githubusercontent.com/Megvii-BaseDetection/YOLOX/main/LICENSE>）

### 3.2 权重与 COCO 数据集条款

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-19 | 官方 README 的 Model Zoo 表：YOLOX-Nano 输入 416、AP 25.8（val）、**0.91M 参数、1.08 GFLOPs**，权重下载指向 0.1.1rc0/yolox_nano.pth | 【来源陈述】 | EVIDENCED | 官方 README，N=1 |
| E-20 | README 明确提供 ONNX export + ONNXRuntime demo（demo/ONNXRuntime） | 【来源陈述】 | EVIDENCED | 官方 README，N=1 |
| E-21 | **权重自身的许可声明**：仓库 LICENSE 只覆盖仓库软件；未在仓库/权重下载页检索到“weights 单独许可”的明文 | 【未确认解释】 | UNKNOWN | 1 个页面 + 1 个 LICENSE 文件，N=2 |
| E-22 | **COCO 数据集条款**：官方 COCO 站点 <https://cocodataset.org/#termsofuse> 的内容为 JS 动态渲染，任务内抓取只得到导航壳与页脚，未取得条款正文；尝试 raw 仓库路径均 404 | 无法确证 | UNKNOWN | 尝试 5 个 URL，均未取得正文，N=0 有效样本 |

- 出处：<https://github.com/Megvii-BaseDetection/YOLOX>、<https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.pth>（README 链接）、<https://cocodataset.org/#termsofuse>
- 判读：COCO 2017 图像多来自 Flickr（各自授权），标注另有条款；**在未读到官方条款正文前，不得写“COCO 权重可自由商用”**。若未来采用 YOLOX-Nano COCO 预训练权重，须单独完成数据集/权重条款核对（PD-006）。
- 说明：YOLOX-Nano 只输出 bbox，绿灯 anchor 仍走经典阶段——**即使许可更宽松也不能解决 anchor 精度/召回问题**（见 configs/perception/landmark_model_selection_v1.json 的 risks）。

### 3.3 切换规则（项目决策）

| 编号 | 主张 | 分类 | 状态 |
| --- | --- | --- | --- |
| E-23 | 主候选 YOLOv8n-pose、备选 YOLOX-Nano；**AGPL 不可接受时先评估备选，不得自动切换、不得由代理代替用户决定** | 【项目决策】 | PROPOSED / PENDING_USER_DECISION（PD-005） |

- 出处：configs/perception/landmark_model_selection_v1.json（decision_condition 字段）、configs/perception/landmark_training_plan_v2.json（license_gate.rule：no automatic model switch; user decision required）。
- 证据域：仓库配置（文档），无实测。

---

## 4. RKNN Model Zoo / RKNN Toolkit2

### 4.1 yolov8_pose 示例的存在性、平台与命令

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-24 | RKNN Model Zoo 支持平台列表包含 **RK3576**；模型表中有 **Body Pose / yolov8_pose / INT8 / yolov8n-pose.onnx** 行，平台列含 RK3576 | 【来源陈述】 | EVIDENCED | 官方 README，N=1 |
| E-25 | 基准表列名为 RK3576 @single_core，yolov8_pose / yolov8n-pose / [1,3,640,640] / INT8 在该列的值为 **75.0**（FPS）；此为该表“模型性能基准”，官方示例口径 | 【来源陈述】 | EVIDENCED（官方示例数字） | 官方 README 基准表，N=1 |
| E-26 | Release Notes：2.1.0 新增 yolov8_pose 等 demo；2.0.0 增加 RK3576 支持；当前最新 2.5.0 对应 **RKNPU2 SDK >=2.5.0** | 【来源陈述】 | EVIDENCED | 官方 README，N=1 |
| E-27 | examples/yolov8_pose/README.md 给出转换命令（fp / i8 / 两段式 hybrid 量化）与支持平台（含 RK3576）；说明 “Currently the C code demo only supports 8-bit quantization”；yolov8n-pose.pt 下载链接指向 ultralytics/assets/releases/download/v8.2.0/yolov8n-pose.pt | 【来源陈述】 | EVIDENCED | 官方示例 README，N=1 |

**原文摘录（examples/yolov8_pose/README.md）**

~~~text
## 2. Current Support Platform
RK3562, RK3566, RK3568, RK3576, RK3588, RV1126B

## 4. Convert to RKNN
python convert.py <onnx_model> <TARGET_PLATFORM> <dtype(optional)> <output_rknn_path(optional)>
python convert.py ../model/yolov8n-pose.onnx rk3588 fp
python convert.py ../model/yolov8n-pose.onnx rk3588 i8 1
python convert.py ../model/yolov8n-pose.onnx rk3588 i8 2
# Currently the C code demo only supports 8-bit quantization
~~~

- 出处：<https://github.com/airockchip/rknn_model_zoo/tree/main/examples/yolov8_pose>、<https://github.com/airockchip/rknn_model_zoo>
- 重要边界：**75.0 FPS 是官方示例模型的推理吞吐（RK3576 单核、INT8、640 输入、不含前后处理），不是我们的模型效果、不是板端验收、不是导航能力**（见 §9）。

### 4.2 自定义 1-keypoint 导出的证据：**UNKNOWN（有代码级理由）**

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-28 | 官方示例的 convert.py 标定数据集硬编码为 ../../../datasets/COCO/coco_subset_20.txt；hybrid 量化还硬编码 YOLOv8 推理头节点名（/model.22/cv4.0/... 等） | 【来源陈述】 | EVIDENCED（代码） | 官方源码，N=1 |
| E-29 | 官方 Python demo 后处理假定 **17 个 COCO 关键点**：kpt_color = pose_palette[[16,16,...,0...]]、17 点 skeleton、reshape(-1,3) | 【来源陈述】 | EVIDENCED（代码） | 官方源码，N=1 |
| E-30 | 官方未提供“自定义 kpt_shape=1 模型的 RKNN 转换/量化/部署”文档或脚本参数 | 【来源陈述】（缺失即事实）/ 解释性 | **UNKNOWN** | 官方示例文档 + 代码，N=2；未找到反例 |

**原文摘录（examples/yolov8_pose/python/convert.py）**

~~~python
DATASET_PATH = '../../../datasets/COCO/coco_subset_20.txt'
...
rknn.hybrid_quantization_step1(
    dataset=DATASET_PATH,
    proposal= False,
    custom_hybrid=[['/model.22/cv4.0/cv4.0.0/act/Mul_output_0','/model.22/Concat_6_output_0'],
                   ['/model.22/cv4.1/cv4.1.0/act/Mul_output_0','/model.22/Concat_6_output_0'],
                   ['/model.22/cv4.2/cv4.2.0/act/Mul_output_0','/model.22/Concat_6_output_0']]
)
~~~

**原文摘录（examples/yolov8_pose/python/yolov8_pose.py，约 L156–L157、L230）**

~~~python
kpt_color  = pose_palette[[16, 16, 16, 16, 16, 0, 0, 0, 0, 0, 0, 9, 9, 9, 9, 9, 9]]
skeleton = [[16, 14], [14, 12], [17, 15], [15, 13], ...]
...
keypoints = predbox[i].keypoint.reshape(-1, 3)  # keypoint [x, y, conf]
~~~

- 出处：<https://github.com/airockchip/rknn_model_zoo/blob/main/examples/yolov8_pose/python/convert.py>、<https://github.com/airockchip/rknn_model_zoo/blob/main/examples/yolov8_pose/python/yolov8_pose.py>
- 判读：rknn.load_onnx(model=...) 本身是通用的，**理论上**自定义 1-keypoint ONNX 可能被加载；但 (a) hybrid 量化节点名与模型结构绑定，(b) 标定集是 COCO 而非本域图像，(c) demo 后处理假定 17 点 → **必须重写转换/标定/后处理并实测**。因此“自定义 1-keypoint 导出与量化”状态 = **UNKNOWN**，不能写成“官方支持”。对应 PD-008。
- 证据域/样本量：官方仓库 3 个文件（README、convert.py、yolov8_pose.py），N=3；**无板卡、无实测**。

### 4.3 许可：Model Zoo 是 Apache-2.0，Toolkit2 是专有许可（新增事实）

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-31 | rknn_model_zoo 仓库 LICENSE 为 Apache License 2.0（sha256=c71d239d…d0ab4，len=11357） | 【来源陈述】 | EVIDENCED | 官方 LICENSE 文件，N=1 |
| E-32 | rknn-toolkit2 仓库 LICENSE **不是** Apache-2.0，而是 Rockchip 的专有《RKNN SDK License》：授予为兼容 Rockchip 产品做设计/开发/测试的有限许可，限制反向工程/移除声明等，**受中华人民共和国法律管辖（福州）** | 【来源陈述】 | EVIDENCED | 官方 LICENSE 文件，N=1；sha256=eaadd949…3790f，len=7561 |
| E-33 | rknn-toolkit2 README：支持平台含 **RK3576 Series**；最新版本 **v2.5.0**；支持 Python 3.6–3.12 | 【来源陈述】 | EVIDENCED | 官方 README，N=1 |

**原文摘录（rknn-toolkit2/LICENSE）**

~~~text
RKNN SDK License
This License Agreement for RKNN Software Development Kit Package ...
1.1 ... Rockchip hereby grants to You a limited, non-exclusive, royalty-free copyright license to use,
reproduce, modify, and create derivative works of the Software ... solely for the design, development
and testing of applications that are compatible with Products ... of Rockchip ...
2.1 ... You may NOT: (a) decompile, reverse-engineer, dissemble ... (b) remove or obscure any copyright...
10. This Agreement will be governed by and construed in accordance with the laws of the People's
Republic of China ("PRC") ...
~~~

- 出处：<https://github.com/airockchip/rknn-toolkit2/blob/master/LICENSE>、<https://github.com/airockchip/rknn-toolkit2>
- 判读：**“Model Zoo Apache-2.0”不能推出“整条 RKNN 工具链可自由使用/再分发”**。工具链安装、CI 使用、转换产物（.rknn）分发是否受 RKNN SDK License 约束，需用户/法务确认（PD-007）。
- 既有证据包只写了 Model Zoo 的 Apache-2.0，未记录 Toolkit2 专有许可 → 见 §8 更正 2。

---

## 5. RTX 5080（sm_120）与 torch 2.7.0+cu128 / CUDA 12.8 / ultralytics 8.2.0

### 5.1 本机只读事实（2026-11-04，N=1 次查询）

| 项目 | 实测值 | 证据域 |
| --- | --- | --- |
| GPU | NVIDIA GeForce RTX 5080，16303 MiB | nvidia-smi |
| 驱动 | 581.80；nvidia-smi 报 “CUDA Version: 13.0”（驱动支持的最高 API） | nvidia-smi |
| Compute capability | **12.0（sm_120）**（nvidia-smi --query-gpu=compute_cap 与 torch.cuda.get_device_capability(0) 一致） | nvidia-smi + torch |
| torch | **2.7.0+cu128**；torch.version.cuda = 12.8；cuda_available=True；device_count=1 | python -c |
| torch.cuda.get_arch_list() | sm_50, sm_60, sm_61, sm_70, sm_75, sm_80, sm_86, sm_90, sm_100, **sm_120** | python -c |
| cuDNN | 9.7.1（torch.backends.cudnn.version()=90701） | python -c |
| Python | 3.11.9（E:\isaac\env_isaaclab\Scripts\python.exe），Windows 10.0.28120 | python -c |
| torchvision / onnx / cv2 / Pillow / numpy | 0.22.0+cu128 / 1.22.0 / 4.11.0 / 11.3.0 / 1.26.0 | pip list + import |
| ultralytics / onnxruntime / rknn / rknn-toolkit2 | **均未安装**（importlib.util.find_spec 均 None） | python -c |
| 仓库内 .onnx/.rknn | **未发现**（Get-ChildItem -Recurse -Include *.onnx,*.rknn，排除 .git） | 文件搜索 |
| 仓库内 .pt | 发现 2 个**与本任务无关**的文件：external/NavRL/quick-demos/ckpts/navrl_checkpoint.pt、logs/rsl_rl/quadcopter_direct/2026-10-11_18-12-23/model_0.pt；**无任何 landmark 命名的训练权重** | 文件搜索 |

- 样本量说明：以上为**单机单次**查询，不是多机统计；不能外推为“所有同型机器都如此”。

### 5.2 官方证据：CUDA 12.8 / Blackwell / sm_120

| 编号 | 主张 | 分类 | 状态 | 证据域/样本量 |
| --- | --- | --- | --- | --- |
| E-34 | PyTorch 2.7 官方发布说明：支持 NVIDIA Blackwell GPU 架构，并提供 CUDA 12.8 预编译 wheel（官方公告写 “across Linux x86 and arm64 architectures”） | 【来源陈述】 | EVIDENCED | PyTorch 官方 blog，N=1（datePublished 2025-04-23/24） |
| E-35 | PyTorch 官方 cu128 wheel 索引存在 **torch-2.7.0+cu128-cp311-cp311-win_amd64.whl**（上传 2025-04-22），cp311 = Python 3.11 = 本机 Python 版本 | 【来源陈述】 | EVIDENCED | 官方 wheel 索引页，N=1 |
| E-36 | 本机 torch 的 arch list 含 sm_120，且实际检测到 device capability (12,0) → 该 wheel 针对 RTX 5080（sm_120）编译 | 本机只读事实 | EVIDENCED | 本机查询，N=1 |

- 出处：<https://pytorch.org/blog/pytorch-2-7/>、<https://download.pytorch.org/whl/cu128/torch/>
- 说明：nvidia-smi 的 “CUDA Version: 13.0” 与 torch 的 cu128 **不矛盾**：前者是驱动支持的最高 CUDA API 版本，后者是 PyTorch 运行时编译/打包的 CUDA 版本；驱动 581.80 向下兼容 cu128。
- 边界：以上只证明“硬件+torch 组合可用（编译/检测层面）”，**不证明** ultralytics 8.2.0 训练/导出可用（见 §2.7），也不证明 RKNN 板端可用（§4）。

### 5.3 ultralytics 8.2.0 组合的结论

| 编号 | 主张 | 分类 | 状态 |
| --- | --- | --- | --- |
| E-37 | 版本组合“RTX 5080 + torch 2.7.0+cu128 + ultralytics 8.2.0”**没有官方兼容性声明**，也未实测（安装被禁止）；只能确认 torch/CUDA/sm_120 层可用 | 【未确认解释】 | **UNKNOWN / 待隔离环境 smoke（PD-009）** |

- 最小 smoke（**未执行，计划**）：隔离 .venv/landmark-train → 安装 pin → YOLO('yolov8n-pose.pt') 加载 → 1 张图 forward → 微批训练 1 epoch → yolo export … format=onnx opset=18 → 记录是否报 Weights only load failed/算子问题。
- 注意：创建 venv 与 pip install 属于本任务**禁止**的“安装训练依赖”，必须由用户授权后另开工作包执行。

---

## 6. 待决项清单（pending decisions）

> 状态均为 PENDING_USER_DECISION 或 UNKNOWN；**未决时不得有默认放行行为**。结构化版本见 license_export_evidence_20261104.json 的 pending_decisions。

| ID | 主题 | 分类 | 影响 | 最小决策问题 | 未决时行为 |
| --- | --- | --- | --- | --- | --- |
| PD-001 | AGPL-3.0 主方案接受与否 | 【未确认解释】 | 阻断 A1 准入、主方案训练、任何分发 | 本项目是否接受 AGPL-3.0 义务？若接受，是“内部研究、不分发”还是“允许开源分发”？若不接受，是否购买 Ultralytics 商业许可或转备选？ | 不训练、不分发、不导出可交付产物 |
| PD-002 | 自训练权重/ONNX 是否衍生作品 | 【未确认解释】 | 决定权重与 ONNX 是否受 AGPL 传染 | 是否接受“保守解释：自训练权重与导出的 ONNX 视为基于 Program 的作品，按 AGPL 处理”（需法务书面意见）？ | 按保守解释：不对外分发权重/ONNX |
| PD-003 | AGPL §13 网络交互触发范围 | 【未确认解释】 | 决定是否需要 source offer 及由谁承担 | 部署形态是否包含对外网络服务/远程交互？谁能承担 Corresponding Source 提供义务？ | 按“可能触发”处理，不承诺对外服务 |
| PD-004 | 是否允许在 AGPL 未决时开始内部训练 | 【项目决策】 | 决定 A1 是否可临时放行 | 是否允许“仅内部、不产生对外分发物”的有界训练实验？ | 不启动训练 |
| PD-005 | 备选 YOLOX-Nano 的启用条件 | 【项目决策】 | 决定路线切换 | 若 AGPL 不可接受，是否授权优先评估 YOLOX-Nano（bbox-only + 经典 anchor）？ | 不自动切换 |
| PD-006 | YOLOX 权重/COCO 数据集条款 | 【未确认解释】 | 备选路线是否可用、是否需要重训 | 是否接受 COCO 预训练权重与数据集条款未核实的风险，或要求从零权重训练？ | 备选也不放行训练 |
| PD-007 | RKNN-Toolkit2 专有许可与转换产物 | 【未确认解释】 | 工具链安装/CI/产物分发 | 是否接受 RKNN SDK License 条款？是否允许在开发机/CI 安装？.rknn 产物能否分发？ | 不安装工具链、不分发 .rknn |
| PD-008 | 自定义 1-keypoint RKNN 导出/量化路径 | **UNKNOWN** | A5/停止条件：导出不可行则该轮停止 | 是否把“自定义 1-kpt ONNX→RKNN(i8)→板端延迟”作为训练后验证前置，并接受可能失败？ | 不声称 RK3576 可部署 |
| PD-009 | 8.2.0 × torch 2.7 未验证组合 | 【未确认解释】 | 版本 pin 与训练可行性 | 是否授权创建隔离 venv 并做最小加载/训练/导出 smoke？ | 不安装、不训练 |
| PD-010 | 版本 pin 策略（8.2.0 vs 升级） | 【项目决策】 | 复现性 / 与 RKNN zoo 资产一致性 | 是否坚持 ultralytics==8.2.0（与 zoo 引用资产一致），还是允许升级到官方支持 torch 2.7 的更新版本？ | 保持 8.2.0 pin，但标“未验证” |
| PD-011 | ONNX opset / RKNN 算子支持 | **UNKNOWN** | 导出可行性与量化掉点 | 是否接受“先导出 ONNX（固定 opset18）、再做 rknn 算子/量化检查，失败则调整 opset 或改结构”？ | 不承诺导出成功 |
| PD-012 | 官方示例性能指标的使用口径 | 【项目决策】 | 防止把官方数字写成我们的效果 | 是否确认：RKNN zoo 的 75.0 FPS 只作“官方示例存在”引用，永不作为我们的模型/板端/导航指标？ | 按“禁止引用为我们指标”执行 |

---

## 7. 未确认项 / UNKNOWN 汇总

- AGPL 对“自训练权重/ONNX/板端二进制”的传染范围（PD-002）、§13 适用性（PD-003）、Ultralytics 商业许可条款原文（本任务未取得）。
- YOLOX 权重自身许可声明、COCO 数据集条款正文（官方站点 JS 渲染，未取得原文）。
- RKNN SDK License 对“转换产物 .rknn 分发”“CI 内安装”的具体约束。
- 自定义 1-keypoint ONNX 的 RKNN 转换/量化/算子回退/板端延迟/热稳定（无板卡、无工具链）。
- ultralytics 8.2.0 在 torch 2.7.0+cu128 上的加载/训练/导出行为（未安装、未实测）。
- 我们的 4–10 px 绿光在 640 输入下是否可分（数据/模型问题，非许可问题；引用既有未确认项）。
- Ultralytics 各版本是否对 kpt_shape=1 有回归覆盖（官方 docs 示例均为 17/12 点，kpt_shape=[1,3] 属文档覆盖空白 → 需实测）。

---

## 8. 对既有证据包的更正（不修改原文件，仅登记）

1. **docs/reports/perception/dsh_landmark_deployment_feasibility_20261104.json 的 model_artifacts_found 写 “none (.onnx/.pt/.rknn search returned no files)”**：
   本任务复搜发现仓库内确有 2 个 .pt（external/NavRL/quick-demos/ckpts/navrl_checkpoint.pt、logs/rsl_rl/quadcopter_direct/2026-10-11_18-12-23/model_0.pt），均与地标任务无关；**结论“无地标相关权重/无 .onnx/.rknn”仍成立，但“no files”表述不准确**。建议后续由原作者修正措辞（本任务不越权修改）。
2. **既有包只写 “RKNN Model Zoo 是 Apache-2.0 代码”，未提 RKNN-Toolkit2 许可**：
   实测 Toolkit2 LICENSE 是 **Rockchip 专有 RKNN SDK License**（非 Apache-2.0，PRC 法律管辖）。此项影响“工具链安装/CI/产物分发”，已列为 PD-007。
3. **既有包对 RKNN 版本/资产的表述可细化**：Model Zoo 最新 2.5.0（对应 RKNPU2 SDK >=2.5.0），yolov8_pose 自 2.1.0 引入，2.0.0 增加 RK3576；示例引用 yolov8n-pose.pt 的 v8.2.0 资产链接——与“pin ultralytics 8.2.0”一致，可作为 pin 的旁证（不是兼容性证明）。
4. **kpt_shape: [1, 3] 的官方支持程度**：代码/格式允许（E-09/E-10），但官方文档示例均为 17/12 点，缺少 1 点示例/回归证据 → 既有计划写 “1 keypoint” 应保持 **PROPOSED**，不得写成“已验证支持”。

---

## 9. 使用边界（禁止越界写法）

1. **不得**把本文件写成“许可已通过”“AGPL 已接受”“法务已批准”。本文件只陈述证据与待决项。
2. **不得**把 RKNN 官方示例的 75.0 FPS（或任何官方 benchmark）写成“我们的模型效果”“板端验收”“导航能力”。该数字的设备/精度/输入/口径见 E-25；我们无 RK3576 板卡、无自定义模型、无板端测量。
3. **不得**把“官方示例存在 yolov8_pose”写成“我们的自定义 1-keypoint 模型可部署到 RK3576”（E-30 = UNKNOWN）。
4. **不得**把“RTX 5080 + torch 2.7.0+cu128 检测正常”写成“ultralytics 8.2.0 训练/导出已验证”（E-37 = UNKNOWN）。
5. **不得**因许可风险自动切到备选模型（E-23、PD-005）。
6. 训练准入口径以 docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §4 为准：A1/A5 在本文件有证据，但**结论仍是“证据到这里，决策待用户”**。

---

## 10. 复现命令（只读）

~~~powershell
# 版本/GPU/包（只读，不安装）
E:\isaac\env_isaaclab\Scripts\python.exe -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.get_device_capability(0), torch.cuda.get_arch_list())"
E:\isaac\env_isaaclab\Scripts\python.exe -m pip list
nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader

# 权重/产物搜索（只读）
Get-ChildItem -Recurse -File E:\isaac\proj_boom_birds -Include *.pt,*.onnx,*.rknn,*.pth,*.engine |
  Where-Object { $_.FullName -notmatch '\\\.git\\' }
~~~

已抓取并核对的官方证据 URL（2026-11-04）：

- Ultralytics v8.2.0 LICENSE：<https://raw.githubusercontent.com/ultralytics/ultralytics/v8.2.0/LICENSE>（sha256 0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0，len 34523）
- FSF AGPL-3.0：<https://www.gnu.org/licenses/agpl-3.0.txt>（同一 sha256）
- Ultralytics v8.2.0 README（License 段）：<https://github.com/ultralytics/ultralytics/blob/v8.2.0/README.md>
- Ultralytics v8.2.0 pose 文档：<https://github.com/ultralytics/ultralytics/blob/v8.2.0/docs/en/tasks/pose.md>
- Ultralytics v8.2.0 数据格式（kpt_shape）：<https://github.com/ultralytics/ultralytics/blob/v8.2.0/docs/en/datasets/pose/index.md>
- Ultralytics v8.2.0 export 文档：<https://github.com/ultralytics/ultralytics/blob/v8.2.0/docs/en/modes/export.md>
- Ultralytics v8.2.0 代码：ultralytics/data/dataset.py、ultralytics/models/yolo/pose/train.py、ultralytics/nn/tasks.py、ultralytics/utils/torch_utils.py（同 tag）
- PyPI ultralytics 8.2.0：<https://pypi.org/pypi/ultralytics/8.2.0/json>
- YOLOX LICENSE：<https://raw.githubusercontent.com/Megvii-BaseDetection/YOLOX/main/LICENSE>（sha256 0ec3668d3274bcf29e8a29e9576d5a2cd96fc78d3c5bec4387355a796e5d9088，len 11371）
- YOLOX README：<https://github.com/Megvii-BaseDetection/YOLOX>
- COCO Terms of Use（未能取得正文）：<https://cocodataset.org/#termsofuse>
- RKNN Model Zoo：<https://github.com/airockchip/rknn_model_zoo>（LICENSE sha256 c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4，len 11357）
- RKNN yolov8_pose 示例：<https://github.com/airockchip/rknn_model_zoo/tree/main/examples/yolov8_pose>
- RKNN convert.py：<https://github.com/airockchip/rknn_model_zoo/blob/main/examples/yolov8_pose/python/convert.py>
- RKNN yolov8_pose.py：<https://github.com/airockchip/rknn_model_zoo/blob/main/examples/yolov8_pose/python/yolov8_pose.py>
- RKNN-Toolkit2：<https://github.com/airockchip/rknn-toolkit2>（LICENSE sha256 eaadd949941ed3b072ffdf0a0d4341501cfa1cf2ec3526ce3f60cf7bf513790f，len 7561）
- PyTorch 2.7 公告：<https://pytorch.org/blog/pytorch-2-7/>（datePublished 2025-04-23）
- PyTorch cu128 wheel 索引：<https://download.pytorch.org/whl/cu128/torch/>
- Ultralytics PR #24829（safe load）：<https://github.com/ultralytics/ultralytics/pull/24829>

---

## 11. 结论

**证据到这里，决策待用户。** 已确证的是“许可文本、官方发布信息、官方/代码层面对 pose 与 kpt_shape 的支持、RKNN 示例存在性与平台支持、本机 RTX 5080/torch/CUDA 事实”；**未确证的是“AGPL 是否可接受、权重/ONNX 的许可地位、自定义 1-keypoint 的 RKNN 可部署性、8.2.0×torch 2.7 组合可用性”**。在这些未决项被用户/法务裁定、且隔离环境实测完成之前：不训练、不分发、不声称板端/模型效果。




