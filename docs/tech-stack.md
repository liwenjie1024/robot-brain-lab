# 기술 스택

라이브러리를 추가하거나 바꾸면 이 문서도 고친다. 버전은 정확히 고정한다.

| 층 | 쓰는 것 | 버전 | 왜 | 대안과 고르지 않은 까닭 |
|---|---|---|---|---|
| 몸: 물리 | MuJoCo | 3.17.0 | 관절·접촉이 정확하고 빠르며 광선(mj_ray)으로 사격을 맞힐 수 있다. 모델을 코드(MjSpec)로 만들어 외부 파일이 없다 | Rapier(게임용, 관절 모터 정확도 낮음), Isaac Sim(무겁고 8GB GPU에 빠듯함) |
| 몸: 서버 | aiohttp | 3.14.5 | HTTP(모델 설명)와 WebSocket(상태·사건·명령)을 한 서버에서 | FastAPI(더 무겁고 WebSocket만 쓰기엔 과함) |
| 몸: 검증·계산 | jsonschema, NumPy | 4.26.0, 2.5.4 | 규약 JSON Schema로 명령 검증, 벡터 계산 | - |
| 몸: 실행 환경 | Python 3.13 (Docker Linux 컨테이너) | python:3.13-slim | Windows 스마트 앱 컨트롤이 서명 없는 mujoco.dll을 막는다 | Windows에서 바로(보안 설정을 꺼야 함) |
| 몸: 점검 | pytest, pytest-asyncio, Ruff | 9.2.0, 1.4.1.post1, 0.17.3 | 물리를 실제로 돌리는 시험, 린트·형식 | - |
| 화면 | Vue 3 + TypeScript + Naive UI | 3.5.44, 5.9.3, 2.45.3 | 사용자가 Vue를 고름, 다른 프로젝트와 같은 도구 | React |
| 화면: 3D | three.js | 0.186.1 | 기본 도형·그림자·카메라 조작·사격 광선, 3D를 쓰는 화면에서만 불러옴 | Babylon.js |
| 화면: 규약 | Ajv (2020-12), json-schema-to-typescript | 8.20.0, 16.0.0 | 받은 메시지를 규약 스키마로 검증, 스키마에서 타입 생성 (규약 한 곳) | 손으로 쓴 타입(규약과 어긋나기 쉬움) |
| 화면: 빌드·점검 | Vite, Vitest(jsdom), vue-tsc, ESLint | 8.3.4, 5.0.5, 3.3.13, 10.13.0 | - | - |
| 두뇌 | TypeScript + Node 24 | 5.9.3, 24.15 | 나중에 두뇌만 휴대폰(React Native)으로 옮길 수 있게. Node 24에 WebSocket·fetch가 들어 있어 몸 연결 코드를 화면과 함께 쓴다 | Python(화면과 코드를 나눠 쓸 수 없음) |
| 두뇌: 서버 | ws | 8.22.0 | Node에는 WebSocket 서버가 없다. 8.22.1은 나온 지 2주가 안 되어 쓰지 않음 | socket.io(자체 규약이라 무거움) |
| 두뇌: 실행 | tsx | 4.23.15 | TypeScript를 바로 실행하고 tsconfig의 경로(@shared)를 읽는다 | Node 자체 타입 지우기(경로·JSON 가져오기를 못 함) |
| 저장소 | npm 작업 공간 (shared, bench, brain) | - | 화면·두뇌가 몸 연결·규약 타입을 함께 쓰고 라이브러리를 한 번에 설치 | 패키지를 따로 배포(지금은 과함) |
| 느린 뇌 | Ollama + qwen2.5:7b | 이 PC에 설치된 0.34.4 | 8GB GPU에 들어가고 JSON 형식 강제(format)를 지원 | 클라우드 API(지연·비용, 로컬 두뇌가 목표) |

1단계에서 쓰던 PyTorch(걷기 정책 실행)·PyYAML(정책 설정)·Unitree G1 모델은 몸을 BL-01로 바꾸며 뺐다 (git 기록 e60ee7e).
