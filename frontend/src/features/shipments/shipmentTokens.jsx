/**
 * Shipment-specific status tokens and small shared pieces.
 *
 * Booking state, operational state, and payment state are distinct badge types with
 * their own colour maps, so they can never be read as one ambiguous status
 * (Design.md section 5). Every badge renders text; colour only reinforces it.
 */

import { StatusBadge } from '../../components/ui/index.jsx';
import { useT } from '../../i18n/index.jsx';

const TONE_BY_OPERATIONAL_STATE = {
  booked: 'orange',
  awaiting_parcel: 'orange',
  received_at_solaris: 'orange',
  processing: 'info',
  departed_origin: 'info',
  in_transit: 'info',
  customs_processing: 'warning',
  arrived_destination: 'info',
  out_for_delivery: 'info',
  partially_delivered: 'warning',
  delivered: 'success',
  delivery_attempted: 'danger',
  exception: 'danger',
  return_in_progress: 'danger',
  returned: 'neutral',
  cancelled: 'neutral',
  tracking_unavailable: 'neutral',
};

const TONE_BY_BOOKING_STATE = {
  draft: 'neutral',
  confirmed: 'success',
  cancelled: 'neutral',
};

const TONE_BY_PAYMENT_STATE = {
  unrecorded: 'neutral',
  unpaid: 'warning',
  partially_paid: 'warning',
  paid: 'success',
  refunded: 'neutral',
};

const TONE_BY_LEG_STATUS = {
  planned: 'neutral',
  in_progress: 'info',
  completed: 'success',
  cancelled: 'neutral',
};

/**
 * A tracking source is never dressed up as a live connection. `manual` and
 * `external_link` are the only modes Phase 2 can produce.
 */
const TONE_BY_SOURCE_MODE = {
  manual: 'neutral',
  external_link: 'info',
  connected_api: 'success',
  demo: 'warning',
};

export function OperationalBadge({ value }) {
  const t = useT();
  if (!value) return <span className="meta">—</span>;
  return (
    <StatusBadge
      value={value}
      tone={TONE_BY_OPERATIONAL_STATE[value] || 'neutral'}
      label={t(`operationalState.${value}`, value)}
    />
  );
}

export function BookingStateBadge({ value }) {
  const t = useT();
  if (!value) return null;
  return (
    <StatusBadge
      value={value}
      tone={TONE_BY_BOOKING_STATE[value] || 'neutral'}
      label={t(`bookingState.${value}`, value)}
    />
  );
}

export function PaymentStateBadge({ value }) {
  const t = useT();
  if (!value) return null;
  return (
    <StatusBadge
      value={value}
      tone={TONE_BY_PAYMENT_STATE[value] || 'neutral'}
      label={t(`paymentState.${value}`, value)}
    />
  );
}

export function LegStatusBadge({ value }) {
  const t = useT();
  if (!value) return null;
  return (
    <StatusBadge
      value={value}
      tone={TONE_BY_LEG_STATUS[value] || 'neutral'}
      label={t(`legStatus.${value}`, value)}
    />
  );
}

export function SourceModeBadge({ value, label }) {
  const t = useT();
  if (!value) return null;
  return (
    <StatusBadge
      value={value}
      tone={TONE_BY_SOURCE_MODE[value] || 'neutral'}
      label={label || t(`sourceMode.${value}`, value)}
    />
  );
}

/** "1 of 3 packages delivered", derived by the server from package rows. */
export function PackageProgress({ progress }) {
  if (!progress) return <span className="meta">—</span>;
  return (
    <span>
      <span className="shipment-progress__count">{progress.summary}</span>
      {progress.cancelled > 0 && (
        <span className="meta"> · {progress.cancelled} cancelled</span>
      )}
    </span>
  );
}

export function dimensionSummary(pkg) {
  const parts = [pkg.length_value, pkg.width_value, pkg.height_value];
  if (parts.some((value) => value === null || value === undefined)) return null;
  return `${parts.map(trimDecimal).join(' × ')} ${pkg.dimension_unit}`;
}

export function weightSummary(pkg) {
  if (pkg.weight_value === null || pkg.weight_value === undefined) return null;
  const entered = `${trimDecimal(pkg.weight_value)} ${pkg.weight_unit}`;
  if (pkg.weight_unit === 'kg' || pkg.weight_kg === null || pkg.weight_kg === undefined) {
    return entered;
  }
  return `${entered} (${trimDecimal(pkg.weight_kg)} kg)`;
}

/** Amounts arrive as decimal strings so precision survives the wire; trim only zeros. */
export function trimDecimal(value) {
  if (value === null || value === undefined) return '—';
  const text = String(value);
  if (!text.includes('.')) return text;
  return text.replace(/0+$/, '').replace(/\.$/, '');
}
