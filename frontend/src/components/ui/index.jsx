/**
 * Reusable interface primitives (Design.md section 5).
 *
 * Feature components compose these; no screen re-implements a button, badge, or table.
 */

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useT } from '../../i18n/index.jsx';
import { RequiredMark } from '../../shared/RequiredMark.jsx';
import './ui.css';

/* --- Button ---------------------------------------------------------- */

export function Button({
  variant = 'secondary',
  compact = false,
  full = false,
  loading = false,
  type = 'button',
  children,
  ...rest
}) {
  const t = useT();
  return (
    <button
      type={type}
      className={[
        'btn',
        `btn--${variant}`,
        compact ? 'btn--compact' : '',
        full ? 'btn--full' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      // A loading button prevents duplicate submission (Design.md section 5).
      {...rest}
      disabled={loading || rest.disabled}
      aria-busy={loading || undefined}
    >
      {loading && <span className="btn__spinner" aria-hidden="true" />}
      {loading ? t('common.saving') : children}
    </button>
  );
}

/* --- Fields ----------------------------------------------------------- */

export function Field({ label, hint, error, required, children, id }) {
  const generatedId = useId();
  const fieldId = id || generatedId;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;

  // RC-UAT-25 item 1, Ben 2026-10-25: a required field shows a red asterisk beside its
  // label and no words. The star is aria-hidden and outside the <label>, so the accessible
  // name is the label alone; `aria-required` on the control says "required" instead.
  return (
    <div className="field">
      <span className="field-label-row">
        <label className="field__label" htmlFor={fieldId}>
          {label}
        </label>
        {required && <RequiredMark />}
      </span>
      {typeof children === 'function'
        ? children({
            id: fieldId,
            'aria-describedby': [hintId, errorId].filter(Boolean).join(' ') || undefined,
            'aria-invalid': error ? 'true' : undefined,
            'aria-required': required ? 'true' : undefined,
          })
        : children}
      {hint && (
        <span className="field__hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field__error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function TextInput(props) {
  return <input className="input" {...props} />;
}

export function TextArea(props) {
  return <textarea className="textarea" {...props} />;
}

export function Select({ options = [], placeholder, ...props }) {
  return (
    <select className="select" {...props}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function Checkbox({ label, hint, id, ...props }) {
  const generatedId = useId();
  const inputId = id || generatedId;
  return (
    <div className="checkbox-row">
      <input type="checkbox" id={inputId} {...props} />
      <label htmlFor={inputId}>
        {label}
        {hint && <div className="field__hint">{hint}</div>}
      </label>
    </div>
  );
}

/* --- Card ------------------------------------------------------------- */

export function Card({ title, actions, children, flush = false, headingLevel: Heading = 'h2' }) {
  const generatedId = useId();
  const titleId = title ? `${generatedId}-title` : undefined;
  return (
    <section className="card" aria-labelledby={titleId}>
      {(title || actions) && (
        <header className="card__header">
          {title && (
            <Heading className="card__title" id={titleId}>
              {title}
            </Heading>
          )}
          <span className="spacer" />
          {actions}
        </header>
      )}
      <div className={flush ? 'card__body card__body--flush' : 'card__body'}>{children}</div>
    </section>
  );
}

/* --- Badge ------------------------------------------------------------ */

const TONE_BY_LIFECYCLE = {
  prospect: 'neutral',
  new: 'orange',
  active: 'success',
  at_risk: 'warning',
  inactive: 'neutral',
  archived: 'neutral',
};

const TONE_BY_TASK_STATUS = {
  not_scheduled: 'neutral',
  scheduled: 'info',
  in_progress: 'info',
  waiting_for_customer: 'warning',
  completed: 'success',
  cancelled: 'neutral',
};

const TONE_BY_CONSENT = {
  unknown: 'neutral',
  consented: 'success',
  withdrawn: 'warning',
  suppressed: 'danger',
};

/**
 * A badge always renders its text label; colour only reinforces it (Design.md section 3).
 * `kind` keeps one state in one colour everywhere it appears.
 */
export function StatusBadge({ kind, value, label, tone: explicitTone }) {
  const t = useT();
  const map =
    kind === 'lifecycle'
      ? TONE_BY_LIFECYCLE
      : kind === 'task'
        ? TONE_BY_TASK_STATUS
        : kind === 'consent'
          ? TONE_BY_CONSENT
          : {};
  const tone = explicitTone || map[value] || 'neutral';
  const text =
    label ||
    (kind === 'lifecycle'
      ? t(`lifecycle.${value}`, value)
      : kind === 'task'
        ? t(`taskStatus.${value}`, value)
        : kind === 'consent'
          ? t(`consentStatus.${value}`, value)
          : value);
  return (
    <span className={`badge badge--${tone}`}>
      <span className="badge__dot" aria-hidden="true" />
      {text}
    </span>
  );
}

export function RouteBadge({ route }) {
  const t = useT();
  if (!route) return <span className="meta">—</span>;
  // Same route-to-colour mapping the dashboard charts use.
  const tone = { VCA: 'orange', CAV: 'navy', CAD: 'teal', XUS: 'info' }[route] || 'neutral';
  return (
    <span className={`badge badge--${tone}`} title={t(`routes.${route}`, route)}>
      {t(`routes.${route}`, route)}
    </span>
  );
}

/* --- Copyable identifier ---------------------------------------------- */

export function CopyableId({ value, ariaLabel }) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  if (!value) return <span className="meta">—</span>;

  return (
    <span className="copyable">
      <span className="mono">{value}</span>
      <button
        type="button"
        className="copyable__button"
        onClick={copy}
        aria-label={ariaLabel || `${t('common.copy')} ${value}`}
      >
        {copied ? t('common.copied') : t('common.copy')}
      </button>
    </span>
  );
}

/* --- Definition tooltip ------------------------------------------------ */

export function InfoDot({ text }) {
  return (
    <span className="info-dot" title={text} tabIndex={0} role="note" aria-label={text}>
      i
    </span>
  );
}

/* --- Tabs -------------------------------------------------------------- */

export function Tabs({ tabs, active, onChange, label }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={active === tab.id}
          aria-controls={`panel-${tab.id}`}
          tabIndex={active === tab.id ? 0 : -1}
          className="tabs__tab"
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.count !== undefined && ` (${tab.count})`}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, active, children }) {
  if (id !== active) return null;
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} tabIndex={0}>
      {children}
    </div>
  );
}

/* --- Overlays ---------------------------------------------------------- */

function useFocusTrap(open, onClose) {
  const ref = useRef(null);
  const triggerRef = useRef(null);
  // The parent usually passes a fresh closure each render. Reading it through a ref
  // keeps the effect keyed on `open` alone, so a keystroke never re-runs the initial
  // focus and pulls the caret back to the first field.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    triggerRef.current = document.activeElement;

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !ref.current) return;
      const focusable = ref.current.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown, true);
    const timer = setTimeout(() => {
      // Focus the first field in the body, not the header close button, so a keyboard
      // user lands where they will actually type (Design.md section 15).
      const body = ref.current?.querySelector('.drawer__body, .modal__body') ?? ref.current;
      const target =
        body?.querySelector('input:not([type="hidden"]), select, textarea, button, [href]') ??
        ref.current?.querySelector('button');
      target?.focus();
    }, 20);

    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      clearTimeout(timer);
      // Focus returns to whatever opened the overlay (Design.md section 15).
      if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus();
    };
  }, [open]);

  return ref;
}

export function Drawer({ open, onClose, title, footer, children }) {
  const t = useT();
  const ref = useFocusTrap(open, onClose);
  if (!open) return null;

  return createPortal(
    <div
      className="overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <header className="drawer__header">
          <h2 className="card__title">{title}</h2>
          <span className="spacer" />
          <Button variant="tertiary" onClick={onClose} aria-label={t('common.close')}>
            ✕
          </Button>
        </header>
        <div className="drawer__body">{children}</div>
        {footer && <footer className="drawer__footer">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

export function Modal({ open, onClose, title, footer, children }) {
  const ref = useFocusTrap(open, onClose);
  if (!open) return null;

  return createPortal(
    <div
      className="overlay overlay--center"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <header className="modal__header">
          <h2 className="card__title">{title}</h2>
        </header>
        <div className="modal__body">{children}</div>
        {footer && <footer className="modal__footer">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

/* --- Banner ------------------------------------------------------------ */

export function Banner({ tone = 'info', title, children, action }) {
  return (
    <div className={`banner banner--${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <div>
        {title && <div className="banner__title">{title}</div>}
        <div>{children}</div>
      </div>
      {action && (
        <>
          <span className="spacer" />
          {action}
        </>
      )}
    </div>
  );
}

/* --- Error summary ----------------------------------------------------- */

/**
 * The problems with a form, listed at its top (UAT round 5: the Add customer dialog showed
 * a bad email inline only, below the fold of a long drawer).
 *
 * `errors` is an ordered list of `{ field, message }`. An entry whose field has a control
 * id in `fieldIds` is a link that moves focus to that control; an entry with no control,
 * such as a whole-form error, stays text. The caller focuses `summaryRef` after a failed
 * submit, so a screen reader announces the count and the list at once.
 */
export function ErrorSummary({ errors, summaryRef, fieldIds = {} }) {
  const t = useT();
  const headingId = useId();
  if (!errors || errors.length === 0) return null;
  const title =
    errors.length === 1
      ? t('forms.errorSummaryOne')
      : t('forms.errorSummaryMany').replace('{count}', String(errors.length));
  return (
    <div
      className="error-summary"
      role="alert"
      tabIndex={-1}
      ref={summaryRef}
      aria-labelledby={headingId}
    >
      <h2 className="error-summary__title" id={headingId}>
        {title}
      </h2>
      <ul className="error-summary__list">
        {errors.map(({ field, message }) => (
          <li key={field ?? message}>
            {field && fieldIds[field] ? (
              <a
                href={`#${fieldIds[field]}`}
                onClick={(event) => {
                  const control = document.getElementById(fieldIds[field]);
                  if (!control) return;
                  // The browser would scroll to the id but not focus a form control.
                  event.preventDefault();
                  control.focus();
                  control.scrollIntoView?.({ block: 'center' });
                }}
              >
                {message}
              </a>
            ) : (
              message
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* --- Chips ------------------------------------------------------------- */

export function FilterChip({ label, onRemove }) {
  const t = useT();
  return (
    <span className="chip">
      {label}
      {onRemove && (
        <button
          type="button"
          className="chip__remove"
          onClick={onRemove}
          aria-label={`${t('common.clear')} ${label}`}
        >
          ✕
        </button>
      )}
    </span>
  );
}

export function Avatar({ initials, large = false }) {
  return (
    <span className={large ? 'avatar avatar--lg' : 'avatar'} aria-hidden="true">
      {initials}
    </span>
  );
}

/* --- Pagination -------------------------------------------------------- */

export function Pagination({ total, limit, offset, onChange }) {
  const t = useT();
  if (total === 0) return null;
  const start = offset + 1;
  const end = Math.min(offset + limit, total);
  return (
    <div className="pagination">
      <span className="meta">
        {start}–{end} {t('common.of')} {total} {t('common.results')}
      </span>
      <div className="row">
        <Button compact onClick={() => onChange(Math.max(0, offset - limit))} disabled={offset === 0}>
          {t('common.previous')}
        </Button>
        <Button compact onClick={() => onChange(offset + limit)} disabled={end >= total}>
          {t('common.next')}
        </Button>
      </div>
    </div>
  );
}
