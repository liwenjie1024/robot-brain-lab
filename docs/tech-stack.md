# 기술 스택

라이브러리를 추가하거나 바꾸면 이 문서도 고친다. 버전은 정확히 고정한다.

| 층 | 쓰는 것 | 버전 | 왜 | 대안과 고르지 않은 까닭 |
|---|---|---|---|---|
| 몸: 물리 | MuJoCo | 3.17.0 | 관절·접촉이 정확하고 빠르며, 로봇 학습 정책 대부분이 MuJoCo에서 시험된다 | Rapier(게임용, 관절 모터 정확도 낮음), Isaac Sim(무겁고 8GB GPU에 빠듯함) |
| 몸: 걷기 정책 실행 | PyTorch (CPU) | 2.15.0 | 받은 정책이 TorchScript라 그대로 읽는다. 신경망이 작아 CPU 1스레드로 충분 | ONNX Runtime(정책을 바꿔 내보내야 함, 휴대폰으로 옮길 때 다시 본다) |
| 몸: 서버 | aiohttp | 3.14.5 | HTTP(모델 설명·메시)와 WebSocket(상태·명령)을 한 서버에서 | FastAPI(더 무겁고 WebSocket만 쓰기엔 과함) |
| 몸: 검증·설정 | jsonschema, PyYAML, NumPy | 4.26.0, 6.0.3, 2.5.4 | 규약 JSON Schema로 명령 검증, 정책 설정 읽기 | - |
| 몸: 실행 환경 | Python 3.13 (Docker Linux 컨테이너) | python:3.13-slim | Windows 스마트 앱 컨트롤이 서명 없는 mujoco.dll을 막는다 | Windows에서 바로(보안 설정을 꺼야 함) |
| 몸: 점검 | pytest, pytest-asyncio, Ruff | 9.2.0, 1.4.1.post1, 0.17.3 | 물리를 실제로 돌리는 시험, 린트·형식 | - |
| 화면 | Vue 3 + TypeScript + Naive UI | 3.5.44, 5.9.3, 2.45.3 | 사용자가 Vue를 고름, 다른 프로젝트와 같은 도구 | React |
| 화면: 3D | three.js | 0.186.1 | 메시·그림자·카메라 조작, 3D를 쓰는 화면에서만 불러옴 | Babylon.js |
| 화면: 규약 | Ajv (2020-12), json-schema-to-typescript | 8.20.0, 16.0.0 | 받은 메시지를 규약 스키마로 검증, 스키마에서 타입 생성 (규약 한 곳) | 손으로 쓴 타입(규약과 어긋나기 쉬움) |
| 화면: 빌드·점검 | Vite, Vitest(jsdom), vue-tsc, ESLint | 8.3.4, 5.0.5, 3.3.13, 10.13.0 | - | - |
| 시험용 몸 | Unitree G1 다리 12관절 모델 + 걷기 정책 | unitree_rl_gym 276801e (BSD-3-Clause) | 공개된 사람형 로봇 중 MuJoCo 모델과 학습된 걷기 정책이 함께 있다 | MuJoCo Playground(내려받을 학습 결과가 없음), 직접 학습(Linux GPU와 시간 필요) |
| (3단계) 느린 뇌 | Ollama + qwen2.5:7b | 이 PC에 설치된 0.34.4 | 8GB GPU에 들어가고 JSON 형식 강제(format)를 지원 | 클라우드 API(지연·비용, 로컬 두뇌가 목표) |
