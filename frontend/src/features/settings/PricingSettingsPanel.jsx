/**
 * Settings → Pricing (Phase 14).
 *
 * The pricing settings the 13C engine reads -- the Air Standard and Air Express default
 * selling rates, the trigger share (OD-48: a surcharge's cost is split, the triggering
 * customer carrying this share), the owner-confirmed flag (shown, never edited here), and the
 * default surcharge markup (OD-74) -- and the per-rule surcharge policies of the active
 * tariff's air sections (OD-44). Changing them is Admin's (`settings:manage`); everyone with
 * `tariff:read` sees them. The server validates and audits every change; this screen checks
 * the obvious first so a mistake is named beside its field. Air only (OD-49).
 *
 * Internal: vendor prices and markups are on this screen. It is staff-only.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { pricingApi, tariffsApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import {
  Banner,
  Button,
  Card,
  Field,
  Select,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { fold } from '../workspace/FeePicker.jsx';
import { formatDateTime } from '../../utils/format.js';

export const DEFAULT_MARKUP_KINDS = ['percent', 'fixed_cad', 'pass_through'];
export const POLICY_MARKUP_KINDS = ['default', 'percent', 'fixed_cad', 'pass_through'];
/** `app/core/enums.py::SurchargeScope`. */
export const SCOPES = ['item_weight', 'full_carton', 'full_master', 'per_unit', 'per_shipment'];
const AIR_SECTIONS = ['hcm_air', 'han_air'];

function text(value) {
  return value === null || value === undefined ? '' : String(Number(value));
}

function settingsForm(data) {
  return {
    air_standard_default_rate_cad: text(data.air_standard_default_rate_cad),
    air_express_default_rate_cad: text(data.air_express_default_rate_cad),
    trigger_share_numerator: String(data.trigger_share_numerator),
    trigger_share_denominator: String(data.trigger_share_denominator),
    default_markup_kind: data.default_markup_kind,
    default_markup_value: text(data.default_markup_value),
  };
}

const POSITIVE = /^\d+(\.\d+)?$/;
const WHOLE = /^\d+$/;
const TWO_DECIMALS = /^\d+(\.\d{1,2})?$/;

/** The problems a person can see before asking the server, by field. */
export function validateSettings(form, t) {
  const errors = {};
  const standard = form.air_standard_default_rate_cad.trim();
  if (!POSITIVE.test(standard) || Number(standard) <= 0) {
    errors.air_standard_default_rate_cad = t('pricingSettings.errors.positiveRate');
  }
  const express = form.air_express_default_rate_cad.trim();
  if (express && (!POSITIVE.test(express) || Number(express) <= 0)) {
    errors.air_express_default_rate_cad = t('pricingSettings.errors.positiveRateOrEmpty');
  }
  const num = form.trigger_share_numerator.trim();
  const den = form.trigger_share_denominator.trim();
  if (!WHOLE.test(num) || !WHOLE.test(den) || Number(num) < 1 || Number(den) < 1) {
    errors.trigger_share_numerator = t('pricingSettings.errors.shareWhole');
  } else if (Number(num) > Number(den)) {
    errors.trigger_share_numerator = t('pricingSettings.errors.shareFraction');
  }
  if (form.default_markup_kind !== 'pass_through') {
    const value = form.default_markup_value.trim();
    if (!POSITIVE.test(value)) {
      errors.default_markup_value = t('pricingSettings.errors.markupNumber');
    } else if (!TWO_DECIMALS.test(value)) {
      // The server stores the default markup to the cent; a third decimal would be rounded
      // away silently (Phase 14 review).
      errors.default_markup_value = t('pricingSettings.errors.markupDecimals');
    } else if (Number(value) > 100) {
      errors.default_markup_value = t('pricingSettings.errors.markupCeiling');
    }
  }
  return errors;
}

/** The server's refusal, beside the field it names (a domain error or a 422 location). */
function serverFieldErrors(error, fields) {
  if (!error) return {};
  const named = error.field ? [error.field] : error.invalidFields || [];
  const out = {};
  for (const field of named) {
    if (fields.includes(field)) out[field] = error.message;
  }
  return out;
}

function markupLabel(kind, value, t) {
  if (kind === 'pass_through') return t('pricingSettings.markupKind.pass_through');
  if (kind === 'fixed_cad') return `${t('pricingSettings.markupKind.fixed_cad')} ${Number(value)} CAD`;
  if (kind === 'percent') return `${t('pricingSettings.markupKind.percent')} ${Number(value)} %`;
  return t(`pricingSettings.markupKind.${kind}`, kind);
}

function DefaultsCard({ data, canEdit }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [form, setForm] = useState(() => settingsForm(data));
  // What the form was filled from. Changes are measured against this, never against the
  // latest query data, so a refetch cannot turn an untouched stale value into a "change"
  // (Phase 14 review). A refetch refills the fields the user has not touched.
  const baseline = useRef(settingsForm(data));
  const [errors, setErrors] = useState({});
  const [saved, setSaved] = useState(null); // 'saved' | 'unchanged'
  const savedRef = useRef(null);
  const formRef = useRef(null);
  const set = (field) => (event) => {
    setSaved(null);
    setForm((current) => ({ ...current, [field]: event.target.value }));
  };

  useEffect(() => {
    if (saved) savedRef.current?.focus();
  }, [saved]);

  useEffect(() => {
    const fresh = settingsForm(data);
    const before = baseline.current;
    baseline.current = fresh;
    setForm((current) => {
      const next = { ...current };
      for (const field of Object.keys(fresh)) {
        if (current[field] === before[field]) next[field] = fresh[field];
      }
      return next;
    });
  }, [data]);

  const save = useMutation({
    mutationFn: (payload) => pricingApi.updateSettings(payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(['pricing-settings'], updated);
      setForm(settingsForm(updated));
      baseline.current = settingsForm(updated);
      setSaved('saved');
    },
  });

  const fields = Object.keys(settingsForm(data));
  const shown = { ...serverFieldErrors(save.error, [...fields, 'trigger_share_denominator']), ...errors };
  if (shown.trigger_share_denominator && !shown.trigger_share_numerator) {
    shown.trigger_share_numerator = shown.trigger_share_denominator;
  }
  const unplaced = save.error && Object.keys(serverFieldErrors(save.error, [...fields, 'trigger_share_denominator'])).length === 0;

  function submit(event) {
    event.preventDefault();
    const found = validateSettings(form, t);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      const first = fields.find((field) => found[field]);
      formRef.current?.querySelector(`[name="${first}"]`)?.focus();
      return;
    }
    const before = baseline.current;
    const payload = {};
    if (form.air_standard_default_rate_cad !== before.air_standard_default_rate_cad) {
      payload.air_standard_default_rate_cad = form.air_standard_default_rate_cad.trim();
    }
    if (form.air_express_default_rate_cad !== before.air_express_default_rate_cad) {
      // Empty is allowed: Operations then enter the rate on each Air Express quote.
      payload.air_express_default_rate_cad = form.air_express_default_rate_cad.trim() || null;
    }
    if (
      form.trigger_share_numerator !== before.trigger_share_numerator ||
      form.trigger_share_denominator !== before.trigger_share_denominator
    ) {
      payload.trigger_share_numerator = Number(form.trigger_share_numerator);
      payload.trigger_share_denominator = Number(form.trigger_share_denominator);
    }
    if (form.default_markup_kind !== before.default_markup_kind) {
      payload.default_markup_kind = form.default_markup_kind;
    }
    if (
      form.default_markup_kind !== 'pass_through' &&
      (form.default_markup_value !== before.default_markup_value ||
        form.default_markup_kind !== before.default_markup_kind)
    ) {
      payload.default_markup_value = form.default_markup_value.trim();
    }
    if (Object.keys(payload).length === 0) {
      setSaved('unchanged');
      return;
    }
    save.mutate(payload);
  }

  const readOnly = !canEdit;
  return (
    <Card title={t('pricingSettings.defaultsTitle')} headingLevel="h3">
      <p className="meta">{t('pricingSettings.defaultsIntro')}</p>
      <p>
        <StatusBadge
          tone={data.defaults_owner_confirmed ? 'success' : 'warning'}
          label={
            data.defaults_owner_confirmed
              ? t('pricingSettings.ownerConfirmed')
              : t('pricingSettings.ownerNotConfirmed')
          }
        />{' '}
        <span className="meta">
          {t('pricingSettings.updatedAt')} {formatDateTime(data.updated_at)}
        </span>
      </p>
      {saved && (
        <div ref={savedRef} tabIndex={-1}>
          <Banner tone="info">
            {saved === 'saved' ? t('pricingSettings.saved') : t('pricingSettings.unchanged')}
          </Banner>
        </div>
      )}
      {unplaced && <Banner tone="danger">{save.error.message}</Banner>}
      <form ref={formRef} onSubmit={submit} noValidate>
        <div className="form-grid">
          <Field
            label={t('pricingSettings.standardRate')}
            hint={t('pricingSettings.rateHint')}
            error={shown.air_standard_default_rate_cad}
            required
          >
            {(props) => (
              <TextInput
                {...props}
                name="air_standard_default_rate_cad"
                inputMode="decimal"
                readOnly={readOnly}
                value={form.air_standard_default_rate_cad}
                onChange={set('air_standard_default_rate_cad')}
              />
            )}
          </Field>
          <Field
            label={t('pricingSettings.expressRate')}
            hint={t('pricingSettings.expressHint')}
            error={shown.air_express_default_rate_cad}
          >
            {(props) => (
              <TextInput
                {...props}
                name="air_express_default_rate_cad"
                inputMode="decimal"
                readOnly={readOnly}
                value={form.air_express_default_rate_cad}
                onChange={set('air_express_default_rate_cad')}
              />
            )}
          </Field>
        </div>
        <fieldset className="pricing-share">
          <legend className="field__label">{t('pricingSettings.share')}</legend>
          <p className="field__hint">{t('pricingSettings.shareHint')}</p>
          <div className="row-wrap">
            <Field label={t('pricingSettings.numerator')} error={shown.trigger_share_numerator}>
              {(props) => (
                <TextInput
                  {...props}
                  name="trigger_share_numerator"
                  inputMode="numeric"
                  size={4}
                  readOnly={readOnly}
                  value={form.trigger_share_numerator}
                  onChange={set('trigger_share_numerator')}
                />
              )}
            </Field>
            <span aria-hidden="true" className="pricing-share__slash">
              /
            </span>
            <Field label={t('pricingSettings.denominator')}>
              {(props) => (
                <TextInput
                  {...props}
                  name="trigger_share_denominator"
                  inputMode="numeric"
                  size={4}
                  readOnly={readOnly}
                  value={form.trigger_share_denominator}
                  onChange={set('trigger_share_denominator')}
                />
              )}
            </Field>
          </div>
        </fieldset>
        {/* Owner, 2026-11-04 (DEC-0270): the old 2 % default (OD-74) prices under the
            RC-UAT-25 method only; the confirmed method's markup is in Pricing method. */}
        <p>
          <StatusBadge tone="neutral" label={t('costMethod.rc25Only')} />{' '}
          <span className="meta">
            {data.default_markup_in_effect === false
              ? t('costMethod.rc25OnlyNoEffect')
              : t('costMethod.rc25OnlyInEffect')}
          </span>
        </p>
        <div className="form-grid">
          <Field
            label={`${t('pricingSettings.defaultMarkupKind')} (${t('costMethod.rc25Only')})`}
            hint={t('pricingSettings.defaultMarkupHint')}
          >
            {(props) => (
              <Select
                {...props}
                name="default_markup_kind"
                disabled={readOnly}
                value={form.default_markup_kind}
                onChange={set('default_markup_kind')}
                options={DEFAULT_MARKUP_KINDS.map((kind) => ({
                  value: kind,
                  label: t(`pricingSettings.markupKind.${kind}`),
                }))}
              />
            )}
          </Field>
          <Field
            label={
              form.default_markup_kind === 'fixed_cad'
                ? t('pricingSettings.markupValueCad')
                : t('pricingSettings.markupValuePercent')
            }
            error={shown.default_markup_value}
          >
            {(props) => (
              <TextInput
                {...props}
                name="default_markup_value"
                inputMode="decimal"
                readOnly={readOnly}
                disabled={form.default_markup_kind === 'pass_through'}
                value={form.default_markup_kind === 'pass_through' ? '0' : form.default_markup_value}
                onChange={set('default_markup_value')}
              />
            )}
          </Field>
        </div>
        {canEdit && (
          <Button type="submit" variant="primary" loading={save.isPending}>
            {t('pricingSettings.save')}
          </Button>
        )}
      </form>
    </Card>
  );
}

const BLANK_POLICY = { markup_kind: 'default', markup_value: '', scope_override: '', note: '' };

function PolicyEditor({ rule, policy, defaultLabel, onDone, onCancel }) {
  const t = useT();
  const queryClient = useQueryClient();
  const formRef = useRef(null);
  const [form, setForm] = useState(() =>
    policy
      ? {
          markup_kind: policy.markup_kind,
          markup_value: text(policy.markup_value),
          scope_override: policy.scope_override || '',
          note: policy.note || '',
        }
      : BLANK_POLICY,
  );
  const [errors, setErrors] = useState({});
  const set = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));
  const needsValue = form.markup_kind === 'percent' || form.markup_kind === 'fixed_cad';

  useEffect(() => {
    formRef.current?.querySelector('select, input, textarea')?.focus();
  }, []);

  const save = useMutation({
    mutationFn: () =>
      pricingApi.setPolicy(rule.section, rule.stt, {
        markup_kind: form.markup_kind,
        markup_value: needsValue ? form.markup_value.trim() : '0',
        scope_override: form.scope_override || null,
        note: form.note.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pricing-policies'] });
      onDone(rule);
    },
  });
  const server = serverFieldErrors(save.error, ['markup_kind', 'markup_value', 'scope_override', 'note']);
  const shown = { ...server, ...errors };
  const unplaced = save.error && Object.keys(server).length === 0;
  const name = `${rule.stt}. ${rule.name}`;

  return (
    <form
      ref={formRef}
      className="pricing-policy-editor"
      aria-label={`${t('pricingSettings.editPolicy')}: ${name}`}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const found = {};
        if (needsValue) {
          const value = form.markup_value.trim();
          if (!POSITIVE.test(value)) found.markup_value = t('pricingSettings.errors.markupNumber');
        }
        setErrors(found);
        if (found.markup_value) {
          formRef.current?.querySelector('[name="markup_value"]')?.focus();
          return;
        }
        save.mutate();
      }}
    >
      <h4>
        {t('pricingSettings.editPolicy')}: {name}
      </h4>
      <p className="meta">
        {t('pricingSettings.vendorPrice')}: {rule.raw_price_text || '—'}
      </p>
      {unplaced && <Banner tone="danger">{save.error.message}</Banner>}
      <div className="form-grid">
        <Field label={t('pricingSettings.markup')} error={shown.markup_kind}>
          {(props) => (
            <Select
              {...props}
              name="markup_kind"
              value={form.markup_kind}
              onChange={set('markup_kind')}
              options={POLICY_MARKUP_KINDS.map((kind) => ({
                value: kind,
                label:
                  kind === 'default'
                    ? `${t('pricingSettings.markupKind.default')} (${defaultLabel})`
                    : t(`pricingSettings.markupKind.${kind}`),
              }))}
            />
          )}
        </Field>
        {needsValue && (
          <Field
            label={
              form.markup_kind === 'fixed_cad'
                ? t('pricingSettings.markupValueCad')
                : t('pricingSettings.markupValuePercent')
            }
            error={shown.markup_value}
            required
          >
            {(props) => (
              <TextInput
                {...props}
                name="markup_value"
                inputMode="decimal"
                value={form.markup_value}
                onChange={set('markup_value')}
              />
            )}
          </Field>
        )}
        <Field
          label={t('pricingSettings.scopeOverride')}
          hint={t('pricingSettings.scopeHint')}
          error={shown.scope_override}
        >
          {(props) => (
            <Select
              {...props}
              name="scope_override"
              value={form.scope_override}
              placeholder={`${t('pricingSettings.scopeNone')} (${t(`pricingSettings.scope.${rule.scope}`, rule.scope)})`}
              onChange={set('scope_override')}
              options={SCOPES.map((scope) => ({ value: scope, label: t(`pricingSettings.scope.${scope}`) }))}
            />
          )}
        </Field>
      </div>
      <Field label={t('pricingSettings.note')} hint={t('common.optional')} error={shown.note}>
        {(props) => (
          <TextArea {...props} name="note" rows={2} maxLength={400} value={form.note} onChange={set('note')} />
        )}
      </Field>
      <div className="row-wrap">
        <Button type="submit" variant="primary" loading={save.isPending}>
          {t('pricingSettings.savePolicy')}
        </Button>
        <Button onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

function PoliciesCard({ settings, canEdit }) {
  const t = useT();
  const [section, setSection] = useState('hcm_air');
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState(null); // `${section}:${stt}`
  const [savedRule, setSavedRule] = useState(null);
  const savedRef = useRef(null);

  const versionsQuery = useQuery({ queryKey: ['tariff-versions'], queryFn: tariffsApi.versions });
  const active = (versionsQuery.data?.items ?? []).find((v) => v.status === 'active');
  const rulesQuery = useQuery({
    queryKey: ['pricing-policy-rules', active?.id, section],
    queryFn: () => tariffsApi.surcharges(active.id, { section }),
    enabled: Boolean(active),
  });
  const policiesQuery = useQuery({ queryKey: ['pricing-policies'], queryFn: pricingApi.policies });

  useEffect(() => {
    if (savedRule) savedRef.current?.focus();
  }, [savedRule]);

  const policies = useMemo(() => {
    const map = new Map();
    for (const policy of policiesQuery.data ?? []) map.set(`${policy.section}:${policy.stt}`, policy);
    return map;
  }, [policiesQuery.data]);
  const folded = fold(query.trim());
  const rules = (rulesQuery.data?.items ?? []).filter(
    (rule) => !folded || fold(rule.name).includes(folded) || String(rule.stt) === folded,
  );
  const defaultLabel = markupLabel(settings.default_markup_kind, settings.default_markup_value, t);
  const editingRule = rules.find((rule) => `${rule.section}:${rule.stt}` === editing) ||
    (rulesQuery.data?.items ?? []).find((rule) => `${rule.section}:${rule.stt}` === editing);

  let body;
  if (versionsQuery.isLoading || policiesQuery.isLoading || rulesQuery.isLoading) {
    body = <SkeletonRows rows={4} />;
  } else if (versionsQuery.error || policiesQuery.error || rulesQuery.error) {
    const error = versionsQuery.error || policiesQuery.error || rulesQuery.error;
    body = <ErrorState error={error} onRetry={() => (versionsQuery.refetch(), policiesQuery.refetch(), rulesQuery.refetch())} />;
  } else if (!active) {
    body = <EmptyState title={t('pricingSettings.noActiveTariff')} body={t('pricingSettings.noActiveTariffBody')} />;
  } else if (rules.length === 0) {
    body = <p className="meta" role="status">{t('pricingSettings.noRules')}</p>;
  } else {
    body = (
      <div className="table-wrap" tabIndex={0} role="region" aria-label={t('pricingSettings.policiesTable')}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">{t('pricingSettings.stt')}</th>
              <th scope="col">{t('pricingSettings.surcharge')}</th>
              <th scope="col">{t('pricingSettings.vendorPrice')}</th>
              <th scope="col">{t('pricingSettings.markup')}</th>
              <th scope="col">{t('pricingSettings.scopeOverride')}</th>
              <th scope="col">{t('pricingSettings.note')}</th>
              {canEdit && (
                <th scope="col">
                  <span className="visually-hidden">{t('pricingSettings.actions')}</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => {
              const key = `${rule.section}:${rule.stt}`;
              const policy = policies.get(key);
              const kind = policy?.markup_kind || 'default';
              return (
                <tr key={key}>
                  <td>{rule.stt}</td>
                  <td>{rule.name}</td>
                  <td className="meta">{rule.raw_price_text || '—'}</td>
                  <td>
                    {kind === 'default'
                      ? `${t('pricingSettings.markupKind.default')} (${defaultLabel})`
                      : markupLabel(kind, policy.markup_value, t)}
                  </td>
                  <td>
                    {policy?.scope_override
                      ? t(`pricingSettings.scope.${policy.scope_override}`, policy.scope_override)
                      : '—'}
                  </td>
                  <td>{policy?.note || '—'}</td>
                  {canEdit && (
                    <td>
                      <Button
                        compact
                        onClick={() => {
                          setSavedRule(null);
                          setEditing(key);
                        }}
                        aria-label={`${t('pricingSettings.editPolicy')}: ${rule.stt}. ${rule.name}`}
                        data-policy-key={key}
                      >
                        {t('common.edit')}
                      </Button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <Card title={t('pricingSettings.policiesTitle')} headingLevel="h3">
      <p className="meta">{t('pricingSettings.policiesIntro')}</p>
      {active && (
        <p className="meta">
          {t('pricingSettings.activeTariff')}: <span className="mono">{active.public_id}</span>
        </p>
      )}
      <div className="form-grid">
        <Field label={t('pricingSettings.section')}>
          {(props) => (
            <Select
              {...props}
              value={section}
              onChange={(event) => {
                setSection(event.target.value);
                setEditing(null);
              }}
              options={AIR_SECTIONS.map((value) => ({ value, label: t(`pricingSettings.sections.${value}`) }))}
            />
          )}
        </Field>
        <Field label={t('pricingSettings.searchRules')} hint={t('pricingSettings.searchHint')}>
          {(props) => (
            <TextInput {...props} type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
          )}
        </Field>
      </div>
      {savedRule && (
        <div ref={savedRef} tabIndex={-1}>
          <Banner tone="info">
            {t('pricingSettings.policySaved').replace('{rule}', `${savedRule.stt}. ${savedRule.name}`)}
          </Banner>
        </div>
      )}
      {editingRule && canEdit && (
        <PolicyEditor
          key={editing}
          rule={editingRule}
          policy={policies.get(editing)}
          defaultLabel={defaultLabel}
          onCancel={() => {
            const key = editing;
            setEditing(null);
            // Back to the button that opened the editor (keyboard users keep their place).
            setTimeout(() => document.querySelector(`[data-policy-key="${key}"]`)?.focus(), 0);
          }}
          onDone={(rule) => {
            setEditing(null);
            setSavedRule(rule);
          }}
        />
      )}
      {body}
    </Card>
  );
}

export function PricingSettingsPanel() {
  const t = useT();
  const { can } = useSession();
  const canEdit = can(P.SETTINGS_MANAGE);
  const query = useQuery({ queryKey: ['pricing-settings'], queryFn: pricingApi.settings });
  if (query.isLoading) return <SkeletonRows rows={4} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  return (
    <>
      <Banner tone="neutral">{t('pricingSettings.intro')}</Banner>
      <DefaultsCard data={query.data} canEdit={canEdit} />
      <PoliciesCard settings={query.data} canEdit={canEdit} />
    </>
  );
}
