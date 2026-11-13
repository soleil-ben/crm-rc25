/**
 * Full-page six-step booking workflow (Design.md section 9).
 *
 * Steps: Customer, Route and service, Sender and recipient, Packages, Review, Confirmed.
 * A sticky footer carries Back, Save draft, and Continue/Confirm.
 *
 * Two properties matter more than the layout:
 *
 * 1. **No customer-facing ID before confirmation.** The draft is saved through
 *    `POST /shipments`, which never returns a public ID, and the ID only appears on the
 *    Confirmed step.
 * 2. **Double submission cannot create two bookings.** One idempotency key is generated
 *    per wizard session and reused for every retry, the confirm button disables while the
 *    request is in flight, and the server treats a repeat as an idempotent read. Both
 *    halves are needed: the disabled button is convenience, the key is the guarantee.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { customersApi, shipmentsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Banner, Button } from '../../components/ui/index.jsx';
import { ErrorState } from '../../components/state/index.jsx';
import {
  ConfirmedStep,
  ContactsStep,
  CustomerStep,
  EMPTY_ADDRESS,
  EMPTY_PACKAGE,
  PackagesStep,
  ReviewStep,
  RouteStep,
  StepIndicator,
  ValidationSummary,
} from './bookingSteps.jsx';
import { LabelPrintDrawer } from './LabelPrintDrawer.jsx';
import './shipments.css';

const INITIAL_DRAFT = {
  customer_id: null,
  route_group: '',
  direction: '',
  service_type: 'standard_parcel',
  transport_mode: 'unspecified',
  booking_reference: '',
  contents_description: '',
  declared_value: '',
  declared_value_currency: '',
  estimated_delivery_at: '',
  sender: { ...EMPTY_ADDRESS },
  recipient: { ...EMPTY_ADDRESS },
  packages: [{ ...EMPTY_PACKAGE }],
};

/** A key that survives re-renders and retries but not a new booking. */
function newIdempotencyKey() {
  const random =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `booking-${random}`.slice(0, 120);
}

function positiveOrBlank(value) {
  if (value === '' || value === null || value === undefined) return true;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0;
}

export function BookingWizardPage() {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();

  const [draft, setDraft] = useState(INITIAL_DRAFT);
  const [shipmentId, setShipmentId] = useState(null);
  const [confirmed, setConfirmed] = useState(null);
  const [alreadyConfirmed, setAlreadyConfirmed] = useState(false);
  const [printOpen, setPrintOpen] = useState(false);
  const [touched, setTouched] = useState(false);
  const idempotencyKey = useRef(newIdempotencyKey());
  const headingRef = useRef(null);

  const stepIndex = Number(params.get('step') || 0);

  const metaQuery = useQuery({ queryKey: ['shipment-meta'], queryFn: shipmentsApi.meta });
  const customerQuery = useQuery({
    queryKey: ['customer', draft.customer_id],
    queryFn: () => customersApi.get(draft.customer_id),
    enabled: Boolean(draft.customer_id),
  });

  const steps = useMemo(
    () => [
      { id: 'customer', label: t('booking.stepCustomer') },
      { id: 'route', label: t('booking.stepRoute') },
      { id: 'contacts', label: t('booking.stepContacts') },
      { id: 'packages', label: t('booking.stepPackages') },
      { id: 'review', label: t('booking.stepReview') },
      { id: 'confirmed', label: t('booking.stepConfirmed') },
    ],
    [t],
  );

  function goToStep(index) {
    const next = new URLSearchParams(params);
    next.set('step', String(index));
    setParams(next, { replace: false });
    setTouched(false);
  }

  useEffect(() => {
    headingRef.current?.focus();
  }, [stepIndex]);

  function update(patch) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  // --- Validation ------------------------------------------------------

  const packageErrors = draft.packages.map((item) => {
    const errors = {};
    ['length_value', 'width_value', 'height_value', 'weight_value'].forEach((key) => {
      if (!positiveOrBlank(item[key])) {
        errors[key] = t('booking.measurementHint');
      }
    });
    return errors;
  });

  const stepErrors = useMemo(() => {
    const errors = [];
    if (stepIndex === 0 && !draft.customer_id) errors.push(t('booking.customerSearch'));
    if (stepIndex === 1) {
      if (!draft.route_group) errors.push(t('booking.routeGroup'));
      const selected = (metaQuery.data?.route_groups ?? []).find(
        (route) => route.value === draft.route_group,
      );
      if (selected && selected.directions.length > 1 && !draft.direction) {
        errors.push(t('booking.direction'));
      }
      if (!draft.contents_description.trim()) errors.push(t('booking.contents'));
    }
    if (stepIndex === 2) {
      if (!draft.sender.name.trim()) errors.push(`${t('booking.sender')}: ${t('booking.contactName')}`);
      if (!draft.sender.country_code.trim())
        errors.push(`${t('booking.sender')}: ${t('booking.country')}`);
      if (!draft.recipient.name.trim())
        errors.push(`${t('booking.recipient')}: ${t('booking.contactName')}`);
      if (!draft.recipient.city.trim())
        errors.push(`${t('booking.recipient')}: ${t('booking.city')}`);
      if (!draft.recipient.country_code.trim())
        errors.push(`${t('booking.recipient')}: ${t('booking.country')}`);
    }
    if (stepIndex === 3) {
      if (draft.packages.length === 0) errors.push(t('booking.noPackages'));
      if (packageErrors.some((item) => Object.keys(item).length > 0)) {
        errors.push(t('booking.measurementHint'));
      }
    }
    return errors;
  }, [stepIndex, draft, metaQuery.data, packageErrors, t]);

  // --- Persistence -----------------------------------------------------

  function payload() {
    const clean = (address) => {
      const result = {};
      Object.entries(address).forEach(([key, value]) => {
        if (value !== '' && value !== null && value !== undefined) result[key] = value;
      });
      return result;
    };
    return {
      customer_id: draft.customer_id,
      route_group: draft.route_group,
      direction: draft.direction || undefined,
      service_type: draft.service_type,
      transport_mode: draft.transport_mode,
      booking_reference: draft.booking_reference || undefined,
      contents_description: draft.contents_description || undefined,
      declared_value: draft.declared_value || undefined,
      declared_value_currency: draft.declared_value_currency || undefined,
      estimated_delivery_at: draft.estimated_delivery_at
        ? `${draft.estimated_delivery_at}T00:00:00`
        : undefined,
      sender: clean(draft.sender),
      recipient: clean(draft.recipient),
      packages: draft.packages.map((item) => {
        const result = { dimension_unit: item.dimension_unit, weight_unit: item.weight_unit };
        Object.entries(item).forEach(([key, value]) => {
          if (value !== '' && value !== null && value !== undefined) result[key] = value;
        });
        return result;
      }),
    };
  }

  const saveDraft = useMutation({
    // Saving twice updates the same draft rather than creating a second one.
    mutationFn: () => {
      if (!shipmentId) return shipmentsApi.createDraft(payload());
      const { packages: _packages, customer_id: _customerId, ...editable } = payload();
      return shipmentsApi.update(shipmentId, editable);
    },
    onSuccess: (saved) => {
      setShipmentId(saved.id);
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
    },
  });

  const confirmBooking = useMutation({
    mutationFn: async () => {
      const saved = shipmentId
        ? { id: shipmentId }
        : await shipmentsApi.createDraft(payload());
      if (!shipmentId) setShipmentId(saved.id);
      return shipmentsApi.confirm(saved.id, idempotencyKey.current);
    },
    onSuccess: (result) => {
      setConfirmed(result.shipment);
      setAlreadyConfirmed(!result.created);
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
      goToStep(5);
    },
  });

  const isBusy = saveDraft.isPending || confirmBooking.isPending;

  function onContinue() {
    if (stepErrors.length) {
      setTouched(true);
      return;
    }
    if (stepIndex === 4) {
      confirmBooking.mutate();
      return;
    }
    goToStep(stepIndex + 1);
  }

  if (metaQuery.error) {
    return <ErrorState error={metaQuery.error} onRetry={metaQuery.refetch} />;
  }

  const current = steps[Math.min(stepIndex, steps.length - 1)];
  const isConfirmedStep = stepIndex === 5 && confirmed;

  return (
    <div className="booking">
      <PageHeader
        title={t('booking.title')}
        subtitle={t('booking.stepOf')
          .replace('{current}', String(Math.min(stepIndex + 1, steps.length)))
          .replace('{total}', String(steps.length))}
      />

      <StepIndicator steps={steps} current={Math.min(stepIndex, steps.length - 1)} />

      <h2 className="booking__step-title" tabIndex={-1} ref={headingRef}>
        {current.label}
      </h2>

      {touched && <ValidationSummary errors={stepErrors} />}
      {saveDraft.error && (
        <Banner tone="danger" title={t('states.saveError')}>
          {saveDraft.error.message}
        </Banner>
      )}

      <div className="booking__body">
        {stepIndex === 0 && <CustomerStep draft={draft} onChange={update} />}
        {stepIndex === 1 && <RouteStep draft={draft} onChange={update} meta={metaQuery.data} />}
        {stepIndex === 2 && <ContactsStep draft={draft} onChange={update} />}
        {stepIndex === 3 && (
          <PackagesStep draft={draft} onChange={update} packageErrors={packageErrors} />
        )}
        {stepIndex === 4 && (
          <ReviewStep
            draft={draft}
            customer={customerQuery.data}
            confirmError={confirmBooking.error}
          />
        )}
        {isConfirmedStep && (
          <ConfirmedStep
            shipment={confirmed}
            alreadyConfirmed={alreadyConfirmed}
            onPrint={() => setPrintOpen(true)}
          />
        )}
      </div>

      {!isConfirmedStep && (
        <div className="booking__footer">
          <Button onClick={() => goToStep(Math.max(0, stepIndex - 1))} disabled={stepIndex === 0}>
            {t('booking.back')}
          </Button>
          <span className="spacer" />
          <Button
            onClick={() => saveDraft.mutate()}
            loading={saveDraft.isPending}
            disabled={!draft.customer_id || !draft.route_group || isBusy}
          >
            {t('booking.saveDraft')}
          </Button>
          <Button
            variant="primary"
            onClick={onContinue}
            loading={confirmBooking.isPending}
            disabled={isBusy}
          >
            {stepIndex === 4 ? t('booking.confirmBooking') : t('booking.continue')}
          </Button>
        </div>
      )}

      {confirmed && (
        <LabelPrintDrawer
          open={printOpen}
          onClose={() => setPrintOpen(false)}
          shipmentId={confirmed.id}
        />
      )}

      {saveDraft.isSuccess && !confirmed && (
        <p className="meta booking__saved" role="status">
          {t('states.savedSuccess')}{' '}
          <button
            type="button"
            className="link-button"
            onClick={() => navigate(`/shipments/${shipmentId}`)}
          >
            {t('shipments.openShipment')}
          </button>
        </p>
      )}
    </div>
  );
}
