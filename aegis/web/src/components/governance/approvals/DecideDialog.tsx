// Approve (optional comment) / Deny (required reason ≥ 3 chars + preset chips) dialog.
// POST /api/approvals/{id}/approve|deny?view_as=… → result toast (id apr-<id>); 403 shown verbatim.
// Owner: B18-dashboard-gov-approvals.
import { Check, LoaderCircle, X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import type { ApprovalRequest } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { ApproverBadge } from '../ApproverBadge';
import { errorTitle, govApi, parseApiError } from '../gov-api';
import { approveLabel, type Viewer } from '../lib/eligibility';
import { fmtMoney } from '../lib/format-gov';
import { toastDecision } from './util';

const DENY_PRESETS = [
  'Not justified for this scope — use the sandbox dataset instead.',
  'Amount too high — request a smaller plan.',
  'Vendor not on the approved list.',
  'Client data must not leave the firm this way.',
];

export interface DecideDialogProps {
  req: ApprovalRequest | null;
  mode: 'approve' | 'deny';
  open: boolean;
  onOpenChange: (open: boolean) => void;
  viewer: Viewer;
  viewerName: string;
  sponsorId: string | null;
  onDone: (res: ApprovalRequest) => void;
}

export function DecideDialog({ req, mode, open, onOpenChange, viewer, viewerName, sponsorId, onDone }: DecideDialogProps) {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [lastKey, setLastKey] = useState('');
  const key = `${req?.id ?? ''}:${mode}:${open}`;
  if (key !== lastKey) {
    // reset the form whenever the dialog opens for a different request/mode
    setLastKey(key);
    setComment('');
    setBusy(false);
  }
  if (!req) return null;
  const deny = mode === 'deny';
  const tooShort = deny && comment.trim().length < 3;

  async function submit() {
    if (!req || tooShort || busy) return;
    setBusy(true);
    try {
      const res = deny ? await govApi.deny(req.id, viewer.member_id, comment.trim()) : await govApi.approve(req.id, viewer.member_id, comment.trim() || null);
      toastDecision(res.data, mode, viewerName);
      onDone(res.data);
      onOpenChange(false);
    } catch (e) {
      const p = parseApiError(e);
      toast.error(errorTitle(p), { id: `apr-${req.id}`, description: p.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {deny ? <X className="size-4 text-block" /> : <Check className="size-4 text-allow" />}
            {deny ? 'Deny request' : approveLabel(req, viewer, { sponsorId })}
          </DialogTitle>
          <DialogDescription className="text-text-2">{req.title}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-2 text-xs text-text-3">
          <ApproverBadge level={req.required_role} size="sm" />
          {req.amount_usd !== null ? <span className="tabular text-approval">{fmtMoney(req.amount_usd)}</span> : null}
          <span className="font-mono">{req.id}</span>
        </div>
        <div className="space-y-2">
          <label htmlFor="decide-comment" className="text-xs text-text-2">
            {deny ? 'Reason (required — sent to the requester and written to the audit log)' : 'Comment (optional — written to the audit log)'}
          </label>
          <Textarea
            id="decide-comment"
            autoFocus
            rows={3}
            value={comment}
            placeholder={deny ? 'Why is this denied?' : 'e.g. OK for this month only'}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit();
            }}
            aria-invalid={deny && comment.length > 0 && tooShort}
          />
          {deny ? (
            <div className="flex flex-wrap gap-1.5">
              {DENY_PRESETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setComment(p)}
                  className={cn('rounded-full border border-border bg-surface-2 px-2 py-0.5 text-2xs text-text-2 hover:border-border-strong hover:text-text-1', comment === p && 'border-block/40 text-block')}
                >
                  {p.split(' — ')[0]}
                </button>
              ))}
            </div>
          ) : null}
          {req.two_person && !deny ? (
            <p className="text-xs text-text-3">Two-person rule: your vote counts once; a second distinct approver completes it. Any eligible deny rejects it.</p>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={tooShort || busy}
            className={deny ? 'bg-block/90 text-white hover:bg-block' : 'bg-emerald-600 text-white hover:bg-emerald-500'}
          >
            {busy ? <LoaderCircle className="size-3.5 animate-spin" /> : deny ? <X className="size-3.5" /> : <Check className="size-3.5" />}
            {deny ? 'Deny request' : approveLabel(req, viewer, { sponsorId })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
