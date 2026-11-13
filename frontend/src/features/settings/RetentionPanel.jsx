/**
 * Settings → Retention, Admin only (RC-UAT-21 Phase D, DEC-0233; OD-01, OD-36).
 *
 * The retention-deletion machinery is **off**, and no retention period has been decided by
 * the owner. This screen says so plainly, shows each record class the worker could clean up
 * (disabled, period undecided), lets an Admin set a period or an action (audited), and runs a
 * **dry run** that counts what would be affected without changing anything. Turning
 * retention deletion on needs the owner's approval and a typed confirmation; a class can be
 * enabled only while it is on and has a period. Nothing runs automatically: the worker is
 * started by hand (`python -m app.workers.retention_worker --once`). Invoices, payments,
 * vendor bills and audit events are not record classes at all. The server enforces all of it.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { dataRetentionApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Field, Select, TextInput } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime, interpolate } from '../../utils/format.js';

const KEY = ['admin', 'data-retention'];
const WHOLE = /^\d+$/;

/** A blank period (undecided) or a whole number of days from 1 to 36500, else an error key. */
export function periodError(value) {
  const text = String(value ?? '').trim();
  if (text === '') return null;
  if (!WHOLE.test(text) || Number(text) < 1 || Number(text) > 36500) return 'retention.periodError';
  return null;
}

function PolicyRow({ policy, globalOn }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState(policy.period_days == null ? '' : String(policy.period_days));
  const [action, setAction] = useState(policy.action);
  const [error, setError] = useState(null);
  const save = useMutation({
    mutationFn: (payload) => dataRetentionApi.updatePolicy(policy.record_class, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
  const label = t(`retention.class.${policy.record_class}`, policy.label);
  const inputId = `retention-period-${policy.record_class}`;
  const savedPeriod = policy.period_days == null ? '' : String(policy.period_days);
  const changed = period.trim() !== savedPeriod || action !== policy.action;
  const canEnable = globalOn && policy.period_days != null;
  return (
    <tr>
      <th scope="row">
        {label}
        <div className="meta">{policy.description}</div>
      </th>
      <td>
        {policy.enabled ? t('retention.enabled') : t('retention.disabled')}
      </td>
      <td>
        <label className="visually-hidden" htmlFor={inputId}>
          {interpolate(t('retention.periodFor'), { name: label })}
        </label>
        <TextInput
          id={inputId}
          inputMode="numeric"
          size={6}
          placeholder={t('retention.undecided')}
          value={period}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${inputId}-error` : undefined}
          onChange={(event) => {
            setError(null);
            setPeriod(event.target.value);
          }}
        />
        {error && (
          <span className="field-error" id={`${inputId}-error`}>
            {t(error)}
          </span>
        )}
      </td>
      <td>
        <Select
          aria-label={interpolate(t('retention.actionFor'), { name: label })}
          value={action}
          onChange={(event) => setAction(event.target.value)}
          options={policy.allowed_actions.map((value) => ({
            value,
            label: t(`retention.actions.${value}`, value),
          }))}
        />
      </td>
      <td className="meta">
        {policy.last_run_at
          ? interpolate(t('retention.lastRun'), {
              date: formatDateTime(policy.last_run_at),
              count: policy.last_run_affected ?? 0,
            })
          : t('retention.neverRun')}
      </td>
      <td>
        <Button
          compact
          disabled={!changed}
          loading={save.isPending}
          aria-label={interpolate(t('retention.saveFor'), { name: label })}
          onClick={() => {
            const problem = periodError(period);
            if (problem) {
              setError(problem);
              return;
            }
            save.mutate({
              period_days: period.trim() === '' ? null : Number(period.trim()),
              action,
            });
          }}
        >
          {t('retention.save')}
        </Button>{' '}
        <Button
          compact
          disabled={!policy.enabled && !canEnable}
          title={!policy.enabled && !canEnable ? t('retention.enableNeeds') : undefined}
          aria-label={interpolate(
            t(policy.enabled ? 'retention.disableFor' : 'retention.enableFor'),
            { name: label },
          )}
          onClick={() => save.mutate({ enabled: !policy.enabled })}
        >
          {policy.enabled ? t('retention.disable') : t('retention.enable')}
        </Button>
        {save.error && (
          <span className="field-error" role="alert">
            {save.error.message}
          </span>
        )}
      </td>
    </tr>
  );
}

function GlobalSwitch({ settings }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState('');
  const change = useMutation({
    mutationFn: (payload) => dataRetentionApi.updateSettings(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(KEY, data);
      setTyped('');
    },
  });
  if (settings.enabled) {
    return (
      <div className="retention-switch">
        <Banner tone="warning" title={t('retention.onTitle')}>
          {interpolate(t('retention.onBody'), {
            who: settings.enabled_by || t('common.unknown'),
            date: formatDateTime(settings.enabled_at),
          })}
        </Banner>
        <Button loading={change.isPending} onClick={() => change.mutate({ enabled: false })}>
          {t('retention.turnOff')}
        </Button>
        {change.error && <Banner tone="danger">{change.error.message}</Banner>}
      </div>
    );
  }
  return (
    <div className="retention-switch">
      <p>
        <strong>{t('retention.offTitle')}</strong> {t('retention.offBody')}
      </p>
      <Field
        label={interpolate(t('retention.typeToEnable'), { phrase: settings.confirmation_phrase })}
        hint={t('retention.ownerApproval')}
      >
        {(props) => (
          <TextInput {...props} value={typed} onChange={(event) => setTyped(event.target.value)} />
        )}
      </Field>
      <Button
        variant="danger"
        disabled={typed.trim() !== settings.confirmation_phrase}
        loading={change.isPending}
        onClick={() => change.mutate({ enabled: true, confirmation: typed.trim() })}
      >
        {t('retention.turnOn')}
      </Button>
      {change.error && <Banner tone="danger">{change.error.message}</Banner>}
    </div>
  );
}

function DryRunReport({ run, policies }) {
  const t = useT();
  const labels = Object.fromEntries(
    policies.map((p) => [p.record_class, t(`retention.class.${p.record_class}`, p.label)]),
  );
  return (
    <div className="table-wrap">
      <table className="table">
        <caption>
          {interpolate(t('retention.dryRunCaption'), { date: formatDateTime(run.started_at) })}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t('retention.recordClass')}</th>
            <th scope="col">{t('retention.eligible')}</th>
            <th scope="col">{t('retention.wouldRun')}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(run.counts).map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{labels[key] || key}</th>
              <td>{value.eligible == null ? t('retention.noPeriod') : value.eligible}</td>
              <td>{value.would_run ? t('common.yes') : t('common.no')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RetentionPanel() {
  const t = useT();
  const { can } = useSession();
  const allowed = can(P.RETENTION_MANAGE);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: dataRetentionApi.overview, enabled: allowed });
  const dry = useMutation({
    mutationFn: dataRetentionApi.dryRun,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
  if (!allowed) return <Banner tone="info">{t('retention.adminOnly')}</Banner>;
  if (query.isLoading) return <SkeletonRows rows={4} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  const { settings, policies, runs } = query.data;
  const lastDry = dry.data || runs.find((run) => run.dry_run);
  return (
    <>
      <Card title={t('retention.title')}>
        <Banner tone="warning" title={t('retention.undecidedTitle')}>
          {t('retention.undecidedBody')}
        </Banner>
        <p className="meta">{t('retention.intro')}</p>
        <GlobalSwitch settings={settings} />
      </Card>
      <Card title={t('retention.policies')}>
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">{t('retention.policies')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('retention.recordClass')}</th>
                <th scope="col">{t('retention.state')}</th>
                <th scope="col">{t('retention.period')}</th>
                <th scope="col">{t('retention.action')}</th>
                <th scope="col">{t('retention.lastRunHeading')}</th>
                <th scope="col">{t('retention.change')}</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((policy) => (
                <PolicyRow
                  key={`${policy.record_class}-${policy.period_days}-${policy.action}-${policy.enabled}`}
                  policy={policy}
                  globalOn={settings.enabled}
                />
              ))}
            </tbody>
          </table>
        </div>
        <p className="meta">{t('retention.neverFinancial')}</p>
      </Card>
      <Card
        title={t('retention.dryRunTitle')}
        actions={
          <Button loading={dry.isPending} onClick={() => dry.mutate()}>
            {t('retention.runDry')}
          </Button>
        }
      >
        <p className="meta">{t('retention.dryRunIntro')}</p>
        {dry.error && <Banner tone="danger">{dry.error.message}</Banner>}
        {lastDry ? (
          <DryRunReport run={lastDry} policies={policies} />
        ) : (
          <p className="meta">{t('retention.noDryRun')}</p>
        )}
      </Card>
    </>
  );
}
