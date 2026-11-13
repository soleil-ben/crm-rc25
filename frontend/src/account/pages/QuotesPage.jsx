/**
 * Quotes (Phase 13G, OD-77): the quotes Solaris Express has sent this customer.
 *
 * One call, `GET /account/quotes`, answering the customer's own offers newest first: the
 * shipment reference, the Solaris service ("Air Standard" or "Air Express", OD-79), the
 * status, when it was sent and the total. Each opens its own page, where the customer reads
 * the charges and accepts or declines. Nothing about cost reaches this surface: the server
 * sends the frozen customer view only.
 */

import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AccountPageHeader } from '../AccountLayout.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { Button, Card, EmptyState, Loading, Notice } from '../components.jsx';
import { FALLBACK_TIMEZONE } from '../format.js';
import { useAccountErrorText, useAccountFormat, useAccountT } from '../i18n.jsx';
import { quoteTaxSentence } from '../quoteTax.js';

export const QUOTE_STATUS_LABELS = {
  sent: 'quotes.status.sent',
  accepted: 'quotes.status.accepted',
  declined: 'quotes.status.declined',
  withdrawn: 'quotes.status.withdrawn',
  // Owner decision 9 (2026-10-21): the rates changed before the goods were received.
  expired: 'quotes.status.expired',
};

export function QuoteStatus({ status }) {
  const t = useAccountT();
  return (
    <span className={`ca-flag ca-quote-status ca-quote-status--${status}`}>
      {QUOTE_STATUS_LABELS[status] ? t(QUOTE_STATUS_LABELS[status]) : status}
    </span>
  );
}

export function QuotesPage() {
  const headingRef = useRef(null);
  const t = useAccountT();
  const errorText = useAccountErrorText();
  const { formatDate, formatMoney, notRecorded } = useAccountFormat();

  const quotes = useQuery({
    queryKey: ['account', 'quotes'],
    queryFn: ({ signal }) => accountApi.quotes({ signal }),
  });

  const settled = !quotes.isPending;
  useEffect(() => {
    if (settled) headingRef.current?.focus();
  }, [settled]);

  if (quotes.isPending) return <Loading label={t('quotes.loading')} />;

  if (quotes.error) {
    const signedOut = quotes.error instanceof AccountApiError && quotes.error.isSignedOut;
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('quotes.title')} headingRef={headingRef} />
        <Card>
          {signedOut ? (
            <>
              <Notice tone="warning" title={t('list.sessionEnded')}>
                <p>{t('quotes.sessionEndedBody')}</p>
              </Notice>
              <ul className="ca-links">
                <li>
                  <Link to="/account/sign-in">{t('common.signIn')}</Link>
                </li>
              </ul>
            </>
          ) : (
            <>
              <Notice tone="error" title={t('quotes.loadFailed')}>
                <p>{errorText(quotes.error)}</p>
              </Notice>
              <div className="ca-form__actions">
                <Button variant="secondary" onClick={() => quotes.refetch()}>
                  {t('common.tryAgain')}
                </Button>
              </div>
            </>
          )}
        </Card>
      </div>
    );
  }

  const items = quotes.data?.items ?? [];
  return (
    <div className="ca-wide">
      <AccountPageHeader title={t('quotes.title')} headingRef={headingRef} intro={t('quotes.intro')} />
      <Card>
        {items.length === 0 ? (
          <EmptyState title={t('quotes.emptyTitle')} body={t('quotes.emptyBody')} />
        ) : (
          <div className="ca-table-wrap">
            <table className="ca-table">
              <caption className="ca-visually-hidden">{t('quotes.caption')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('quotes.colShipment')}</th>
                  <th scope="col">{t('quotes.colService')}</th>
                  <th scope="col">{t('quotes.colSent')}</th>
                  <th scope="col">{t('quotes.colTotal')}</th>
                  <th scope="col">{t('quotes.colStatus')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className="ca-table__reference">
                      <Link
                        to={`/account/quotes/${item.id}`}
                        aria-label={t('quotes.openQuote', {
                          reference: item.shipment_reference || notRecorded,
                        })}
                      >
                        <span className="ca-mono">{item.shipment_reference || notRecorded}</span>
                      </Link>
                      {item.version ? (
                        <span className="ca-table__sub">
                          {t('quotes.versionLabel', { version: item.version })}
                        </span>
                      ) : null}
                    </td>
                    <td>{item.service || notRecorded}</td>
                    <td>{formatDate(item.sent_at, FALLBACK_TIMEZONE) || notRecorded}</td>
                    <td>
                      {formatMoney(item.total_cad, item.currency) || notRecorded}
                      {item.tax ? (
                        <span className="ca-table__sub">{quoteTaxSentence(t, item.tax)}</span>
                      ) : null}
                    </td>
                    <td>
                      <QuoteStatus status={item.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
