import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { EmptyState } from './EmptyState';

export function NotFound() {
  return (
    <EmptyState
      className="mt-16"
      icon="MapPinOff"
      title="Page not found"
      hint="This route is not provided by any dashboard page. Pick one from the sidebar or press ⌘K."
      action={
        <Button asChild size="sm" variant="secondary">
          <Link to="/">Back to Command Center</Link>
        </Button>
      }
    />
  );
}
