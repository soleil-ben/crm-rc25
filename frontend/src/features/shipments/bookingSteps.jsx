/**
 * The five editing steps of the booking workflow (Design.md section 9).
 *
 * Each step is a plain presentational component over one shared draft object. Validation
 * runs on change so a staff member sees a problem before the sticky footer refuses to
 * advance — but the server revalidates everything, so nothing here is a security control.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { customersApi, opsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import {
  Banner,
  Button,
  Card,
  Checkbox,
  Field,
  RouteBadge,
  Select,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, InlineSpinner } from '../../components/state/index.jsx';
import { CustomerFormDrawer } from '../customers/CustomerFormDrawer.jsx';

// Which address-book roles each picker may offer. Stated as an allowlist rather than as
// "not the other one": a fourth role exists since Phase 10 (`billing`), and an exclusion
// filter would have offered it in both pickers. A billing address is a correspondence
// target, not a place a driver collects from or delivers to.
const SENDER_ROLES = new Set(['sender', 'both']);
const RECIPIENT_ROLES = new Set(['recipient', 'both']);

/**
 * The recipient picker's choices (RC-UAT-25 item 4, Ben 2026-10-25: "Use a saved address"
 * for the recipient, as the sender has). A Customer Account registration saves the
 * customer's own address as a *sender* address only, so a recipient-only list was empty
 * for most customers and the picker never appeared. Stand-in: every saved address except
 * billing is offered, the customer's recipient (and both) addresses first, and a sender
 * address says so in its label. A billing address is still never offered.
 */
export function recipientChoices(addresses) {
  const usable = addresses.filter(
    (address) => RECIPIENT_ROLES.has(address.role) || SENDER_ROLES.has(address.role),
  );
  return [
    ...usable.filter((address) => RECIPIENT_ROLES.has(address.role)),
    ...usable.filter((address) => !RECIPIENT_ROLES.has(address.role)),
  ];
}

export const EMPTY_ADDRESS = {
  address_id: '',
  name: '',
  company: '',
  phone_entered: '',
  email: '',
  address_line1: '',
  address_line2: '',
  city: '',
  province_state: '',
  postal_code: '',
  country_code: '',
  delivery_note: '',
};

export const EMPTY_PACKAGE = {
  length_value: '',
  width_value: '',
  height_value: '',
  dimension_unit: 'cm',
  weight_value: '',
  weight_unit: 'kg',
  contents_summary: '',
  handling_note: '',
  warehouse_location: '',
};

/* --- Step 1: customer ------------------------------------------------- */

export function CustomerStep({ draft, onChange }) {
  const t = useT();
  const { can } = useSession();
  const [term, setTerm] = useState('');
  const [debounced, setDebounced] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term.trim()), 220);
    return () => clearTimeout(timer);
  }, [term]);

  const { data, isFetching } = useQuery({
    queryKey: ['booking-customer-search', debounced],
    queryFn: () => opsApi.search(debounced, 8),
    enabled: debounced.length >= 2,
  });

  const selectedQuery = useQuery({
    queryKey: ['customer', draft.customer_id],
    queryFn: () => customersApi.get(draft.customer_id),
    enabled: Boolean(draft.customer_id),
  });

  const addressesQuery = useQuery({
    queryKey: ['customer-addresses', draft.customer_id],
    queryFn: () => customersApi.addresses(draft.customer_id),
    enabled: Boolean(draft.customer_id),
  });

  const customer = selectedQuery.data;
  const results = data?.items ?? [];

  if (draft.customer_id && customer) {
    return (
      <Card title={t('booking.customerSelected')}>
        <div className="booking-customer">
          <div>
            <p className="booking-customer__name">{customer.full_name}</p>
            <p className="meta mono">{customer.public_id}</p>
            <p className="meta">
              {[customer.phone_entered, customer.email_entered].filter(Boolean).join(' · ') || '—'}
            </p>
            <div className="row-wrap" style={{ marginTop: 'var(--space-2)' }}>
              <StatusBadge kind="lifecycle" value={customer.lifecycle_status} />
              {customer.observed_primary_route_group && (
                <RouteBadge route={customer.observed_primary_route_group} />
              )}
              <span className="meta">
                {(addressesQuery.data ?? []).length} {t('booking.savedContacts')}
              </span>
            </div>
          </div>
          <span className="spacer" />
          <Button onClick={() => onChange({ customer_id: null })}>
            {t('booking.changeCustomer')}
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <>
      <Card title={t('booking.customerSearch')}>
        <Field label={t('booking.customerSearch')} hint={t('booking.customerSearchHint')}>
          {(props) => (
            <TextInput
              {...props}
              type="search"
              autoFocus
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder={t('customers.searchPlaceholder')}
            />
          )}
        </Field>

        {isFetching && results.length === 0 && <InlineSpinner />}

        {debounced.length >= 2 && !isFetching && results.length === 0 && (
          <EmptyState
            title={t('booking.noCustomerMatches')}
            action={
              can(P.CUSTOMER_CREATE) && (
                <Button variant="primary" onClick={() => setDrawerOpen(true)}>
                  {t('booking.createCustomer')}
                </Button>
              )
            }
          />
        )}

        {results.length > 0 && (
          <ul className="booking-results">
            {results.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="booking-results__item"
                  onClick={() => onChange({ customer_id: item.id })}
                >
                  <span className="mono">{item.public_id}</span>
                  <span className="booking-results__name">{item.full_name}</span>
                  <span className="meta">
                    {[item.phone_entered, item.email_entered].filter(Boolean).join(' · ')}
                  </span>
                  {item.primary_route_group && <RouteBadge route={item.primary_route_group} />}
                </button>
              </li>
            ))}
          </ul>
        )}

        {can(P.CUSTOMER_CREATE) && results.length > 0 && (
          <Button variant="tertiary" onClick={() => setDrawerOpen(true)}>
            {t('booking.createCustomer')}
          </Button>
        )}
      </Card>

      <CustomerFormDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        navigateOnCreate={false}
        onSaved={(created) => {
          if (created?.id) onChange({ customer_id: created.id });
        }}
      />
    </>
  );
}

/* --- Step 2: route and service ---------------------------------------- */

/** The server's list until the meta request answers; it is the same two codes. */
export const DECLARED_VALUE_CURRENCIES = ['CAD', 'VND'];

/**
 * The currency choices. A draft saved before the list existed may hold another code; it
 * stays selectable on that draft (the server accepts an unchanged value) rather than being
 * silently blanked.
 */
function currencyOptions(meta, current, t) {
  const codes = [...(meta?.declared_value_currencies ?? DECLARED_VALUE_CURRENCIES)];
  if (current && !codes.includes(current)) codes.push(current);
  return codes.map((code) => {
    const name = t(`booking.currencyNames.${code}`, '');
    return { value: code, label: name ? `${code} — ${name}` : code };
  });
}

export function RouteStep({ draft, onChange, meta }) {
  const t = useT();
  const routes = meta?.route_groups ?? [];
  const selected = routes.find((route) => route.value === draft.route_group);
  const directions = selected?.directions ?? [];

  return (
    <Card>
      <div className="form-grid">
        <Field label={t('booking.routeGroup')} required>
          {(props) => (
            <Select
              {...props}
              value={draft.route_group}
              placeholder="—"
              onChange={(event) => onChange({ route_group: event.target.value, direction: '' })}
              options={routes.map((route) => ({
                value: route.value,
                label: t(`routes.${route.value}`, route.label),
              }))}
            />
          )}
        </Field>

        <Field
          label={t('booking.direction')}
          hint={directions.length > 1 ? t('booking.directionHint') : undefined}
          required={directions.length > 1}
        >
          {(props) => (
            <Select
              {...props}
              value={draft.direction}
              placeholder={directions.length === 1 ? directions[0].label : '—'}
              disabled={directions.length <= 1}
              onChange={(event) => onChange({ direction: event.target.value })}
              options={directions.map((direction) => ({
                value: direction.value,
                label: t(`routeDirections.${direction.value}`, direction.label),
              }))}
            />
          )}
        </Field>

        <Field label={t('booking.serviceType')}>
          {(props) => (
            <Select
              {...props}
              value={draft.service_type}
              onChange={(event) => onChange({ service_type: event.target.value })}
              options={(meta?.service_types ?? []).map((item) => ({
                value: item.value,
                label: t(`serviceType.${item.value}`, item.label),
              }))}
            />
          )}
        </Field>

        <Field label={t('booking.transportMode')}>
          {(props) => (
            <Select
              {...props}
              value={draft.transport_mode}
              onChange={(event) => onChange({ transport_mode: event.target.value })}
              options={(meta?.transport_modes ?? []).map((item) => ({
                value: item.value,
                label: t(`transportMode.${item.value}`, item.label),
              }))}
            />
          )}
        </Field>

        <Field label={t('booking.bookingReference')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={draft.booking_reference}
              onChange={(event) => onChange({ booking_reference: event.target.value })}
            />
          )}
        </Field>

        <Field label={t('booking.estimatedDelivery')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              type="date"
              value={draft.estimated_delivery_at}
              onChange={(event) => onChange({ estimated_delivery_at: event.target.value })}
            />
          )}
        </Field>

        <Field label={t('booking.declaredValue')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              inputMode="decimal"
              value={draft.declared_value}
              onChange={(event) => onChange({ declared_value: event.target.value })}
            />
          )}
        </Field>

        {/* RC-UAT-25 item 3, Ben 2026-10-25: a list, not free text. The server's list
            (`/shipments/meta`), which it also enforces; optional, so "—" is blank. */}
        <Field label={t('booking.declaredCurrency')} hint={t('common.optional')}>
          {(props) => (
            <Select
              {...props}
              value={draft.declared_value_currency}
              placeholder="—"
              onChange={(event) => onChange({ declared_value_currency: event.target.value })}
              options={currencyOptions(meta, draft.declared_value_currency, t)}
            />
          )}
        </Field>
      </div>

      <Field
        label={t('booking.contents')}
        hint={t('booking.contentsHint')}
        required
      >
        {(props) => (
          <TextArea
            {...props}
            rows={2}
            value={draft.contents_description}
            onChange={(event) => onChange({ contents_description: event.target.value })}
          />
        )}
      </Field>

      <Banner tone="neutral">{t('booking.routeLockNote')}</Banner>
    </Card>
  );
}

/* --- Step 3: sender and recipient ------------------------------------- */

function AddressFields({ role, value, onChange, addresses, title, pickerHint, emptyNote }) {
  const t = useT();
  const usingSaved = Boolean(value.address_id);

  function applySaved(addressId) {
    if (!addressId) {
      onChange({ ...EMPTY_ADDRESS });
      return;
    }
    const address = addresses.find((item) => String(item.id) === String(addressId));
    if (!address) return;
    onChange({
      ...EMPTY_ADDRESS,
      address_id: address.id,
      name: address.contact_name || '',
      company: address.company_name || '',
      phone_entered: address.phone_entered || '',
      email: address.email_entered || '',
      address_line1: address.address_line1 || '',
      address_line2: address.address_line2 || '',
      city: address.city || '',
      province_state: address.province_state || '',
      postal_code: address.postal_code || '',
      country_code: address.country_code || '',
      delivery_note: address.delivery_note || '',
    });
  }

  return (
    <Card title={title}>
      {addresses.length > 0 && (
        <Field label={t('booking.useSavedAddress')} hint={pickerHint}>
          {(props) => (
            <Select
              {...props}
              value={value.address_id || ''}
              placeholder={t('booking.enterManually')}
              onChange={(event) => applySaved(event.target.value)}
              options={addresses.map((address) => ({
                value: address.id,
                label: `${address.label ? `${address.label} — ` : ''}${address.contact_name}${
                  address.city ? `, ${address.city}` : ''
                }${
                  role === 'recipient' && !RECIPIENT_ROLES.has(address.role)
                    ? ` (${t('booking.savedAsSender')})`
                    : ''
                }`,
              }))}
            />
          )}
        </Field>
      )}
      {addresses.length === 0 && emptyNote && <p className="meta">{emptyNote}</p>}

      {usingSaved && <Banner tone="info">{t('booking.snapshotNote')}</Banner>}

      <div className="form-grid">
        <Field label={t('booking.contactName')} required>
          {(props) => (
            <TextInput
              {...props}
              value={value.name}
              onChange={(event) => onChange({ ...value, name: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.company')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.company}
              onChange={(event) => onChange({ ...value, company: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.phone')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.phone_entered}
              onChange={(event) => onChange({ ...value, phone_entered: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.email')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              type="email"
              value={value.email}
              onChange={(event) => onChange({ ...value, email: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.addressLine1')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.address_line1}
              onChange={(event) => onChange({ ...value, address_line1: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.addressLine2')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.address_line2}
              onChange={(event) => onChange({ ...value, address_line2: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.city')} required={role === 'recipient'}>
          {(props) => (
            <TextInput
              {...props}
              value={value.city}
              onChange={(event) => onChange({ ...value, city: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.provinceState')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.province_state}
              onChange={(event) => onChange({ ...value, province_state: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.postalCode')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.postal_code}
              onChange={(event) => onChange({ ...value, postal_code: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.country')} required>
          {(props) => (
            <TextInput
              {...props}
              maxLength={40}
              placeholder="CA"
              value={value.country_code}
              onChange={(event) => onChange({ ...value, country_code: event.target.value })}
            />
          )}
        </Field>
      </div>

      {role === 'recipient' && (
        <Field label={t('booking.deliveryNote')} hint={t('common.optional')}>
          {(props) => (
            <TextArea
              {...props}
              rows={2}
              value={value.delivery_note}
              onChange={(event) => onChange({ ...value, delivery_note: event.target.value })}
            />
          )}
        </Field>
      )}
    </Card>
  );
}

export function ContactsStep({ draft, onChange }) {
  const t = useT();
  const addressesQuery = useQuery({
    queryKey: ['customer-addresses', draft.customer_id],
    queryFn: () => customersApi.addresses(draft.customer_id),
    enabled: Boolean(draft.customer_id),
  });
  const addresses = addressesQuery.data ?? [];
  const forRecipient = recipientChoices(addresses);
  // Billing addresses do not count: neither picker offers one.
  const noneSaved = addressesQuery.isSuccess && forRecipient.length === 0;

  return (
    <>
      <Banner tone="neutral">{t('booking.snapshotNote')}</Banner>
      <AddressFields
        role="sender"
        title={t('booking.sender')}
        value={draft.sender}
        addresses={addresses.filter((address) => SENDER_ROLES.has(address.role))}
        emptyNote={noneSaved ? t('booking.noSavedAddresses') : undefined}
        onChange={(sender) => onChange({ sender })}
      />
      <AddressFields
        role="recipient"
        title={t('booking.recipient')}
        value={draft.recipient}
        addresses={forRecipient}
        pickerHint={t('booking.recipientSavedHint')}
        emptyNote={noneSaved ? t('booking.noSavedAddresses') : undefined}
        onChange={(recipient) => onChange({ recipient })}
      />
    </>
  );
}

/* --- Step 4: packages -------------------------------------------------- */

function PackageCard({ index, value, count, onChange, onDuplicate, onRemove, errors }) {
  const t = useT();
  return (
    <Card
      title={t('booking.packageCard', `Package ${index + 1}`).replace('{index}', index + 1)}
      actions={
        <>
          <Button compact onClick={onDuplicate}>
            {t('booking.duplicatePackage')}
          </Button>
          <Button compact variant="tertiary" onClick={onRemove} disabled={count === 1}>
            {t('booking.removePackage')}
          </Button>
        </>
      }
    >
      <div className="form-grid form-grid--tight">
        {['length_value', 'width_value', 'height_value'].map((key) => (
          <Field
            key={key}
            label={t(`booking.${key.replace('_value', '')}`)}
            error={errors?.[key]}
          >
            {(props) => (
              <TextInput
                {...props}
                inputMode="decimal"
                value={value[key]}
                onChange={(event) => onChange({ ...value, [key]: event.target.value })}
              />
            )}
          </Field>
        ))}
        <Field label={t('booking.dimensionUnit')}>
          {(props) => (
            <Select
              {...props}
              value={value.dimension_unit}
              onChange={(event) => onChange({ ...value, dimension_unit: event.target.value })}
              options={[
                { value: 'cm', label: 'cm' },
                { value: 'in', label: 'in' },
              ]}
            />
          )}
        </Field>
        <Field label={t('booking.weight')} error={errors?.weight_value}>
          {(props) => (
            <TextInput
              {...props}
              inputMode="decimal"
              value={value.weight_value}
              onChange={(event) => onChange({ ...value, weight_value: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.weightUnit')}>
          {(props) => (
            <Select
              {...props}
              value={value.weight_unit}
              onChange={(event) => onChange({ ...value, weight_unit: event.target.value })}
              options={[
                { value: 'kg', label: 'kg' },
                { value: 'lb', label: 'lb' },
              ]}
            />
          )}
        </Field>
      </div>

      <div className="form-grid">
        <Field label={t('booking.packageContents')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.contents_summary}
              onChange={(event) => onChange({ ...value, contents_summary: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.handlingNote')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.handling_note}
              onChange={(event) => onChange({ ...value, handling_note: event.target.value })}
            />
          )}
        </Field>
        <Field label={t('booking.warehouseLocation')} hint={t('common.optional')}>
          {(props) => (
            <TextInput
              {...props}
              value={value.warehouse_location}
              onChange={(event) => onChange({ ...value, warehouse_location: event.target.value })}
            />
          )}
        </Field>
      </div>
    </Card>
  );
}

export function PackagesStep({ draft, onChange, packageErrors }) {
  const t = useT();
  const packages = draft.packages;

  function update(index, next) {
    onChange({ packages: packages.map((item, i) => (i === index ? next : item)) });
  }

  return (
    <>
      <Banner tone="neutral">{t('booking.measurementHint')}</Banner>
      {packages.map((value, index) => (
        <PackageCard
          key={index}
          index={index}
          count={packages.length}
          value={value}
          errors={packageErrors?.[index]}
          onChange={(next) => update(index, next)}
          onDuplicate={() =>
            onChange({ packages: [...packages, { ...value }] })
          }
          onRemove={() =>
            onChange({ packages: packages.filter((_item, i) => i !== index) })
          }
        />
      ))}
      <Button onClick={() => onChange({ packages: [...packages, { ...EMPTY_PACKAGE }] })}>
        {t('booking.addPackage')}
      </Button>
    </>
  );
}

/* --- Step 5: review ---------------------------------------------------- */

function ReviewRow({ label, children }) {
  return (
    <div className="review-row">
      <span className="review-row__label">{label}</span>
      <span className="review-row__value">{children ?? '—'}</span>
    </div>
  );
}

export function ReviewStep({ draft, customer, confirmError }) {
  const t = useT();
  const address = (value) =>
    [value.name, value.address_line1, value.city, value.province_state, value.country_code]
      .filter(Boolean)
      .join(', ') || '—';

  return (
    <>
      {confirmError && (
        <Banner tone="danger" title={t('states.errorTitle')}>
          {confirmError.message}
        </Banner>
      )}
      <Card title={t('booking.reviewTitle')}>
        <ReviewRow label={t('shipments.columnCustomer')}>
          {customer ? `${customer.full_name} (${customer.public_id})` : '—'}
        </ReviewRow>
        <ReviewRow label={t('booking.routeGroup')}>
          <RouteBadge route={draft.route_group} />
        </ReviewRow>
        <ReviewRow label={t('booking.direction')}>
          {draft.direction ? t(`routeDirections.${draft.direction}`, draft.direction) : '—'}
        </ReviewRow>
        <ReviewRow label={t('booking.serviceType')}>
          {t(`serviceType.${draft.service_type}`, draft.service_type)}
        </ReviewRow>
        <ReviewRow label={t('booking.transportMode')}>
          {t(`transportMode.${draft.transport_mode}`, draft.transport_mode)}
        </ReviewRow>
        <ReviewRow label={t('booking.sender')}>{address(draft.sender)}</ReviewRow>
        <ReviewRow label={t('booking.recipient')}>{address(draft.recipient)}</ReviewRow>
        <ReviewRow label={t('booking.contents')}>{draft.contents_description}</ReviewRow>
        <ReviewRow label={t('booking.declaredValue')}>
          {draft.declared_value
            ? `${draft.declared_value} ${draft.declared_value_currency || ''}`.trim()
            : t('common.notRecorded')}
        </ReviewRow>
        <ReviewRow label={t('shipments.columnPackages')}>
          {draft.packages.length} {t('shipments.packagesLabel')}
        </ReviewRow>
      </Card>

      <Card title={t('booking.stepPackages')}>
        <ul className="review-packages">
          {draft.packages.map((value, index) => (
            <li key={index}>
              <strong>
                {t('booking.packageCard', `Package ${index + 1}`).replace('{index}', index + 1)}
              </strong>
              <span className="meta">
                {[value.length_value, value.width_value, value.height_value].every(Boolean)
                  ? `${value.length_value} × ${value.width_value} × ${value.height_value} ${value.dimension_unit}`
                  : t('common.notRecorded')}
                {value.weight_value
                  ? ` · ${value.weight_value} ${value.weight_unit}`
                  : ''}
              </span>
              <span>{value.contents_summary || ''}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Banner tone="warning" title={t('booking.reviewLockNote')}>
        {t('booking.routeGroup')}, {t('booking.direction')} · {t('booking.reviewConfirmNote')}
      </Banner>
    </>
  );
}

/* --- Step 6: confirmed -------------------------------------------------- */

export function ConfirmedStep({ shipment, alreadyConfirmed, onPrint }) {
  const t = useT();
  const headingRef = useRef(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const references = useMemo(
    () => (shipment?.packages ?? []).filter((item) => item.is_active),
    [shipment],
  );

  return (
    <Card>
      <div className="booking-confirmed">
        <h2 className="booking-confirmed__title" tabIndex={-1} ref={headingRef}>
          {t('booking.confirmedTitle')}
        </h2>
        <p className="state-block__body">{t('booking.confirmedBody')}</p>
        {alreadyConfirmed && <Banner tone="info">{t('booking.confirmedAgain')}</Banner>}

        <p className="meta">{t('booking.solarisId')}</p>
        <p className="booking-confirmed__id mono">{shipment.public_id}</p>

        <p className="meta">{t('booking.packageReferences')}</p>
        <ul className="booking-confirmed__references">
          {references.map((item) => (
            <li key={item.id} className="mono">
              {item.package_reference}
              <span className="meta"> — {item.position_label}</span>
            </li>
          ))}
        </ul>

        <div className="row-wrap">
          <Button variant="primary" onClick={onPrint}>
            {t('labels.open')}
          </Button>
          <Link to={`/shipments/${shipment.id}`} className="btn btn--secondary">
            {t('shipments.openShipment')}
          </Link>
          <Link to="/shipments" className="btn btn--tertiary">
            {t('shipments.title')}
          </Link>
        </div>
      </div>
    </Card>
  );
}

export function StepIndicator({ steps, current }) {
  const t = useT();
  return (
    <ol className="stepper" aria-label={t('booking.title')}>
      {steps.map((step, index) => {
        const state = index === current ? 'is-current' : index < current ? 'is-done' : '';
        return (
          <li key={step.id} className={`stepper__step ${state}`}>
            <span className="stepper__index" aria-hidden="true">
              {index + 1}
            </span>
            <span className="stepper__label">{step.label}</span>
            {index === current && <span className="visually-hidden">(current step)</span>}
          </li>
        );
      })}
    </ol>
  );
}

export function ValidationSummary({ errors }) {
  const t = useT();
  if (!errors.length) return null;
  return (
    <Banner tone="danger" title={t('booking.validationTitle')}>
      <ul className="validation-list">
        {errors.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    </Banner>
  );
}

export function DraftSavedNote({ savedAt }) {
  const t = useT();
  if (!savedAt) return null;
  return (
    <span className="meta" role="status">
      {t('states.savedSuccess')}
    </span>
  );
}

export { Checkbox };
