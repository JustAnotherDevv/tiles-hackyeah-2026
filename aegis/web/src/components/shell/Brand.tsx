// Logomark: shield outline with an "A" monogram, white on a flat brand-blue tile.
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <span
      className="inline-grid shrink-0 place-items-center rounded-[6px] bg-brand text-white"
      style={{ width: size, height: size }}
      aria-hidden
    >
      <svg width={size * 0.64} height={size * 0.64} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
        <path d="M12 2.8 4.8 5.6v5.6c0 4.5 3 8.3 7.2 9.9 4.2-1.6 7.2-5.4 7.2-9.9V5.6L12 2.8Z" />
        <path d="m8.9 15.2 3.1-7.4 3.1 7.4M10 12.8h4" />
      </svg>
    </span>
  );
}

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 px-2 pb-3.5 pt-1.5">
      <BrandMark />
      {!collapsed ? (
        <div className="min-w-0">
          <div className="text-[15px] font-semibold leading-5 tracking-[-0.01em] text-text-1">Aegis</div>
          <div className="text-[11px] leading-3 text-text-3">Control layer</div>
        </div>
      ) : null}
    </div>
  );
}
