# Nova（humanoid 分支）

做一个真正像人、真正能被人依靠的人形机器人 Nova。先在物理仿真里做，以后做真机；第一件要做到可靠的事是家务。
现在只在这台电脑上开发（Windows、Docker Desktop、RTX 4060 Ti 8 GB）。
设计都在 `docs/` 里：规格是"现在定下的"，`docs/research/` 是讨论的经过。

## 开发守则（一直遵守）

1. **代码的质量和可读性**
   - 一个类、一个函数只做一件事。看名字就知道它做什么。
   - 魔法数字和字符串提成有名字的常量或配置。
   - 注释只写"为什么"；"是什么"让代码自己说。
   - 外面来的输入（网络、文件、命令行、语言模型的输出）在边界上检查；里面的代码只处理检查过的值。
2. **没有经验的人也好用的画面**
   - 画面上的字用简单的中文；术语要解释，或者加帮助。
   - 状态用颜色加文字，不只靠颜色。
   - 每个画面都有加载中、空的、出错（带"再试一次"）三种状态；连接断了以后的值要标明是旧的。
   - 不能撤销的、危险的操作，先用确认框说明会发生什么。
3. **测试**
   - 加功能、改功能，测试一起写。
   - 重要的功能（质量和身体的计算、关节控制、停止和安全、判分、计划）要测：正常、边界值、失败、重复和顺序颠倒。
   - 测试的说明用中文写（pytest 用 docstring 和 ids，vitest 用 describe 和 it 的名字，GoogleTest 在 TEST 上面写 `// 说明：`）。
   - 身体的测试要真的跑物理（站、走、抓）。数要实测以后再定。

## 结构

```text
docs/            设计。规格（现在定下的）：机体规格、系统结构、AI模型、Nova考试、商用要求
                 核心和待证明（做哪些）、P1计划（做完了）、P2计划（步骤和进度）、技术栈、决定记录
                 research/（讨论的经过）、报告/（程序算出来的，不要手改）
body/            身体：设计计算和模型生成。Python 3.13，只在 Linux 容器里跑
                 nova_body，Nova 自己的: anthropometry（人体比例） actuator_mass（驱动器有多重） design（关节表）
                 mass_closure（质量闭环：每一段、每个驱动器、每样东西多重） mass_report（报告）
                 skeleton（骨架：关节的转轴和范围、尺寸、左右镜像） hand（手的 22 个关节）
                 model（生成 MuJoCo 的模型：形状、东西放哪、驱动器、传感器、相机） model_report（报告）
                 nova_body，每个身体共用的: body（测试台眼里的"一个身体"） bench（测试台：地面、步长、关节控制的软硬）
                 posture（站姿） standing（在仿真里站着、推、量结果） drawing（画成 SVG）
                 ik（全身的逆运动学） inverse（逆动力学：每个关节要的力矩、撑着的地方受的力）
                 gait（走路、楼梯的计划：脚步、压力中心、重心的路） motions（第一次考试的动作，一帧一帧）
                 strength（从动作算力量的目标，几个进程一起算） strength_report（力量的报告）
                 drives（驱动器的模型：按峰值、发热、转速选；力矩-转速、降额、热的两个节点）
                 heat（一轮家务的热预算） drive_report（驱动器和热的报告）
                 actuation（仿真里的驱动器：每一步的力的上下限、发热、命令的延迟）
                 sensing（身体自己的传感器：噪声、零偏、延迟） packaging（放不放得下：驱动器的大小、骨盆）
                 nova_body，基线: third_party（按清单下载、核对外面来的文件） baseline（把 Unitree G1 放上测试台）
                 baseline_report（基线和 Nova 比的报告）
                 nova_body，练出来的策略: policy（照规约读进来、核对） policy_runner（接到身体上：观测，动作变成关节的命令）
                 spine（脊髓层接到身体上：照模型建、每 1 毫秒一步） estimation（状态估计接到身体上：IMU、腿的运动学、着地）
                 spinal（脊髓层合起来：反射 → 硬限制和换算；皮肤管哪几个关节；刹车的阻尼）
                 policy_bodies（练的时候的身体：推哪里、状态估计用哪个 IMU、哪两只脚）
                 policy_bench（测试台上跑一个策略：小脑层 → 脊髓层 → 驱动器 → 仿真，状态估计跟着；站着、躺着开始；楼梯）
                 policy_walk（按命令表考走路的策略） p2_exam（P2 的考试：站 1 小时、被推、走 1 公里、上下楼梯、起来）
                 height_scan（高度扫描：从骨盆往下打一片竖直的射线，和 mjlab 一样）
                 nova_body，SONIC（NVIDIA 现成的 G1 全身控制，基线）: sonic_params（照它源码的数） sonic_motion（参考动作：
                 30 Hz 换 50 Hz、上下文、新旧两段混合） sonic_planner（运动规划器） sonic_brain（G1 的身体、每一步的控制器）
                 nova_sim，实时的仿真和给网页的服务（容器 sim，端口 8870）: bodies（能选的身体） scene（给网页的"样子"）
                 live（跟着钟走的仿真：暂停、松开、推、重新开始） protocol（照规约检查） server（HTTP 和 WebSocket）
                 channel（给每个网页发东西的队列）
contracts/       规约（JSON Schema），只写在这一处：sim/ 里是仿真和网页之间的三种东西：scene（身体的样子）、
                 message（招呼、状态、答复）、command（命令）。仿真（jsonschema）和网页（ajv）用同一份文件检查
                 policy/ 里是练出来的策略的规约（看什么、出什么）：训练那边写，测试台读
rt/             实时分区（C++20，Eigen）：现在是脊髓层（第一版）。include/nova_rt、src: coupling（驱动器 ↔ 关节的换算）
                 limits（关节空间的硬限制） spine（一步：换算、限制、驱动器的命令） estimator（状态估计：带接触的 InEKF）
                 reflexes（反射：保护、碰撞、跌倒、停止） lie（转动的小工具）。python/（nanobind 的模块 nova_rt，
                 装进身体的镜像） tests/（GoogleTest）。在身体的镜像的第一段（rt-build）里编译
train/          训练：在显卡上做强化学习（容器 nova-train）。mjlab、MuJoCo Warp、PyTorch，版本锁在 uv.lock
                 nova_train: gpu（显卡能不能用） train（mjlab 的训练，关掉预料之中的提醒） contract（写策略的规约）
                 export_policy（导出给测试台） nova_warp（Nova 在显卡上的仿真） fixtures（测试用的小策略）
                 tasks（我们自己的训练任务，名字以 Nova- 开头：G1 练楼梯）
results/        训练的记录、练出来的策略、考的结果（不提交）
view/            网页：Vue 3 + TypeScript + Naive UI + three.js，直接在这台电脑上跑（Node.js，端口 5280）
                 sim/（连接 link、检查 contracts、网格 meshes、画面上的数多久换 display、算出来的 derive、总的 useSim）
                 stage/（3D：figure 搭身体和摆姿势，stage 碰显卡） components/（画面的各块） text/（数和状态的写法）
                 generated/（照规约生成的类型，不手改） test/（测试用的样本，从真的仿真里抓的）
third_party/     外面来的东西：清单（提交）和按清单下载的文件（不提交）。现在只有基线的模型 unitree_g1
scripts/         本地检查（check.ps1）、打开网页（view.ps1）
```

## 常用命令

```powershell
docker compose run --rm body pytest                            # 身体的测试
docker compose run --rm body python -m nova_body.mass_report   # 算质量闭环，报告写进 docs/报告/质量闭环.md
docker compose run --rm body python -m nova_body.model_report  # 生成身体的模型、站 10 秒，报告和图写进 docs/报告/身体模型.md
docker compose run --rm body python -m nova_body.third_party   # 下载、核对基线的模型（已经有的只核对，不连网）
docker compose run --rm body python -m nova_body.baseline_report  # 基线和 Nova 跑同一套测试，报告和图写进 docs/报告/基线身体.md
docker compose run --rm body python -m nova_body.strength_report  # 两个身体做全部的动作、算力量，报告写进 docs/报告/力量.md（约两分半钟）
docker compose run --rm body python -m nova_body.drive_report  # 选驱动器、算一轮家务的热，报告写进 docs/报告/驱动器.md（一两分钟）
.\scripts\check.ps1                                            # 提交前的检查：外面来的文件、格式、规则、测试、报告和代码对得上、网页
.\scripts\view.ps1                                             # 打开网页：启动仿真（容器）和网页的服务，再打开浏览器
docker compose up -d sim                                       # 只启动实时的仿真（http://127.0.0.1:8870）。改了 Python 代码要 docker compose restart sim
npm --prefix view run contracts                                # 改了 contracts/ 里的规约以后，重新生成网页用的类型
npm --prefix view run fixtures                                 # 改了规约或身体以后，从开着的仿真里重新抓网页测试用的样本
npm --prefix view run test                                     # 网页的测试（lint、build 也是这样跑）
docker compose run --rm rt                                     # 实时分区（C++）：编译、跑 C++ 的测试
docker compose build body                                      # 改了 rt/ 里的 C++ 以后：重新做身体的镜像（里面装着 nova_rt）
docker compose run --rm train                                  # 训练的容器：看显卡能不能用（要显卡）
docker compose run --rm train pytest                           # 训练这边的测试
docker compose run --rm train python -m nova_train.train <任务> ... # 训练，参数和 mjlab 的 train 一样（见 train/README.md）
docker compose run -d --name nova-train-<名字> train python -m nova_train.train <任务> ...  # 要练几个小时的：容器自己跑
docker logs -f nova-train-<名字>                               # 看它练到哪了（练完 docker rm nova-train-<名字>）
docker compose run --rm train python -m nova_train.export_policy <任务> <那次训练的目录> --name <名字> --body <身体>  # 交给测试台
docker compose run --rm body python -m nova_body.policy_walk /results/policies/<名字>/contract.json  # 在测试台上考走路
docker compose run --rm body python -m nova_body.p2_exam /results/policies/<名字>/contract.json  # P2 的考试（几个进程一起考，约 15 分钟）
docker compose run -d --name nova-exam-sonic body python -m nova_body.p2_exam sonic  # 考 SONIC（4 个进程，一个多小时）
docker compose run --rm train-lock                             # 改了 train/pyproject.toml 以后重新锁版本
```

## 规则

- **P1、P2 只做"核心"。** 范围看 `docs/核心和待证明.md`，步骤和进度看 `docs/P2计划.md`（P1 的看 `docs/P1计划.md`）。
- 用户没有开发经验，计划和细节由 Claude 定（2026-11-13 用户定）。只有这几种事要先问：要花钱的、和已经定下的事有冲突的、不能撤销的。
- 规格在 `docs/` 里。改设计就改规格，并在 `docs/决定记录.md` 加一行。`research/` 是历史，内容不再改（只在最上面写"用户定"的结果）。
- 技术栈看 `docs/技术栈.md`。加库、换库要改它。版本写死；新版本发布超过两周才用。
- 新的模型、数据、素材先查许可证，登记进 `docs/AI模型.md` 第 10 节（以后要商用）。
- **力量的目标从动作算**（1.5 步，`strength.py`）：改了动作、身体、质量的假设以后，跑力量的报告；"这一遍算的目标"和
  `design.DAILY_TARGETS` 差得多（超过几个百分点）就把新的数写进去，再跑一遍（换了目标，体重和身体都变，要算两遍才到头）。
  报告是确定的（同样的代码算出同样的字），提交前的检查会比对。
- **驱动器按发热也要选**（1.6 步，`drives.py`、`heat.py`）：一直要出的力矩写在 `design.CONTINUOUS_TARGETS`，和力量的目标一样要算两遍到头（驱动器的报告第 6 节比"这一遍算的"和"设计里的"）。改了动作、家务的循环、驱动器的数以后，跑驱动器的报告。转速只改绕组和电流，不改重量；并联的两个驱动器是同一种零件。
  热的数（电机常数、每公斤散多少热）来自公开的产品数和一篇论文，不是实测的；报告里写的是估计。
- **驱动器和关节不是一一对应的**（1.6 步）：并联的一对（踝、腰、腕）在模型里是两根"固定肌腱"上的两个驱动器，一个是两个关节的和、一个是差。`Body.actuators` 是驱动器的清单（顺序和模型里的驱动器一样，每个写着带哪几个关节、系数），`Body.joints` 是有驱动器带着的关节（峰值是这个关节单独用力时最多出的，并联的是一个驱动器的两倍）。站姿里每个驱动器的力 `stand.holding_torque_nm` 按驱动器排；要按关节看用 `body.joint_holding_torques_nm`。站姿按 MuJoCo 的力臂（`actuator_moment`，3.17 里是稀疏的，用 `mju_sparse2dense`）解，不管驱动器怎么带关节。
- **仿真每一步都经过驱动器的那一层**（`actuation.step`）：力的上下限每一步按转速和绕组的温度改（`actuator_forcerange`，改了马上生效），热每 10 毫秒算一次，命令晚 1 毫秒到（`DriveLayer.command`）。这一层改模型，所以仿真要用自己的一份模型（`copy.copy`）。没有驱动器模型的身体（基线）只有延迟。
- **身体各段之间也碰撞**（1.6 步）：外壳的 conaffinity 是 1；父子两段 MuJoCo 自己不算，腕那里本来就挨着的用 exclude 去掉（站姿里它们插着几毫米）。加新的段要看站姿里有没有插到一起（`strength.self_contacts`）。接触传感器也量得到身体自己碰自己（大腿顶着胸），测"碰到地面没有"要看接触的清单，不要只看接触传感器。
- **实时分区和脊髓层**（`rt/`、`nova_body/spine.py`，2.1 步，为什么这样做）：
  - C++20，警告都当错误。`Spine::step` 里不分配内存（缓冲在建的时候分好）；输入不对（长度、不是数、负的软硬）抛 `std::invalid_argument`，到 Python 里是 ValueError。C++ 的测试（GoogleTest）每个 TEST 上面写一行中文的 `// 说明：`。
  - `nova_rt` 是装进身体的镜像里的（不是挂源码）：改了 `rt/` 要 `docker compose build body`，C++ 的测试是 `docker compose run --rm rt`。
  - 脊髓层照 MuJoCo 的模型建（`spine_for`）：驱动器要是位置控制的，带着一个关节或者一根固定肌腱；力的上限用模型里写的（驱动器那一层每一步改它以前的），模型在关节上写了力矩上限就取小的。脊髓层的关节顺序是"驱动器带着的关节，按模型里的顺序"，和 `Body.joints` 一样。
  - 并联的一对两个关节软硬不一样时，驱动器那边的软硬有交叉的项：驱动器只管对角的，交叉的由脊髓层每 1 毫秒按读数算成前馈力。限过的部分从前馈力里扣，目标、软硬照小脑层给的。
  - 策略（`PolicyRunner`）只给关节的命令（`JointCommand`），经过脊髓层（`step_spine`）和驱动器那一层（`DriveLayer.command_impedance`：目标、刚度、阻尼、前馈力一起晚 1 毫秒到；前馈力放在 MuJoCo 的 position 驱动器的偏置里）。策略不管的关节要测试台给命令（`base`）。
  - 状态估计（`estimation.py`）：IMU 的读数来自 `SensorModel`（它要的是 `SensorList`：`Body` 或 `SensorSet`），腿的运动学用一份自己的仿真状态（骨盆放在原点），关节的角度从驱动器的读数换算（像编码器）。着地的点"会滑多少"的噪声不能给大（给 0.1 m/s/√Hz 时站着也差 0.1 m/s），现在是 0.002。练的时候的身体（规约里的 `body.name`）用哪个 IMU、哪两只脚、推哪里写在 `policy_bodies.POLICY_BODIES`；测试台的身体用 `setup_for_body`。G1 脚上没有力传感器，着地用仿真里脚和地面的接触力：地面是固定在世界上的形状（平地、楼梯的每一级），不只是叫 floor 的那一块。`policy_walk` 走两遍：策略看仿真里的真数、看身体自己感觉到的（`BodySense`）。
  - 反射（`reflexes.hpp`、`spinal.py`）在小脑层的命令和硬限制之间：先改命令（变软、顶住、断力），再由 Spine 守住硬限制；保护的反射把每个驱动器能出的力的比例交给 Spine（`actuator_force_scale`）。跌倒、停止一直留着，直到 `reset`；停止只升不降。2 类停止只标出来（要小脑层停下来站住），1 类的"坐下"等 2.6 步。碰撞只看手臂的皮肤（`SkinMap`）。0 类停止的刹车阻尼是驱动器的 Km²（没有驱动器模型的身体是 0）。走路的考试也走整条脊髓层（`SpinalLayer`）。跌倒的反射可以关掉（`fall_armed`）：考"起来"时关掉，因为躺着本来就是歪的（以后是小脑层在做起来的动作时关）；关掉只是不判断新的摔倒，已经在摔倒的要 `reset`。测试台不认识的身体没有状态估计，反射看真的歪斜。跌倒的门槛（歪过 50°，或者歪过 35° 又每秒倒 3 弧度以上）是 2.2 步按 G1 被推的数定的（88 次，推的时刻错开）：原来的 40°、25°、每秒 1.5 弧度把救得回来的也当成在摔倒，变软了反而摔了（往左、往右推时扛得住的因此少了一档）。G1 最多从 46° 救回来，30° 上下时还会每秒倒 3.8 弧度：光看歪斜分不清，所以宁可晚报（2.6 步换成更好的判断）。改门槛以前先把反射关掉推一遍：救得回来的最多歪多少、倒得多快，救不回来的提前多久报。
- **SONIC 接到测试台**（`sonic_*.py`，2.2 步，为什么这样做）：
  - 测试台认两种"大脑"（`policy_bench.BenchBrain`：怎么建身体、默认的姿势、每一步的控制器）：有规约的策略（`ContractBrain`）和 `SonicBrain`。SONIC 不吃速度命令、也不是一个网络，表达不进规约，所以照它部署的 C++（`third_party/gr00t_wbc` 里的 `g1_deploy_onnx_ref.cpp`）用 Python 重写了那一圈。读源码的笔记要点都写在 `sonic_*.py` 的说明里；改之前先对照源码。
  - 每秒 50 次：记状态 → 对齐朝向 → 编码器（1762 个数，G1 模式只填未来 10 帧的关节、转速、骨盆朝向，别的留 0）→ 解码器（994 个数：动作记号 + 10 帧的历史）→ 目标 = 默认 + 动作 x 比例 → 换上新规划的一段、前进一帧。换上新的一段的同一步帧号就变成 1（不然每次重新规划参考动作都慢一帧）。朝向的对齐量只在第一次拿到规划的动作时定下，之后不变。规划器每秒看 10 次要不要重新规划（走法、脸朝的方向变了；走着时速度、方向变了或者每 1 秒）。
  - 考试的速度命令照它手柄的程序换：脸朝的方向按转的速度累加，走的方向 = 命令的方向 + 脸朝的方向，速度定走法（慢走 0.2~0.8、走 0.8~1.5、跑 1.5~3.0 m/s）。不替它校正速度：它的规划器生成的参考动作比要的慢（要 0.5 给 0.42，要 1.0 给 0.82），机器人跟参考动作跟得很紧。
  - 身体用部署代码里的 `g1_29dof.xml`（不带手），加上官方仿真里关节的动力学（转子惯量 0.01、阻尼 0.05、摩擦 0.2，腕 0.1），力矩电机换成位置控制（SONIC 的软硬、关节上写的力矩上限），骨盆上加 IMU、两个脚底的点（位置照 mjlab 的 G1）。MuJoCo 3.17 的 MjSpec 里关节的阻尼是三个数，力矩上限叫 `actfrcrange`。
  - 规划器有 774 MB：一个进程里读一次大家共用（`functools.cache`），考试只开 4 个进程（每个约 1.8 GB 内存）。
- **P2 的考试**（`p2_exam.py`，2.2 步，为什么这样做）：
  - 都在 `PolicyBench` 上考（小脑层 → 脊髓层 → 驱动器那一层 → 仿真），策略看身体自己感觉到的；裁判看仿真里的真数。几道题互不相干，每一份一个进程（用 spawn：父进程里已经有 ONNX 的线程）。
  - 摔倒 = 骨盆歪过 60° 或者离脚下的地面低到站着时的一半（楼梯上从骨盆下面那一级算）；站着 = 至少站着时的八成高、歪不过 20°。
  - 被推照 P1（胸上 0.5 秒，力按体重的比例），从 4% 起每档加 4%，到 60%，推到倒了为止；四个方向。每档推 4 次，推的时刻在策略的一个周期里错开（推到时策略算到哪一步不一样，同一档 G1 最多差 9°、倒不倒都会变），4 次都没倒才算扛得住。走 1 公里是一圈 8 段的命令（往前 0.5~1.1 m/s、转弯、横着、后退）一圈一圈地走。
  - 楼梯是套内楼梯里最难的（一级 0.20 m、踏面 0.22 m，上 15 级、平台、下 15 级），三种：平常的、中间往右推一下（体重的 10%，0.3 秒）、第 8 级是滑的（摩擦 0.3）。上了几级、下了几级按"站得好好的"走到的最远的地方算（掉下去、扑上去不算）。
  - 起来：从趴着、仰着、侧躺着（都是头朝 +x）开始，跌倒的反射关掉，10 秒内站起来、再站住 2 秒才算。
- **训练**（`train/`，为什么这样做）：
  - 训练的容器用显卡（compose 里的 `deploy.resources`），镜像 10.6 GB，要的时候才开。Warp 第一次用时要编译显卡的程序，编译好的留在 `train-cache` 卷里。
  - 版本锁在 `train/uv.lock`（uv；`exclude-newer` 只要两周以前发布的）。改了 `train/pyproject.toml` 先 `docker compose run --rm train-lock`，再 `docker compose build train`；镜像用 `uv sync --locked`，锁和 pyproject 对不上就不装。
  - mjlab 用 2026-11-01 那一版（1.6.0）。它写的是 MuJoCo 3.16，我们用 override 装 3.17（和身体一样）。绕开的四处，都不改 mjlab：`MUJOCO_GL=disable`（容器里没有 EGL）；`GIT_PYTHON_REFRESH=quiet`（没有 git）；训练用 `nova_train.train`，它关掉"解的次数用完了"的提醒（迭代、线搜索；接触、约束放不下的提醒留着）；导出身体时按训练的设置另建一份 Entity（已经接进场景的那一份，3.17 里再复制会崩）。
  - 在 Git Bash 里给容器传 `/results/...` 这样的路径要加 `MSYS_NO_PATHCONV=1`，不然会变成 Windows 的路径（训练的记录写进过 `train/E:/...`）。PowerShell 里不用。
  - **只认测试台的分数**：练完用 `export_policy` 导出（ONNX、练的时候的身体模型、规约），在测试台上考（`policy_walk`、`p2_exam`）。导出时比一比 ONNX 和 PyTorch 的动作，对不上就不交。
  - 策略的规约只写在 `contracts/policy`：训练那边写，测试台读，两边都照 JSON Schema 检查。规约表达不了的（观测的历史、剪裁、延迟、每一维的缩放）导出时就拒绝；测试台的 `PolicyRunner` 对不上（关节、驱动器、IMU 的点、步长凑不成策略的周期）就拒绝；命令超出练过的范围拒绝，不剪。规约里哪个数的意思变了，`contract_version` 加一。
  - 要练几个小时的训练用 `docker compose run -d --name …` 让容器自己跑：跟着会话的后台命令，会话结束时会被一起停掉（2026-11-20 练楼梯练到第 111 轮就停了）。练到一半停了可以接着练（`--agent.resume True --agent.load-run …`），但命令、地形"由易到难"的计数会从头算，练得不多时不如重新练。
  - 楼梯的任务（`nova_train/tasks.py`）照 mjlab 的 G1 不平地的任务，只换地形（楼梯到 20 cm、踏面 22 cm 和 30 cm、高低不平的方块地面）和凸形状的迭代（50 次）：mjlab 的 500 次时，这块 8 GB 的显卡放不下碰撞的缓冲（4096 个仿真光一块就要 2.9 GB）。地形都用方块，因为 G1 碰撞的形状只有球和胶囊，它们和方块之间有现成的算法，用不到那些迭代（高度场才用得到）。4096 个仿真时显卡要用到约 6.2 GB，一轮约 3.6 秒。
  - 高度扫描（`height_scan.py`、规约的 `height_scan`）照 mjlab 的打法：从骨盆那一点出发、网格只跟着转偏航、射线竖直朝下、先 y 后 x 地排、只打给定的几组形状（地面在第 0 组，mjlab 的 G1 的形状在第 2、3 组）、骨盆自己不打、打不到就当最远的距离。测试台现在用仿真里的真数（以后换成深度相机算的，2.5 步）。规约表达不了的打法（跟着全身转、减常数、打不到另算）导出时就拒绝。
  - 身体那边测试用的小策略（`body/tests/fixtures/policy`，看脚下高度的 `policy_scan`）是 `nova_train.fixtures` 做的（身体的容器里没有做 ONNX 的库），训练这边的测试核对提交的和做出来的一个字节都不差；改了要重新做、一起提交。
  - 量显卡上的显存用 Warp 自己记的（`wp.get_mempool_used_mem_current`）：Warp 会留着用过的显存，"显卡还剩多少"量不准（量出过负数）。
  - mjlab 自带的 G1 和测试台的 G1（Menagerie 的 `g1.xml`）不一样：碰撞的形状、关节的摩擦、转子惯量、软硬都不一样。策略是在哪个身体上练的，规约里写着（`body`），测试台（`policy_bench`）用那一个。
- **身体的传感器读到的不是理想的数**（1.6 步，`sensing.py`）：IMU、六轴力、接触力都加上噪声（按数据手册的噪声密度）、零偏（每一回随机取一次）、延迟（IMU 2 毫秒、六轴力 1 毫秒、接触力 2 毫秒）。实时的仿真每一步读一次，网页上"感觉"那一块给的是它们；测试按传感器的精度比（零偏 + 几倍的噪声），不按理想的数比。测试台自己量的（地面托着多少、压力中心）还是仿真里的真数。
- **用踝的六轴力算压力中心要扣掉脚自己**（`standing.pressure_center_from_ankle` 的 `FootLoad`）：传感器在脚的上面，脚的重量（和脚加速时要的力）也压在地上，却不经过传感器。不扣差半毫米多，扣了差不到 0.05 mm。脚的加速度像加速度计那样读（站着是朝上的 9.81），真机上用脚的 IMU。
- **逆运动学一帧一帧解，要防它在一帧里跳**（跳一下就算出几倍的假力矩，1.5 步踩过）：关节的边是软的（离边 5° 开始不划算）；
  每帧拉向上一帧（`Goals.near`）；原地的动作给关键时刻（`key_times`），所有关节一起慢慢变；只用腿的动作里手臂和头不动
  （`leg_ik`）；逆动力学算加速度以前先低通滤一下（约 6 Hz，和量人的动作一样）。看一个动作可不可信：
  关节的加速度（几百 rad/s² 以上就可疑）、压力中心离脚底的边、要的摩擦。
- **压力中心那张换算表跟着骨盆在哪变**，每一帧都要重新算（1.5 步发现一直用着第一帧的，走路的修正越修越偏）。
- **走路和楼梯的重心高低不直接给**：先不定高低解一遍（姿势尽量像站着），取一条处处不比它高的平滑的线，楼梯再加一条"匀匀地升"的上限。
  脚跟离地时绕"踩着的那一块的最前面"转（平地是脚尖，下楼是台阶的边），撑着的只有那一条。
- **计算和仿真只在 Linux 容器里跑。** 这台电脑的 Windows 开着智能应用控制，会拦没有签名的 `mujoco.dll`。
  不要关这个安全设置（关了要重装 Windows 才能再开）。容器挂着源码：改了 Python 代码不用重新做镜像；改了依赖要 `docker compose build body`。
- **规约只写一处。** 关节表（有哪些关节、力矩、记号）的源头是 `body/nova_body/design.py`；每个关节的转轴和范围在 `skeleton.py`、`hand.py`；
  质量只从质量闭环来（模型不自己定重量：质量闭环里多了一样模型不认识的东西，生成时会报错）。
  `docs/报告/` 里的文件是程序生成的：改假设、改代码以后重新生成，不要手改。报告里不写每次运行不一样的数（比如仿真比实时快多少）。
- **身体的模型**（`model.py`，为什么这样做）：
  - 骨架只写左侧，右侧用 `mirror_point`、`mirror_axis` 镜像，所以同一个正方向在两侧是同一个动作。加关节要加一条"往正方向转是不是说的那个动作"的测试。
  - 身体要按"先把一段和它带着的都加完，再加下一段"的顺序加。MuJoCo 编译以后是这个顺序，这样关节清单和模型里的顺序才一样。
  - 模型生成两遍：第一遍算站姿（要知道重心在哪），第二遍把站姿存成关键帧 `stand`。
  - 站姿的目标 = 关节的角度 + 顶住重力要的力矩 ÷ 刚度。只给角度的话身体会往下沉（力量减半的身体沉了 2°）。
  - 驱动器是"位置 + 阻尼"，积分用 implicitfast：阻尼很大，不这样算会不稳。以后要在运行时调软硬，就改模型里的 `actuator_gainprm`、`actuator_biasprm`。
- **测试台和身体分开**（`bench.py`、`body.py`，为什么这样做）：Nova 和基线要比，结果只能差在身体上。
  - 地面、步长、积分的方法、关节位置控制的软硬、站姿的算法、合格线，对每个身体都一样，只写在测试台这一处。
    新的身体（比如 NVIDIA 的参考人形机器人）交出一个 `Body` 就行；测试台、站姿、画图的代码不许认身体是哪一个。
  - 测试台的地面、楼梯（`bench.ground_settings`）的组、摩擦、软硬都写死成 MuJoCo 的默认值：加进身体的模型时不写的会跟着那个模型的默认值走（看脚下高度的小身体说"形状都在第 3 组"，地面也跟进了第 3 组，射线就打不到了）。G1、Nova 原来就是默认值，以前的结果不变。
  - 和地面的摩擦、软硬由地面定：地面的优先级（`priority`）比任何身体的形状都高。现成的模型会给自己的脚写摩擦和优先级。
  - 站姿按动作写（膝弯、脚尖向上、髋向前抬）。每个身体的关节往哪边算正不一样（G1 的髋和踝跟 Nova 是反的），
    所以先看转轴朝哪边，再定正负；不要直接往 qpos 里写带正负号的角度。
  - 用到 `body` 这个 fixture 的测试，Nova 和基线各跑一遍，这就是"同一套测试"。新写的测试能通用的就用它；
    只有一个身体才有的东西（Nova 的力传感器、手指）另外写。
  - 比较时推力按体重的比例算（`push_of_weight`），不要用同样的牛顿数去推轻重差一倍的身体。
- **基线的模型**（`baseline.py`、`third_party.py`）：文件不提交进仓库，按 `third_party/*.json` 的清单下载，每次用之前核对 SHA-256。
  - 模型文件一个字都不改。身体本身（质量、关节、电机的峰值力矩、摩擦、形状）都用文件里的；
    读进来以后只换测试台管的东西（地面、步长、软硬），加脚底的点和关节的传感器。有测试逐项对照文件原样的模型。
  - 换版本、加新的模型：先查许可证（[AI 模型](docs/AI模型.md) 第 10 节），再写清单，看 `third_party/README.md`。
  - 文件里的模型和代码以为的不一样（驱动器的个数、不是位置控制、不认识的关节）就报错，不要猜。
- **实时的仿真和网页**（`nova_sim`、`view`，为什么这样做）：
  - **一直开着的仿真不会自己读改过的代码。** 测试（`docker compose run`）每次是新的容器所以能过，
    网页连着的那个要 `docker compose restart sim` 才是新代码。改了规约、改了身体也一样。
  - 规约只写在 `contracts/sim/*.schema.json`。改了以后：`npm --prefix view run contracts` 重新生成类型（生成的文件要提交），
    重启仿真，`npm --prefix view run fixtures` 重新抓样本。规约里"引用"的旁边不要写说明（写在上一层），不然生成的类型会多出 Vector1、Vector2。
  - 网页发来的命令先照规约检查再做；范围以外的值直接拒绝、说为什么，不改成范围里的。做完命令再答复。
  - 仿真只在一个循环里往前走，命令也在这个循环里做。没有网页连着的时候它停着不算。
  - **给网页发东西都经过这个网页自己的队列**（`channel`）：仿真的循环只往里放，从不等网页收（以前一个收不动的网页能把仿真拖停）。
    还没发出去的状态只留最新的一条，答复前后的状态不合并；积压超过上限（`MAX_PENDING`）就断开它，网页会自己再连。
  - 身体的样子和网格**按身体的记号拿**（`/scene/记号`、`/mesh/记号/编号`），不按"现在测试台上的"：拿的中间换了身体也不会拿错。
  - 网页**每次连上（收到招呼）都再拿一次样子**：仿真重启过、身体改过也不会接着用旧的样子；上次没拿到的也再试一次。
    原文一个字都没变就不重新搭（3D 选的视角不会被重置），再拿的那一会儿先不用新的状态（身体改过的话数组对不上）。
  - 只让我们自己的网页（`http://127.0.0.1:5280`、`http://localhost:5280`）连上来发命令；两个端口都只在这台电脑自己上开。
  - 网页不认身体是哪一个：只照仿真给的"样子"画，有什么感觉就列什么。给身体加一种感觉，要加进 `Body` 的清单、规约和网页三处。
  - 画面上的数隔 0.1 秒换一次，重要的变化（倒了、暂停了……）马上换；3D 用每一条状态。
  - **Naive UI 的折叠面板（NCollapse）里的内容不跟着状态更新**（表格停在刚打开时的数上）。会一直变的内容用浏览器自带的 `<details>`。
  - 画面上的字、状态的叫法只写在 `view/src/text`。命令的函数别叫 `push`（代码检查会当成在改数组）。
  - 用预览工具的 `preview_start` 按名字启动，启动的是上一个项目的画面（它读的是 `main` 那个目录的配置）。
    Nova 的网页这样开：后台直接运行 `node view/node_modules/vite/bin/vite.js view --port 5280 --strictPort --host 127.0.0.1`，
    再用 `preview_start` 的 `url` 打开 `http://127.0.0.1:5280`。预览的那一栏很窄，截图看不清；
    要一张清楚的整页截图：`node view/scripts/screenshot.mjs <输出.png> [--body g1]`（仿真和网页要先开着；用无界面的 Edge 等几秒再拍）。
- **MuJoCo 容易踩的坑**（都实测过）：
  - MjSpec 的角度默认是度，开头就设 `spec.compiler.degree = False`；但相机的 `fovy` 总是度。
  - `mj_step` 以后，`sensordata` 里是这一步**开始时**的值，比 `qpos` 早一步。要现在的值先 `mj_forward`。
  - 联动的等式约束（`mjEQ_JOINT`）的 `data` 要给满 12 个数。
  - `contact` 传感器：用 `reftype`、`refname` 指定身体，读到的是这个身体**受到**的力，在世界坐标里；`intprm` 是 [报什么, 怎么合, 报几个]。
  - 力传感器（`force`、`torque`）量的是上一段给这一段的力，带着这一段自己的重量；力矩是绕传感器那个点的。
  - 脚底正好贴着地面时接触力是 0；身体先掉下去一点点（约 0.2 mm）地面才托住它。
  - 测"只有某处碰到"时，别让别的地方深深插进地面：那样整个身体被猛地往上推，要测的那个接触反而没有力。
  - 改现成模型的驱动器：直接改 `gainprm[0]`（刚度）、`biasprm[1]`（负的刚度）、`biasprm[2]`（负的阻尼）。
    文件里写的 `dampratio` 存成正的 `biasprm[2]`，编译时才换成阻尼；写成负数就是直接给阻尼。
  - 带肌腱的驱动器，上限写在驱动器上（`forcerange`），`actuator_force` 就是限过的；关节上的力矩看 `qfrc_actuator`（几个驱动器合起来）。
  - 关节上的力矩上限（`actuatorfrcrange`）限的是 `qfrc_actuator`，不是 `actuator_force`：G1 的膝出到顶时，后一个读到 3639 N·m，
    实际只有 139。要看关节实际得到多大的力矩，看前一个；测试台的力矩传感器量的也是它（`jointactuatorfrc`）。
  - `contact.friction` 是五个数（两个方向的滑动、转动、两个方向的滚动），`geom_friction` 是三个数。
  - 两个形状碰在一起时，优先级高的那个定摩擦和软硬；一样高才取大的、取平均。
  - 传感器的 `noise` 在 3.17 里只是一个记下来的数，仿真不会真的加噪声。
  - 同一个名字加两次，`add_geom` 当场就报错；不用等到编译。`spec.compile()` 可以改了再编译一遍。
  - 仿真算出了"不是数"的时候，MuJoCo 自己悄悄回到零位接着走，只留一条警告（`data.warning`）和一个 `MUJOCO_LOG.TXT`。
    所以实时的仿真每一步都看这几条警告，有了就停下、说出来。
- 画图（`drawing.py`）不用显卡：把每个形状投影成多边形写成 SVG，颜色用模型里写的。加了新的形状（比如圆柱）要先教它怎么画，不然会报错。
  网格画成凸包。要看图渲染出来的样子（字有没有被挡住），用无界面的 Edge 截一张：
  `msedge --headless=new --user-data-dir=<临时目录> --window-size=宽,高 --screenshot=<png> file:///<svg>`；应用里的浏览器不能看本地的文件。
- 文档、画面、测试的说明、提交信息都用中文。代码里的名字用英文，注释用中文。
- 每加一样东西，记下它加了多少重量：多带 1 kg，总重要加 1.7~2 kg（质量闭环的结果）。
- 换行一律用 LF（`.gitattributes`）。PowerShell 脚本里有中文，文件开头要带 BOM，不然 Windows PowerShell 会读成乱码。
- 不和别的项目混：`main` 分支是上一个项目（BL-01 机甲）；`E:\Workspace\iot`、`E:\Workspace\humen` 是别的项目。
- 不用现有作品的名字、设计和标志。
