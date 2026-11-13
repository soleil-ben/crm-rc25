/**
 * Address book (CRM.md section 4).
 *
 * Customer-owned sender/recipient contacts with optional labels. The panel states that
 * confirmed shipments keep their own address snapshot, so editing here never rewrites
 * shipment history (AC-5).
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
  Checkbox,
  Drawer,
  Field,
  Select,
  TextInput,
} from '../../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../../components/state/index.jsx';

const EMPTY = {
  label: '',
  role: 'both',
  contact_name: '',
  phone: '',
  email: '',
  address_line1: '',
  address_line2: '',
  city: '',
  province_state: '',
  postal_code: '',
  country_code: '',
  delivery_note: '',
  is_default_sender: false,
  is_default_recipient: false,
};

export function AddressBookTab({ customer }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['addresses', customer.id],
    queryFn: () => customersApi.addresses(customer.id),
  });

  const saveMutation = useMutation({
    mutationFn: (payload) =>
      editing
        ? customersApi.updateAddress(editing.id, payload)
        : customersApi.createAddress(customer.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['addresses', customer.id] });
      setOpen(false);
      setEditing(null);
      setForm(EMPTY);
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (addressId) => customersApi.archiveAddress(addressId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['addresses', customer.id] }),
  });

  function startEdit(address) {
    setEditing(address);
    setForm({
      label: address.label ?? '',
      role: address.role ?? 'both',
      contact_name: address.contact_name ?? '',
      phone: address.phone_entered ?? '',
      email: address.email_entered ?? '',
      address_line1: address.address_line1 ?? '',
      address_line2: address.address_line2 ?? '',
      city: address.city ?? '',
      province_state: address.province_state ?? '',
      postal_code: address.postal_code ?? '',
      country_code: address.country_code ?? '',
      delivery_note: address.delivery_note ?? '',
      is_default_sender: address.is_default_sender,
      is_default_recipient: address.is_default_recipient,
    });
    setOpen(true);
  }

  if (isLoading) return <SkeletonRows rows={3} height={100} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  const addresses = data ?? [];

  return (
    <>
      <div className="stack">
        <Banner tone="neutral">{t('profile.addressSnapshotNote')}</Banner>

        <Card
          title={t('profile.addresses')}
          actions={
            can(P.ADDRESS_WRITE) ? (
              <Button
                variant="primary"
                compact
                onClick={() => {
                  setEditing(null);
                  setForm({ ...EMPTY, contact_name: customer.full_name });
                  setOpen(true);
                }}
              >
                {t('profile.addAddress')}
              </Button>
            ) : null
          }
          flush
        >
          {addresses.length === 0 ? (
            <EmptyState
              title="No saved addresses"
              body="Save the addresses this customer ships from and to, so bookings are faster."
            />
          ) : (
            <ul className="address-list">
              {addresses.map((address) => (
                <li key={address.id} className="address-card">
                  <div className="row-wrap">
                    <strong>{address.label || address.contact_name}</strong>
                    <span className="badge badge--neutral">{address.role}</span>
                    {address.is_default_sender && (
                      <span className="badge badge--teal">{t('profile.defaultSender')}</span>
                    )}
                    {address.is_default_recipient && (
                      <span className="badge badge--orange">{t('profile.defaultRecipient')}</span>
                    )}
                  </div>
                  <p>{address.contact_name}</p>
                  <p className="meta">
                    {[address.address_line1, address.address_line2, address.city,
                      address.province_state, address.postal_code, address.country_code]
                      .filter(Boolean)
                      .join(', ') || '—'}
                  </p>
                  <p className="meta">
                    {address.phone_entered || '—'} · {address.email_entered || '—'}
                  </p>
                  {can(P.ADDRESS_WRITE) && (
                    <div className="row">
                      <Button compact onClick={() => startEdit(address)}>
                        {t('common.edit')}
                      </Button>
                      <Button
                        compact
                        variant="tertiary"
                        onClick={() => archiveMutation.mutate(address.id)}
                      >
                        Archive
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={editing ? 'Edit address' : t('profile.addAddress')}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              type="submit"
              form="address-form"
              loading={saveMutation.isPending}
              disabled={!form.contact_name.trim()}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        <form
          id="address-form"
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            const payload = { ...form };
            Object.keys(payload).forEach((key) => {
              if (payload[key] === '') payload[key] = null;
            });
            payload.contact_name = form.contact_name;
            payload.role = form.role;
            payload.is_default_sender = form.is_default_sender;
            payload.is_default_recipient = form.is_default_recipient;
            saveMutation.mutate(payload);
          }}
        >
          {saveMutation.error && <ErrorState error={saveMutation.error} />}
          <Field label={t('profile.addressLabel')} hint='For example "Family in Vietnam".'>
            {(props) => (
              <TextInput
                {...props}
                value={form.label}
                onChange={(event) => setForm({ ...form, label: event.target.value })}
              />
            )}
          </Field>
          <div className="form-grid">
            <Field label={t('profile.contactName')} required>
              {(props) => (
                <TextInput
                  {...props}
                  value={form.contact_name}
                  onChange={(event) => setForm({ ...form, contact_name: event.target.value })}
                />
              )}
            </Field>
            <Field label="Role">
              {(props) => (
                <Select
                  {...props}
                  value={form.role}
                  onChange={(event) => setForm({ ...form, role: event.target.value })}
                  options={[
                    { value: 'both', label: 'Sender and recipient' },
                    { value: 'sender', label: 'Sender' },
                    { value: 'recipient', label: 'Recipient' },
                    { value: 'billing', label: 'Billing' },
                  ]}
                />
              )}
            </Field>
            <Field label={t('customers.phone')}>
              {(props) => (
                <TextInput
                  {...props}
                  value={form.phone}
                  onChange={(event) => setForm({ ...form, phone: event.target.value })}
                />
              )}
            </Field>
            <Field label={t('customers.email')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="email"
                  value={form.email}
                  onChange={(event) => setForm({ ...form, email: event.target.value })}
                />
              )}
            </Field>
          </div>
          <Field label="Address line 1">
            {(props) => (
              <TextInput
                {...props}
                value={form.address_line1}
                onChange={(event) => setForm({ ...form, address_line1: event.target.value })}
              />
            )}
          </Field>
          <Field label="Address line 2">
            {(props) => (
              <TextInput
                {...props}
                value={form.address_line2}
                onChange={(event) => setForm({ ...form, address_line2: event.target.value })}
              />
            )}
          </Field>
          <div className="form-grid">
            <Field label={t('customers.city')}>
              {(props) => (
                <TextInput
                  {...props}
                  value={form.city}
                  onChange={(event) => setForm({ ...form, city: event.target.value })}
                />
              )}
            </Field>
            <Field label={t('customers.provinceState')}>
              {(props) => (
                <TextInput
                  {...props}
                  value={form.province_state}
                  onChange={(event) => setForm({ ...form, province_state: event.target.value })}
                />
              )}
            </Field>
            <Field label="Postal code">
              {(props) => (
                <TextInput
                  {...props}
                  value={form.postal_code}
                  onChange={(event) => setForm({ ...form, postal_code: event.target.value })}
                />
              )}
            </Field>
            <Field label={t('customers.country')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.country_code}
                  onChange={(event) => setForm({ ...form, country_code: event.target.value })}
                  placeholder={t('common.unknown')}
                  options={[
                    { value: 'CA', label: 'Canada' },
                    { value: 'VN', label: 'Vietnam' },
                    { value: 'US', label: 'United States' },
                  ]}
                />
              )}
            </Field>
          </div>
          <Field label="Delivery note">
            {(props) => (
              <TextInput
                {...props}
                value={form.delivery_note}
                onChange={(event) => setForm({ ...form, delivery_note: event.target.value })}
              />
            )}
          </Field>
          <Checkbox
            label={t('profile.defaultSender')}
            checked={form.is_default_sender}
            onChange={(event) => setForm({ ...form, is_default_sender: event.target.checked })}
          />
          <Checkbox
            label={t('profile.defaultRecipient')}
            checked={form.is_default_recipient}
            onChange={(event) => setForm({ ...form, is_default_recipient: event.target.checked })}
          />
        </form>
      </Drawer>
    </>
  );
}
