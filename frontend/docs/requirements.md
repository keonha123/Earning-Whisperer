# 🖥️ Frontend (SaaS 웹 대시보드 및 랜딩) 요구사항 정의서

## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 시스템의 클라우드 기반 고객 접점(SaaS Client-side)이자 핵심 마케팅 채널이다. 
복잡한 AI 실시간 실적 분석과 퀀트 매매 시스템을 일반 투자자가 직관적으로 체험하고 구독(결제)할 수 있도록 모던 웹 환경을 제공한다. **웹 프론트엔드에서는 사용자의 증권사 API 키를 일절 수집하거나 저장하지 않으며, 실제 주문 API를 호출하지도 않는다.**

## 2. 핵심 화면 및 기능 명세 (Core Pages)

### [Page 1] 동적 랜딩 페이지 (Dynamic Landing Page)
- Hero Section, Pain Point 해결 스토리텔링, Core Features 기술 스택 시각화
- Framer Motion 스크롤 애니메이션

### [Page 2] 🔴 라이브 모의 체험장 (Showcase Demo Room)
- 백엔드 `DemoReplayService`가 서버 기동 시부터 과거 주요 어닝콜 데이터를 무한 반복 재생 (라디오 방송국 모델)
- `/topic/live/demo` 채널 구독 → Raw Score 텐션 미터기, EMA 그래프 시각화
- 미인증 사용자 회원가입 유도 (CTA 블러 레이어)

### [Page 3] 인증 및 요금제 결제 (Auth & Pricing)
- JWT 기반 회원가입/로그인
- Free Plan / Pro Plan (월 구독 ₩9,900) 구분
- 토스페이먼츠(Toss Payments) 결제 연동 (준비 중)

### [Page 4] 마이페이지 및 원격 대시보드 (My Dashboard)
- 거래내역, 구독관리, 설정 탭 구성
- 로컬 에이전트가 동기화한 거래 히스토리 조회

### [Page 5] 관심종목 & 어닝 캘린더
- 관심종목 추가/삭제/검색
- S&P 500 종목 어닝콜 일정 조회

## 3. 핵심 UI/UX 정책 (Conversion Funnel)
유저를 **[랜딩 페이지 ➔ 모의 체험 ➔ 로그인/결제 ➔ 로컬 에이전트 다운로드]**의 퍼널(Funnel)로 자연스럽게 이끄는 것이 목표.

## 4. 기술 스택 (Frontend)
- **Framework:** `Next.js` (React 18+, App Router)
- **Styling & UI:** `Tailwind CSS`, `Framer Motion`, `shadcn/ui`
- **State Management:** `Zustand`
- **Real-time 통신:** `SockJS` + `@stomp/stompjs`
- **Payment Gateway:** `Toss Payments` (테스트 환경)
- **Deployment:** `Vercel`

## 5. 완료 기준 (Definition of Done - DoD)
1. [ ] **퍼널 무결성 테스트:** 비회원 접속 시 동적 랜딩 페이지가 쾌적하게 렌더링되며, 로그인 ➔ 모의 체험 ➔ 테스트 결제 완료까지의 UX 플로우가 에러 없이 연결되는가?
2. [ ] **웹소켓 렌더링 부하 테스트:** 데모 룸에서 과거 어닝콜 데이터 스트리밍 수신 시, 차트와 텍스트 타이핑 애니메이션이 브라우저 메인 스레드를 블로킹하지 않고 부드럽게 그려지는가?
3. [ ] **보안 및 책임 분리 확인:** 소스 코드 및 UI의 어떤 부분에서도 증권사 API 키를 입력받거나 전송하는 로직이 완전히 배제되었는가?
