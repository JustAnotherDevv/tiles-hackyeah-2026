// Viewport < md (768 px): the policy page swaps Monaco for the plain read-only view and inline diffs.
// Owner: B19-dashboard-gov-policy.
import { useEffect, useState } from 'react';

const Q = '(max-width: 767px)';

export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => (typeof window !== 'undefined' ? window.matchMedia(Q).matches : false));
  useEffect(() => {
    const mql = window.matchMedia(Q);
    const on = () => setNarrow(mql.matches);
    mql.addEventListener('change', on);
    return () => mql.removeEventListener('change', on);
  }, []);
  return narrow;
}
