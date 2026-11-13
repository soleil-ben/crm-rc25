/**
 * `/track` -- the tracking landing page.
 *
 * One field and one button. `Design.md` section 14 is explicit that nothing should sit
 * between a customer and their tracking result: no testimonials, no rates, no marketing.
 */

import { useId, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePublicI18n } from './i18n.jsx';
import { normalizeReference } from './reference.js';
import { PublicHelpLink } from './PublicCallouts.jsx';

export function TrackLandingPage({ initialValue = '' }) {
  const { t } = usePublicI18n();
  const navigate = useNavigate();
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState(null);
  const fieldId = useId();
  const hintId = `${fieldId}-hint`;
  const errorId = `${fieldId}-error`;

  function submit(event) {
    event.preventDefault();
    const reference = normalizeReference(value);
    if (!reference) {
      // The only thing the page decides for itself. Everything else -- whether the
      // reference is well formed, whether it exists -- is the server's answer, so the
      // page cannot leak a distinction the server works to hide.
      setError(t('landing.emptyError'));
      return;
    }
    setError(null);
    // Navigating rather than fetching in place means the result is bookmarkable, the
    // back button works, and a QR code lands on exactly the same screen.
    navigate(`/track/${encodeURIComponent(reference)}`);
  }

  return (
    <div className="public-card public-card--form">
      <h1 className="public-title">{t('landing.title')}</h1>
      <p className="public-lede">{t('landing.instruction')}</p>

      <form className="public-form" onSubmit={submit} noValidate>
        <label className="public-label" htmlFor={fieldId}>
          {t('landing.fieldLabel')}
        </label>
        <input
          id={fieldId}
          className="public-input"
          type="text"
          name="reference"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            if (error) setError(null);
          }}
          placeholder={t('landing.placeholder')}
          // A handheld scanner types the code and presses Enter. Autocorrect,
          // capitalization, and spellcheck all fight that, so they are all turned off.
          autoCapitalize="characters"
          autoCorrect="off"
          autoComplete="off"
          spellCheck="false"
          inputMode="text"
          enterKeyHint="search"
          maxLength={120}
          aria-describedby={error ? `${errorId} ${hintId}` : hintId}
          aria-invalid={error ? 'true' : undefined}
        />

        {error ? (
          // `role="alert"` so a screen reader announces the problem rather than leaving
          // it to be discovered by someone re-reading the form.
          <p className="public-field-error" id={errorId} role="alert">
            {error}
          </p>
        ) : null}

        <p className="public-hint" id={hintId}>
          <span className="public-hint__label">{t('landing.exampleLabel')}:</span>{' '}
          {t('landing.exampleHint')}
        </p>

        <button type="submit" className="public-button public-button--primary">
          {t('landing.submit')}
        </button>
      </form>

      <PublicHelpLink className="public-help-link" />
    </div>
  );
}
