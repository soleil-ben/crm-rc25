/**
 * One quote (Phase 13G, OD-77): the charges Solaris Express is offering, and the
 * customer's answer.
 *
 * `GET /account/quotes/{id}` answers the frozen customer view: the Solaris service, billable
 * kilograms, rate per kilogram, base charge, each surcharge the customer pays, the total and
 * the currency. Nothing about cost reaches this page.
 *
 * **Accepting asks first.** "Accept quote" opens a confirmation stating the total; only
 * "Yes, accept" sends it. **Declining** opens a short form with an optional reason. Focus
 * moves to the confirmation (or the form) when it opens, and to the outcome when the answer
 * is saved, so a screen-reader user hears what happened. A quote that can no longer be
 * answered (already answered, withdrawn, or replaced by a newer one) says so in words and
 * offers no buttons; the server refuses a second answer in any case.
 */

import { useEffect, useId, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AccountPageHeader } from '../AccountLayout.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { Button, Card, DetailRow, Field, Loading, Notice } from '../components.jsx';
import { FALLBACK_TIMEZONE } from '../format.js';
import { useAccountErrorText, useAccountFormat, useAccountT } from '../i18n.jsx';
import { quoteTaxSentence } from '../quoteTax.js';
import { QuoteStatus } from './QuotesPage.jsx';

const REASON_MAX = 400;

/** One sentence per reason the server gives (`closed_reason`); no reason is guessed. */
const CLOSED_NOTES = {
  accepted: 'quotes.closedAccepted',
  declined: 'quotes.closedDeclined',
  withdrawn: 'quotes.closedWithdrawn',
  replaced: 'quotes.closedReplaced',
  updating: 'quotes.closedUpdating',
  expired: 'quotes.closedExpired',
};

export function QuoteDetailPage() {
  const { quoteId } = useParams();
  const queryClient = useQueryClient();
  const t = useAccountT();
  const errorText = useAccountErrorText();
  const { formatDateTime, formatKg, formatMoney, notRecorded } = useAccountFormat();
  const headingRef = useRef(null);
  const confirmRef = useRef(null);
  const outcomeRef = useRef(null);
  const acceptRef = useRef(null);
  const declineRef = useRef(null);
  // After Cancel, focus goes back to the button that opened the step.
  const [returnTo, setReturnTo] = useState(null);
  const reasonId = useId();

  // null | 'accept' | 'decline'
  const [step, setStep] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);
  const [outcome, setOutcome] = useState(null);

  const key = ['account', 'quote', quoteId];
  const quote = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => accountApi.quote(quoteId, { signal }),
  });

  const settled = !quote.isPending;
  useEffect(() => {
    if (settled) headingRef.current?.focus();
  }, [settled]);
  useEffect(() => {
    if (step) confirmRef.current?.focus();
  }, [step]);
  useEffect(() => {
    if (outcome || failure) outcomeRef.current?.focus();
  }, [outcome, failure]);
  useEffect(() => {
    if (step || !returnTo) return;
    (returnTo === 'accept' ? acceptRef : declineRef).current?.focus();
    setReturnTo(null);
  }, [step, returnTo]);

  if (quote.isPending) return <Loading label={t('quotes.loadingOne')} />;

  if (quote.error) {
    const error = quote.error;
    const signedOut = error instanceof AccountApiError && error.isSignedOut;
    const missing = error instanceof AccountApiError && error.status === 404;
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('quotes.detailTitle')} headingRef={headingRef} />
        <Card>
          {signedOut ? (
            <Notice tone="warning" title={t('list.sessionEnded')}>
              <p>{t('quotes.sessionEndedBody')}</p>
            </Notice>
          ) : missing ? (
            <Notice tone="warning" title={t('quotes.notFound')}>
              <p>{t('quotes.notFoundBody')}</p>
            </Notice>
          ) : (
            <Notice tone="error" title={t('quotes.loadFailedOne')}>
              <p>{errorText(error)}</p>
            </Notice>
          )}
          <ul className="ca-links">
            <li>
              <Link to={signedOut ? '/account/sign-in' : '/account/quotes'}>
                {signedOut ? t('common.signIn') : t('quotes.backToList')}
              </Link>
            </li>
          </ul>
        </Card>
      </div>
    );
  }

  const data = quote.data;
  const total = formatMoney(data.total_cad, data.currency) || notRecorded;

  async function answer(kind) {
    setBusy(true);
    setFailure(null);
    try {
      const updated =
        kind === 'accept'
          ? await accountApi.acceptQuote(quoteId)
          : await accountApi.declineQuote(quoteId, reason.trim() || undefined);
      queryClient.setQueryData(key, updated);
      // The list shows the status too; read it again next time it is opened.
      queryClient.invalidateQueries({ queryKey: ['account', 'quotes'] });
      setStep(null);
      setReason('');
      setOutcome(kind === 'accept' ? 'accepted' : 'declined');
    } catch (error) {
      setFailure(error);
      // Already answered, withdrawn or replaced: show the quote as it now stands.
      if (error instanceof AccountApiError && error.status === 409) {
        setStep(null);
        quote.refetch();
        queryClient.invalidateQueries({ queryKey: ['account', 'quotes'] });
      }
    } finally {
      setBusy(false);
    }
  }

  const tooLong = reason.length > REASON_MAX;

  return (
    <div className="ca-wide">
      <AccountPageHeader
        title={t('quotes.detailHeading', { reference: data.shipment_reference || notRecorded })}
        headingRef={headingRef}
        intro={t('quotes.detailIntro')}
      />
      <p className="ca-meta">
        <Link to="/account/quotes">{t('quotes.backToList')}</Link>
      </p>

      {outcome || failure ? (
        <div tabIndex={-1} ref={outcomeRef} className="ca-quote-outcome">
          {outcome ? (
            <Notice
              tone="success"
              title={t(outcome === 'accepted' ? 'quotes.acceptedNotice' : 'quotes.declinedNotice')}
            >
              <p>
                {t(outcome === 'accepted' ? 'quotes.acceptedBody' : 'quotes.declinedBody')}
              </p>
            </Notice>
          ) : (
            <Notice
              tone="error"
              title={
                failure instanceof AccountApiError && failure.status === 409
                  ? t('quotes.noLongerOpen')
                  : t('common.couldNotSave')
              }
            >
              <p>{errorText(failure)}</p>
            </Notice>
          )}
        </div>
      ) : null}

      <Card title={t('quotes.summaryCard')}>
        <dl className="ca-detail-grid">
          <DetailRow label={t('quotes.colStatus')}>
            <QuoteStatus status={data.status} />
          </DetailRow>
          <DetailRow label={t('quotes.colService')}>{data.service || notRecorded}</DetailRow>
          <DetailRow label={t('quotes.version')}>{data.version ?? notRecorded}</DetailRow>
          <DetailRow label={t('quotes.colSent')}>
            {formatDateTime(data.sent_at, FALLBACK_TIMEZONE) || notRecorded}
          </DetailRow>
          <DetailRow label={t('quotes.billableWeight')}>
            {formatKg(data.billable_weight_kg) || notRecorded}
          </DetailRow>
          <DetailRow label={t('quotes.ratePerKg')}>
            {data.rate_per_kg_cad
              ? `${formatMoney(data.rate_per_kg_cad, data.currency)} / kg`
              : notRecorded}
          </DetailRow>
        </dl>
      </Card>

      <Card title={t('quotes.chargesCard')}>
        <div className="ca-table-wrap">
          <table className="ca-table">
            <caption className="ca-visually-hidden">{t('quotes.chargesCaption')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('quotes.colCharge')}</th>
                <th scope="col">{t('quotes.colAmount')}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{t('quotes.baseCharge', { service: data.service || '' })}</td>
                <td>{formatMoney(data.base_charge_cad, data.currency) || notRecorded}</td>
              </tr>
              {(data.surcharges ?? []).map((line, index) => (
                <tr key={`${line.name}-${index}`}>
                  <td>{line.name}</td>
                  <td>{formatMoney(line.amount_cad, data.currency) || notRecorded}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">{t('quotes.colTotal')}</th>
                <td>
                  <strong>{total}</strong>
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
        {/* RC-UAT-21 (P-9 stand-in): the invoice's GST/HST rule, replacing OD-108's note. */}
        {data.tax ? <p className="ca-meta">{quoteTaxSentence(t, data.tax)}</p> : null}
      </Card>

      <Card title={t('quotes.answerCard')}>
        {data.status === 'declined' && data.decline_reason ? (
          <p>{t('quotes.yourReason', { reason: data.decline_reason })}</p>
        ) : null}
        {data.responded_at ? (
          <p className="ca-meta">
            {t('quotes.answeredOn', {
              date: formatDateTime(data.responded_at, FALLBACK_TIMEZONE) || notRecorded,
            })}
          </p>
        ) : null}
        {!data.can_answer ? (
          <p>{t(CLOSED_NOTES[data.closed_reason] || 'quotes.noLongerOpen')}</p>
        ) : step === 'accept' ? (
          <section
            className="ca-quote-confirm"
            aria-labelledby={`${reasonId}-accept`}
            tabIndex={-1}
            ref={confirmRef}
          >
            <h3 id={`${reasonId}-accept`} className="ca-card__title">
              {t('quotes.confirmAcceptTitle')}
            </h3>
            <p>{t('quotes.confirmAcceptBody', { total })}</p>
            <div className="ca-form__actions">
              <Button busy={busy} onClick={() => answer('accept')}>
                {t('quotes.confirmAccept')}
              </Button>
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  setReturnTo('accept');
                  setStep(null);
                }}
              >
                {t('quotes.cancel')}
              </Button>
            </div>
          </section>
        ) : step === 'decline' ? (
          <form
            className="ca-quote-confirm"
            aria-labelledby={`${reasonId}-decline`}
            tabIndex={-1}
            ref={confirmRef}
            onSubmit={(event) => {
              event.preventDefault();
              if (!tooLong) answer('decline');
            }}
          >
            <h3 id={`${reasonId}-decline`} className="ca-card__title">
              {t('quotes.confirmDeclineTitle')}
            </h3>
            <Field
              label={t('quotes.declineReason')}
              hint={t('quotes.declineReasonHint')}
              optional
              fieldKey="decline_reason"
              error={tooLong ? t('quotes.reasonTooLong') : undefined}
            >
              {({ id, describedBy, invalid }) => (
                <textarea
                  id={id}
                  className="ca-input"
                  rows={3}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              )}
            </Field>
            <div className="ca-form__actions">
              <Button type="submit" busy={busy} disabled={tooLong}>
                {t('quotes.confirmDecline')}
              </Button>
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  setReturnTo('decline');
                  setStep(null);
                }}
              >
                {t('quotes.cancel')}
              </Button>
            </div>
          </form>
        ) : (
          <>
            <p>{t('quotes.answerPrompt')}</p>
            <div className="ca-form__actions">
              <Button ref={acceptRef} onClick={() => setStep('accept')}>
                {t('quotes.accept')}
              </Button>
              <Button ref={declineRef} variant="secondary" onClick={() => setStep('decline')}>
                {t('quotes.decline')}
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
