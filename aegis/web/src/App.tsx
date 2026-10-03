// Owner: dashboard-shell (scaffold seed).
import { RouterProvider } from 'react-router-dom';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { router } from './router';

export default function App() {
  return (
    <TooltipProvider delayDuration={200}>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" visibleToasts={4} gap={8} offset={20} />
    </TooltipProvider>
  );
}
