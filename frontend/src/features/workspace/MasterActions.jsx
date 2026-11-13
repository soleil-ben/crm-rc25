/**
 * The master's milestones and its end (Phase 14).
 *
 * A milestone recorded here is recorded once on the master and the server writes it on every
 * active member shipment (v2.1 Test 2): the result lists which shipments received it, which
 * already had it from this master, and which refused it (a cancelled member, for instance),
 * with the server's reason. Publishing works as on a single shipment: an approved template or
 * the staff's own wording, never both, and the customer sees it on each member's timeline.
 * `tracking:write` (Operations, Admin); the buttons are hidden from a role without
 * `tracking:write` (milestones) or `shipment:write` (complete, cancel).
 *
 * Completing (a booked master, after its members are delivered) and cancelling (an open or
 * booked one; every member is released; a reason is required) each ask for confirmation
 * first. The server enforces every rule again.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi } from '../../api/endpoints.js';
import { P, useOptionalSession } from '../../app/SessionContext.jsx';
import { useI18n, useT } from '../../i18n/index.jsx';
import {
  Banner,
  Button,
  Checkbox,
  Field,
  Modal,
  Select,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { CollapsibleCard } from './CollapsibleCard.jsx';
import { renderTemplate, templatesFor } from '../../shared/publicUpdateTemplates.js';
import { EVENT_TYPES, publicDefaults } from '../shipments/shipmentTabs.jsx';
import { wsKey } from './workspaceFormat.js';

const INITIAL_EVENT_TYPE = 'in_transit';

function blankEvent() {
  return {
    event_type: INITIAL_EVENT_TYPE,
    occurred_at: '',
    location_label: '',
    internal_detail: '',
    ...publicDefaults(INITIAL_EVENT_TYPE),
  };
}

function useRefresh(consolidationId) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: wsKey(consolidationId) });
    queryClient.invalidateQueries({ queryKey: ['workspace-list'] });
    queryClient.invalidateQueries({ queryKey: ['shipments'] });
  };
}

function EventResult({ result, resultRef }) {
  const t = useT();
  const event = t(`eventType.${result.event_type}`, result.event_type);
  // Nothing applied and nothing already there: the milestone is on no shipment at all, which
  // is a failure to say plainly, not a success with footnotes (Phase 14 review).
  const nowhere = result.applied.length === 0 && result.duplicates.length === 0;
  return (
    <div ref={resultRef} tabIndex={-1} className="ws-event-result">
      <Banner
        tone={nowhere ? 'danger' : result.refused.length ? 'warning' : 'info'}
        title={
          nowhere
            ? t('masterOps.eventNowhere').replace('{event}', event)
            : t('masterOps.eventRecorded').replace('{event}', event)
        }
      >
        <ul aria-label={t('masterOps.eventOutcome')}>
          <li>
            {t('masterOps.applied')}: {result.applied.length ? result.applied.join(', ') : '—'}
          </li>
          {result.duplicates.length > 0 && (
            <li>
              {t('masterOps.duplicates')}: {result.duplicates.join(', ')}
            </li>
          )}
          {result.refused.map((row) => (
            <li key={row.shipment}>
              {t('masterOps.refused')}: {row.shipment} — {row.reason}
            </li>
          ))}
        </ul>
      </Banner>
    </div>
  );
}

export function MasterEventForm({ master, onCancel, onRecorded }) {
  const t = useT();
  const { locale } = useI18n();
  const refresh = useRefresh(master.id);
  const [form, setForm] = useState(blankEvent);
  const [errors, setErrors] = useState({});
  const formRef = useRef(null);
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));

  useEffect(() => {
    formRef.current?.querySelector('select, input, textarea')?.focus();
  }, []);

  const record = useMutation({
    mutationFn: () =>
      consolidationsApi.recordEvent(master.id, {
        event_type: form.event_type,
        occurred_at: form.occurred_at ? new Date(form.occurred_at).toISOString() : undefined,
        location_label: form.location_label.trim() || undefined,
        internal_detail: form.internal_detail.trim() || undefined,
        is_public_update: form.is_public_update,
        public_update_template_key:
          form.is_public_update && form.public_update_template_key
            ? form.public_update_template_key
            : undefined,
        public_update_text:
          form.is_public_update && !form.public_update_template_key
            ? form.public_update_text.trim()
            : undefined,
      }),
    onSuccess: (result) => {
      refresh();
      onRecorded(result);
    },
  });

  return (
    <form
      ref={formRef}
      className="ws-form"
      aria-label={t('masterOps.eventTitle')}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const found = {};
        if (form.is_public_update && !form.public_update_template_key && !form.public_update_text.trim()) {
          found.public_update_text = t('masterOps.errors.publicText');
        }
        setErrors(found);
        if (found.public_update_text) {
          formRef.current?.querySelector('[name="public_update_text"]')?.focus();
          return;
        }
        record.mutate();
      }}
    >
      <p className="meta">{t('masterOps.eventIntro').replace('{count}', String(master.members.length))}</p>
      {record.error && <Banner tone="danger">{record.error.message}</Banner>}
      <div className="ws-grid">
        <Field label={t('shipmentDetail.eventType')} required>
          {(props) => (
            <Select
              {...props}
              value={form.event_type}
              onChange={(event) => set({ event_type: event.target.value, ...publicDefaults(event.target.value) })}
              options={EVENT_TYPES.map((value) => ({ value, label: t(`eventType.${value}`, value) }))}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.occurredAt')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              type="datetime-local"
              value={form.occurred_at}
              onChange={(event) => set({ occurred_at: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.location')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              maxLength={160}
              value={form.location_label}
              onChange={(event) => set({ location_label: event.target.value })}
            />
          )}
        </Field>
      </div>
      <Field label={t('shipmentDetail.internalDetail')} hint={t('shipmentDetail.internalOnly')}>
        {(props) => (
          <TextArea
            {...props}
            rows={2}
            maxLength={2000}
            value={form.internal_detail}
            onChange={(event) => set({ internal_detail: event.target.value })}
          />
        )}
      </Field>
      <Checkbox
        label={t('masterOps.publish')}
        hint={t('masterOps.publishHint')}
        checked={form.is_public_update}
        onChange={(event) => set({ is_public_update: event.target.checked })}
      />
      {form.is_public_update && (
        <div className="public-update">
          <Field label={t('shipmentDetail.publicUpdateTemplate')}>
            {(props) => (
              <Select
                {...props}
                value={form.public_update_template_key}
                placeholder={t('shipmentDetail.publicUpdateOwnWording')}
                onChange={(event) =>
                  set({
                    public_update_template_key: event.target.value,
                    public_update_text: event.target.value ? '' : form.public_update_text,
                  })
                }
                options={templatesFor(form.event_type).map((key) => ({
                  value: key,
                  label: renderTemplate(key, locale) ?? key,
                }))}
              />
            )}
          </Field>
          {form.public_update_template_key ? (
            <div className="public-update__preview">
              <p className="public-update__preview-title">{t('shipmentDetail.publicUpdatePreview')}</p>
              <p lang="en">
                <span className="public-update__lang">EN</span>
                {renderTemplate(form.public_update_template_key, 'en')}
              </p>
              <p lang="vi">
                <span className="public-update__lang">VI</span>
                {renderTemplate(form.public_update_template_key, 'vi')}
              </p>
            </div>
          ) : (
            <Field
              label={t('shipmentDetail.publicUpdateText')}
              hint={t('shipmentDetail.publicUpdateTextHint')}
              error={errors.public_update_text}
              required
            >
              {(props) => (
                <TextArea
                  {...props}
                  name="public_update_text"
                  rows={2}
                  maxLength={400}
                  value={form.public_update_text}
                  onChange={(event) => set({ public_update_text: event.target.value })}
                />
              )}
            </Field>
          )}
        </div>
      )}
      <div className="row-wrap">
        <Button type="submit" variant="primary" loading={record.isPending}>
          {t('masterOps.recordEvent')}
        </Button>
        <Button onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

/**
 * Members whose customer already has a finalised quote or an accepted offer, read from what
 * the workspace has already loaded for each customer card (no extra request). Cancelling does
 * not touch quotes or offers on the server; the dialog only warns (Phase 14 review).
 */
function committedMembers(queryClient, master) {
  const out = [];
  for (const member of master.members) {
    const quotes = queryClient.getQueryData(wsKey(master.id, 'quotes', member.shipment_id)) || [];
    const offers = queryClient.getQueryData(wsKey(master.id, 'offers', member.shipment_id)) || [];
    const finalised = quotes.filter((v) => v.status === 'finalized').map((v) => v.version);
    const accepted = offers.some((o) => o.status === 'accepted');
    if (finalised.length || accepted) {
      out.push({ reference: member.public_id, finalised, accepted });
    }
  }
  return out;
}

/** Complete (booked) and cancel (open or booked), each behind a confirmation. */
function Lifecycle({ master, onDone, canWrite }) {
  const t = useT();
  const queryClient = useQueryClient();
  const refresh = useRefresh(master.id);
  const [confirm, setConfirm] = useState(null); // 'complete' | 'cancel'
  const [reason, setReason] = useState('');
  const [reasonError, setReasonError] = useState(null);
  const complete = useMutation({
    mutationFn: () => consolidationsApi.complete(master.id),
    onSuccess: () => {
      setConfirm(null);
      refresh();
      onDone('completed');
    },
  });
  const cancel = useMutation({
    mutationFn: () => consolidationsApi.cancel(master.id, reason.trim()),
    onSuccess: () => {
      setConfirm(null);
      setReason('');
      refresh();
      onDone('cancelled');
    },
  });
  const close = () => {
    setConfirm(null);
    setReasonError(null);
    complete.reset();
    cancel.reset();
  };
  const canComplete = canWrite && master.state === 'booked';
  const canCancel = canWrite && (master.state === 'open' || master.state === 'booked');
  const committed = confirm === 'cancel' ? committedMembers(queryClient, master) : [];

  return (
    <>
      <div className="row-wrap">
        {canComplete && (
          <Button compact onClick={() => setConfirm('complete')}>
            {t('masterOps.complete')}
          </Button>
        )}
        {canCancel && (
          <Button compact variant="danger" onClick={() => setConfirm('cancel')}>
            {t('masterOps.cancel')}
          </Button>
        )}
      </div>
      <Modal
        open={confirm === 'complete'}
        onClose={close}
        title={`${t('masterOps.completeTitle')} ${master.public_id}`}
        footer={
          <>
            <Button onClick={close}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={complete.isPending} onClick={() => complete.mutate()}>
              {t('masterOps.confirmComplete')}
            </Button>
          </>
        }
      >
        <p>{t('masterOps.completeBody')}</p>
        {complete.error && <Banner tone="danger">{complete.error.message}</Banner>}
      </Modal>
      <Modal
        open={confirm === 'cancel'}
        onClose={close}
        title={`${t('masterOps.cancelTitle')} ${master.public_id}`}
        footer={
          <>
            <Button onClick={close}>{t('masterOps.keepMaster')}</Button>
            <Button
              variant="danger"
              loading={cancel.isPending}
              onClick={() => {
                if (!reason.trim()) {
                  setReasonError(t('masterOps.errors.reason'));
                  document.getElementById('master-cancel-reason')?.focus();
                  return;
                }
                setReasonError(null);
                cancel.mutate();
              }}
            >
              {t('masterOps.confirmCancel')}
            </Button>
          </>
        }
      >
        <p>{t('masterOps.cancelBody').replace('{count}', String(master.members.length))}</p>
        {committed.length > 0 && (
          <Banner tone="warning" title={t('masterOps.cancelCommittedTitle')}>
            <ul aria-label={t('masterOps.cancelCommittedTitle')}>
              {committed.map((row) => (
                <li key={row.reference}>
                  {row.reference}:{' '}
                  {[
                    row.finalised.length
                      ? t('masterOps.finalisedQuote').replace('{versions}', row.finalised.map((v) => `v${v}`).join(', '))
                      : null,
                    row.accepted ? t('masterOps.acceptedOffer') : null,
                  ]
                    .filter(Boolean)
                    .join('; ')}
                </li>
              ))}
            </ul>
            <p>{t('masterOps.cancelCommittedBody')}</p>
          </Banner>
        )}
        {cancel.error && <Banner tone="danger">{cancel.error.message}</Banner>}
        <Field id="master-cancel-reason" label={t('masterOps.cancelReason')} error={reasonError} required>
          {(props) => (
            <TextArea
              {...props}
              rows={2}
              maxLength={255}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
      </Modal>
    </>
  );
}

export function MasterActionsPanel({ master, collapsible = false, defaultOpen = true }) {
  const t = useT();
  const session = useOptionalSession();
  // Hidden from a role that cannot use them; with no session (rendered on its own) nothing is
  // hidden. The server refuses either way.
  const canTrack = !session || session.can(P.TRACKING_WRITE);
  const canWrite = !session || session.can(P.SHIPMENT_WRITE);
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState(null);
  const [ended, setEnded] = useState(null);
  const resultRef = useRef(null);
  const endedRef = useRef(null);
  const live = master.state === 'open' || master.state === 'booked';

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);
  useEffect(() => {
    if (ended) endedRef.current?.focus();
  }, [ended]);

  if (!canTrack && !canWrite) return null;

  return (
    <CollapsibleCard
      collapsible={collapsible}
      defaultOpen={defaultOpen}
      summary={t(`workspace.states.${master.state}`, master.state)}
      title={t('masterOps.title')}
      actions={
        live &&
        canTrack &&
        !adding &&
        master.members.length > 0 && (
          <Button
            compact
            data-master-add-event=""
            onClick={() => {
              setResult(null);
              setAdding(true);
            }}
          >
            {t('masterOps.addEvent')}
          </Button>
        )
      }
    >
      {ended && (
        <div ref={endedRef} tabIndex={-1}>
          <Banner tone="info">{t(`masterOps.ended.${ended}`)}</Banner>
        </div>
      )}
      {!live && !ended && <p className="meta">{t('masterOps.closed')}</p>}
      {live && master.members.length === 0 && <p className="meta">{t('masterOps.noMembers')}</p>}
      {result && <EventResult result={result} resultRef={resultRef} />}
      {adding && (
        <MasterEventForm
          master={master}
          onCancel={() => {
            setAdding(false);
            // Back to the button that opened the form.
            setTimeout(() => document.querySelector('[data-master-add-event]')?.focus(), 0);
          }}
          onRecorded={(outcome) => {
            setAdding(false);
            setResult(outcome);
          }}
        />
      )}
      {live && !adding && canWrite && <Lifecycle master={master} onDone={setEnded} canWrite={canWrite} />}
    </CollapsibleCard>
  );
}
