interface Props {
  reason: string
  onDismiss: () => void
}

export default function ForcedManualBanner({ reason, onDismiss }: Props) {
  return (
    <div className="forced-manual-banner">
      <span className="text-sell font-bold">⚠</span>
      <span className="flex-1">{reason} — 수동 모드로 자동 전환됨</span>
      <button
        className="text-sell/70 hover:text-sell text-lg leading-none"
        onClick={onDismiss}
        aria-label="닫기"
      >
        ×
      </button>
    </div>
  )
}
