// Seeded RNG (mulberry32, ported from the prototype data.js) for deterministic mock curves.
// Owner: dashboard-shell (B16).
export function mulberry32(seed: number): () => number {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Shared live RNG for the mock pump (non-deterministic sequence is fine there). */
export const liveRand = mulberry32(Date.now() & 0xffffffff);

export function pick<T>(items: readonly T[], r: () => number = liveRand): T {
  return items[Math.floor(r() * items.length) % items.length];
}

/** Weighted pick over items with a numeric `w` field. */
export function pickWeighted<T extends { w: number }>(items: readonly T[], r: () => number = liveRand): T {
  const total = items.reduce((a, b) => a + b.w, 0);
  let x = r() * total;
  for (const it of items) {
    x -= it.w;
    if (x <= 0) return it;
  }
  return items[items.length - 1];
}

/** Diurnal activity curve (peak ~13:00), 0.22..1.0 — prototype view-overview.js. */
export function diurnal(hour: number): number {
  return 0.22 + 0.78 * Math.exp(-((hour - 13) ** 2) / (2 * 3.6 * 3.6));
}

let idCounter = 0;
export function mockId(prefix: string): string {
  idCounter += 1;
  const rand = Math.floor(liveRand() * 0xffffff).toString(16).padStart(6, '0');
  return `${prefix}_${Date.now().toString(36)}${rand}${idCounter.toString(36)}`;
}
