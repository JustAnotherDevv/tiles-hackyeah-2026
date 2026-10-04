// Page-local colours for data classes / entity spans (plan 16 §2.3). Decision colours always come from
// ACTION_COLORS (@/lib/colors); data-class colours deliberately avoid amber (redact) and violet (approval).
import type { DataClass, Severity } from '@/api/types';

export const DATA_CLASS_COLORS: Record<DataClass, { label: string; color: string }> = {
  CONFIDENTIAL: { label: 'Confidential · PII', color: '#38BDF8' },
  RESTRICTED: { label: 'Restricted · PCI', color: '#FB923C' },
  SECRET: { label: 'Secret', color: '#FB7185' },
  INTERNAL: { label: 'Internal · metadata', color: '#2DD4BF' },
  PUBLIC: { label: 'Public', color: '#94A3B8' },
};

export const DROPPED_COLOR = '#FB7185';
export const RESTORED_COLOR = '#34D399';
export const NEUTRAL_ENTITY_COLOR = '#A5B4FC';

export function dataClassColor(dc: DataClass | null | undefined): string {
  return dc ? DATA_CLASS_COLORS[dc].color : NEUTRAL_ENTITY_COLOR;
}

export const SEVERITY_TONE: Record<Severity, { label: string; className: string }> = {
  info: { label: 'Info', className: 'text-text-3 border-border bg-surface-2' },
  low: { label: 'Low', className: 'text-sky-300 border-sky-400/25 bg-sky-400/10' },
  medium: { label: 'Medium', className: 'text-orange-300 border-orange-400/25 bg-orange-400/10' },
  high: { label: 'High', className: 'text-block border-block/30 bg-block/10' },
  critical: { label: 'Critical', className: 'text-white border-block/60 bg-block/40' },
};

export const KIND_COLORS: Record<string, string> = {
  deterministic: '#818CF8',
  stateful: '#2DD4BF',
  hybrid: '#F472B6',
  semantic: '#38BDF8',
};
