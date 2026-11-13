/**
 * Async state components (Design.md section 5 and section 18).
 *
 * Loading, empty, validation error, permission denied, provider unavailable, stale, and
 * not-found are all designed states rather than blank screens.
 */

import { useT } from '../../i18n/index.jsx';
import { Banner, Button } from '../ui/index.jsx';

/** Layout-preserving skeleton for a first load. */
export function SkeletonRows({ rows = 5, height = 52 }) {
  const t = useT();
  return (
    <div className="stack" role="status" aria-live="polite" aria-busy="true">
      <span className="visually-hidden">{t('states.loading')}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton" style={{ height }} aria-hidden="true" />
      ))}
    </div>
  );
}

export function SkeletonCards({ count = 4, height = 118 }) {
  return (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="skeleton" style={{ height }} aria-hidden="true" />
      ))}
    </>
  );
}

export function EmptyState({ title, body, action }) {
  const t = useT();
  return (
    <div className="state-block">
      <p className="state-block__title">{title || t('states.emptyTitle')}</p>
      {body && <p className="state-block__body">{body}</p>}
      {action}
    </div>
  );
}

/**
 * One error surface that reads the API error and explains the recovery action.
 * Permission denied and not found are distinct designed states, not generic failures.
 */
export function ErrorState({ error, onRetry }) {
  const t = useT();
  if (!error) return null;

  if (error.isPermissionDenied) {
    return (
      <div className="state-block">
        <p className="state-block__title">{t('states.permissionTitle')}</p>
        <p className="state-block__body">{error.message || t('states.permissionBody')}</p>
      </div>
    );
  }

  if (error.isNotFound) {
    return (
      <div className="state-block">
        <p className="state-block__title">{t('states.notFoundTitle')}</p>
        <p className="state-block__body">{t('states.notFoundBody')}</p>
      </div>
    );
  }

  const isOffline = error.code === 'network_error';
  return (
    <div className="state-block">
      <p className="state-block__title">
        {isOffline ? t('states.offlineTitle') : t('states.errorTitle')}
      </p>
      <p className="state-block__body">{error.message}</p>
      {error.isRateLimited && error.detail?.retry_after_seconds && (
        <p className="meta">Retry in about {error.detail.retry_after_seconds} seconds.</p>
      )}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  );
}

/** Inline banner for a result that is being refreshed but is still displayed. */
export function StaleBanner({ children }) {
  const t = useT();
  return (
    <Banner tone="warning" title={t('states.staleTitle')}>
      {children}
    </Banner>
  );
}

export function InlineSpinner({ label }) {
  const t = useT();
  return (
    <span className="row meta" role="status">
      <span className="btn__spinner" aria-hidden="true" />
      {label || t('states.loading')}
    </span>
  );
}
