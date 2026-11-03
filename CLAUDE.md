# 로봇 두뇌 시험장 (robot-brain-lab)

사람형 로봇의 AI 두뇌(빠른 뇌 System 1, 느린 뇌 System 2)를 물리 시뮬레이션 안의 몸으로 시험하는 플랫폼이다.
몸과 운동 제어는 시험 대상이 아니라 시험 장치다. 지금은 이 PC(Windows, Docker Desktop, RTX 4060 Ti 8GB)에서만 돌린다.
층마다 하는 일과 까닭은 `docs/architecture.md`가 기준이다.

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
   - 중요한 기능(명령 검증, 운동 제어, 판단·계획, 안전 정지)은 정상, 경계값, 실패, 중복·순서 뒤바뀜 상황을 모두 테스트한다.
   - 테스트 설명은 한국어로 쓴다 (pytest는 docstring과 ids, vitest는 it 이름).
   - 몸의 시험은 물리를 실제로 돌려 확인한다 (걷기·밀기·넘어짐). 값은 실제로 재 보고 정한다.

## 구조

```text
contracts/sim/   몸 ↔ 화면·두뇌 규약 (JSON Schema: 명령, 메시지, 모델 설명). 규약은 여기 한 곳에서 정한다
sim/             몸: MuJoCo 물리(500Hz) + 운동 제어 System 0(학습된 걷기 정책, 50Hz) + 서버(aiohttp, :8765)
                 Python 3.13, Linux 컨테이너에서만 돈다 (아래 규칙)
bench/           시험장 화면: Vue 3 + TypeScript + Naive UI + three.js. 3D 모습, 상태, 직접 조종, 보낸 명령
brain/           (2단계) 두뇌: System 1·2, TypeScript (나중에 휴대폰 React Native로 옮길 수 있게)
docs/            구조(architecture.md), 기술 스택(tech-stack.md), 받아 쓰는 외부 파일(assets.md)
scripts/         로컬 점검(check.ps1)
```

## 자주 쓰는 명령

```powershell
python sim\tools\fetch_assets.py        # 처음 한 번: 시험용 몸 파일 내려받기 (해시로 확인)
docker compose up -d --build sim        # 몸 띄우기 (http://localhost:8765, 코드를 고치면 docker compose restart sim)
cd bench; npm install; npm run dev      # 시험장 화면 (http://localhost:5180)
.\scripts\check.ps1                     # 커밋 전 점검: 몸 lint·시험(컨테이너), 화면 lint·형식·시험·빌드
docker compose run --rm sim pytest      # 몸 시험만
cd bench; npm run contracts             # contracts의 JSON Schema를 고친 뒤 TypeScript 타입 다시 만들기
```

## 규칙

- 기술 스택은 `docs/tech-stack.md`가 기준이다. 라이브러리를 추가하거나 바꾸면 그 문서도 고친다.
  버전은 정확히 고정한다 (requirements.txt, package.json). 새 버전은 나온 지 2주 넘은 것을 쓴다.
- **몸(sim)은 Linux 컨테이너에서만 돌린다.** 이 PC는 Windows 스마트 앱 컨트롤이 켜져 있어 서명 없는 `mujoco.dll`을 막는다.
  보안 설정을 끄지 않는다 (한 번 끄면 Windows를 다시 설치해야 켤 수 있다). 컨테이너는 소스를 붙여 쓰므로
  Python 코드를 고치면 `docker compose restart sim`, 의존성을 바꾸면 `docker compose build sim`.
- 규약을 바꾸면 `contracts/sim/*.schema.json`을 고치고 `npm run contracts`로 화면 타입을 다시 만든다. 몸은 같은 파일로
  명령을 검증한다 (`robot_sim/commands.py`). 값의 범위는 몸마다 달라 스키마가 아니라 몸이 정해 `/scene`의 limits로 알린다.
  범위 밖 명령은 잘라 쓰지 않고 거절한다 (두뇌의 실수가 드러나게).
- 몸의 모양은 화면이 로봇을 모르게 `/scene`(모양·메시·움직이는 몸체 순서)로만 그린다. 로봇을 바꿔도 화면 코드는 그대로다.
- 시험용 몸(Unitree G1 다리 12관절, 걷기 정책)은 `unitree_rl_gym`의 고정한 커밋에서 내려받고 SHA-256으로 확인한다
  (`sim/tools/assets.lock.json`, `docs/assets.md`). 저장소에 넣지 않는다. 커밋을 바꾸면 `--update-lock`과 문서를 함께 고친다.
- 운동 제어(System 0)의 관측 값 구성·순서·배율은 정책을 학습할 때와 같아야 한다 (`robot_sim/locomotion.py`). 바꾸면 바로 넘어진다.
- 시뮬레이션은 시뮬레이션 스레드 하나만 만진다. 명령은 큐로 받아 제어 주기 사이에 적용하고, 답(ack)은 그 명령을 적용한 뒤의
  상태보다 앞서 보내지 않는다 (`server.ClientChannel`: 보낼 것을 만든 순서대로, 밀린 상태만 가장 새 것으로 합친다).
- 걷기 정책은 멈춤 명령에서도 제자리걸음을 하며 1초에 몇 cm씩 흘러간다 (측정값, docs/architecture.md). 두뇌가 위치를
  지키려면 열린 명령이 아니라 지금 위치를 보고 고쳐 가는 되먹임(System 1)으로 한다.
- 화면 키보드 조종은 슬라이더·입력칸처럼 키를 스스로 쓰는 요소에 초점이 있으면 쓰지 않는다 (`drive.keyboardAction`).
- 사용자의 다른 프로젝트(E:\Workspace\iot)와 섞지 않는다. 그 프로젝트는 마무리되었다.
