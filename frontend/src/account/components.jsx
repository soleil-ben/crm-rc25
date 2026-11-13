/**
 * The Customer Account's own primitives.
 *
 * A separate component tree, not an import of `src/components/ui`. The reason is not
 * purity: the staff primitives carry staff assumptions — a `StatusBadge` whose tones are
 * keyed to internal lifecycle vocabularies, a `Pagination` that speaks in the staff list's
 * terms, a `Card` whose heading level suits a page with a staff `PageHeader` above it.
 * Importing them would make every later change to a staff screen a change to a customer
 * screen, which is the coupling `Design.md` §14a.2 says this surface does not have.
 *
 * What **is** shared is `src/styles/tokens.css`: the colours, the type scale, the spacing
 * and the focus ring. That is the brand foundation of section 3, and a second copy of it
 * would be the actual mistake.
 *
 * Accessibility rules that apply to everything here, because they are the ones that get
 * dropped when a component is written in a hurry:
 *
 * * every input has a `<label>` bound by `id`, never a placeholder standing in for one;
 * * an error is announced by `aria-describedby` **and** `aria-invalid`, so a screen reader
 *   reaching the field hears why it is wrong without hunting for the message;
 * * status is never colour alone — every tone carries a word;
 * * a control that changes the page announces the change through a live region rather than
 *   relying on the change being visible.
 */

import { createContext, forwardRef, useContext, useId } from 'react';
import { RequiredMark } from '../shared/RequiredMark.jsx';
import { useAccountT } from './i18n.jsx';

/** Whether the enclosing `Field` is required, so its input can say so (`aria-required`). */
const FieldRequiredContext = createContext(false);

/**
 * The wordmark. Text, not an image: no official logo asset exists and none is invented
 * (CRM.md section 14, DEC-0019).
 */
export function AccountWordmark() {
  return (
    <span className="ca-wordmark">
      <span className="ca-wordmark__first">Solaris</span>
      <span className="ca-wordmark__second">Express</span>
    </span>
  );
}

// `forwardRef` so a screen can return focus to the button that opened a step (13G).
export const Button = forwardRef(function Button(
  { children, variant = 'primary', type = 'button', busy = false, disabled = false, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={`ca-button ca-button--${variant}`}
      // Busy disables, and `aria-busy` says why. A control that looks disabled with no
      // explanation is a control somebody clicks repeatedly.
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <span className="ca-button__spinner" aria-hidden="true" /> : null}
      <span>{children}</span>
    </button>
  );
});

/**
 * A labelled form control.
 *
 * `children` is a render function receiving the ids it must apply. Passing them rather
 * than cloning the child keeps the association explicit at the call site, which is where
 * somebody removing a field will see it.
 */
/**
 * The control id a field gets when the form names it with `fieldKey`. The error summary
 * links to the same id, so each entry there moves focus to its own control.
 */
export function fieldControlId(fieldKey) {
  return `ca-field-${fieldKey}`;
}

export function Field({
  label,
  hint,
  error,
  required = false,
  optional = false,
  fieldKey,
  children,
}) {
  const base = useId();
  const controlId = fieldKey ? fieldControlId(fieldKey) : `${base}-control`;
  const hintId = hint ? `${base}-hint` : undefined;
  const optionalId = optional ? `${base}-optional` : undefined;
  const errorId = error ? `${base}-error` : undefined;
  const describedBy = [hintId, optionalId, errorId].filter(Boolean).join(' ') || undefined;
  const t = useAccountT();

  // RC-UAT-25 item 1, Ben 2026-10-25: a required field shows a red asterisk beside its
  // label and no words ("(required)" / "(bắt buộc)" are gone); an optional field shows
  // "Optional" under the control, as the Staff Portal does. The star is aria-hidden and
  // outside the <label>, so the accessible name is the label alone; "required" reaches
  // assistive technology through `aria-required`, set on the control by the inputs below.
  return (
    <div className={`ca-field${error ? ' ca-field--invalid' : ''}`}>
      <span className="field-label-row">
        <label className="ca-field__label" htmlFor={controlId}>
          {label}
        </label>
        {required ? <RequiredMark /> : null}
      </span>
      {hint ? (
        <p className="ca-field__hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      <FieldRequiredContext.Provider value={required}>
        {children({ id: controlId, describedBy, invalid: Boolean(error) })}
      </FieldRequiredContext.Provider>
      {optional ? (
        <p className="ca-field__optional" id={optionalId}>
          {t('field.optional')}
        </p>
      ) : null}
      {error ? (
        <p className="ca-field__error" id={errorId}>
          <span className="ca-field__error-mark" aria-hidden="true">
            !
          </span>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function TextInput({ id, describedBy, invalid, ...rest }) {
  const required = useContext(FieldRequiredContext);
  return (
    <input
      id={id}
      className="ca-input"
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      aria-required={required || undefined}
      {...rest}
    />
  );
}

export function SelectInput({ id, describedBy, invalid, options = [], placeholder, ...rest }) {
  const required = useContext(FieldRequiredContext);
  return (
    <select
      id={id}
      className="ca-input ca-select"
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      aria-required={required || undefined}
      {...rest}
    >
      {placeholder ? <option value="">{placeholder}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/**
 * A checkbox with its label beside it.
 *
 * **Never pre-checked by a default in this component.** Consent controls are unchecked by
 * default (OD-27, OD-38) and `checked` is always supplied by the caller from state that
 * starts `false`; there is no `defaultChecked` here to make the other mistake with.
 */
export function CheckboxField({ label, hint, error, checked, onChange, name, fieldKey }) {
  const base = useId();
  const controlId = fieldKey ? fieldControlId(fieldKey) : `${base}-control`;
  const hintId = hint ? `${base}-hint` : undefined;
  const errorId = error ? `${base}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  return (
    <div className={`ca-checkbox${error ? ' ca-checkbox--invalid' : ''}`}>
      <input
        type="checkbox"
        id={controlId}
        name={name}
        className="ca-checkbox__input"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        aria-describedby={describedBy}
        aria-invalid={Boolean(error) || undefined}
      />
      <div className="ca-checkbox__text">
        <label htmlFor={controlId} className="ca-checkbox__label">
          {label}
        </label>
        {hint ? (
          <p className="ca-checkbox__hint" id={hintId}>
            {hint}
          </p>
        ) : null}
        {error ? (
          <p className="ca-field__error" id={errorId}>
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function Card({ title, headingLevel: Heading = 'h2', children, actions }) {
  return (
    <section className="ca-card">
      {title ? (
        <div className="ca-card__head">
          <Heading className="ca-card__title">{title}</Heading>
          {actions ? <div className="ca-card__actions">{actions}</div> : null}
        </div>
      ) : null}
      <div className="ca-card__body">{children}</div>
    </section>
  );
}

/**
 * A message block.
 *
 * `role` is `status` for information and `alert` for a problem, so the two are announced
 * with the urgency they deserve rather than both interrupting.
 */
export function Notice({ tone = 'info', title, children, role }) {
  const resolvedRole = role || (tone === 'error' ? 'alert' : 'status');
  const t = useAccountT();
  return (
    <div className={`ca-notice ca-notice--${tone}`} role={resolvedRole}>
      {/* The tone word, not only the tone colour. Colour never carries meaning alone
          (Design.md section 15). */}
      <p className="ca-notice__tone">{t(TONE_WORDS[tone])}</p>
      {title ? <p className="ca-notice__title">{title}</p> : null}
      <div className="ca-notice__body">{children}</div>
    </div>
  );
}

const TONE_WORDS = {
  info: 'notice.info',
  success: 'notice.success',
  warning: 'notice.warning',
  error: 'notice.error',
};

/**
 * The validation summary at the top of a form.
 *
 * Present because a long form's inline errors can all be below the fold. Each entry whose
 * key is in `linkedFields` is a link to that field's control (`fieldControlId`), and
 * following it moves focus there, so a keyboard user reaches a problem in one press (UAT
 * round 4: the entries were plain text). An entry with no field, such as a whole-form
 * error, stays text. Focus is moved here by the caller after a failed submit.
 */
export function ErrorSummary({ errors, headingId, summaryRef, linkedFields = [] }) {
  const t = useAccountT();
  const entries = Object.entries(errors).filter(([, message]) => Boolean(message));
  if (entries.length === 0) return null;
  return (
    <div
      className="ca-error-summary"
      role="alert"
      tabIndex={-1}
      ref={summaryRef}
      aria-labelledby={headingId}
    >
      <h2 className="ca-error-summary__title" id={headingId}>
        {entries.length === 1
          ? t('errorSummary.one')
          : t('errorSummary.many', { count: entries.length })}
      </h2>
      <ul className="ca-error-summary__list">
        {entries.map(([field, message]) => (
          <li key={field}>
            {linkedFields.includes(field) ? (
              <a
                href={`#${fieldControlId(field)}`}
                onClick={(event) => {
                  const control = document.getElementById(fieldControlId(field));
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

/**
 * A shipment's status, as a word and a shape.
 *
 * The tone is chosen from the **public** status vocabulary the response already carries,
 * and the label is the server's `status_label`. Nothing here maps an internal operational
 * state: the account never receives one.
 */
export function StatusPill({ status, label }) {
  return (
    <span className={`ca-status ca-status--${toneForStatus(status)}`}>
      <span className="ca-status__dot" aria-hidden="true" />
      {label}
    </span>
  );
}

function toneForStatus(status) {
  if (status === 'delivered') return 'success';
  if (status === 'cancelled') return 'muted';
  if (status === 'exception' || status === 'delivery_attempted') return 'warning';
  if (status === 'returned' || status === 'return_in_progress') return 'warning';
  return 'progress';
}

/** A neutral marker for a fact about a row — cancelled, rebooked. Word, not colour. */
export function Flag({ children }) {
  return <span className="ca-flag">{children}</span>;
}

export function EmptyState({ title, body, action }) {
  return (
    <div className="ca-empty">
      <p className="ca-empty__title">{title}</p>
      {body ? <p className="ca-empty__body">{body}</p> : null}
      {action ? <div className="ca-empty__action">{action}</div> : null}
    </div>
  );
}

/**
 * The loading placeholder.
 *
 * A live region rather than a silent spinner, because a screen-reader user otherwise hears
 * nothing between pressing a control and the content arriving. `aria-busy` on the region
 * stops the skeleton's shapes being announced as content.
 */
export function Loading({ label }) {
  const t = useAccountT();
  return (
    <div className="ca-loading" role="status" aria-live="polite" aria-busy="true">
      <span className="ca-loading__spinner" aria-hidden="true" />
      <span>{label ?? t('loading.default')}</span>
    </div>
  );
}

/**
 * Pagination. Two buttons and a sentence — not a page-number strip. The noun is always
 * "shipments": it is the only list this surface pages.
 *
 * The sentence is the accessible name of the region, so "Showing 21 to 40 of 57
 * shipments" is read rather than inferred from two arrows.
 */
export function Pagination({ total, limit, offset, onChange }) {
  const t = useAccountT();
  if (total <= limit && offset === 0) return null;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  const summary = t('pagination.summary', { first, last, total });

  return (
    <nav className="ca-pagination" aria-label={t('pagination.label')}>
      <p className="ca-pagination__summary">{summary}</p>
      <div className="ca-pagination__controls">
        <Button
          variant="secondary"
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
        >
          {t('pagination.previous')}
        </Button>
        <Button
          variant="secondary"
          onClick={() => onChange(offset + limit)}
          disabled={last >= total}
        >
          {t('pagination.next')}
        </Button>
      </div>
    </nav>
  );
}

/**
 * A key/value row, used by the detail screen.
 *
 * A description list rather than a table: these are properties of one thing, and `<dl>`
 * says so to a screen reader without any ARIA.
 */
export function DetailRow({ label, children }) {
  return (
    <div className="ca-detail-row">
      <dt className="ca-detail-row__label">{label}</dt>
      <dd className="ca-detail-row__value">{children}</dd>
    </div>
  );
}

/**
 * A link to a carrier's own tracking page.
 *
 * Only ever rendered from `carrier_link` in the approved response, which the server has
 * already checked against the provisional host allowlist — the frontend does not decide
 * whether a URL is safe and does not assemble one. `rel` stops the target reaching this
 * page through `window.opener` or receiving it as a referrer, and the new-window
 * behaviour is stated in the link text rather than left to an icon.
 */
export function CarrierLink({ href, trackingNameKey }) {
  const t = useAccountT();
  // The leg's generic name (owner, 2026-10-22), never the stored carrier or vendor name.
  const key = trackingNameKey === 'master_tracking' ? 'master_tracking' : 'last_mile_tracking';
  const carrierName = t(`tracking.${key}`);
  return (
    <a
      className="ca-carrier-link"
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow external"
      referrerPolicy="no-referrer"
    >
      {t('carrier.trackWith', { carrier: carrierName })}
      <span className="ca-carrier-link__note">{t('common.opensInNewTab')}</span>
    </a>
  );
}
