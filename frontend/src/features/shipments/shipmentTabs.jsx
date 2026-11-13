/**
 * Shipment detail tab panels (Design.md section 9).
 *
 * Each panel is permission-aware for *display*; the server enforces every rule again.
 * The financial panel is absent rather than empty when the API omits the block, so a
 * missing cost never reads as zero.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { opsApi, shipmentsApi } from '../../api/endpoints.js';
import { useI18n, useT } from '../../i18n/index.jsx';
import {
  publishesByDefault,
  renderTemplate,
  templatesFor,
} from '../../shared/publicUpdateTemplates.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import {
  Banner,
  Button,
  Card,
  Checkbox,
  CopyableId,
  Field,
  Modal,
  Select,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDate, formatDateTime } from '../../utils/format.js';
import {
  LegStatusBadge,
  OperationalBadge,
  PaymentStateBadge,
  SourceModeBadge,
  dimensionSummary,
  trimDecimal,
  weightSummary,
} from './shipmentTokens.jsx';
import { EventEditForm, EventRevisionHistory, useEditedEventIds } from './EventEditForm.jsx';
import './shipments.css';

function Detail({ label, children }) {
  return (
    <div className="detail-row">
      <span className="detail-row__label">{label}</span>
      <span className="detail-row__value">{children ?? '—'}</span>
    </div>
  );
}

function AddressBlock({ title, snapshot, note }) {
  const t = useT();
  const lines = [
    snapshot.company,
    snapshot.address_line1,
    snapshot.address_line2,
    [snapshot.city, snapshot.province_state, snapshot.postal_code].filter(Boolean).join(', '),
    snapshot.country_input || snapshot.country_code,
  ].filter(Boolean);

  return (
    <Card title={title}>
      <p className="address-block__name">{snapshot.name || '—'}</p>
      {lines.map((line) => (
        <p key={line} className="address-block__line">
          {line}
        </p>
      ))}
      <p className="meta">
        {[snapshot.phone_entered, snapshot.email].filter(Boolean).join(' · ') || '—'}
      </p>
      {snapshot.delivery_note && <p className="meta">{snapshot.delivery_note}</p>}
      {note && <p className="meta address-block__note">{t('shipmentDetail.snapshotNote')}</p>}
    </Card>
  );
}

/* --- Tracking tab ------------------------------------------------------- */

/**
 * Recording one shipment-wide milestone writes a row per active package, because
 * per-package state is what "1 of 3 delivered" is derived from. Showing three identical
 * rows would bury the timeline, so identical entries are displayed as one with every
 * affected package reference listed.
 */
function groupEvents(events) {
  const groups = [];
  const index = new Map();
  for (const event of events) {
    const key = [
      event.event_type,
      event.occurred_at,
      event.recorded_at,
      event.location_label ?? '',
      event.public_update_text ?? '',
      event.internal_detail ?? '',
      event.is_voided,
    ].join('|');
    const existing = index.get(key);
    if (existing) {
      if (event.package_reference) existing.references.push(event.package_reference);
      existing.ids.push(event.id);
      continue;
    }
    const group = {
      ...event,
      references: event.package_reference ? [event.package_reference] : [],
      ids: [event.id],
    };
    index.set(key, group);
    groups.push(group);
  }
  return groups;
}


export const EVENT_TYPES = [
  'received_at_solaris',
  'processing',
  'departed_origin',
  'in_transit',
  'customs_processing',
  'arrived_destination',
  'out_for_delivery',
  'delivered_to_collection_point',
  'delivered_to_recipient',
  'delivery_attempted',
  'exception',
  'return_in_progress',
  'returned',
  'awaiting_parcel',
];

/**
 * The form's opening state for an event type.
 *
 * Publishing is the norm, so the box starts ticked and the first approved template is
 * already selected: recording a milestone and telling the customer about it is one action,
 * not two, and staying silent is now the deliberate choice (DEC-0083). The exception states
 * start unticked -- canned wording about a problem nobody has diagnosed yet is worse than
 * no wording.
 */
export function publicDefaults(eventType) {
  const isPublic = publishesByDefault(eventType);
  const [firstTemplate] = templatesFor(eventType);
  return {
    is_public_update: isPublic,
    public_update_template_key: isPublic && firstTemplate ? firstTemplate : '',
    public_update_text: '',
  };
}

const INITIAL_EVENT_TYPE = 'in_transit';

function EventForm({ shipment, packages, legs, onDone }) {
  const t = useT();
  const { locale } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    event_type: INITIAL_EVENT_TYPE,
    occurred_at: '',
    package_id: '',
    leg_id: '',
    location_label: '',
    location_country_code: '',
    internal_detail: '',
    ...publicDefaults(INITIAL_EVENT_TYPE),
  });

  const mutation = useMutation({
    mutationFn: () =>
      shipmentsApi.recordEvent(shipment.id, {
        event_type: form.event_type,
        occurred_at: form.occurred_at ? new Date(form.occurred_at).toISOString() : undefined,
        package_id: form.package_id ? Number(form.package_id) : undefined,
        leg_id: form.leg_id ? Number(form.leg_id) : undefined,
        location_label: form.location_label || undefined,
        location_country_code: form.location_country_code || undefined,
        internal_detail: form.internal_detail || undefined,
        is_public_update: form.is_public_update,
        // A milestone carries an approved template key or a typed sentence, never both.
        // The server enforces the same rule; sending both would just earn a 422.
        public_update_template_key:
          form.is_public_update && form.public_update_template_key
            ? form.public_update_template_key
            : undefined,
        public_update_text:
          form.is_public_update && !form.public_update_template_key
            ? form.public_update_text
            : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment', String(shipment.id)] });
      queryClient.invalidateQueries({ queryKey: ['shipment-events', String(shipment.id)] });
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
      onDone();
    },
  });

  function set(patch) {
    setForm((current) => ({ ...current, ...patch }));
  }

  // The form opens in place of the button that revealed it, so focus would otherwise be
  // left on nothing. Move it to the first field (UAT round 3, keyboard).
  const formRef = useRef(null);
  useEffect(() => {
    formRef.current?.querySelector('select, input, textarea')?.focus();
  }, []);

  return (
    <form
      ref={formRef}
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      {mutation.error && (
        <Banner tone="danger" title={t('states.saveError')}>
          {mutation.error.message}
        </Banner>
      )}
      <div className="form-grid">
        <Field label={t('shipmentDetail.eventType')} required>
          {(props) => (
            <Select
              {...props}
              value={form.event_type}
              onChange={(event) =>
                set({ event_type: event.target.value, ...publicDefaults(event.target.value) })
              }
              options={EVENT_TYPES.map((value) => ({
                value,
                label: t(`eventType.${value}`, value),
              }))}
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
        <Field label={t('shipmentDetail.forPackage')}>
          {(props) => (
            <Select
              {...props}
              value={form.package_id}
              placeholder={t('shipmentDetail.allActivePackages')}
              onChange={(event) => set({ package_id: event.target.value })}
              options={packages
                .filter((item) => item.is_active)
                .map((item) => ({
                  value: item.id,
                  label: `${item.package_reference} — ${item.position_label}`,
                }))}
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

      <Checkbox
        label={t('shipmentDetail.publicUpdate')}
        hint={t('shipmentDetail.publicUpdateHint')}
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
                    // Switching to a standard update discards a half-typed sentence rather
                    // than keeping it around to be sent by accident. The two are exclusive.
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
            /* What the customer actually reads, in both languages, before it is sent.
               The point of a template is that the staff member does not have to trust a
               translation they cannot check -- so show them both. */
            <div className="public-update__preview">
              <p className="public-update__preview-title">
                {t('shipmentDetail.publicUpdatePreview')}
              </p>
              <p lang="en">
                <span className="public-update__lang">EN</span>
                {renderTemplate(form.public_update_template_key, 'en')}
              </p>
              <p lang="vi">
                <span className="public-update__lang">VI</span>
                {renderTemplate(form.public_update_template_key, 'vi')}
              </p>
              <p className="public-update__note">{t('shipmentDetail.publicUpdateLanguageNote')}</p>
            </div>
          ) : (
            <Field
              label={t('shipmentDetail.publicUpdateText')}
              hint={t('shipmentDetail.publicUpdateTextHint')}
              required
            >
              {(props) => (
                <TextArea
                  {...props}
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
        <Button type="submit" variant="primary" loading={mutation.isPending}>
          {t('shipmentDetail.addEvent')}
        </Button>
        <Button onClick={onDone}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

export function TrackingTab({ shipment, packages, legs, onPrint }) {
  const t = useT();
  const { locale } = useI18n();
  const { can } = useSession();
  const [adding, setAdding] = useState(false);
  // RC-UAT-25 item 6: the event being corrected, by its rows' ids.
  const [editing, setEditing] = useState(null);
  const editedIds = useEditedEventIds(shipment.id);

  const eventsQuery = useQuery({
    queryKey: ['shipment-events', String(shipment.id)],
    queryFn: () => shipmentsApi.events(shipment.id),
  });

  const events = groupEvents(eventsQuery.data ?? []);
  // A cancelled booking takes no new events -- the server refuses them -- so the action
  // is hidden, as Cancel and Rebook are, with a line saying why (UAT round 3).
  const isCancelled = shipment.booking_state === 'cancelled';

  return (
    <div className="detail-grid">
      <div>
        <Card
          title={t('shipmentDetail.timeline')}
          actions={
            can(P.TRACKING_WRITE) &&
            !isCancelled &&
            !adding && <Button onClick={() => setAdding(true)}>{t('shipmentDetail.addEvent')}</Button>
          }
        >
          {can(P.TRACKING_WRITE) && isCancelled && (
            <p className="meta">{t('shipmentDetail.eventsClosedCancelled')}</p>
          )}
          {adding && !isCancelled && (
            <EventForm
              shipment={shipment}
              packages={packages}
              legs={legs}
              onDone={() => setAdding(false)}
            />
          )}

          {eventsQuery.isLoading && <SkeletonRows rows={4} height={44} />}
          {eventsQuery.error && <ErrorState error={eventsQuery.error} />}

          {!eventsQuery.isLoading && events.length === 0 && !adding && (
            <EmptyState
              title={t('shipmentDetail.noEvents')}
              // No invitation to record a milestone on a booking that cannot take one
              // (UAT round 4); the line above already says why.
              body={isCancelled ? undefined : t('shipmentDetail.noEventsBody')}
            />
          )}

          {events.length > 0 && (
            <ol className="op-timeline">
              {events.map((event) => (
                <li
                  key={event.ids.join('-')}
                  className={event.is_voided ? 'op-timeline__item is-voided' : 'op-timeline__item'}
                >
                  <div className="op-timeline__marker" aria-hidden="true" />
                  <div className="op-timeline__body">
                    <div className="row-wrap">
                      <strong>{t(`eventType.${event.event_type}`, event.event_type_label)}</strong>
                      {event.is_public_update && (
                        <span className="chip chip--public">{t('shipmentDetail.publicBadge')}</span>
                      )}
                      {event.is_voided && (
                        <span className="chip">{t('shipmentDetail.voided')}</span>
                      )}
                      {event.ids.some((id) => editedIds.has(id)) && (
                        <span className="chip">{t('shipmentDetail.eventEdit.edited')}</span>
                      )}
                      {can(P.TRACKING_WRITE) &&
                        !isCancelled &&
                        !event.is_voided &&
                        event.source === 'manual' &&
                        editing === null && (
                          <Button
                            compact
                            aria-label={`${t('shipmentDetail.eventEdit.action')}: ${t(`eventType.${event.event_type}`, event.event_type_label)}`}
                            onClick={() => setEditing(event.ids.join('-'))}
                          >
                            {t('shipmentDetail.eventEdit.action')}
                          </Button>
                        )}
                    </div>
                    {editing === event.ids.join('-') && (
                      <EventEditForm
                        shipment={shipment}
                        packages={packages}
                        legs={legs}
                        rows={(eventsQuery.data ?? []).filter((row) => event.ids.includes(row.id))}
                        eventTypes={EVENT_TYPES}
                        onDone={() => setEditing(null)}
                      />
                    )}
                    <div className="meta">
                      {formatDateTime(event.occurred_at)}
                      {event.location_label ? ` · ${event.location_label}` : ''}
                    </div>
                    {event.references.length > 0 && (
                      <div className="meta mono">
                        {event.references.length === packages.filter((item) => item.is_active).length
                          ? t('shipmentDetail.allActivePackages')
                          : event.references.join(', ')}
                      </div>
                    )}
                    <div className="meta">
                      {t('shipmentDetail.recordedAt')} {formatDateTime(event.recorded_at)}
                      {event.recorded_by ? ` · ${event.recorded_by.full_name}` : ''}
                    </div>
                    {(event.public_update_text || event.public_update_template_key) && (
                      <p className="op-timeline__public">
                        {/* A standard update is rendered in the staff member's own language
                            here; the customer sees the same milestone in theirs. */}
                        {event.public_update_text ||
                          renderTemplate(event.public_update_template_key, locale) ||
                          event.public_update_template_text}
                        {event.public_update_template_key && (
                          <span className="chip chip--template">
                            {t('shipmentDetail.publicUpdateStandard')}
                          </span>
                        )}
                      </p>
                    )}
                    {event.internal_detail && (
                      <p className="op-timeline__internal">
                        <span className="chip">{t('shipmentDetail.internalOnly')}</span>{' '}
                        {event.internal_detail}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
          <EventRevisionHistory shipment={shipment} />
        </Card>
      </div>

      <div>
        <Card title={t('shipmentDetail.packagesTitle')}>
          <ul className="package-summary">
            {packages.map((item) => (
              <li key={item.id} className={item.is_active ? '' : 'is-cancelled'}>
                <span className="mono">{item.package_reference || '—'}</span>
                <span className="meta">{item.position_label}</span>
                <OperationalBadge value={item.operational_state} />
              </li>
            ))}
          </ul>
          {can(P.LABEL_GENERATE) && shipment.public_id && (
            <Button variant="primary" onClick={onPrint}>
              {t('labels.open')}
            </Button>
          )}
        </Card>

        <Card title={t('shipmentDetail.trackingReferences')}>
          <Banner tone="neutral">{t('shipmentDetail.noProviderNote')}</Banner>
          {legs.flatMap((leg) => leg.tracking_references).length === 0 && (
            <p className="meta">{t('shipments.noCarrier')}</p>
          )}
          <ul className="reference-list">
            {legs.flatMap((leg) =>
              leg.tracking_references.map((reference) => (
                <li key={reference.id} className={reference.is_active ? '' : 'is-retired'}>
                  <span>{reference.carrier_name}</span>
                  <span className="mono">{reference.tracking_number}</span>
                  <SourceModeBadge
                    value={reference.source_mode}
                    label={reference.source_mode_label}
                  />
                  {!reference.is_active && (
                    <span className="chip">{t('shipmentDetail.retired')}</span>
                  )}
                </li>
              )),
            )}
          </ul>
        </Card>
      </div>
    </div>
  );
}

/* --- Details tab -------------------------------------------------------- */

export function DetailsTab({ shipment }) {
  const t = useT();
  return (
    <>
      <div className="detail-grid">
        <Card title={t('shipmentDetail.tabDetails')}>
          <Detail label={t('shipments.columnCustomer')}>
            {shipment.customer ? `${shipment.customer.full_name} (${shipment.customer.public_id})` : '—'}
          </Detail>
          <Detail label={t('shipmentDetail.bookingState')}>
            {t(`bookingState.${shipment.booking_state}`, shipment.booking_state)}
          </Detail>
          <Detail label={t('shipments.columnStatus')}>
            <OperationalBadge value={shipment.operational_state} />
          </Detail>
          <Detail label={t('shipmentDetail.paymentState')}>
            <PaymentStateBadge value={shipment.payment_state} />
          </Detail>
          <Detail label={t('booking.routeGroup')}>{shipment.route_label}</Detail>
          <Detail label={t('booking.direction')}>{shipment.direction_label}</Detail>
          <Detail label={t('booking.serviceType')}>
            {t(`serviceType.${shipment.service_type}`, shipment.service_type)}
          </Detail>
          <Detail label={t('booking.transportMode')}>
            {t(`transportMode.${shipment.transport_mode}`, shipment.transport_mode)}
          </Detail>
          <Detail label={t('booking.bookingReference')}>{shipment.booking_reference}</Detail>
          <Detail label={t('shipmentDetail.contents')}>{shipment.contents_description}</Detail>
          <Detail label={t('shipmentDetail.booked')}>{formatDate(shipment.booking_date)}</Detail>
          <Detail label={t('shipmentDetail.confirmed')}>
            {formatDateTime(shipment.confirmed_at)}
          </Detail>
          <Detail label={t('shipmentDetail.firstHandoff')}>
            {formatDateTime(shipment.first_handoff_at)}
          </Detail>
          <Detail label={t('shipmentDetail.estimatedDelivery')}>
            {formatDate(shipment.estimated_delivery_at)}
          </Detail>
          <Detail label={t('shipmentDetail.delivered')}>
            {formatDateTime(shipment.delivered_at)}
          </Detail>
          {shipment.cancellation_reason && (
            <Detail label={t('shipmentDetail.cancelledReason')}>
              {shipment.cancellation_reason}
            </Detail>
          )}
          {shipment.rebooked_from_public_id && (
            <Detail label={t('shipmentDetail.rebookedFrom')}>
              <span className="mono">{shipment.rebooked_from_public_id}</span>
            </Detail>
          )}
          {shipment.rebooked_to_public_id && (
            <Detail label={t('shipmentDetail.rebookedTo')}>
              <span className="mono">{shipment.rebooked_to_public_id}</span>
            </Detail>
          )}
        </Card>
        <div>
          <AddressBlock
            title={t('shipmentDetail.senderSnapshot')}
            snapshot={shipment.sender}
            note
          />
          <AddressBlock
            title={t('shipmentDetail.recipientSnapshot')}
            snapshot={shipment.recipient}
            note
          />
        </div>
      </div>
    </>
  );
}

/* --- Packages tab ------------------------------------------------------- */

export function PackagesTab({ shipment, packages, onPrint }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [cancelling, setCancelling] = useState(null);
  const [reason, setReason] = useState('');

  const cancelMutation = useMutation({
    mutationFn: () => shipmentsApi.cancelPackage(cancelling.id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment', String(shipment.id)] });
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
      setCancelling(null);
      setReason('');
    },
  });

  return (
    <Card
      title={t('shipmentDetail.packagesTitle')}
      actions={
        can(P.LABEL_GENERATE) &&
        shipment.public_id && <Button onClick={onPrint}>{t('labels.open')}</Button>
      }
    >
      <div className="table-wrap">
        <table className="table table--stacked">
          <thead>
            <tr>
              <th scope="col">{t('booking.packageReferences')}</th>
              <th scope="col">{t('shipmentDetail.dimensions')}</th>
              <th scope="col">{t('shipmentDetail.grossWeight')}</th>
              <th scope="col">{t('booking.packageContents')}</th>
              <th scope="col">{t('booking.warehouseLocation')}</th>
              <th scope="col">{t('shipments.columnStatus')}</th>
              <th scope="col">
                <span className="visually-hidden">{t('common.edit')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {packages.map((item) => (
              <tr key={item.id} className={item.is_active ? '' : 'is-cancelled'}>
                <td data-label={t('booking.packageReferences')}>
                  <CopyableId value={item.package_reference} />
                  <div className="meta">{item.position_label}</div>
                </td>
                <td data-label={t('shipmentDetail.dimensions')}>
                  {dimensionSummary(item) || t('common.notRecorded')}
                  {item.length_cm && (
                    <div className="meta">
                      {trimDecimal(item.length_cm)} × {trimDecimal(item.width_cm)} ×{' '}
                      {trimDecimal(item.height_cm)} cm {t('shipmentDetail.canonical')}
                    </div>
                  )}
                </td>
                <td data-label={t('shipmentDetail.grossWeight')}>
                  {weightSummary(item) || t('common.notRecorded')}
                </td>
                <td data-label={t('booking.packageContents')}>
                  {item.contents_summary || '—'}
                  {item.handling_note && <div className="meta">{item.handling_note}</div>}
                </td>
                <td data-label={t('booking.warehouseLocation')}>
                  {item.warehouse_location || '—'}
                </td>
                <td data-label={t('shipments.columnStatus')}>
                  <OperationalBadge value={item.operational_state} />
                  {!item.is_active && (
                    <div className="meta">{item.cancellation_reason}</div>
                  )}
                </td>
                <td>
                  {item.is_active && can(P.SHIPMENT_WRITE) && (
                    <Button compact variant="tertiary" onClick={() => setCancelling(item)}>
                      {t('shipmentDetail.cancelPackage')}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal
        open={Boolean(cancelling)}
        onClose={() => setCancelling(null)}
        title={t('shipmentDetail.cancelPackage')}
        footer={
          <>
            <Button onClick={() => setCancelling(null)}>{t('common.cancel')}</Button>
            <span className="spacer" />
            <Button
              variant="primary"
              disabled={!reason.trim()}
              loading={cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
            >
              {t('shipmentDetail.cancelPackage')}
            </Button>
          </>
        }
      >
        {cancelMutation.error && (
          <Banner tone="danger">{cancelMutation.error.message}</Banner>
        )}
        <p>
          <span className="mono">{cancelling?.package_reference}</span> —{' '}
          {t('shipmentDetail.referenceRetained')}
        </p>
        <Field label={t('shipmentDetail.cancelPackageReason')} required>
          {(props) => (
            <TextInput
              {...props}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
      </Modal>
    </Card>
  );
}

/* --- Transport legs tab -------------------------------------------------- */

function LegForm({ shipment, packages, onDone }) {
  const t = useT();
  const queryClient = useQueryClient();
  const metaQuery = useQuery({ queryKey: ['shipment-meta'], queryFn: shipmentsApi.meta });
  const [form, setForm] = useState({
    leg_type: 'origin_pickup',
    provider_name: '',
    service_display: '',
    origin_label: '',
    destination_label: '',
    destination_country_code: '',
    consolidation_reference: '',
    is_final_recipient_delivery: false,
    package_ids: packages.filter((item) => item.is_active).map((item) => item.id),
  });

  const mutation = useMutation({
    mutationFn: () => shipmentsApi.createLeg(shipment.id, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment-legs', String(shipment.id)] });
      onDone();
    },
  });

  function set(patch) {
    setForm((current) => ({ ...current, ...patch }));
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      {mutation.error && <Banner tone="danger">{mutation.error.message}</Banner>}
      <div className="form-grid">
        <Field label={t('shipmentDetail.legType')} required>
          {(props) => (
            <Select
              {...props}
              value={form.leg_type}
              onChange={(event) => set({ leg_type: event.target.value })}
              options={(metaQuery.data?.leg_types ?? []).map((item) => ({
                value: item.value,
                label: t(`legType.${item.value}`, item.label),
              }))}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.provider')}>
          {(props) => (
            <Select
              {...props}
              value={form.provider_name}
              placeholder="—"
              onChange={(event) => set({ provider_name: event.target.value })}
              // The providers offered for this leg type; the vendor is on every leg,
              // final delivery included (RC-20).
              options={(
                metaQuery.data?.leg_providers?.[form.leg_type] ??
                metaQuery.data?.carriers ??
                []
              ).map((name) => ({
                value: name,
                label: name,
              }))}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.service')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={form.service_display}
              onChange={(event) => set({ service_display: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.legOrigin')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={form.origin_label}
              onChange={(event) => set({ origin_label: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.legDestination')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={form.destination_label}
              onChange={(event) => set({ destination_label: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.consolidationReference')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={form.consolidation_reference}
              onChange={(event) => set({ consolidation_reference: event.target.value })}
            />
          )}
        </Field>
      </div>
      <Checkbox
        label={t('shipmentDetail.finalDelivery')}
        checked={form.is_final_recipient_delivery}
        onChange={(event) => set({ is_final_recipient_delivery: event.target.checked })}
      />
      <div className="row-wrap">
        <Button type="submit" variant="primary" loading={mutation.isPending}>
          {t('shipmentDetail.addLeg')}
        </Button>
        <Button onClick={onDone}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

/** The form's own wording for each field the server can refuse (UAT round 3). */
const REFERENCE_FIELD_MESSAGES = {
  carrier_name: 'shipmentDetail.carrierRequired',
  tracking_number: 'shipmentDetail.trackingNumberRequired',
  public_url: 'shipmentDetail.publicUrlInvalid',
};

/**
 * Field errors for the carrier-reference form, from the form's own check or the server.
 *
 * A blank carrier used to surface pydantic's "String should have at least 1 character".
 * A request-validation 422 is now mapped to the form's wording beside the field; a domain
 * error with a field keeps its message, which the service already writes for a person.
 */
function referenceErrors(form, error, t) {
  const fields = {};
  if (form) {
    if (!form.carrier_name.trim()) fields.carrier_name = t(REFERENCE_FIELD_MESSAGES.carrier_name);
    if (!form.tracking_number.trim()) {
      fields.tracking_number = t(REFERENCE_FIELD_MESSAGES.tracking_number);
    }
  }
  let general = null;
  if (error) {
    const invalid = error.invalidFields ?? [];
    if (invalid.length > 0) {
      invalid.forEach((name) => {
        if (REFERENCE_FIELD_MESSAGES[name]) fields[name] = t(REFERENCE_FIELD_MESSAGES[name]);
      });
      // Never pydantic's own sentence; a field the form does not show gets a plain summary.
      if (invalid.some((name) => !REFERENCE_FIELD_MESSAGES[name])) {
        general = t('shipmentDetail.referenceNotSaved');
      }
    } else if (error.field && REFERENCE_FIELD_MESSAGES[error.field]) {
      fields[error.field] = error.message;
    } else {
      general = error.message;
    }
  }
  return { fields, general };
}

function TrackingReferenceForm({ leg, packages, onDone }) {
  const t = useT();
  const queryClient = useQueryClient();
  const metaQuery = useQuery({ queryKey: ['shipment-meta'], queryFn: shipmentsApi.meta });
  const [form, setForm] = useState({
    carrier_name: '',
    tracking_number: '',
    public_url: '',
    source_mode: 'manual',
    package_id: '',
  });
  // The form's own check runs on submit, so an untouched form is not already red.
  const [checked, setChecked] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      shipmentsApi.addTrackingReference(leg.id, {
        carrier_name: form.carrier_name,
        tracking_number: form.tracking_number,
        public_url: form.public_url || undefined,
        source_mode: form.source_mode,
        package_id: form.package_id ? Number(form.package_id) : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment-legs', String(leg.shipment_id)] });
      onDone();
    },
  });

  const errors = referenceErrors(checked ? form : null, mutation.error, t);

  function update(patch) {
    // Editing a field withdraws the server's verdict on it; the form's own check re-runs.
    if (mutation.error) mutation.reset();
    setForm((current) => ({ ...current, ...patch }));
  }

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setChecked(true);
        if (Object.keys(referenceErrors(form, null, t).fields).length > 0) return;
        mutation.mutate();
      }}
    >
      {errors.general && <Banner tone="danger">{errors.general}</Banner>}
      <div className="form-grid">
        <Field label={t('shipmentDetail.carrier')} required error={errors.fields.carrier_name}>
          {(props) => (
            <Select
              {...props}
              value={form.carrier_name}
              placeholder="—"
              onChange={(event) => update({ carrier_name: event.target.value })}
              options={(metaQuery.data?.carriers ?? []).map((name) => ({
                value: name,
                label: name,
              }))}
            />
          )}
        </Field>
        <Field
          label={t('shipmentDetail.trackingNumber')}
          required
          error={errors.fields.tracking_number}
        >
          {(props) => (
            <TextInput
              {...props}
              maxLength={120}
              value={form.tracking_number}
              onChange={(event) => update({ tracking_number: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.sourceMode')}>
          {(props) => (
            <Select
              {...props}
              value={form.source_mode}
              onChange={(event) => update({ source_mode: event.target.value })}
              options={[
                { value: 'manual', label: t('sourceMode.manual') },
                { value: 'external_link', label: t('sourceMode.external_link') },
              ]}
            />
          )}
        </Field>
        <Field
          label={t('shipmentDetail.publicUrl')}
          hint={t('common.optional')}
          error={errors.fields.public_url}
        >
          {(props) => (
            <TextInput
              {...props}
              type="url"
              maxLength={500}
              value={form.public_url}
              onChange={(event) => update({ public_url: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('shipmentDetail.forPackage')} hint={t('common.optional')}>
          {(props) => (
            <Select
              {...props}
              value={form.package_id}
              placeholder={t('shipmentDetail.allActivePackages')}
              onChange={(event) => update({ package_id: event.target.value })}
              options={packages
                .filter((item) => item.is_active)
                .map((item) => ({ value: item.id, label: item.package_reference }))}
            />
          )}
        </Field>
      </div>
      <div className="row-wrap">
        <Button type="submit" variant="primary" loading={mutation.isPending}>
          {t('shipmentDetail.addTrackingReference')}
        </Button>
        <Button onClick={onDone}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

/** Legs customers read as "Master Tracking"; every other leg is "Last Mile Tracking". */
const MASTER_TRACKING_LEG_TYPES = new Set(['origin_pickup', 'consolidation_linehaul']);

/** The leg's generic tracking-name key: the server's, else the same rule (DEC-0224). */
function legTrackingNameKey(leg) {
  if (leg.tracking_name_key === 'master_tracking' || leg.tracking_name_key === 'last_mile_tracking') {
    return leg.tracking_name_key;
  }
  return MASTER_TRACKING_LEG_TYPES.has(leg.leg_type) ? 'master_tracking' : 'last_mile_tracking';
}

export function LegsTab({ shipment, packages, legs, isLoading }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [addingLeg, setAddingLeg] = useState(false);
  const [addingReferenceFor, setAddingReferenceFor] = useState(null);
  const [retiring, setRetiring] = useState(null);
  const [reason, setReason] = useState('');

  const retireMutation = useMutation({
    mutationFn: () => shipmentsApi.retireTrackingReference(retiring.id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment-legs', String(shipment.id)] });
      setRetiring(null);
      setReason('');
    },
  });

  return (
    <>
      <Banner tone="neutral">{t('shipmentDetail.noProviderNote')}</Banner>

      <Card
        title={t('shipmentDetail.legsTitle')}
        actions={
          can(P.TRACKING_WRITE) &&
          !addingLeg && <Button onClick={() => setAddingLeg(true)}>{t('shipmentDetail.addLeg')}</Button>
        }
      >
        {addingLeg && (
          <LegForm shipment={shipment} packages={packages} onDone={() => setAddingLeg(false)} />
        )}
        {isLoading && <SkeletonRows rows={3} height={44} />}
        {!isLoading && legs.length === 0 && !addingLeg && (
          <EmptyState title={t('shipmentDetail.noLegs')} body={t('shipmentDetail.noLegsBody')} />
        )}

        <ol className="leg-list">
          {legs.map((leg) => (
            <li key={leg.id} className="leg-list__item">
              <div className="row-wrap">
                <span className="leg-list__sequence">{leg.sequence}</span>
                <strong>{t(`legType.${leg.leg_type}`, leg.leg_type_label)}</strong>
                {/* The leg's generic tracking name, as customers read it (RC-20, DEC-0224). */}
                <span className="chip" data-testid="leg-tracking-name">
                  {t(`legTrackingName.${legTrackingNameKey(leg)}`)}
                </span>
                <LegStatusBadge value={leg.status} />
                {leg.is_final_recipient_delivery && (
                  <span className="chip chip--final">{t('shipmentDetail.finalDelivery')}</span>
                )}
              </div>
              <div className="meta">
                {[leg.provider_name, leg.service_display].filter(Boolean).join(' · ') || '—'}
              </div>
              <div className="meta">
                {[leg.origin_label, leg.destination_label].filter(Boolean).join(' → ') || '—'}
              </div>
              {leg.consolidation_reference && (
                <div className="meta">
                  {t('shipmentDetail.consolidationReference')}:{' '}
                  <span className="mono">{leg.consolidation_reference}</span>
                </div>
              )}
              {leg.package_references.length > 0 && (
                <div className="meta">
                  {t('shipmentDetail.legPackages')}:{' '}
                  <span className="mono">{leg.package_references.join(', ')}</span>
                </div>
              )}

              <ul className="reference-list">
                {leg.tracking_references.map((reference) => (
                  <li key={reference.id} className={reference.is_active ? '' : 'is-retired'}>
                    <span>{reference.carrier_name}</span>
                    <span className="mono">{reference.tracking_number}</span>
                    <SourceModeBadge
                      value={reference.source_mode}
                      label={reference.source_mode_label}
                    />
                    {reference.package_reference && (
                      <span className="meta mono">{reference.package_reference}</span>
                    )}
                    {reference.public_url && (
                      <a href={reference.public_url} target="_blank" rel="noreferrer noopener">
                        {t('shipmentDetail.publicUrl')}
                      </a>
                    )}
                    {reference.is_active ? (
                      can(P.TRACKING_WRITE) && (
                        <Button compact variant="tertiary" onClick={() => setRetiring(reference)}>
                          {t('shipmentDetail.retire')}
                        </Button>
                      )
                    ) : (
                      <span className="chip">{t('shipmentDetail.retired')}</span>
                    )}
                  </li>
                ))}
              </ul>

              {can(P.TRACKING_WRITE) &&
                (addingReferenceFor === leg.id ? (
                  <TrackingReferenceForm
                    leg={leg}
                    packages={packages}
                    onDone={() => setAddingReferenceFor(null)}
                  />
                ) : (
                  <Button compact onClick={() => setAddingReferenceFor(leg.id)}>
                    {t('shipmentDetail.addTrackingReference')}
                  </Button>
                ))}
            </li>
          ))}
        </ol>
      </Card>

      <Modal
        open={Boolean(retiring)}
        onClose={() => setRetiring(null)}
        title={t('shipmentDetail.retire')}
        footer={
          <>
            <Button onClick={() => setRetiring(null)}>{t('common.cancel')}</Button>
            <span className="spacer" />
            <Button
              variant="primary"
              disabled={!reason.trim()}
              loading={retireMutation.isPending}
              onClick={() => retireMutation.mutate()}
            >
              {t('shipmentDetail.retire')}
            </Button>
          </>
        }
      >
        {retireMutation.error && <Banner tone="danger">{retireMutation.error.message}</Banner>}
        <Field label={t('shipmentDetail.retireReason')} required>
          {(props) => (
            <TextInput
              {...props}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
      </Modal>
    </>
  );
}

/* --- Financials tab: ./FinancialsTab.jsx (RC-UAT-25 items 7 and 8) ---------- */

export { FinancialsTab } from './FinancialsTab.jsx';

/* --- Notes and audit tab -------------------------------------------------- */

export function NotesTab({ shipment }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [notes, setNotes] = useState(shipment.internal_notes ?? '');
  const [savedNotice, setSavedNotice] = useState(false);

  const mutation = useMutation({
    mutationFn: () => shipmentsApi.update(shipment.id, { internal_notes: notes }),
    onMutate: () => setSavedNotice(false),
    onSuccess: (saved) => {
      // The response is the same detail the page reads, so it replaces the cached copy
      // at once and the box shows exactly what was stored, instead of the pre-save copy
      // until a refetch lands (UAT round 3).
      if (saved) {
        queryClient.setQueryData(['shipment', String(shipment.id)], saved);
        setNotes(saved.internal_notes ?? '');
      }
      queryClient.invalidateQueries({ queryKey: ['shipment', String(shipment.id)] });
      // A visible confirmation, and the audit list below re-read so the new
      // "Internal notes updated" row appears without a reload (UAT round 4).
      setSavedNotice(true);
      queryClient.invalidateQueries({ queryKey: ['shipment-audit', String(shipment.id)] });
    },
  });

  const auditQuery = useQuery({
    queryKey: ['shipment-audit', String(shipment.id)],
    queryFn: () => opsApi.audit({ entity_type: 'shipment', entity_id: shipment.id, limit: 50 }),
    enabled: can(P.AUDIT_READ),
  });

  return (
    <>
      <Card title={t('shipmentDetail.notesTitle')}>
        <Banner tone="neutral">{t('shipmentDetail.notesHint')}</Banner>
        {savedNotice && <Banner tone="success">{t('shipmentDetail.notesSaved')}</Banner>}
        {mutation.error && <Banner tone="danger">{mutation.error.message}</Banner>}
        <Field label={t('shipmentDetail.notesTitle')}>
          {(props) => (
            <TextArea
              {...props}
              rows={5}
              value={notes}
              disabled={!can(P.SHIPMENT_WRITE)}
              onChange={(event) => {
                setNotes(event.target.value);
                setSavedNotice(false);
              }}
            />
          )}
        </Field>
        {can(P.SHIPMENT_WRITE) && (
          <Button variant="primary" loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {t('common.save')}
          </Button>
        )}
      </Card>

      <Card title={t('shipmentDetail.auditTitle')}>
        {!can(P.AUDIT_READ) && <p className="meta">{t('shipmentDetail.auditHidden')}</p>}
        {can(P.AUDIT_READ) && auditQuery.isLoading && <SkeletonRows rows={4} height={40} />}
        {can(P.AUDIT_READ) && (auditQuery.data?.items ?? []).length === 0 && !auditQuery.isLoading && (
          <EmptyState title={t('states.emptyTitle')} />
        )}
        {can(P.AUDIT_READ) && (auditQuery.data?.items ?? []).length > 0 && (
          <ul className="audit-list">
            {auditQuery.data.items.map((entry) => (
              <li key={entry.id}>
                <span>{entry.summary}</span>
                <span className="meta">
                  {formatDateTime(entry.occurred_at)} · {entry.actor_label}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
