/**
 * BackendGate — holds a launch screen over the app until the backend answers.
 *
 * Children are not rendered at all until then, not rendered underneath: every
 * page fires its own requests on mount, and a sleeping Render instance should
 * be woken by one cheap /health probe rather than by a dozen hanging requests
 * that each carry their own retry loop (the doubled cold-start load app/CLAUDE.md
 * warns about). Once the probe succeeds the gate stays open for the session.
 *
 * What it draws depends on how long the wait has been (utils/launchScreen.js):
 * nothing for the first moments, so a warm backend never flashes a screen;
 * then the "waking up" screen; then, past a cold start's usual length, a
 * line that stops promising it will be over soon.
 */
import { useBackendReady } from '../../hooks/useBackendReady';
import { launchPhase } from '../../utils/launchScreen';
import { Loading } from '../ui/Loading';

export function BackendGate({ children }) {
  const { ready, waitedMs } = useBackendReady();
  if (ready) return children;

  const phase = launchPhase(waitedMs);
  const background = 'h-screen overflow-hidden bg-[var(--bg)]';
  if (phase === 'quiet') return <div className={background} />;

  return (
    <div
      className={`${background} flex flex-col items-center justify-center gap-6 px-6 text-center text-[var(--fg-1)] font-[var(--font-body)]`}
      role="status"
      aria-live="polite"
    >
      <img src="/ma_logo_64.png" alt="" width={56} height={56} className="rounded-[var(--radius-md)]" />
      <div className="flex flex-col gap-2 max-w-sm">
        <h1 className="text-lg font-semibold">
          {phase === 'slow' ? 'Still waiting for the server' : 'Waking up the server'}
        </h1>
        <p className="text-sm text-[var(--fg-2)]">
          {phase === 'slow'
            ? 'This is taking longer than a normal start. It keeps trying on its own. If it never gets through, the server may be down or misconfigured.'
            : 'The market data server sleeps when nobody is using it and takes about a minute to start. The dashboard opens by itself as soon as it is up.'}
        </p>
      </div>
      <Loading variant="bar" className="max-w-xs" />
    </div>
  );
}
