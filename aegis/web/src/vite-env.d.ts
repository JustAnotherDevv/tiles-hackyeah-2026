/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Gateway origin for API calls; empty = same origin (Vite dev proxy / gateway-served /ui). */
  readonly VITE_AEGIS_API?: string;
  /** "1" forces mock data everywhere (UI development without a gateway). */
  readonly VITE_AEGIS_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
