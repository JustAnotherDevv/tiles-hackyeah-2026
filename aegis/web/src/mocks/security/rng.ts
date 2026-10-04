// Seeded PRNG + small helpers for security mocks. No randomness at import time.
// Owner: dashboard-security.

export type Rng = () => number;

export function mulberry32(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic pseudo-hash hex (NOT cryptographic; mock audit chain only). */
export function fakeHex(input: string, len = 64): string {
  let out = '';
  let seed = hashString(input);
  while (out.length < len) {
    seed = hashString(`${seed}:${input}:${out.length}`);
    out += seed.toString(16).padStart(8, '0');
  }
  return out.slice(0, len);
}

export function pick<T>(rng: Rng, items: readonly T[]): T {
  return items[Math.floor(rng() * items.length)] as T;
}

export function between(rng: Rng, min: number, max: number): number {
  return min + rng() * (max - min);
}

export function round(n: number, dp = 2): number {
  const f = 10 ** dp;
  return Math.round(n * f) / f;
}

export function idHex(rng: Rng, len = 12): string {
  let s = '';
  for (let i = 0; i < len; i++) s += Math.floor(rng() * 16).toString(16);
  return s;
}

const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const B64ISH = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/+';

/** Secret-shaped demo strings are generated at runtime and never committed (push protection). */
export function fakeAwsKeyId(rng: Rng = Math.random): string {
  let s = 'AK' + 'IA';
  for (let i = 0; i < 16; i++) s += B32[Math.floor(rng() * 32)];
  return s;
}

export function fakeAwsSecret(rng: Rng = Math.random): string {
  let s = '';
  for (let i = 0; i < 40; i++) s += B64ISH[Math.floor(rng() * 64)];
  return s;
}
