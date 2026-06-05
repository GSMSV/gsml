# GSML

llama.cpp를 OpenAI 호환 API로 감싸 사용자에게 API Key 형태로 배포하는 교내 서비스.

## 구성

- `apps/api` — FastAPI 백엔드 (OAuth, JWT, API Key, OpenAI 프록시)
- `apps/web` — React + Vite SPA 대시보드
- `docker-compose.yml` — api + web 통합 실행 (llama-server는 외부 운영)
