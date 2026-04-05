# EarningWhisperer 랜딩 페이지 UI 컴포넌트 스펙

> 기준: Tailwind CSS v4, Geist Sans/Mono, 다크 테마 전용, WCAG AA

---

## 디자인 토큰 기준

기존 데모룸에서 사용 중인 토큰을 랜딩 페이지에도 일관 적용한다.

### 색상

| 역할 | 토큰 | 값 |
|------|------|-----|
| 최외곽 배경 | `bg-gray-950` | `#030712` |
| 카드/섹션 배경 | `bg-gray-900` | `#111827` |
| 보조 배경 | `bg-gray-800` | `#1F2937` |
| 테두리 | `border-gray-800` | `#1F2937` |
| 보조 테두리 | `border-gray-700` | `#374151` |
| 1차 텍스트 | `text-white` | `#FFFFFF` |
| 2차 텍스트 | `text-gray-300` | `#D1D5DB` |
| 보조 텍스트 | `text-gray-400` | `#9CA3AF` |
| 비활성 텍스트 | `text-gray-600` | `#4B5563` |
| 강조 (Primary) | `purple-500` | `#8B5CF6` |
| 강조 Hover | `purple-400` | `#A78BFA` |
| 강조 Active | `purple-600` | `#7C3AED` |
| 강조 배경 | `purple-500/10` | `8B5CF6 @ 10%` |
| 강조 테두리 | `purple-500/30` | `8B5CF6 @ 30%` |
| 매수 신호 | `green-400` | `#4ADE80` |
| 매도 신호 | `red-400` | `#F87171` |
| 경고 | `yellow-400` | `#FACC15` |

### 타이포그래피

| 레벨 | 클래스 | 용도 |
|------|--------|------|
| Display | `text-5xl lg:text-7xl font-bold tracking-tight` | Hero 헤드라인 |
| Heading 1 | `text-3xl lg:text-4xl font-bold` | 섹션 타이틀 |
| Heading 2 | `text-xl font-semibold` | 카드 타이틀 |
| Body Large | `text-lg leading-8` | 서브카피 |
| Body | `text-sm leading-6` | 본문 |
| Caption | `text-xs text-gray-400` | 보조 설명 |
| Mono | `font-mono text-sm` | 숫자, 코드, 점수값 |

폰트 패밀리: `var(--font-geist-sans)` (UI), `var(--font-geist-mono)` (수치)

### 간격 스케일

`4px / 8px / 12px / 16px / 24px / 32px / 48px / 64px / 96px / 128px`

Tailwind 단위: `p-1 / p-2 / p-3 / p-4 / p-6 / p-8 / p-12 / p-16 / p-24 / p-32`

### 섀도 / 글로우

```
shadow-lg shadow-purple-500/20   /* 강조 카드 글로우 */
shadow-xl shadow-black/50        /* 일반 카드 */
```

### 모서리

```
rounded-xl   /* 카드 (16px) */
rounded-2xl  /* 큰 카드 (24px) */
rounded-lg   /* 버튼 (8px) */
rounded-full /* 필 버튼, 배지 */
```

### 전환

```css
transition-colors duration-200   /* 버튼, 링크 색상 전환 */
transition-all duration-300      /* 레이아웃 변화 */
transition-all duration-700      /* 게이지 바 (데모룸 일치) */
```

### 브레이크포인트

| 이름 | 값 | 적용 |
|------|-----|------|
| `sm` | 640px | 1열 → 2열 전환 시작 |
| `md` | 768px | 패딩 확장 |
| `lg` | 1024px | 주요 2컬럼 레이아웃 |
| `xl` | 1280px | 최대 콘텐츠 너비 `max-w-6xl` |

---

## CTA 버튼 계층

```
Primary   — bg-purple-600 hover:bg-purple-500 active:bg-purple-700
            text-white font-semibold
            px-8 py-3 rounded-lg text-base
            shadow-lg shadow-purple-500/30
            focus-visible:ring-2 focus-visible:ring-purple-400

Secondary — border border-gray-600 hover:border-gray-400
            text-gray-300 hover:text-white font-semibold
            px-8 py-3 rounded-lg text-base
            transition-colors duration-200

Ghost     — text-gray-400 hover:text-white underline-offset-4
            hover:underline text-sm
```

**비활성 상태 (공통)**: `disabled:opacity-40 disabled:cursor-not-allowed`

**접근성**: 모든 버튼 `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950`

---

## 섹션 1: Hero

### 레이아웃

```
<section> — min-h-screen flex flex-col items-center justify-center
            relative overflow-hidden
            px-4 pt-24 pb-32 (모바일)
            px-8 pt-32 pb-48 (lg+)
```

콘텐츠 최대 너비: `max-w-4xl mx-auto text-center`

### 컴포넌트 목록

| 컴포넌트 | 역할 |
|---------|------|
| `HeroBackground` | 배경 장식 레이어 (완전 독립 div, `aria-hidden`) |
| `HeroBadge` | 상단 소형 레이블 ("AI-Powered · Real-time") |
| `HeroHeadline` | 메인 헤드라인 h1 |
| `HeroSubcopy` | 서브 설명 p |
| `HeroCtaGroup` | CTA 버튼 2개 묶음 |
| `HeroScrollHint` | 하단 스크롤 유도 아이콘 |

### HeroBackground — 배경 장식 상세

```
div.absolute.inset-0.overflow-hidden.pointer-events-none[aria-hidden]
  └─ (1) 방사형 그라디언트 중심 글로우
         div.absolute.top-1/2.left-1/2.-translate-x-1/2.-translate-y-1/2
         w-[800px] h-[800px] rounded-full
         bg-[radial-gradient(circle,rgba(139,92,246,0.15)_0%,transparent_70%)]

  └─ (2) 상단 좌측 보조 글로우
         div.absolute.-top-32.-left-32
         w-[400px] h-[400px] rounded-full
         bg-[radial-gradient(circle,rgba(139,92,246,0.08)_0%,transparent_60%)]

  └─ (3) 하단 우측 보조 글로우
         div.absolute.-bottom-32.-right-32
         w-[500px] h-[500px] rounded-full
         bg-[radial-gradient(circle,rgba(167,139,250,0.06)_0%,transparent_60%)]

  └─ (4) 격자 패턴 오버레이
         div.absolute.inset-0
         background-image: linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
                           linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)
         background-size: 64px 64px
         (그라디언트로 하단 페이드: mask-image: linear-gradient(to bottom, black 40%, transparent))

  └─ (5) 우상단 장식 파티클 그룹 — 3개 소형 dot
         각각 w-1 h-1 rounded-full bg-purple-400/40
         absolute top-{n} right-{n} (임의 위치)
```

**구현 노트**: `(4)` 격자는 CSS `background-image` 인라인 스타일로 적용. Tailwind arbitrary value로 표현하면 `[background-image:linear-gradient(...)]`.

### HeroBadge

```
div.inline-flex.items-center.gap-2
  .px-3.py-1.rounded-full
  .border.border-purple-500/30.bg-purple-500/10
  .text-xs.font-medium.text-purple-300.tracking-wide

내용:
  span.w-1.5.h-1.5.rounded-full.bg-purple-400.animate-pulse
  "AI-Powered Real-time Analysis"
```

### HeroHeadline

```html
<h1 class="text-5xl lg:text-7xl font-bold tracking-tight leading-[1.1] text-white mt-6">
  어닝콜이 끝나기 전에
  <br/>
  <span class="text-transparent bg-clip-text
               bg-gradient-to-r from-purple-400 to-purple-600">
    AI가 먼저 판단합니다
  </span>
</h1>
```

그라디언트: `from-purple-400 (#A78BFA) to-purple-600 (#7C3AED)`

### HeroSubcopy

```html
<p class="mt-6 text-lg lg:text-xl text-gray-400 leading-8 max-w-2xl mx-auto">
  실시간 음성을 FinBERT가 분석하고, EMA 스코어가 0.6을 넘는 순간
  자동 매매 신호를 Trading Terminal로 전송합니다.
  어닝콜 정보 격차, 이제 AI가 줄여드립니다.
</p>
```

### HeroCtaGroup

```
div.flex.flex-col.sm:flex-row.gap-4.justify-center.mt-10

[Primary] 데모 체험하기
  <a href="/demo">
    class="px-8 py-3.5 bg-purple-600 hover:bg-purple-500 active:bg-purple-700
           text-white font-semibold rounded-lg text-base
           shadow-lg shadow-purple-500/30
           transition-colors duration-200
           focus-visible:outline-none focus-visible:ring-2
           focus-visible:ring-purple-400 focus-visible:ring-offset-2
           focus-visible:ring-offset-gray-950"

[Secondary] 무료로 시작하기
  <a href="/auth?mode=signup">
    class="px-8 py-3.5 border border-gray-700 hover:border-gray-500
           text-gray-300 hover:text-white font-semibold rounded-lg text-base
           transition-colors duration-200
           focus-visible:outline-none focus-visible:ring-2
           focus-visible:ring-purple-400 focus-visible:ring-offset-2
           focus-visible:ring-offset-gray-950"
```

버튼 내 아이콘: 좌측 `w-4 h-4` SVG, `flex items-center gap-2`

### HeroScrollHint

```
div.absolute.bottom-8.left-1/2.-translate-x-1/2
  .flex.flex-col.items-center.gap-2
  .text-gray-600.animate-bounce

  ChevronDownIcon (w-5 h-5)
  span.text-xs "스크롤"
```

### Framer Motion 진입 애니메이션

```
HeroBadge:     initial={opacity:0, y:-16} animate={opacity:1, y:0} delay=0
HeroHeadline:  initial={opacity:0, y:24}  animate={opacity:1, y:0} delay=0.1
HeroSubcopy:   initial={opacity:0, y:24}  animate={opacity:1, y:0} delay=0.2
HeroCtaGroup:  initial={opacity:0, y:24}  animate={opacity:1, y:0} delay=0.35

공통: duration=0.6, ease="easeOut"
```

---

## 섹션 2: Pain Point

### 레이아웃

```
<section> — py-24 lg:py-32 px-4
콘텐츠: max-w-6xl mx-auto
섹션 헤더: text-center mb-16
카드 그리드: grid grid-cols-1 md:grid-cols-3 gap-6
```

### 컴포넌트 목록

| 컴포넌트 | 역할 |
|---------|------|
| `SectionLabel` | 섹션 분류 레이블 (공통 컴포넌트) |
| `SectionTitle` | 섹션 제목 |
| `PainPointCard` | 문제 스토리텔링 카드 (3개) |

### SectionLabel (공통)

```
span.text-xs.font-semibold.uppercase.tracking-widest.text-purple-400
```

### SectionTitle (공통)

```
h2.text-3xl.lg:text-4xl.font-bold.text-white.mt-3
p.text-gray-400.text-lg.mt-4.max-w-2xl.mx-auto (서브타이틀)
```

### PainPointCard 스펙

카드 3개, 각각 다른 아이콘과 내용. 스크롤 진입 시 아래에서 순차 페이드인.

```
<article>
  class="bg-gray-900 rounded-xl p-6 border border-gray-800
         hover:border-purple-500/40 hover:bg-gray-900/80
         transition-all duration-300 group"

내부 구조:
  ┌─ 아이콘 컨테이너
  │    div.w-10.h-10.rounded-lg
  │    .bg-purple-500/10.border.border-purple-500/20
  │    .flex.items-center.justify-center.mb-4
  │    SVG icon (w-5 h-5 text-purple-400)
  │
  ├─ 숫자 배지 (선택)
  │    span.font-mono.text-2xl.font-bold.text-white
  │    span.text-gray-600.text-sm.ml-1 (단위)
  │
  ├─ 카드 타이틀
  │    h3.text-lg.font-semibold.text-white.mt-2
  │
  └─ 설명
       p.text-sm.text-gray-400.leading-6.mt-2
```

**카드 3개 내용**:

```
카드 1 — 정보 격차
아이콘: ClockIcon (clock)
숫자: "23분" (평균 어닝콜 분석 지연)
타이틀: "개인 투자자는 항상 늦게 알게 됩니다"
설명: 헤지펀드는 실시간 NLP 분석팀을 운영합니다.
      개인 투자자가 어닝콜 내용을 파악할 때,
      기관은 이미 포지션을 정리한 뒤입니다.

카드 2 — 감정적 판단
아이콘: BrainIcon (brain/cpu)
숫자: "68%" (감정적 판단으로 인한 손실 비율 — 가상)
타이틀: "실시간 음성을 들으며 냉정하게 판단하기 어렵습니다"
설명: 어닝 서프라이즈인지 미스인지, 가이던스 톤은 어떤지.
      수십 분의 음성을 듣는 동안 시장은 이미 움직입니다.

카드 3 — 실행 지연
아이콘: ZapIcon (lightning)
숫자: "4.2초" (평균 인간 반응 + 주문 실행 지연)
타이틀: "판단이 맞아도 실행이 늦으면 소용없습니다"
설명: AI 신호 수신부터 주문 실행까지 1초 이내.
      EarningWhisperer는 판단을 자동화하고,
      실행은 당신의 로컬 PC에서 직접 처리합니다.
```

**Framer Motion**: `whileInView` 사용, `viewport={{ once: true, margin: "-100px" }}`

```
카드 1: delay=0
카드 2: delay=0.1
카드 3: delay=0.2
initial={opacity:0, y:32} whileInView={opacity:1, y:0} duration=0.5
```

---

## 섹션 3: How It Works

### 레이아웃

```
<section> — py-24 lg:py-32 px-4 bg-gray-900/40
콘텐츠: max-w-5xl mx-auto
섹션 헤더: text-center mb-16
다이어그램: 중앙 정렬 flex-col 또는 horizontal (lg+)
```

### 컴포넌트 목록

| 컴포넌트 | 역할 |
|---------|------|
| `FlowDiagram` | 전체 파이프라인 시각화 컨테이너 |
| `FlowNode` | 파이프라인 각 단계 카드 |
| `FlowArrow` | 단계 간 연결 화살표 |
| `FlowDataTag` | 노드 간 전송 데이터 레이블 |

### FlowDiagram 전체 구조

모바일: 수직 스택 (`flex-col items-center`)
lg+: 수평 배열 (`flex-row items-center justify-between`)

```
[Data Pipeline] → [AI Engine] → [Backend] → [Trading Terminal]
```

각 노드 너비: `w-full max-w-[180px]` (lg: `flex-1`)
화살표: 모바일 `rotate-90`, lg `rotate-0`

### FlowNode 스펙

```
<div>
  class="relative flex flex-col items-center text-center
         bg-gray-900 border border-gray-800 rounded-xl p-5
         hover:border-purple-500/50 transition-all duration-300"

내부 구조:
  ┌─ 아이콘 영역
  │    div.w-12.h-12.rounded-xl.mb-3
  │    .flex.items-center.justify-center
  │    [노드별 고유 색상 배경 + 아이콘]
  │
  ├─ 노드 번호
  │    span.text-xs.font-mono.text-gray-600.absolute.top-3.right-3
  │    "01" / "02" / "03" / "04"
  │
  ├─ 노드 이름
  │    p.text-sm.font-semibold.text-white
  │
  ├─ 기술 스택 레이블
  │    span.text-xs.text-gray-500.font-mono.mt-0.5
  │    (Python, FastAPI 등)
  │
  └─ 상태 인디케이터 (노드 3, Backend만)
       div.flex.items-center.gap-1.mt-2
       span.w-1.5.h-1.5.rounded-full.bg-green-400.animate-pulse
       span.text-xs.text-green-400 "Live"
```

**4개 노드 상세**:

```
노드 1 — Data Pipeline
아이콘 배경: bg-blue-500/10 border-blue-500/20
아이콘: MicrophoneIcon (text-blue-400, w-6 h-6)
이름: "Data Pipeline"
기술: "yt-dlp · Whisper"
설명 (툴팁용): "어닝콜 오디오 실시간 수집 및 STT 변환"

노드 2 — AI Engine
아이콘 배경: bg-purple-500/10 border-purple-500/20
아이콘: CpuChipIcon (text-purple-400, w-6 h-6)
이름: "AI Engine"
기술: "FinBERT · FastAPI"
설명: "음성 텍스트 감성 분석, Raw Score 생성"

노드 3 — Backend
아이콘 배경: bg-green-500/10 border-green-500/20
아이콘: ServerIcon (text-green-400, w-6 h-6)
이름: "Backend"
기술: "Spring Boot · Redis"
설명: "EMA 계산, WebSocket 브로드캐스트"
상태: "Live" 인디케이터 표시

노드 4 — Trading Terminal
아이콘 배경: bg-orange-500/10 border-orange-500/20
아이콘: ComputerDesktopIcon (text-orange-400, w-6 h-6)
이름: "Trading Terminal"
기술: "Electron · KIS API"
설명: "로컬 PC에서 직접 주문 실행"
```

### FlowArrow 스펙

```
div.flex.items-center.justify-center
   .text-gray-600 (기본) → hover 시 text-purple-400/60

모바일 (수직):
  div.w-px.h-8.bg-gradient-to-b.from-transparent.via-gray-700.to-transparent

lg (수평):
  div.flex-1.h-px.bg-gradient-to-r.from-transparent.via-gray-700.to-transparent
  + ChevronRightIcon (w-4 h-4 text-gray-600, absolute center)
```

### FlowDataTag 스펙

화살표 위에 오버레이되는 데이터 레이블 (각 화살표마다 1개):

```
div.absolute (화살표 중앙 기준)
  span.text-xs.font-mono
       .bg-gray-950.border.border-gray-800
       .text-gray-500.px-2.py-0.5.rounded
       .whitespace-nowrap

내용:
  화살표 1 (Pipeline→AI):   "text_chunk"
  화살표 2 (AI→Backend):    "raw_score: 0.72"
  화살표 3 (Backend→Terminal): "action: BUY"
```

### 하단 보조 설명 바

다이어그램 하단에 2개 포인트 강조:

```
div.grid.grid-cols-1.md:grid-cols-2.gap-4.mt-12

[포인트 1] — 보안
border-l-2 border-green-500/50
pl-4
h3.text-sm.font-semibold.text-white "로컬 PC 직접 실행"
p.text-xs.text-gray-400.mt-1
"KIS API 키는 서버에 저장되지 않습니다.
Trading Terminal이 사용자의 PC에서 직접 주문을 실행합니다."

[포인트 2] — 속도
border-l-2 border-purple-500/50
pl-4
h3.text-sm.font-semibold.text-white "실시간 60fps 업데이트"
p.text-xs.text-gray-400.mt-1
"Redis Pub/Sub → WebSocket STOMP → 브라우저까지
평균 지연 200ms 이내."
```

### Framer Motion

```
섹션 타이틀: whileInView opacity:0→1, y:24→0, delay=0

노드 1: whileInView opacity:0→1, x:-32→0, delay=0
노드 2: whileInView opacity:0→1, x:-32→0, delay=0.15
노드 3: whileInView opacity:0→1, x:-32→0, delay=0.3
노드 4: whileInView opacity:0→1, x:-32→0, delay=0.45

화살표: whileInView scaleX:0→1, delay=0.2~0.5 (순차)
        transformOrigin: "left"
```

---

## 섹션 4: Final CTA

### 레이아웃

```
<section> — py-24 lg:py-32 px-4
콘텐츠: max-w-3xl mx-auto text-center
```

### 컴포넌트 목록

| 컴포넌트 | 역할 |
|---------|------|
| `FinalCtaCard` | 전체 감싸는 글로우 카드 |
| `PlanCompareRow` | Free/Pro 플랜 2열 비교 |
| `FinalCtaButtons` | 최종 CTA 버튼 그룹 |

### FinalCtaCard

```
div.relative.overflow-hidden.rounded-2xl
   .border.border-purple-500/20
   .bg-gradient-to-b.from-purple-500/10.to-gray-900/80
   .p-10.lg:p-16

배경 장식 (aria-hidden):
  div.absolute.-top-24.-right-24
  w-64.h-64.rounded-full
  bg-[radial-gradient(circle,rgba(139,92,246,0.2)_0%,transparent_70%)]
```

### 카피라이팅

```
SectionLabel: "지금 바로 시작하세요"

h2.text-4xl.lg:text-5xl.font-bold.text-white.mt-3:
  "어닝콜 정보 격차를
   지금 좁히세요"

p.text-lg.text-gray-400.mt-4:
  "무료 플랜으로 실시간 AI 신호를 바로 확인할 수 있습니다.
   Pro 플랜은 Trading Terminal 자동매매까지 지원합니다."
```

### PlanCompareRow

```
div.grid.grid-cols-2.gap-4.mt-10.text-left

[Free 플랜 카드]
div.bg-gray-900.border.border-gray-800.rounded-xl.p-5
  p.text-sm.font-semibold.text-white "Free"
  p.text-3xl.font-bold.text-white.mt-1 "₩0"
    span.text-sm.text-gray-500.font-normal "/월"
  ul.mt-4.space-y-2 (체크리스트)
    li: CheckIcon (w-4 h-4 text-green-400) + "실시간 AI 신호 열람"
    li: CheckIcon + "데모룸 체험"
    li: XMarkIcon (w-4 h-4 text-gray-600) + "자동매매 Terminal" (strike-through)

[Pro 플랜 카드]
div.bg-purple-500/10.border.border-purple-500/30.rounded-xl.p-5
   .relative (권장 배지 포함)
  span.absolute.top-3.right-3
       .text-xs.font-semibold.bg-purple-600.text-white
       .px-2.py-0.5.rounded-full "권장"
  p.text-sm.font-semibold.text-purple-300 "Pro"
  p.text-3xl.font-bold.text-white.mt-1 "₩29,900"
    span.text-sm.text-gray-400.font-normal "/월"
  ul.mt-4.space-y-2
    li: CheckIcon (text-green-400) + "Free 플랜 전체 포함"
    li: CheckIcon + "Trading Terminal 다운로드"
    li: CheckIcon + "AUTO_PILOT 자동매매 모드"
```

### FinalCtaButtons

```
div.flex.flex-col.sm:flex-row.gap-4.justify-center.mt-10

[Primary] 데모 체험하기 (Primary 스펙 동일)
  href="/demo"

[Secondary] 무료 가입 →
  href="/auth?mode=signup"
  클래스에 inline-flex items-center gap-1 추가
  ArrowRightIcon (w-4 h-4)

아래 Ghost 링크:
  이미 계정이 있나요?
  <a href="/auth" class="text-purple-400 hover:text-purple-300 font-medium">
    로그인
  </a>
```

### 하단 신뢰 문구

```
p.text-xs.text-gray-600.mt-8:
  "보안을 위해 실제 증권사 API 키는 웹에 저장되지 않으며,
   PC에 설치된 로컬 에이전트 앱 내부에만 암호화되어 보관됩니다."
```

---

## 전역 구성 요소

### Navbar

```
<header>
  class="fixed top-0 inset-x-0 z-50
         border-b border-gray-800/60
         bg-gray-950/80 backdrop-blur-md"

내부: max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between

좌: 로고 텍스트 "EarningWhisperer" (font-bold text-white)
    + span.text-purple-400 "." (강조 dot)

우: nav.hidden.md:flex items-center gap-8
      a (Ghost 스타일): "서비스 소개" / "데모 체험"
    + CTA 버튼 2개 (sm 사이즈)
      [로그인] Secondary sm
      [무료 시작] Primary sm
    + 모바일 햄버거 (md:hidden)
```

### Footer (간략)

```
<footer>
  class="border-t border-gray-800 py-8 px-4
         text-center text-xs text-gray-600"

"© 2026 EarningWhisperer · 투자는 본인의 책임입니다"
```

---

## 접근성 체크리스트

- [ ] 모든 색상 조합 4.5:1 이상 (white on gray-950: 19.1:1 / white on gray-900: 13.7:1 / purple-300 on gray-950: 5.2:1)
- [ ] 모든 인터랙티브 요소 `focus-visible` 링 스타일 적용
- [ ] 배경 장식 요소 전체 `aria-hidden="true"`
- [ ] CTA 버튼 `aria-label` 구체적 명시 ("데모룸에서 AI 분석 체험하기")
- [ ] 섹션 별 landmark 사용: `<header>`, `<main>`, `<section>`, `<footer>`
- [ ] `prefers-reduced-motion`: Framer Motion `useReducedMotion()` 훅으로 애니메이션 비활성화

---

## 파일 구조 제안

```
frontend/src/
├── app/
│   └── page.tsx                      ← 랜딩 페이지 (SSG)
└── components/
    └── landing/
        ├── LandingLayout.tsx         ← Navbar + Footer 래핑
        ├── HeroSection.tsx
        ├── HeroBackground.tsx
        ├── PainPointSection.tsx
        ├── PainPointCard.tsx
        ├── HowItWorksSection.tsx
        ├── FlowDiagram.tsx
        ├── FlowNode.tsx
        ├── FinalCtaSection.tsx
        └── PlanCompareRow.tsx
```

공통 컴포넌트는 `components/ui/` 하위에 위치:
```
components/ui/
├── SectionLabel.tsx
├── SectionTitle.tsx
└── CtaButton.tsx
```
