import { useEffect, useState } from 'react';
import { fmtAgo, fmtDateTime } from '@/lib/format';

export function TimeAgo({ ts }: { ts: string | number }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 5000);
    return () => clearInterval(id);
  }, []);
  return (
    <time className="tabular text-text-3" dateTime={new Date(ts).toISOString()} title={fmtDateTime(ts)}>
      {fmtAgo(ts)}
    </time>
  );
}
