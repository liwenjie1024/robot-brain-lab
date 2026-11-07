# 로봇 두뇌 시험장 (robot-brain-lab)

사람형 기체의 AI 두뇌(빠른 뇌 System 1, 느린 뇌 System 2)를 물리 시뮬레이션 안의 몸으로 시험하는 플랫폼이다.
시험 기체는 날고 무장한 사람형 기체 BL-01(이 프로젝트의 독자 설계)이다. 몸과 비행·팔 제어는 시험 대상이 아니라 시험 장치다.
지금은 이 PC(Windows, Docker Desktop, RTX 4060 Ti 8GB)에서만 돌린다. 층마다 하는 일과 까닭은 `docs/architecture.md`가 기준이다.

## 개발 지침 (항상 지킨다)

1. **코드 품질과 가독성**
   - 클래스와 함수는 한 가지 일만 한다. 이름만 읽어도 하는 일을 알 수 있게 짓는다.
   - 매직 넘버와 문자열은 이름 있는 상수나 설정으로 뺀다.
   - 주석은 "왜"를 설명할 때만 쓴다. "무엇"은 코드가 말하게 한다.
   - 외부 입력(WebSocket, HTTP, 언어 모델 출력)은 경계에서 검증하고, 안쪽 코드는 검증된 값만 다룬다.
2. **초보자도 쉽게 쓰는 UI/UX**
   - 화면 문구는 쉬운 한국어로 쓴다. 전문 용어는 풀어서 설명하거나 도움말을 붙인다.
   - 상태는 색과 글자를 함께 쓴다(색만으로 구분하지 않는다).
   - 모든 화면에 로딩, 빈 상태, 오류 상태(다시 시도 버튼 포함)를 둔다. 연결이 끊긴 동안의 값은 오래된 값이라고 알린다.
   - 되돌릴 수 없거나 위험한 작업은 무슨 일이 일어나는지 설명하는 확인 창을 거친다 (실제 로봇을 붙이면 밀기·되돌리기도).
3. **테스트**
   - 기능을 추가하거나 바꾸면 테스트도 함께 쓴다.
   - 중요한 기능(명령 검증, 비행·팔 제어, 사격·피해, 판단·계획)은 정상, 경계값, 실패, 중복·순서 뒤바뀜 상황을 모두 테스트한다.
   - 테스트 설명은 한국어로 쓴다 (pytest는 docstring과 ids, vitest는 it 이름).
   - 몸의 시험은 물리를 실제로 돌려 확인한다 (날기·자세·조준·사격·막기). 값은 실제로 재 보고 정한다.

## 구조

```text
contracts/       규약 (JSON Schema). 규약은 여기 한 곳에서 정하고, 몸·두뇌·화면이 같은 파일로 검증한다
  sim/             몸 ↔ 화면·두뇌: 명령, 상태·사건, 시험장 설명
  brain/           화면 ↔ 두뇌: 지시(말로 한 명령 포함), 두뇌 상태·판단 기록, 느린 뇌의 계획 형식(plan)
sim/             몸: MuJoCo 물리(500Hz) + 비행·팔 제어 System 0 + 무장·드론 + 서버(aiohttp, :8765)
                 Python 3.13, Linux 컨테이너에서만 돈다 (아래 규칙)
                 mecha(기체 모양) arena(시험장) flight(비행 제어) arms(팔 제어) weapons·combat(사격·체력)
                 drones·scenarios(표적 드론·시험 장면) simulation(진행) runner·server(실시간·서버)
ros/             ROS 2 쪽 몸 (Lyrical 컨테이너 하나): bl01_msgs(메시지·서비스) bl01_driver(몸의 WebSocket → ROS 2 토픽·서비스,
                 sim_link(몸 연결) convert(바꾸기) driver_node) + rosbridge(:9090). scripts/record-bag.sh(rosbag2로 남기기)
brain/           두뇌 (TypeScript, Node, :8766). 나중에 휴대폰 React Native로 옮길 수 있게 TypeScript로 쓴다
                 System 1: perception(보이는 것) skills/(기술) reflexes(반사) commander(바뀐 명령만) system1(판단·기록·지표)
                 System 2(system2/): quickOrders(짧은 명령) planCache(기억) model(Ollama) prompt planStream(흘려 받기)
                 planCheck(계획 확인) planRun(단계 넘기기) system2(묻기·다시 묻기·끊기)
                 trials/: trialRunner(판 돌리기) runRecorder(한 판의 결과, 몸이 알린 값으로) trialStats(가운데 값) trialStore(남기기)
                 brain(둘과 시험을 묶음, 사람이 앞섬) server·controls(화면이 붙는 곳, 지시 검증)
shared/          화면과 두뇌가 함께 쓰는 것: 몸 연결(SimClient, 같은 모양 BodyLink), ROS 2로 몸 연결(ros/: rosbridge·bl01·RosBodyClient),
                 규약에서 만든 타입(*/generated), 기술·계획 이름(brain/labels),
                 시험 점수 셈법(brain/trialScore), 시험용 값(test/fixtures)
bench/           시험장 화면: Vue 3 + TypeScript + Naive UI + three.js. 한 화면(넘기지 않음)에 조종 보기 네 칸:
                 3D·기체 상태 | 두뇌(말로 명령·빠른 뇌) | 직접 조종(장면·비행·드론과 무장) | 기록(판단·전투·명령 탭).
                 시험과 점수는 머리의 "보기"로 바꾼다. 몸은 /sim, 두뇌는 /brain으로 개발 서버가 넘겨 준다
results/         두뇌가 남긴 시험 결과(trials/*.json), rosbag2 기록(bags/). git에 넣지 않는다
docs/            구조·기체·시험 장면·잰 값(architecture.md), 기술 스택(tech-stack.md)
scripts/         로컬 점검(check.ps1)
```

저장소 맨 위가 npm 작업 공간(shared, bench, brain)이다. `npm install`은 저장소 맨 위에서 한 번만 한다.

## 자주 쓰는 명령

```powershell
docker compose up -d --build sim        # 몸 띄우기 (http://localhost:8765, 코드를 고치면 docker compose restart sim)
npm install                             # 저장소 맨 위에서 (화면·두뇌·공용 모두)
npm run brain                           # 두뇌 (ws://localhost:8766, 몸과 Ollama(:11434)에 붙는다)
npm run bench                           # 시험장 화면 (http://localhost:5180)
.\scripts\check.ps1                     # 커밋 전 점검: 몸(컨테이너)·화면·공용·두뇌 lint·형식·시험·빌드
docker compose run --rm sim pytest      # 몸 시험만
npm run contracts                       # contracts의 JSON Schema를 고친 뒤 TypeScript 타입 다시 만들기
docker compose up -d --build ros        # ROS 2 쪽 몸 (rosbridge ws://localhost:9090, 코드를 고치면 docker compose build ros)
$env:BODY_LINK='ros'; npm run brain     # 두뇌를 ROS 2로 몸에 붙이기 (기본은 몸의 WebSocket: BODY_LINK=ws)
docker compose exec ros bl01-record     # 토픽을 rosbag2(MCAP)로 남기기 → results/bags (Ctrl+C로 멈춤)
```

사람이 화면을 쓰는 동안 시험을 오래 돌리려면 몸·두뇌·화면을 하나 더 띄운다 (시험은 장면을 계속 되돌린다):

```bash
docker compose run -d --rm --name robot-brain-lab-sim-trials -p 8775:8765 sim
cd brain && SIM_URL=http://localhost:8775 BRAIN_PORT=8776 node --import tsx src/main.ts
cd bench && VITE_SIM_TARGET=http://localhost:8775 VITE_BRAIN_TARGET=http://localhost:8776 node ../node_modules/vite/bin/vite.js --port 5181 --strictPort
# ROS 2로 잴 때: 드라이버를 시험용 몸에 붙이고, 두뇌는 BODY_LINK=ros ROSBRIDGE_URL=ws://localhost:9091
docker compose run -d --rm --no-deps --name robot-brain-lab-ros-trials -p 9091:9090 -e SIM_WS_URL=ws://robot-brain-lab-sim-trials:8765/ws ros
```

## 규칙

- 기술 스택은 `docs/tech-stack.md`가 기준이다. 라이브러리를 추가하거나 바꾸면 그 문서도 고친다.
  버전은 정확히 고정한다 (requirements.txt, package.json). 새 버전은 나온 지 2주 넘은 것을 쓴다.
- **몸(sim)은 Linux 컨테이너에서만 돌린다.** 이 PC는 Windows 스마트 앱 컨트롤이 켜져 있어 서명 없는 `mujoco.dll`을 막는다.
  보안 설정을 끄지 않는다 (한 번 끄면 Windows를 다시 설치해야 켤 수 있다). 컨테이너는 소스를 붙여 쓰므로
  Python 코드를 고치면 `docker compose restart sim`, 의존성을 바꾸면 `docker compose build sim`.
- **오래 떠 있는 몸 서비스는 고친 코드를 저절로 읽지 않는다.** 시험(`docker compose run`)은 새 컨테이너라 통과해도,
  화면·두뇌가 붙는 서비스는 `docker compose restart sim`을 해야 새 코드로 돈다 (드론 조준을 바꾸고 다시 띄우지 않아
  두뇌의 피하기가 듣지 않는 것처럼 보인 일이 있었다).
- 두뇌·화면 개발 서버를 백그라운드로 띄울 때는 npm을 거치지 말고 `node`를 바로 띄운다 (`node --import tsx src/main.ts`,
  `node ../node_modules/vite/bin/vite.js`). npm만 멈추면 아래 프로세스가 남아 포트(8766·5180)를 붙잡는다.
  `exec node`로 백그라운드에 띄운 두뇌가 출력 없이 종료 코드 127로 꺼진 일이 세 번 있었다 (앞에서 띄우면 재현되지 않음).
  오래 돌릴 두뇌는 출력과 종료 코드를 로그 파일에 남기게 띄운다 (`node … > 로그 2>&1; echo exit=$? >> 로그`).
- 규약을 바꾸면 `contracts/*/*.schema.json`을 고치고 `npm run contracts`로 타입을 다시 만든다(`shared/src/*/generated`). 몸은 같은 파일로
  명령을 검증한다 (`robot_sim/commands.py`). 값의 범위는 몸마다 달라 스키마가 아니라 몸이 정해 `/scene`의 limits로 알린다.
  범위 밖 명령은 잘라 쓰지 않고 거절한다 (두뇌의 실수가 드러나게). 몸의 시험 `tests/test_contracts.py`가 실제로 내보내는
  메시지·모델 설명을 스키마로 검증한다.
- 시험장의 모양은 화면이 기체를 모르게 `/scene`(모양·움직이는 몸체 순서·유닛)으로만 그린다. 기체를 바꿔도 화면 코드는 그대로다.
- 기체 모양은 코드(`robot_sim/mecha.py`, MjSpec)로 만든다. 특정 작품의 이름·디자인·로고(건담 등)를 쓰지 않는다.
  모델은 두 번 만든다: 처음 모델로 무게 중심·질량·관성을 재고, 추진기 힘이 걸리는 점과 힘 한도를 정해 다시 만든다 (`arena.py`).
  MjSpec의 각 단위 기본값은 도(degree)라 `spec.compiler.degree = False`로 라디안을 쓴다 (안 그러면 관절 범위가 1/57로 준다).
- 비행 제어(System 0)는 물리 주기마다 속도 차이 → 가속 → 힘(중력 포함)을 몸 기준 추진기에 나누고 자세를 세운다.
  값은 기체의 질량·관성으로 나눠 정한다. 명령 범위(`limits.py`)는 기체를 2° 안으로 세운 채 따라갈 수 있게 재 보고 정했다.
- 사격은 총구에서 **실제 총열 방향**으로 광선(mj_ray)을 쏜다. 겨눈 방향이 아니다. 그래서 두뇌는 상태의 aimError가 작을 때 쏴야 한다.
  광선은 geom 묶음으로(세계 0, 기체 1, 드론 2), 충돌은 비트로(서로 다른 것만 부딪힘) 나눈다.
- 드론은 시험 장치라 힘을 바로 걸어 움직인다. 모델의 드론 수는 `MAX_DRONES`로 고정하고 장면에서 쓰지 않는 드론은 시험장 밖에 둔다
  (화면이 받는 모양이 바뀌지 않게). 무장한 드론은 조준 경고(위협) 1.2초 뒤 쏘고, 드론마다 1초씩 엇갈려 시작한다.
- 지금 할 수 없는 명령(식는 중 사격, 없는 표적, 파괴된 기체)은 시뮬레이션이 `CommandRejectedError`로 까닭을 붙여 거절한다.
  시뮬레이션 시각 비교에는 `TIME_EPSILON_S`를 둔다 (정확히 같은 때가 실수 오차로 조금 모자라 "0.0초 남음"으로 거절하지 않게).
- 시뮬레이션은 시뮬레이션 스레드 하나만 만진다. 명령은 큐로 받아 제어 주기 사이에 적용하고, 답(ack)은 그 명령을 적용한 뒤의
  상태보다 앞서 보내지 않는다 (`server.ClientChannel`: 보낼 것을 만든 순서대로, 밀린 상태만 가장 새 것으로 합친다).
  사건(사격·격파)은 상태와 달리 합치지 않고 빠짐없이 보낸다. 명령으로 바로 생긴 사건은 그 명령의 답 바로 뒤에 보낸다.
- 화면 키보드 조종은 슬라이더·입력칸처럼 키를 스스로 쓰는 요소에 초점이 있으면 쓰지 않는다 (`drive.keyboardAction`).
- 화면 템플릿에서 컴포넌트 이름(CombatLog)과 같은 이름의 값(combatLog)을 두지 않는다. 템플릿이 값을 먼저 써 컴포넌트가 사라진다.
- 화면은 조작 칸을 넘기지 않고 한 화면에 다 보이게 둔다 (사용자 요청 2026-11-07). 페이지는 100vh에 고정하고, 칸이 모자라면 그 칸
  안에서만 넘긴다(기록 탭 등). 1320px보다 좁으면 기록을 3D 아래로, 1100px보다 좁으면(태블릿·휴대폰) 한 줄로 쌓아 넘긴다.
  긴 설명은 도움말 "?"(`HelpTip`, 화면 읽기용 aria-label 포함)에 둔다. 칸을 고치면 1920×960·1536×730(1080p 125%)·1440×780에서
  칸마다 내용 높이가 칸보다 작은지 재 본다 (재 보니 1536×730에서 두뇌 632/677px, 직접 조종 642/677px).
  Naive UI의 라디오 버튼 묶음은 버튼 사이에 구분선이 들어 있어 grid가 아니라 flex로 나눈다. 좁은 칸용 @container 규칙은 기본 규칙보다 뒤에 둔다.
- Vite 개발 서버가 같은 파일을 몇 초 안에 연달아 고친 것을 놓친 일이 있었다. 화면이 바뀌지 않으면 파일을 touch하고 새로 고친다.
- 위협 경고·기체 모드가 바뀌면 화면 표시 간격(0.1초)을 기다리지 않고 바로 보인다 (`useSim.changedUrgently`).
- 드론은 조준을 시작할 때 기체의 위치·속도로 쏠 자리를 셈해 그곳을 쏜다. 그래서 경고를 보고 속도를 바꾸면 빗나가고,
  같은 속도로 날면 맞는다. 두뇌의 피하기는 새 경고마다 속도를 다시 바꾼다 (피하는 속도도 다음 드론의 셈에 들어간다).
- 빠른 뇌(System 1)는 언어 모델을 쓰지 않는다. 기술(대기·자리 지키기·교전·물러나기)은 사람이나 느린 뇌가 고르고,
  반사(조준 경고에 피하기·막기)는 기술 위에 얹힌다. 몸에는 바뀐 명령만 보내고(`commander`), 속도는 몸이 알린 범위로
  자른 뒤 단위로 맞춘다(실수 오차로 범위를 넘지 않게 다시 자름). 사격은 거리에 따라 허용 어긋남을 줄여(1m를 지나가는 각) 쏜다.
- 두뇌가 조종을 맡으면 화면의 직접 조종 칸은 까닭을 보이며 잠긴다. 맡지 않으면 두뇌는 "두뇌라면 이렇게 함"만 보인다.
- 느린 뇌(System 2)는 기체를 직접 움직이지 않고 빠른 뇌의 기술만 바꾼다. 말로 한 명령은 짧은 명령(규칙) → 기억한 계획 →
  언어 모델 차례로 본다. 언어 모델의 답은 흘려 받아 단계 하나를 다 받는 대로 확인해 시작하고, 틀린 것이 보이면 끊고
  까닭을 붙여 한 번 더 묻는다 (2번까지). 확인은 스키마(모양)와 `planCheck`(뜻: 표적은 engage만·장면에 있는 드론,
  격파 조건은 engage만, hpBelow는 engage·hold만, never 뒤 단계 없음). 고쳐 쓰지 않는다.
- 언어 모델에게 주는 형식(`prompt.PLAN_FORMAT`)은 계획 스키마에서 $ref를 풀고 피하기에서 none을 뺀 것이다 (7B 모델이 말이 없는
  피하기에 none을 골랐다). 시스템 글은 명령마다 같게 둔다 (Ollama가 앞부분 계산을 다시 써 첫 글자가 40~80ms).
- 사람이 앞선다: 사람이 기술을 직접 고르거나 조종을 가져가면 계획을 그만둔다(`Brain`). 새 명령은 앞 계획과 묻던 요청을 끊고,
  늦게 온 답은 세대 번호로 버린다. 계획을 그만둬도 기체는 지금 기술을 그대로 한다.
- Ollama는 이 PC의 앱이 쓰는 모델 폴더로 띄운다 (`OLLAMA_MODELS=E:\ProgramData\ollama`; 기본 폴더는 비어 있다). 두뇌는 15초마다
  언어 모델을 다시 찾고, 찾으면 GPU에 미리 올린다. 없으면 짧은 명령(공격·물러나·멈춰·자리 지켜)만 따른다.
- 시험(trials)은 두뇌 밖의 심판처럼 돈다: 장면을 되돌리고(몸이 답한 뒤 처음 온 상태가 판의 시작), 두뇌에게 맡기고, 결과는 두뇌가
  센 값이 아니라 몸이 알린 값(상태의 체력·드론, 사격 사건)으로 낸다. 몸과 두뇌는 같은 때 맡으면 같은 결과를 내므로(재 보니
  다섯 판이 똑같음) 판마다 맡는 때를 고르게 늦추고(startSpreadS), 시간·피해는 맡은 때부터 잰다. 견줄 것을 번갈아 돌리고
  (1판째를 모두 → 2판째, 같은 판 번호는 같은 늦춤), 가운데 값과 범위로 견준다. 시험 중에는 화면의 다른 지시를 거절하고(시험 멈추기만), 다른 곳에서 장면을
  되돌리거나 몸과 끊기면 시험이 실패한다. 말로 한 명령은 판마다 기억한 계획을 잊고 새로 묻는다.
- **ROS 2 쪽 몸(ros/)은 몸을 바꾸지 않고 드라이버 노드가 몸의 WebSocket에 붙어 ROS 2로 낸다** (실제 로봇의 SDK + ROS 드라이버처럼).
  몸은 Python 3.13(MuJoCo), ROS 이미지는 3.14라 몸 안에 rclpy를 넣지 않는다. ROS 2 노드는 모두 한 컨테이너 안에 두고
  (`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, DDS는 Docker Desktop 가상 머신 밖으로 잘 나가지 않는다) 바깥은 rosbridge로 붙는다.
  ROS 이미지는 digest로, apt 패키지는 판으로 고정한다. Python 패키지는 pip가 아니라 Ubuntu 패키지로 넣는다.
- 몸의 규약(`contracts/sim`)을 바꾸면 `ros/src/bl01_msgs`, 바꾸기(`bl01_driver/convert.py`, `shared/src/ros/bl01.ts`)와 그 시험도
  함께 고친다. ROS 메시지에는 없음(null)이 없어 빈 글이나 `has_*`로 알린다. 명령은 서비스로(답: accepted·reason), 속도는 REP 103.
- 서비스 답과 상태 토픽은 다른 길로 와 순서가 보장되지 않는다. 되돌린 뒤의 상태는 상태의 `episode`(되돌린 횟수)로 알아본다
  (시험이 답 뒤에 온 첫 상태에 기대지 않는다). 두뇌는 `BodyLink` 모양만 쓰므로 `SimClient`·`RosBodyClient` 어느 쪽이든 그대로 돈다.
- 드라이버의 `/bl01/get_scene`은 몸과 붙어 있을 때만 장면 설명을 준다 (끊긴 뒤 남은 설명으로 두뇌가 붙은 줄 알지 않게).
  ROS 이미지는 소스를 붙이지 않고 복사하므로 드라이버를 고치면 `docker compose build ros` 뒤 다시 띄운다.
- 두뇌의 기본 연결은 몸의 WebSocket이다. ROS 2로 붙여도 15판이 똑같았다 (명령의 답 둘 다 약 20ms, 반응 18ms; architecture.md).
  Lyrical의 `ros2 bag record`는 토픽을 `--topics`로 받고, ROS의 setup.bash는 `set -u`에서 멈추므로 source한 뒤에 켠다.
- 장면 설명(`/scene`의 scenarios)은 드론 수·반격하는 드론 수를 알린다. 화면·시험은 장면 이름을 몰라도 드론이 없는 장면을 거른다.
- 사용자의 다른 프로젝트(E:\Workspace\iot)와 섞지 않는다. 그 프로젝트는 마무리되었다.
