interface PaginationProps {
  page: number       // 0-indexed
  totalPages: number
  onPageChange: (page: number) => void
}

export default function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
  if (totalPages <= 1) return null

  // 최대 7개 페이지 버튼 표시
  const maxVisible = 7
  let startPage = Math.max(0, page - Math.floor(maxVisible / 2))
  const endPage = Math.min(totalPages, startPage + maxVisible)
  if (endPage - startPage < maxVisible) {
    startPage = Math.max(0, endPage - maxVisible)
  }
  const pages = Array.from({ length: endPage - startPage }, (_, i) => startPage + i)

  return (
    <div className="flex items-center justify-center gap-1 py-3">
      <button
        className="pagination-btn"
        disabled={page === 0}
        onClick={() => onPageChange(page - 1)}
        aria-label="이전 페이지"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>

      {startPage > 0 && (
        <>
          <button className="pagination-btn" onClick={() => onPageChange(0)}>1</button>
          {startPage > 1 && <span className="num text-[10px] text-text-disabled px-1">…</span>}
        </>
      )}

      {pages.map((p) => (
        <button
          key={p}
          className={p === page ? 'pagination-btn-active' : 'pagination-btn'}
          onClick={() => onPageChange(p)}
        >
          {p + 1}
        </button>
      ))}

      {endPage < totalPages && (
        <>
          {endPage < totalPages - 1 && <span className="num text-[10px] text-text-disabled px-1">…</span>}
          <button className="pagination-btn" onClick={() => onPageChange(totalPages - 1)}>
            {totalPages}
          </button>
        </>
      )}

      <button
        className="pagination-btn"
        disabled={page >= totalPages - 1}
        onClick={() => onPageChange(page + 1)}
        aria-label="다음 페이지"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
    </div>
  )
}
