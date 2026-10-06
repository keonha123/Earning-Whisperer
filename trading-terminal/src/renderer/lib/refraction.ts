/**
 * 리퀴드 글래스 굴절.
 *
 * 요소 크기와 모서리 반경에 맞춘 굴절 맵(가장자리일수록 바깥 법선 방향으로 크게 미는 변위)을
 * canvas 로 그리고, SVG feImage → feDisplacementMap 필터로 만들어 backdrop-filter 앞에 건다.
 * Chromium 전용 기법이라 Electron 에서만 동작한다.
 *
 * 기본은 켜져 있다. #154 측정(움직이는 글 위에 유리 판 · 캡슐 · 버튼 10개를 겹친 경우)에서
 * 켠 경우와 끈 경우의 프레임 시간이 같았다. 느린 기기에서 끄는 방법:
 *   localStorage.setItem('logothea.refraction', 'off') 후 다시 불러오기.
 * 투명도 줄이기 설정이 켜져 있어도 끈다. 꺼져 있으면 유리는 tokens.css 의 블러만 쓴다.
 */
import { useEffect, type RefObject } from 'react'

const SVG_NS = 'http://www.w3.org/2000/svg'
const STORAGE_KEY = 'logothea.refraction'

export function isRefractionEnabled(): boolean {
  if (window.matchMedia?.('(prefers-reduced-transparency: reduce)').matches) return false
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off'
  } catch {
    return true
  }
}

let defs: SVGDefsElement | null = null
let nextId = 0

function filterDefs(): SVGDefsElement {
  if (defs && defs.isConnected) return defs
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('aria-hidden', 'true')
  svg.setAttribute('width', '0')
  svg.setAttribute('height', '0')
  svg.style.position = 'absolute'
  defs = document.createElementNS(SVG_NS, 'defs')
  svg.appendChild(defs)
  document.body.appendChild(svg)
  return defs
}

/** 둥근 사각형의 부호 있는 거리. 안쪽이 음수. */
function sdRoundRect(px: number, py: number, hw: number, hh: number, r: number): number {
  const qx = Math.abs(px) - hw + r
  const qy = Math.abs(py) - hh + r
  return Math.min(Math.max(qx, qy), 0) + Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) - r
}

function setAttrs(el: Element, attrs: Record<string, string | number>) {
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v))
}

/**
 * el 에 굴절 필터를 만들어 건다. 같은 요소에 다시 부르면 필터를 새 크기로 바꾼다.
 * bezel 은 가장자리 폭(px) — 판 24, 버튼 14, 작은 칩 10 안팎.
 * 반환값은 필터를 지우고 원래 backdrop-filter 로 되돌리는 함수.
 */
export function applyRefraction(el: HTMLElement, bezel: number): () => void {
  // transform(누를 때 0.97 등)의 영향을 받지 않도록 레이아웃 크기로 잰다
  const W = el.offsetWidth
  const H = el.offsetHeight
  if (W < 4 || H < 4) return () => {}

  const style = getComputedStyle(el)
  const radius = Math.min(parseFloat(style.borderTopLeftRadius) || 0, Math.min(W, H) / 2)
  const edge = Math.min(bezel, Math.min(W, H) / 2 - 1)
  // 큰 면은 맵을 줄여 그리고 늘려 쓴다 — 변위는 부드러운 값이라 해상도가 낮아도 티가 나지 않는다
  const scale = Math.max(1, Math.round(Math.max(W, H) / 240))
  const w = Math.ceil(W / scale)
  const h = Math.ceil(H / scale)

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return () => {}
  const img = ctx.createImageData(w, h)
  const hw = W / 2
  const hh = H / 2
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const px = x * scale - hw
      const py = y * scale - hh
      const d = -sdRoundRect(px, py, hw, hh, radius)
      let dx = 0
      let dy = 0
      if (d < edge) {
        const e = 0.9
        const nx = sdRoundRect(px + e, py, hw, hh, radius) - sdRoundRect(px - e, py, hw, hh, radius)
        const ny = sdRoundRect(px, py + e, hw, hh, radius) - sdRoundRect(px, py - e, hw, hh, radius)
        const nl = Math.hypot(nx, ny) || 1
        const k = Math.pow(1 - Math.max(0, d) / edge, 2.2)
        dx = (nx / nl) * k
        dy = (ny / nl) * k
      }
      const i = (y * w + x) * 4
      img.data[i] = 128 + dx * 127
      img.data[i + 1] = 128 + dy * 127
      img.data[i + 2] = 128
      img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)

  const id = el.dataset.refractId ?? `lg-refract-${nextId++}`
  el.dataset.refractId = id
  document.getElementById(id)?.remove()

  const filter = document.createElementNS(SVG_NS, 'filter')
  setAttrs(filter, {
    id,
    x: 0,
    y: 0,
    width: W,
    height: H,
    filterUnits: 'userSpaceOnUse',
    'color-interpolation-filters': 'sRGB',
  })
  const feImage = document.createElementNS(SVG_NS, 'feImage')
  setAttrs(feImage, {
    href: canvas.toDataURL(),
    x: 0,
    y: 0,
    width: W,
    height: H,
    preserveAspectRatio: 'none',
    result: 'map',
  })
  const feDisp = document.createElementNS(SVG_NS, 'feDisplacementMap')
  setAttrs(feDisp, {
    in: 'SourceGraphic',
    in2: 'map',
    scale: Math.min(70, edge * 2.4),
    xChannelSelector: 'R',
    yChannelSelector: 'G',
  })
  filter.append(feImage, feDisp)
  filterDefs().appendChild(filter)

  // 색상 유리 버튼은 채도 · 밝기를 더 올린다 (tokens.css --tint-filter)
  const tinted = /\bgbtn-(lapis|olive|porphyra)\b/.test(el.className)
  const base = tinted ? 'var(--tint-filter)' : 'var(--glass-filter)'
  el.style.backdropFilter = `url(#${id}) ${base}`

  return () => {
    document.getElementById(id)?.remove()
    el.style.backdropFilter = ''
    delete el.dataset.refractId
  }
}

/**
 * 요소에 굴절을 걸고 크기가 바뀔 때마다 맵을 다시 만든다.
 * 굴절이 꺼져 있으면 아무것도 하지 않는다.
 * 내용 위에 떠 있는 유리(콜 바 · 시트 · 팝오버)에만 건다. 다른 유리 안에 든 유리는 바깥 유리에 가려
 * 뒤를 보지 못하므로 걸어도 보이지 않는다.
 */
export function useRefraction(ref: RefObject<HTMLElement | null>, bezel = 14) {
  useEffect(() => {
    const el = ref.current
    if (!el || bezel <= 0 || !isRefractionEnabled()) return
    let cleanup = applyRefraction(el, bezel)
    let timer: ReturnType<typeof setTimeout> | undefined
    const observer = new ResizeObserver(() => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        cleanup()
        cleanup = applyRefraction(el, bezel)
      }, 120)
    })
    observer.observe(el)
    return () => {
      clearTimeout(timer)
      observer.disconnect()
      cleanup()
    }
  }, [ref, bezel])
}
