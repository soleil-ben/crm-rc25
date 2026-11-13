/**
 * Consent tab (Design.md section 7, CRM.md section 11).
 *
 * Shows the current state per channel plus the immutable history. Recording a change
 * appends an event; nothing is overwritten, and eligibility is stated explicitly so a
 * segment is never mistaken for an outreach list.
 *
 * "Suppress address" (UAT round 4) is its own action for holders of `suppression:add`
 * (Marketing and Admin): an evidence reference and a reason are required, and the server
 * writes the consent event, the global suppression and the audit row together.
 *
 * Operations does not suppress (owner decision, 2026-10-15): the "Suppressed" status is
 * offered in the consent form only to holders of `suppression:add`, and the server refuses
 * it from anyone else.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customersApi } from '../../../api/endpoints.js';
import { useT } from '../../../i18n/index.jsx';
import { P, useSession } from '../../../app/SessionContext.jsx';
import {
  Banner,
  Button,
  Card,
  Drawer,
  Field,
  Select,
  StatusBadge,
  TextInput,
} from '../../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../../components/state/index.jsx';
import { formatDateTime } from '../../../utils/format.js';

const STATUSES = ['unknown', 'consented', 'withdrawn'];
const SUPPRESSED = 'suppressed';
const BASES = ['not_recorded', 'express', 'implied_business_relationship'];

export function ConsentTab({ customer }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [suppressOpen, setSuppressOpen] = useState(false);
  const [suppressDone, setSuppressDone] = useState(false);
  const [suppressForm, setSuppressForm] = useState({
    channel: 'email',
    evidence_reference: '',
    reason: '',
  });
  const [form, setForm] = useState({
    channel: 'email',
    status: 'consented',
    basis: 'express',
    evidence_reference: '',
    source: '',
    note: '',
  });

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['consent', customer.id],
    queryFn: () => customersApi.consent(customer.id),
  });

  const recordMutation = useMutation({
    mutationFn: (payload) => customersApi.recordConsent(customer.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['consent', customer.id] });
      setOpen(false);
    },
  });

  const suppressMutation = useMutation({
    mutationFn: (payload) => customersApi.suppressAddress(customer.id, payload),
    onSuccess: (overview) => {
      queryClient.setQueryData(['consent', customer.id], overview);
      queryClient.invalidateQueries({ queryKey: ['consent', customer.id] });
      setSuppressOpen(false);
      setSuppressDone(true);
      setSuppressForm({ channel: 'email', evidence_reference: '', reason: '' });
    },
  });

  const suppressReady =
    suppressForm.evidence_reference.trim().length >= 3 && suppressForm.reason.trim().length >= 3;

  if (isLoading) return <SkeletonRows rows={4} height={72} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      <div className="stack">
        <Banner tone="neutral">{data.note}</Banner>

        {data.do_not_contact && (
          <Banner tone="warning" title={t('customers.doNotContact')}>
            A service restriction is recorded on this customer. It applies regardless of
            consent state.
          </Banner>
        )}

        {suppressDone && <Banner tone="success">{t('profile.suppressDone')}</Banner>}

        <Card
          title={t('profile.consent')}
          actions={
            can(P.CONSENT_WRITE) || can(P.SUPPRESSION_ADD) ? (
              <div className="row-wrap">
                {can(P.SUPPRESSION_ADD) && (
                  <Button
                    compact
                    onClick={() => {
                      suppressMutation.reset();
                      setSuppressDone(false);
                      setSuppressOpen(true);
                    }}
                  >
                    {t('profile.suppressAction')}
                  </Button>
                )}
                {can(P.CONSENT_WRITE) && (
                  <Button variant="primary" compact onClick={() => setOpen(true)}>
                    {t('profile.consentRecord')}
                  </Button>
                )}
              </div>
            ) : null
          }
        >
          <div className="table-wrap">
            <table className="table table--stacked">
              <caption className="visually-hidden">Current consent state per channel</caption>
              <thead>
                <tr>
                  <th scope="col">{t('profile.consentChannel')}</th>
                  <th scope="col">Address</th>
                  <th scope="col">{t('profile.consentStatus')}</th>
                  <th scope="col">{t('profile.consentBasis')}</th>
                  <th scope="col">Eligibility</th>
                </tr>
              </thead>
              <tbody>
                {data.states.map((state) => (
                  <tr key={state.channel}>
                    <td data-label={t('profile.consentChannel')}>{state.channel}</td>
                    <td data-label="Address">{state.address_value || '—'}</td>
                    <td data-label={t('profile.consentStatus')}>
                      <StatusBadge kind="consent" value={state.status} />
                    </td>
                    <td data-label={t('profile.consentBasis')}>
                      {state.basis.replace(/_/g, ' ')}
                      {state.recorded_at && (
                        <div className="meta">{formatDateTime(state.recorded_at)}</div>
                      )}
                    </td>
                    <td data-label="Eligibility">
                      {state.is_suppressed ? (
                        <>
                          <StatusBadge tone="danger" value="suppressed" label={t('profile.suppressed')} />
                          <div className="meta">{state.suppression_reason}</div>
                        </>
                      ) : state.is_marketing_eligible ? (
                        <StatusBadge tone="success" value="eligible" label={t('profile.marketingEligible')} />
                      ) : (
                        <StatusBadge
                          tone="neutral"
                          value="not-eligible"
                          label={t('profile.notMarketingEligible')}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title={t('profile.consentHistory')} flush>
          {data.history.length === 0 ? (
            <EmptyState
              title="No consent events recorded"
              body="Consent history is append-only. Every change is kept with its evidence."
            />
          ) : (
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">{t('profile.consentHistory')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('profile.consentRecorded')}</th>
                    <th scope="col">{t('profile.consentChannel')}</th>
                    <th scope="col">{t('profile.consentStatus')}</th>
                    <th scope="col">{t('profile.consentBasis')}</th>
                    <th scope="col">{t('profile.consentEvidence')}</th>
                    <th scope="col">{t('profile.consentBy')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.history.map((event) => (
                    <tr key={event.id}>
                      <td data-label={t('profile.consentRecorded')}>
                        {formatDateTime(event.recorded_at)}
                      </td>
                      <td data-label={t('profile.consentChannel')}>{event.channel}</td>
                      <td data-label={t('profile.consentStatus')}>
                        <StatusBadge kind="consent" value={event.status} />
                      </td>
                      <td data-label={t('profile.consentBasis')}>{event.basis.replace(/_/g, ' ')}</td>
                      <td data-label={t('profile.consentEvidence')}>
                        {event.evidence_reference || '—'}
                        {event.source && <div className="meta">{event.source}</div>}
                      </td>
                      {/* A staff name, the customer's own account when they recorded it from
                          the portal (UAT round 8), otherwise the system. */}
                      <td data-label={t('profile.consentBy')}>
                        {event.recorded_by?.full_name ||
                          event.recorded_by_account ||
                          t('profile.consentBySystem')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t('profile.consentRecord')}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              type="submit"
              form="consent-form"
              loading={recordMutation.isPending}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        <form
          id="consent-form"
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            recordMutation.mutate({
              channel: form.channel,
              status: form.status,
              basis: form.basis,
              evidence_reference: form.evidence_reference || null,
              source: form.source || null,
              note: form.note || null,
            });
          }}
        >
          {recordMutation.error && <ErrorState error={recordMutation.error} />}
          <Banner tone="neutral">
            Recording consent appends a new event. Earlier events stay in the history.
            Consent requires a basis and an evidence reference.
          </Banner>
          <Field label={t('profile.consentChannel')}>
            {(props) => (
              <Select
                {...props}
                value={form.channel}
                onChange={(event) => setForm({ ...form, channel: event.target.value })}
                options={[
                  { value: 'email', label: 'Email' },
                  { value: 'sms', label: 'SMS' },
                ]}
              />
            )}
          </Field>
          <Field label={t('profile.consentStatus')}>
            {(props) => (
              <Select
                {...props}
                value={form.status}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
                options={(can(P.SUPPRESSION_ADD) ? [...STATUSES, SUPPRESSED] : STATUSES).map(
                  (value) => ({ value, label: t(`consentStatus.${value}`) }),
                )}
              />
            )}
          </Field>
          <Field label={t('profile.consentBasis')}>
            {(props) => (
              <Select
                {...props}
                value={form.basis}
                onChange={(event) => setForm({ ...form, basis: event.target.value })}
                options={BASES.map((value) => ({
                  value,
                  label: value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()),
                }))}
              />
            )}
          </Field>
          <Field
            label={t('profile.consentEvidence')}
            hint={t('profile.evidenceReferenceHint')}
          >
            {(props) => (
              <TextInput
                {...props}
                value={form.evidence_reference}
                onChange={(event) => setForm({ ...form, evidence_reference: event.target.value })}
              />
            )}
          </Field>
          <Field label="Source">
            {(props) => (
              <TextInput
                {...props}
                value={form.source}
                onChange={(event) => setForm({ ...form, source: event.target.value })}
              />
            )}
          </Field>
          <Field label="Note">
            {(props) => (
              <TextInput
                {...props}
                value={form.note}
                onChange={(event) => setForm({ ...form, note: event.target.value })}
              />
            )}
          </Field>
        </form>
      </Drawer>

      <Drawer
        open={suppressOpen}
        onClose={() => setSuppressOpen(false)}
        title={t('profile.suppressTitle')}
        footer={
          <>
            <Button onClick={() => setSuppressOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="danger"
              type="submit"
              form="suppress-form"
              disabled={!suppressReady}
              loading={suppressMutation.isPending}
            >
              {t('profile.suppressConfirm')}
            </Button>
          </>
        }
      >
        <form
          id="suppress-form"
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (!suppressReady) return;
            suppressMutation.mutate({
              channel: suppressForm.channel,
              evidence_reference: suppressForm.evidence_reference.trim(),
              reason: suppressForm.reason.trim(),
            });
          }}
        >
          {suppressMutation.error && <ErrorState error={suppressMutation.error} />}
          <Banner tone="warning">{t('profile.suppressBody')}</Banner>
          <Field label={t('profile.suppressChannel')}>
            {(props) => (
              <Select
                {...props}
                value={suppressForm.channel}
                onChange={(event) =>
                  setSuppressForm({ ...suppressForm, channel: event.target.value })
                }
                options={[
                  { value: 'email', label: 'Email' },
                  { value: 'sms', label: 'SMS' },
                ]}
              />
            )}
          </Field>
          <Field
            label={t('profile.suppressEvidence')}
            hint={t('profile.evidenceReferenceHint')}
            required
          >
            {(props) => (
              <TextInput
                {...props}
                maxLength={255}
                value={suppressForm.evidence_reference}
                onChange={(event) =>
                  setSuppressForm({ ...suppressForm, evidence_reference: event.target.value })
                }
              />
            )}
          </Field>
          <Field
            label={t('profile.suppressReason')}
            hint={t('profile.suppressReasonHint')}
            required
          >
            {(props) => (
              <TextInput
                {...props}
                maxLength={200}
                value={suppressForm.reason}
                onChange={(event) =>
                  setSuppressForm({ ...suppressForm, reason: event.target.value })
                }
              />
            )}
          </Field>
        </form>
      </Drawer>
    </>
  );
}
