/**
 * Correcting a recorded timeline event, and the history of corrections (RC-UAT-25 item 6,
 * Ben 2026-10-25).
 *
 * Offered to whoever may record and void events (`tracking:write`: Admin and Operations),
 * on any live event staff entered -- including one already published to the customer, which
 * is the case this exists for. The form says so plainly before anything else.
 *
 * What it can correct: event type, occurred at, packages, leg, location, country, internal
 * note, and -- on a published event -- the customer-visible sentence, but only to a standard
 * update offered for the (new) event type. Own wording already on the event can be kept, not
 * rewritten; an edit never publishes or unpublishes, and never sends a milestone email. The
 * server enforces each of those rules again (`event_service.edit_event`); a reason is required
 * and every edit is kept with its before and after.
 */

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { shipmentsApi } from '../../api/endpoints.js';
import { useI18n, useT } from '../../i18n/index.jsx';
import { renderTemplate, templatesFor } from '../../shared/publicUpdateTemplates.js';
import {
  Banner,
  Button,
  Checkbox,
  Field,
  Select,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { formatDateTime, fromLocalInputValue, interpolate, toLocalInputValue } from '../../utils/format.js';

const KEEP = '__keep__';

/** The edit history as the server sent it, or nothing: never a crash on an odd answer. */
function revisionList(data) {
  return Array.isArray(data)
    ? data.filter((item) => item && item.before && item.after && Array.isArray(item.event_ids_after))
    : [];
}

/** The query key of a shipment's edit history. */
export function revisionsKey(shipmentId) {
  return ['shipment-event-revisions', String(shipmentId)];
}

export function EventEditForm({ shipment, packages, legs, rows, eventTypes, onDone }) {
  const t = useT();
  const { locale } = useI18n();
  const queryClient = useQueryClient();
  const first = rows[0];
  const published = first.is_public_update;
  const initialOccurred = toLocalInputValue(first.occurred_at);
  const currentPackageIds = rows.map((row) => row.package_id).filter(Boolean);
  const activeCount = packages.filter((item) => item.is_active).length;
  const coversAll = currentPackageIds.length === activeCount;

  const [form, setForm] = useState({
    event_type: first.event_type,
    occurred_at: initialOccurred,
    package_ids: coversAll ? [] : currentPackageIds.map(String),
    leg_id: first.leg_id ? String(first.leg_id) : '',
    location_label: first.location_label ?? '',
    location_country_code: first.location_country_code ?? '',
    internal_detail: first.internal_detail ?? '',
    wording: KEEP,
    reason: '',
  });

  function set(patch) {
    setForm((current) => ({ ...current, ...patch }));
  }

  const offered = templatesFor(form.event_type);
  // The current sentence may be kept while it is still allowed: own wording always (it cannot
  // be rewritten, only kept or replaced), a standard update while the type is unchanged.
  const canKeep =
    published &&
    (Boolean(first.public_update_text) ||
      (Boolean(first.public_update_template_key) && form.event_type === first.event_type));
  const wording = form.wording === KEEP && !canKeep ? offered[0] ?? '' : form.wording;

  const selectable = packages.filter(
    (item) => item.is_active || currentPackageIds.includes(item.id),
  );

  const mutation = useMutation({
    mutationFn: () => {
      const keep = wording === KEEP;
      return shipmentsApi.editEvent(shipment.id, {
        event_ids: rows.map((row) => row.id),
        event_type: form.event_type,
        occurred_at:
          form.occurred_at && form.occurred_at !== initialOccurred
            ? fromLocalInputValue(form.occurred_at)
            : undefined,
        package_ids: form.package_ids.map(Number),
        leg_id: form.leg_id ? Number(form.leg_id) : null,
        location_label: form.location_label || null,
        location_country_code: form.location_country_code || null,
        internal_detail: form.internal_detail || null,
        public_update_template_key: published
          ? keep
            ? first.public_update_template_key
            : wording || null
          : null,
        public_update_text: published && keep ? first.public_update_text : null,
        reason: form.reason,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment', String(shipment.id)] });
      queryClient.invalidateQueries({ queryKey: ['shipment-events', String(shipment.id)] });
      queryClient.invalidateQueries({ queryKey: revisionsKey(shipment.id) });
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
      onDone();
    },
  });

  function togglePackage(id, checked) {
    const value = String(id);
    set({
      package_ids: checked
        ? [...form.package_ids, value]
        : form.package_ids.filter((item) => item !== value),
    });
  }

  const currentSentence =
    first.public_update_text ||
    renderTemplate(first.public_update_template_key, locale) ||
    first.public_update_template_text;

  return (
    <form
      className="event-edit"
      aria-label={t('shipmentDetail.eventEdit.title')}
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      {published ? (
        <Banner tone="warning" title={t('shipmentDetail.eventEdit.title')}>
          {t('shipmentDetail.eventEdit.publishedWarning')}
        </Banner>
      ) : (
        <Banner tone="neutral" title={t('shipmentDetail.eventEdit.title')}>
          {t('shipmentDetail.eventEdit.internalNote')}
        </Banner>
      )}
      {mutation.error && (
        <Banner tone="danger" title={t('states.saveError')}>
          {mutation.error.message}
        </Banner>
      )}
      <div className="form-grid">
        <Field label={t('shipmentDetail.eventType')}>
          {(props) => (
            <Select
              {...props}
              value={form.event_type}
              onChange={(event) => set({ event_type: event.target.value, wording: KEEP })}
              options={eventTypes.map((value) => ({
                value,
                label: t(`eventType.${value}`, value),
              }))}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.occurredAt')}>
          {(props) => (
            <TextInput
              {...props}
              type="datetime-local"
              value={form.occurred_at}
              onChange={(event) => set({ occurred_at: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.tabLegs')} hint={t('common.optional')}>
          {(props) => (
            <Select
              {...props}
              value={form.leg_id}
              placeholder="—"
              onChange={(event) => set({ leg_id: event.target.value })}
              options={legs.map((leg) => ({
                value: leg.id,
                label: `${leg.leg_type_label}${leg.provider_name ? ` — ${leg.provider_name}` : ''}`,
              }))}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.location')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={form.location_label}
              onChange={(event) => set({ location_label: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.country')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              maxLength={40}
              value={form.location_country_code}
              onChange={(event) => set({ location_country_code: event.target.value })}
            />
          )}
        </Field>
      </div>

      {selectable.length > 0 && (
        <fieldset className="event-edit__packages">
          <legend>{t('shipmentDetail.eventEdit.packages')}</legend>
          <p className="meta">{t('shipmentDetail.eventEdit.packagesHint')}</p>
          {selectable.map((item) => (
            <Checkbox
              key={item.id}
              label={`${item.package_reference} — ${item.position_label}`}
              checked={form.package_ids.includes(String(item.id))}
              onChange={(event) => togglePackage(item.id, event.target.checked)}
            />
          ))}
        </fieldset>
      )}

      <Field label={t('shipmentDetail.internalDetail')} hint={t('shipmentDetail.internalOnly')}>
        {(props) => (
          <TextArea
            {...props}
            rows={2}
            value={form.internal_detail}
            onChange={(event) => set({ internal_detail: event.target.value })}
          />
        )}
      </Field>

      {published && (
        <div className="public-update">
          <Field label={t('shipmentDetail.eventEdit.wording')}>
            {(props) => (
              <Select
                {...props}
                value={wording}
                onChange={(event) => set({ wording: event.target.value })}
                options={[
                  ...(canKeep
                    ? [{ value: KEEP, label: t('shipmentDetail.eventEdit.keepWording') }]
                    : []),
                  ...offered.map((key) => ({ value: key, label: renderTemplate(key, locale) ?? key })),
                ]}
              />
            )}
          </Field>
          {wording === KEEP ? (
            <p className="op-timeline__public">{currentSentence}</p>
          ) : (
            wording && (
              <div className="public-update__preview">
                <p className="public-update__preview-title">
                  {t('shipmentDetail.publicUpdatePreview')}
                </p>
                <p lang="en">
                  <span className="public-update__lang">EN</span>
                  {renderTemplate(wording, 'en')}
                </p>
                <p lang="vi">
                  <span className="public-update__lang">VI</span>
                  {renderTemplate(wording, 'vi')}
                </p>
              </div>
            )
          )}
          {first.public_update_text && (
            <p className="meta">{t('shipmentDetail.eventEdit.ownWordingLocked')}</p>
          )}
        </div>
      )}

      <Field
        label={t('shipmentDetail.eventEdit.reason')}
        hint={t('shipmentDetail.eventEdit.reasonHint')}
        required
      >
        {(props) => (
          <TextArea
            {...props}
            rows={2}
            maxLength={255}
            value={form.reason}
            onChange={(event) => set({ reason: event.target.value })}
          />
        )}
      </Field>

      <div className="row-wrap">
        <Button
          type="submit"
          variant="primary"
          loading={mutation.isPending}
          disabled={!form.reason.trim() || mutation.isPending}
        >
          {t('shipmentDetail.eventEdit.save')}
        </Button>
        <Button onClick={onDone}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

/** Every edit of this shipment's timeline, newest first. Read by anyone who reads shipments. */
export function EventRevisionHistory({ shipment }) {
  const t = useT();
  const query = useQuery({
    queryKey: revisionsKey(shipment.id),
    queryFn: () => shipmentsApi.eventRevisions(shipment.id),
  });
  const items = revisionList(query.data);
  if (!items.length) return null;
  return (
    <details className="event-history">
      <summary>{t('shipmentDetail.eventEdit.historyTitle')}</summary>
      <ul className="event-history__list">
        {items.map((item) => {
          const changed = Object.keys(item.after).filter(
            (key) => JSON.stringify(item.after[key]) !== JSON.stringify(item.before[key]),
          );
          return (
            <li key={item.id}>
              <div className="meta">
                {formatDateTime(item.edited_at)}
                {item.edited_by ? ` · ${item.edited_by.full_name}` : ''}
                {' · '}
                {t(`eventType.${item.before.event_type}`, item.before.event_type)}
                {item.after.event_type !== item.before.event_type
                  ? ` → ${t(`eventType.${item.after.event_type}`, item.after.event_type)}`
                  : ''}
              </div>
              <div>
                {interpolate(t('shipmentDetail.eventEdit.historyChanged'), {
                  fields: changed
                    .map((key) => t(`shipmentDetail.eventEdit.field.${key}`, key))
                    .join(', '),
                })}
              </div>
              {item.public_wording_changed && (
                <div className="meta">{t('shipmentDetail.eventEdit.historyWordingChanged')}</div>
              )}
              <div className="meta">{item.reason}</div>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

/** The ids of every event row an edit has touched, for the "Edited" mark on the timeline. */
export function useEditedEventIds(shipmentId) {
  const query = useQuery({
    queryKey: revisionsKey(shipmentId),
    queryFn: () => shipmentsApi.eventRevisions(shipmentId),
  });
  return useMemo(
    () => new Set(revisionList(query.data).flatMap((item) => item.event_ids_after)),
    [query.data],
  );
}
