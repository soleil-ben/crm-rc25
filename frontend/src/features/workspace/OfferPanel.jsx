/**
 * The quote sent to the customer (Phase 13G, OD-77): send the finalised quote, see the
 * customer's answer (accepted, declined with their reason, or withdrawn), withdraw it.
 *
 * Everything is the server's: only the latest finalised version can be sent, once; a newer
 * finalised version withdraws an unanswered offer; the customer answers in the Customer
 * Account. Sending and withdrawing need `financial:write` (Operations and Admin), the same
 * as finalising; the server enforces it and the buttons are hidden without it.
 *
 * Phase 15: a quote email that failed (or found no address, once one is added) can be sent
 * again; an accepted quote whose shipment has no invoice prompts staff to issue it through
 * the existing Issue invoice button (nothing is invoiced automatically).
 */

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { financeApi, pricingApi } from '../../api/endpoints.js';
import { P, useOptionalSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Field, StatusBadge, TextArea } from '../../components/ui/index.jsx';
import { formatDateTime } from '../../utils/format.js';
import { wsKey } from './workspaceFormat.js';
import { issueInvoiceButtonId } from './InvoiceLink.jsx';

/** Phase 15: the quote email can be sent again after these outcomes. */
const RESENDABLE = ['failed', 'no_email'];

const OFFER_TONE = {
  sent: 'info',
  accepted: 'success',
  declined: 'danger',
  withdrawn: 'neutral',
  // Owner decision 9: a new tariff became active before the goods were received.
  expired: 'warning',
};

function fill(text, values) {
  return Object.entries(values).reduce(
    (out, [name, value]) => out.replace(`{${name}}`, String(value ?? '')),
    text,
  );
}

function OfferSummary({ offer, current }) {
  const t = useT();
  return (
    <div className="ws-offer__summary">
      <StatusBadge
        tone={OFFER_TONE[offer.status]}
        label={`${fill(t('workspace.offer.version'), { version: offer.version ?? '' })} · ${t(
          `workspace.offer.status.${offer.status}`,
          offer.status,
        )}`}
      />
      <p className="meta">
        {fill(t('workspace.offer.sentOn'), { date: formatDateTime(offer.sent_at) })}
        {offer.email_status
          ? ` · ${fill(t('workspace.offer.email'), {
              status: t(`workspace.offer.emailStatus.${offer.email_status}`, offer.email_status),
            })}`
          : ''}
      </p>
      {offer.responded_at && (
        <p className="meta">
          {fill(t('workspace.offer.answeredOn'), {
            date: formatDateTime(offer.responded_at),
            account: offer.responded_by || '—',
          })}
        </p>
      )}
      {offer.status === 'declined' && (
        <p>
          {offer.decline_reason
            ? fill(t('workspace.offer.declineReason'), { reason: offer.decline_reason })
            : t('workspace.offer.noDeclineReason')}
        </p>
      )}
      {offer.status === 'withdrawn' && offer.withdrawn_reason && (
        <p className="meta">
          {fill(t('workspace.offer.withdrawnReason'), { reason: offer.withdrawn_reason })}
        </p>
      )}
      {offer.status === 'accepted' && offer.superseded_by_version && (
        <Banner tone="warning">
          {fill(t('workspace.offer.acceptedEarlierPrice'), {
            accepted: offer.version ?? '',
            version: offer.superseded_by_version,
          })}
        </Banner>
      )}
      {current && offer.status === 'sent' && !offer.is_current && (
        <Banner tone="warning">{t('workspace.offer.notCurrent')}</Banner>
      )}
    </div>
  );
}

export function OfferPanel({ consolidationId, shipmentId, finalized, canSend, customerLabel, refresh }) {
  const t = useT();
  const session = useOptionalSession();
  const canWrite = Boolean(session?.can(P.FINANCIAL_WRITE));
  const offersQuery = useQuery({
    queryKey: wsKey(consolidationId, 'offers', shipmentId),
    queryFn: () => pricingApi.offers(shipmentId),
  });
  const [withdrawing, setWithdrawing] = useState(false);
  const [reason, setReason] = useState('');
  const [resentStatus, setResentStatus] = useState(null);
  const [goMessage, setGoMessage] = useState(null);
  const canReadFinance = Boolean(session?.can(P.FINANCIAL_READ));
  const canIssue = Boolean(session?.can(P.FINANCIAL_WRITE));
  const send = useMutation({ mutationFn: () => pricingApi.sendQuote(shipmentId), onSuccess: refresh });
  const resend = useMutation({
    mutationFn: (offerId) => pricingApi.resendOfferEmail(offerId),
    onSuccess: (offer) => {
      setResentStatus(offer.email_status);
      refresh();
    },
  });
  const withdraw = useMutation({
    mutationFn: (offerId) => pricingApi.withdrawOffer(offerId, reason.trim()),
    onSuccess: () => {
      setWithdrawing(false);
      setReason('');
      refresh();
    },
  });

  const offers = offersQuery.data ?? [];
  const latest = offers[0];
  const accepted = latest?.status === 'accepted';
  // The same query (and cache entry) as the Issue invoice control beside this panel.
  const invoiceQuery = useQuery({
    queryKey: wsKey(consolidationId, 'invoice', shipmentId),
    queryFn: () => financeApi.shipmentInvoice(shipmentId),
    enabled: canReadFinance && accepted,
  });
  const needsInvoice = accepted && invoiceQuery.isSuccess && !invoiceQuery.data;

  if (offersQuery.isLoading) return null;
  const forThisVersion = finalized ? offers.find((o) => o.quote_version_id === finalized.id) : null;
  const forWhom = (label) => (customerLabel ? `${label} — ${customerLabel}` : label);

  return (
    <section className="ws-offer" aria-label={forWhom(t('workspace.offer.title'))}>
      <h5>{t('workspace.offer.title')}</h5>
      {send.error && <Banner tone="danger">{send.error.message}</Banner>}
      {withdraw.error && <Banner tone="danger">{withdraw.error.message}</Banner>}
      {resend.error && <Banner tone="danger">{resend.error.message}</Banner>}
      {latest ? <OfferSummary offer={latest} current /> : <p className="meta">{t('workspace.offer.notSent')}</p>}

      {needsInvoice && latest.superseded_by_version && (
        // A newer version was finalised after the acceptance: the price is agreed first, so
        // there is no shortcut to the invoice (review 2026-10-21).
        <Banner tone="warning">
          {fill(t('workspace.offer.acceptedPromptSuperseded'), {
            accepted: latest.version ?? '',
            version: latest.superseded_by_version,
          })}
        </Banner>
      )}
      {needsInvoice && !latest.superseded_by_version && (
        <Banner
          tone="warning"
          action={
            <Button
              compact
              onClick={() => {
                if (!canIssue) {
                  setGoMessage(t('workspace.offer.invoiceNoPermission'));
                  return;
                }
                const target = document.getElementById(issueInvoiceButtonId(shipmentId));
                if (!target) {
                  setGoMessage(t('workspace.offer.invoiceUnavailable'));
                  return;
                }
                setGoMessage(null);
                target.scrollIntoView?.({ block: 'center' });
                target.focus();
              }}
              aria-label={forWhom(t('workspace.offer.goToInvoice'))}
            >
              {t('workspace.offer.goToInvoice')}
            </Button>
          }
        >
          {fill(t('workspace.offer.acceptedPrompt'), { version: latest.version ?? '' })}
        </Banner>
      )}
      {needsInvoice && (
        <div role="status" className="meta">
          {goMessage || ''}
        </div>
      )}

      {canWrite && latest?.status === 'sent' && RESENDABLE.includes(latest.email_status) && (
        <div className="ws-form">
          <p className="meta">
            {latest.email_status === 'no_email'
              ? t('workspace.offer.resendHintNoEmail')
              : t('workspace.offer.resendHint')}
          </p>
          <Button
            compact
            loading={resend.isPending}
            onClick={() => {
              setResentStatus(null);
              resend.mutate(latest.id);
            }}
            aria-label={forWhom(t('workspace.offer.resendEmail'))}
          >
            {t('workspace.offer.resendEmail')}
          </Button>
        </div>
      )}
      <div role="status" className="meta">
        {resentStatus
          ? fill(t('workspace.offer.resent'), {
              status: t(`workspace.offer.emailStatus.${resentStatus}`, resentStatus),
            })
          : ''}
      </div>

      {canWrite && latest?.status === 'sent' && !withdrawing && (
        <Button compact onClick={() => setWithdrawing(true)} aria-label={forWhom(t('workspace.offer.withdraw'))}>
          {t('workspace.offer.withdraw')}
        </Button>
      )}
      {canWrite && latest?.status === 'sent' && withdrawing && (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            withdraw.mutate(latest.id);
          }}
        >
          <Field label={t('workspace.offer.withdrawReason')} required>
            {(props) => (
              <TextArea
                {...props}
                rows={2}
                maxLength={400}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            )}
          </Field>
          <Button
            type="submit"
            variant="primary"
            loading={withdraw.isPending}
            disabled={!reason.trim()}
            aria-label={forWhom(t('workspace.offer.confirmWithdraw'))}
          >
            {t('workspace.offer.confirmWithdraw')}
          </Button>{' '}
          <Button compact onClick={() => setWithdrawing(false)}>
            {t('workspace.offer.cancel')}
          </Button>
        </form>
      )}

      {canWrite && canSend && finalized && !forThisVersion && (
        <div className="ws-form">
          <p className="meta">{t('workspace.offer.sendHint')}</p>
          <Button
            variant="primary"
            loading={send.isPending}
            onClick={() => send.mutate()}
            aria-label={forWhom(t('workspace.offer.send'))}
          >
            {t('workspace.offer.send')}
          </Button>
        </div>
      )}

      {offers.length > 1 && (
        <details className="ws-offer__history">
          <summary>{t('workspace.offer.history')}</summary>
          {offers.slice(1).map((offer) => (
            <OfferSummary key={offer.id} offer={offer} current={false} />
          ))}
        </details>
      )}
    </section>
  );
}
