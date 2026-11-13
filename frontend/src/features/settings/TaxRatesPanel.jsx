/**
 * Settings → GST/HST rates (owner Ben, 2026-10-23; DEC-0227).
 *
 * The GST/HST rate of each Canadian province or territory. A draft invoice for a **domestic**
 * shipment auto-fills its destination province's rate, included in the price; an
 * international shipment is zero-rated (0 %, not in this table). Everyone with
 * `financial:read` sees the table; Admin (`settings:manage`) edits a rate or its label. The
 * server validates (a whole percent from 0 to 30; GST or HST) and audits every change
 * (`tax_rate.update`). A change applies to drafts created from then on; an existing draft
 * keeps its rate.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { financeApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Select, TextInput } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';

const WHOLE = /^\d+$/;

/** A whole percent from 0 to 30, else an error key. */
export function rateError(value) {
  const text = String(value ?? '').trim();
  if (!WHOLE.test(text) || Number(text) > 30) return 'taxRates.rateError';
  return null;
}

function RateRow({ row, canEdit }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [rate, setRate] = useState(String(row.rate_percent));
  const [label, setLabel] = useState(row.tax_label);
  const [error, setError] = useState(null);
  const save = useMutation({
    mutationFn: () =>
      financeApi.updateTaxRate(row.province_code, {
        rate_percent: Number(rate.trim()),
        tax_label: label,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['finance', 'tax-rates'], data);
      queryClient.invalidateQueries({ queryKey: ['finance', 'invoice-draft'] });
    },
  });
  const changed = rate.trim() !== String(row.rate_percent) || label !== row.tax_label;
  const inputId = `tax-rate-${row.province_code}`;
  return (
    <tr>
      <th scope="row">
        <span className="mono">{row.province_code}</span> {row.province_name}
      </th>
      <td>
        {canEdit ? (
          <>
            <label className="visually-hidden" htmlFor={inputId}>
              {t('taxRates.rateFor').replace('{province}', row.province_name)}
            </label>
            <TextInput
              id={inputId}
              inputMode="numeric"
              size={3}
              value={rate}
              aria-invalid={error ? 'true' : undefined}
              aria-describedby={error ? `${inputId}-error` : undefined}
              onChange={(event) => {
                setError(null);
                setRate(event.target.value);
              }}
            />{' '}
            %
            {error && (
              <span className="field-error" id={`${inputId}-error`}>
                {t(error)}
              </span>
            )}
          </>
        ) : (
          `${row.rate_percent} %`
        )}
      </td>
      <td>
        {canEdit ? (
          <Select
            aria-label={t('taxRates.labelFor').replace('{province}', row.province_name)}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            options={['GST', 'HST'].map((value) => ({ value, label: value }))}
          />
        ) : (
          row.tax_label
        )}
      </td>
      <td className="meta">
        {row.updated_by
          ? t('taxRates.changedBy')
              .replace('{who}', row.updated_by)
              .replace('{date}', formatDateTime(row.updated_at))
          : t('taxRates.asSeeded')}
      </td>
      {canEdit && (
        <td>
          <Button
            compact
            aria-label={t('taxRates.saveFor').replace('{province}', row.province_name)}
            disabled={!changed}
            loading={save.isPending}
            onClick={() => {
              const problem = rateError(rate);
              if (problem) {
                setError(problem);
                return;
              }
              save.mutate();
            }}
          >
            {t('taxRates.save')}
          </Button>
          {save.error && (
            <span className="field-error" role="alert">
              {save.error.message}
            </span>
          )}
        </td>
      )}
    </tr>
  );
}

export function TaxRatesPanel() {
  const t = useT();
  const { can } = useSession();
  const canEdit = can(P.SETTINGS_MANAGE);
  const query = useQuery({ queryKey: ['finance', 'tax-rates'], queryFn: financeApi.taxRates });
  if (query.isLoading) return <SkeletonRows rows={4} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  return (
    <Card title={t('taxRates.title')}>
      <p className="meta">{t('taxRates.intro')}</p>
      {!canEdit && <Banner tone="info">{t('taxRates.readOnly')}</Banner>}
      <div className="table-wrap">
        <table className="table">
          <caption className="visually-hidden">{t('taxRates.caption')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('taxRates.province')}</th>
              <th scope="col">{t('taxRates.rate')}</th>
              <th scope="col">{t('taxRates.label')}</th>
              <th scope="col">{t('taxRates.changed')}</th>
              {canEdit && <th scope="col">{t('taxRates.action')}</th>}
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((row) => (
              <RateRow
                key={`${row.province_code}-${row.rate_percent}-${row.tax_label}`}
                row={row}
                canEdit={canEdit}
              />
            ))}
          </tbody>
        </table>
      </div>
      <p className="meta">
        {t('taxRates.allowed').replace(
          '{rates}',
          query.data.allowed_rates.map((rate) => `${rate} %`).join(', '),
        )}
      </p>
    </Card>
  );
}
