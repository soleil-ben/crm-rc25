/**
 * Settings → Pricing method (step 2, DEC-0270).
 *
 * The confirmed cost and quote method's settings (`GET/PATCH /pricing/method-settings`) and
 * the dated sea vendor cost (`POST /pricing/sea-cost`). Changing them is Admin's
 * (`settings:manage`); everyone with `tariff:read` sees them. The server validates and
 * audits; only changed fields are sent. The old 2 % default markup is the RC-UAT-25 method's
 * and lives on the Pricing tab, labelled "RC25 method only".
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { methodApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Field, Select, TextInput } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatVnd } from '../workspace/workspaceFormat.js';

/** Choice settings and their values, as the server accepts them. */
export const CHOICES = {
  pricing_method: ['confirmed', 'rc25'],
  threshold_basis: ['customer', 'package'],
  markup_kind: ['none', 'fixed_cad', 'percent'],
  fx_source_cost: ['kango_fixed', 'vcb_cash_buy', 'vcb_sell'],
  fx_source_quote: ['kango_fixed', 'vcb_cash_buy', 'vcb_sell'],
  residual_mode: ['prorata', 'unallocated'],
  pkg_surcharge_billing: ['same_as_cost', 'triggers_only'],
  parcel_band_cost_basis: ['box', 'parcel'],
  parcel_quote_mode: ['each', 'share'],
  vendor_bill_rounding: ['kango', 'od50'],
};
export const NUMBERS = [
  'air_std_rate_low_cad',
  'air_std_threshold_kg',
  'sea_rate_cad',
  'markup_value',
  'kango_fixed_rate_vnd',
];
const FIELDS = [...Object.keys(CHOICES), ...NUMBERS];

function toForm(data) {
  return Object.fromEntries(
    FIELDS.map((field) => {
      const value = data?.[field];
      if (value === null || value === undefined) return [field, ''];
      return [field, NUMBERS.includes(field) ? String(Number(value)) : String(value)];
    }),
  );
}

/** The fields that differ from what the form was filled from. */
export function changedFields(form, baseline) {
  return Object.fromEntries(
    FIELDS.filter((field) => form[field] !== baseline[field]).map((field) => [
      field,
      form[field].trim?.() ?? form[field],
    ]),
  );
}

function SeaCostCard({ data, canEdit }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [cost, setCost] = useState('');
  const [from, setFrom] = useState('');
  const save = useMutation({
    mutationFn: () => methodApi.setSeaCost({ sea_cost_vnd_per_kg: cost.trim(), effective_from: from }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['method-settings'], updated);
      setCost('');
      setFrom('');
    },
  });
  return (
    <Card title={t('methodSettings.seaCostTitle')} headingLevel="h3">
      <p className="meta">{t('methodSettings.seaCostIntro')}</p>
      <p>
        {t('methodSettings.seaCostCurrent')} <strong>{formatVnd(data.sea_cost_vnd_per_kg)}</strong>
        /kg
      </p>
      <div className="table-wrap">
        <table className="table" aria-label={t('methodSettings.seaCostHistory')}>
          <thead>
            <tr>
              <th scope="col">{t('methodSettings.effectiveFrom')}</th>
              <th scope="col">{t('methodSettings.seaCostPerKg')}</th>
              <th scope="col">{t('methodSettings.source')}</th>
            </tr>
          </thead>
          <tbody>
            {(data.sea_cost_history ?? []).map((row) => (
              <tr key={row.effective_from}>
                <td>{row.effective_from}</td>
                <td>{formatVnd(row.sea_cost_vnd_per_kg)}</td>
                <td>{row.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <form
          className="row-wrap"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <Field label={t('methodSettings.seaCostPerKg')} error={save.error?.message} required>
            {(props) => (
              <TextInput
                {...props}
                inputMode="decimal"
                value={cost}
                onChange={(event) => setCost(event.target.value)}
              />
            )}
          </Field>
          <Field label={t('methodSettings.effectiveFrom')} required>
            {(props) => (
              <TextInput {...props} type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
            )}
          </Field>
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!cost.trim() || !from}>
            {t('methodSettings.addSeaCost')}
          </Button>
        </form>
      )}
    </Card>
  );
}

export function MethodSettingsPanel() {
  const t = useT();
  const { can } = useSession();
  const canEdit = can(P.SETTINGS_MANAGE);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['method-settings'], queryFn: methodApi.settings });
  const [form, setForm] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    if (query.data) {
      setForm(toForm(query.data));
      setBaseline(toForm(query.data));
    }
  }, [query.data]);

  const save = useMutation({
    mutationFn: (payload) => methodApi.update(payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(['method-settings'], updated);
      queryClient.invalidateQueries({ queryKey: ['workspace'] });
      setNotice('saved');
    },
  });

  if (query.isLoading || !form) return <SkeletonRows rows={5} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  const data = query.data;
  const set = (field) => (event) => {
    setNotice(null);
    setForm((current) => ({ ...current, [field]: event.target.value }));
  };

  function submit(event) {
    event.preventDefault();
    const payload = changedFields(form, baseline);
    if (Object.keys(payload).length === 0) {
      setNotice('unchanged');
      return;
    }
    save.mutate(payload);
  }

  const choice = (field) => (
    <Field key={field} label={t(`methodSettings.field.${field}`)} hint={t(`methodSettings.hint.${field}`)}>
      {(props) => (
        <Select
          {...props}
          name={field}
          disabled={!canEdit}
          value={form[field]}
          onChange={set(field)}
          options={CHOICES[field].map((value) => ({
            value,
            label: t(`methodSettings.option.${field}.${value}`),
          }))}
        />
      )}
    </Field>
  );
  const number = (field) => (
    <Field key={field} label={t(`methodSettings.field.${field}`)} hint={t(`methodSettings.hint.${field}`)}>
      {(props) => (
        <TextInput
          {...props}
          name={field}
          inputMode="decimal"
          readOnly={!canEdit}
          disabled={field === 'markup_value' && form.markup_kind === 'none'}
          value={form[field]}
          onChange={set(field)}
        />
      )}
    </Field>
  );

  return (
    <div className="settings-stack">
      <Card title={t('methodSettings.title')} headingLevel="h3">
        <p className="meta">{t('methodSettings.intro')}</p>
        {data.pricing_method !== 'confirmed' && (
          <Banner tone="warning">{t('methodSettings.rc25Active')}</Banner>
        )}
        {notice && (
          <Banner tone="info">
            {notice === 'saved' ? t('methodSettings.saved') : t('methodSettings.unchanged')}
          </Banner>
        )}
        {save.error && <Banner tone="danger">{save.error.message}</Banner>}
        <form onSubmit={submit} noValidate>
          <h4>{t('methodSettings.sectionMethod')}</h4>
          <div className="form-grid">{choice('pricing_method')}</div>
          <h4>{t('methodSettings.sectionRates')}</h4>
          <p className="meta">
            {t('methodSettings.highRate').replace('{rate}', String(Number(data.air_std_rate_high_cad)))}
          </p>
          <div className="form-grid">
            {number('air_std_rate_low_cad')}
            {number('air_std_threshold_kg')}
            {choice('threshold_basis')}
            {number('sea_rate_cad')}
          </div>
          <h4>{t('methodSettings.sectionMarkup')}</h4>
          <div className="form-grid">
            {choice('markup_kind')}
            {number('markup_value')}
          </div>
          <h4>{t('methodSettings.sectionFx')}</h4>
          <div className="form-grid">
            {choice('fx_source_cost')}
            {choice('fx_source_quote')}
            {number('kango_fixed_rate_vnd')}
          </div>
          <h4>{t('methodSettings.sectionAllocation')}</h4>
          <div className="form-grid">
            {choice('residual_mode')}
            {choice('pkg_surcharge_billing')}
            {choice('parcel_band_cost_basis')}
            {choice('parcel_quote_mode')}
            {choice('vendor_bill_rounding')}
          </div>
          {canEdit && (
            <div className="row-wrap">
              <Button type="submit" variant="primary" loading={save.isPending}>
                {t('methodSettings.save')}
              </Button>
            </div>
          )}
        </form>
      </Card>
      <SeaCostCard data={data} canEdit={canEdit} />
    </div>
  );
}
