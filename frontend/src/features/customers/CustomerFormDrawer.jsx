/**
 * Create/edit customer drawer (Design.md section 7).
 *
 * Sections follow the specified order, the form requires a name plus one contact
 * method, and an inline duplicate-candidate panel appears before save. Nothing is ever
 * merged from here: the staff member chooses to open the existing record or to create a
 * separate customer (CRM.md section 13).
 *
 * Validation (UAT round 5): the email's shape and the monthly estimate are checked before
 * sending, and every problem -- found here or by the server -- is listed in an error
 * summary at the top whose entries move focus to their field. A request-validation 422
 * from the server is mapped to its fields with this form's own wording, never pydantic's
 * and never a generic "Something went wrong".
 *
 * While an active or suspended Customer Account holds the record, its email is that
 * account's sign-in email: the field is read-only and says the account must be deactivated
 * first (owner decision, 2026-10-16). The server refuses the change either way.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../../api/client.js';
import { customersApi, opsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useOptionalSession } from '../../app/SessionContext.jsx';
import {
  Banner,
  Button,
  Checkbox,
  Drawer,
  ErrorSummary,
  Field,
  Select,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { ErrorState } from '../../components/state/index.jsx';
import { isValidEmail } from '../../shared/email.js';

const LANGUAGES = ['unknown', 'en', 'vi', 'fr', 'other'];
const ROUTES = ['VCA', 'CAV', 'CAD', 'XUS'];
const PURPOSES = [
  'unknown',
  'personal_items',
  'gifts_family_support',
  'online_orders',
  'returns',
  'business_samples',
  'moving',
  'other',
];
const FREQUENCIES = ['unknown', 'one_time', 'occasional', 'monthly', 'weekly', 'frequent'];
const CHANNELS = ['phone', 'email', 'sms', 'messaging_app', 'in_person', 'other'];
const COUNTRIES = [
  { value: 'CA', label: 'Canada' },
  { value: 'VN', label: 'Vietnam' },
  { value: 'US', label: 'United States' },
];

const EMPTY = {
  full_name: '',
  phone: '',
  email: '',
  city: '',
  province_state: '',
  country_code: '',
  preferred_language: 'unknown',
  category: 'individual',
  business_name: '',
  business_type: '',
  primary_shipping_purpose: 'unknown',
  primary_route_group: '',
  additional_route_interests: [],
  shipping_frequency: 'unknown',
  estimated_monthly_shipments: '',
  preferred_contact_channel: '',
  best_contact_time: '',
  owner_user_id: '',
  do_not_contact: false,
  service_restriction_note: '',
  notes: '',
  tag_ids: [],
};

/**
 * The fields the error summary can link to, in the order they appear, and the id of each
 * one's control. A server error naming any other field is still listed, as text.
 */
const FIELD_IDS = {
  full_name: 'customer-field-full-name',
  phone: 'customer-field-phone',
  email: 'customer-field-email',
  estimated_monthly_shipments: 'customer-field-estimated-monthly',
};
const FIELD_ORDER = Object.keys(FIELD_IDS);

/** This form's sentence for a field the server's request validation refused. */
const FIELD_MESSAGE_KEYS = {
  full_name: 'customers.errorFullName',
  phone: 'customers.errorPhone',
  email: 'customers.errorEmail',
  estimated_monthly_shipments: 'customers.errorMonthly',
};

/** Problems that need no server: the email's shape and the monthly estimate. */
function localErrors(form) {
  const found = {};
  if (form.email.trim() && !isValidEmail(form.email)) found.email = 'customers.errorEmail';
  const monthly = String(form.estimated_monthly_shipments ?? '').trim();
  if (monthly !== '') {
    const value = Number(monthly);
    if (!Number.isInteger(value) || value < 0) {
      found.estimated_monthly_shipments = 'customers.errorMonthly';
    }
  }
  return found;
}

/**
 * Turn a failed save into field errors. A domain error names one field and is already
 * written for a person; a request-validation 422 names fields by `loc` and gets this
 * form's wording. Anything else is not about a field and is shown for the whole form.
 */
function serverErrors(error, t) {
  if (!(error instanceof ApiError)) return {};
  if (error.field) return { [error.field]: error.message };
  const found = {};
  error.invalidFields.forEach((field) => {
    found[field] = FIELD_MESSAGE_KEYS[field]
      ? t(FIELD_MESSAGE_KEYS[field])
      : `${field.replace(/_/g, ' ')}: ${t('customers.errorField')}`;
  });
  return found;
}

/** Ordered for the summary: the linked fields in form order, then anything else. */
function summaryEntries(errors) {
  const known = FIELD_ORDER.filter((field) => errors[field]);
  const other = Object.keys(errors).filter((field) => !FIELD_IDS[field]);
  return [...known, ...other].map((field) => ({ field, message: errors[field] }));
}

/** A slug the tag API accepts, from a name somebody typed. */
function slugify(name) {
  return name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
}

function toPayload(form, { includeTags }) {
  const payload = { ...form };
  // `tag_ids` is sent only when the role may set tags; otherwise the key is absent and
  // the server leaves the tags exactly as they were.
  if (!includeTags) delete payload.tag_ids;
  ['city', 'province_state', 'country_code', 'business_name', 'business_type',
    'primary_route_group', 'preferred_contact_channel', 'best_contact_time',
    'service_restriction_note', 'notes', 'phone', 'email'].forEach((key) => {
    if (payload[key] === '') payload[key] = null;
  });
  payload.owner_user_id = form.owner_user_id ? Number(form.owner_user_id) : null;
  payload.estimated_monthly_shipments =
    form.estimated_monthly_shipments === '' ? null : Number(form.estimated_monthly_shipments);
  if (!payload.additional_route_interests?.length) payload.additional_route_interests = null;
  return payload;
}

export function CustomerFormDrawer({
  open,
  onClose,
  customer = null,
  onSaved,
  // The booking workflow creates a customer without leaving the stepper, so it opts out
  // of the default "jump to the new profile" behaviour.
  navigateOnCreate = true,
}) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isEdit = Boolean(customer);
  const emailHeld = isEdit && Boolean(customer.email_held_by_account);
  // Tags are a separate permission (`tag:write`). The control exists only for a role that
  // holds it; the server enforces the same rule on the request (fix pack item 6).
  const session = useOptionalSession();
  const canWriteTags = Boolean(session?.can(P.TAG_WRITE));

  const [form, setForm] = useState(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [acknowledgedDuplicates, setAcknowledgedDuplicates] = useState(false);
  const [newTagName, setNewTagName] = useState('');
  const [errors, setErrors] = useState({});
  // Bumped on every failed submit, so focus returns to the summary even when the same
  // problems are found twice in a row.
  const [failedSubmits, setFailedSubmits] = useState(0);
  const summaryRef = useRef(null);

  useEffect(() => {
    if (failedSubmits > 0) summaryRef.current?.focus();
  }, [failedSubmits]);

  useEffect(() => {
    if (!open) return;
    setAcknowledgedDuplicates(false);
    setDirty(false);
    setErrors({});
    setForm(
      customer
        ? {
            ...EMPTY,
            full_name: customer.full_name ?? '',
            phone: customer.phone_entered ?? '',
            email: customer.email_entered ?? '',
            city: customer.city ?? '',
            province_state: customer.province_state ?? '',
            country_code: customer.country_code ?? '',
            preferred_language: customer.preferred_language ?? 'unknown',
            category: customer.category ?? 'individual',
            business_name: customer.business_name ?? '',
            business_type: customer.business_type ?? '',
            primary_shipping_purpose: customer.primary_shipping_purpose ?? 'unknown',
            primary_route_group: customer.primary_route_group ?? '',
            additional_route_interests: customer.additional_route_interests ?? [],
            shipping_frequency: customer.shipping_frequency ?? 'unknown',
            estimated_monthly_shipments: customer.estimated_monthly_shipments ?? '',
            preferred_contact_channel: customer.preferred_contact_channel ?? '',
            best_contact_time: customer.best_contact_time ?? '',
            owner_user_id: customer.owner?.id ?? '',
            do_not_contact: customer.do_not_contact ?? false,
            service_restriction_note: customer.service_restriction_note ?? '',
            notes: customer.notes ?? '',
            tag_ids: (customer.tags ?? []).map((tag) => tag.id),
          }
        : EMPTY,
    );
    setNewTagName('');
  }, [open, customer]);

  const staffQuery = useQuery({
    queryKey: ['staff-assignable'],
    queryFn: opsApi.assignableStaff,
    enabled: open,
  });

  const tagsQuery = useQuery({
    queryKey: ['tags'],
    queryFn: opsApi.tags,
    enabled: open && canWriteTags,
  });

  const createTagMutation = useMutation({
    mutationFn: (name) => opsApi.createTag({ slug: slugify(name), name: name.trim() }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
      setNewTagName('');
      setDirty(true);
      setForm((current) => ({
        ...current,
        tag_ids: current.tag_ids.includes(created.id)
          ? current.tag_ids
          : [...current.tag_ids, created.id],
      }));
    },
  });

  // Duplicate candidates are looked up as soon as there is enough to match on.
  const duplicateKey = [form.full_name, form.email, form.phone].join('|');
  const duplicatesQuery = useQuery({
    queryKey: ['duplicate-check', duplicateKey, customer?.id ?? null],
    queryFn: () =>
      customersApi.duplicateCheck({
        full_name: form.full_name || null,
        email: form.email || null,
        phone: form.phone || null,
        country_code: form.country_code || null,
        exclude_customer_id: customer?.id ?? null,
      }),
    enabled: open && (form.full_name.length > 2 || form.email.length > 4 || form.phone.length > 5),
    staleTime: 5_000,
  });

  const candidates = duplicatesQuery.data?.candidates ?? [];
  const blockedByDuplicates = !isEdit && candidates.length > 0 && !acknowledgedDuplicates;

  const saveMutation = useMutation({
    mutationFn: (payload) =>
      isEdit ? customersApi.update(customer.id, payload) : customersApi.create(payload),
    onSuccess: (saved) => {
      // The response is the saved record, so the profile shows it at once (its internal
      // notes included) rather than the pre-save copy until the refetch lands (UAT round
      // 3). The duplicate flag is kept from the cached copy: only the profile read
      // computes it, and the refetch below brings the authoritative value.
      if (isEdit) {
        queryClient.setQueryData(['customer', String(saved.id)], (current) =>
          current
            ? { ...current, ...saved, has_duplicate_candidates: current.has_duplicate_candidates }
            : current,
        );
      }
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      queryClient.invalidateQueries({ queryKey: ['customer', String(saved.id)] });
      setDirty(false);
      onSaved?.(saved);
      onClose();
      if (!isEdit && navigateOnCreate) navigate(`/customers/${saved.id}`);
    },
    onError: (failure) => {
      const found = serverErrors(failure, t);
      if (Object.keys(found).length === 0) return;
      setErrors(found);
      setFailedSubmits((count) => count + 1);
    },
  });

  function update(key, value) {
    setDirty(true);
    setForm((current) => ({ ...current, [key]: value }));
    // An edited field's error is withdrawn; the rest stay until the next attempt.
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function toggleRouteInterest(route) {
    setDirty(true);
    setForm((current) => ({
      ...current,
      additional_route_interests: current.additional_route_interests.includes(route)
        ? current.additional_route_interests.filter((item) => item !== route)
        : [...current.additional_route_interests, route],
    }));
  }

  function toggleTag(tagId) {
    setDirty(true);
    setForm((current) => ({
      ...current,
      tag_ids: current.tag_ids.includes(tagId)
        ? current.tag_ids.filter((item) => item !== tagId)
        : [...current.tag_ids, tagId],
    }));
  }

  function requestClose() {
    // Unsaved-change protection (Design.md section 14).
    if (dirty && !window.confirm(t('states.unsavedChanges'))) return;
    onClose();
  }

  function onSubmit(event) {
    event.preventDefault();
    const found = localErrors(form);
    if (Object.keys(found).length > 0) {
      saveMutation.reset();
      setErrors(Object.fromEntries(Object.entries(found).map(([key, value]) => [key, t(value)])));
      setFailedSubmits((count) => count + 1);
      return;
    }
    setErrors({});
    saveMutation.mutate(toPayload(form, { includeTags: canWriteTags }));
  }

  const contactMissing = !form.phone.trim() && !form.email.trim();
  const error = saveMutation.error;
  const fieldError = (name) => errors[name];
  const entries = summaryEntries(errors);
  // A failure about a field lives in the summary; only one about nothing in particular
  // (a permission, the network) is shown for the whole form.
  const formError = error && Object.keys(serverErrors(error, t)).length === 0 ? error : null;

  const languageOptions = useMemo(
    () => LANGUAGES.map((value) => ({ value, label: t(`languages.${value}`) })),
    [t],
  );

  return (
    <Drawer
      open={open}
      onClose={requestClose}
      title={isEdit ? t('customers.editTitle') : t('customers.createTitle')}
      footer={
        <>
          <Button onClick={requestClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            type="submit"
            form="customer-form"
            loading={saveMutation.isPending}
            disabled={!form.full_name.trim() || contactMissing || blockedByDuplicates}
          >
            {isEdit ? t('common.save') : t('customers.add')}
          </Button>
        </>
      }
    >
      <form id="customer-form" className="stack" onSubmit={onSubmit} noValidate>
        <ErrorSummary errors={entries} summaryRef={summaryRef} fieldIds={FIELD_IDS} />
        {formError && <ErrorState error={formError} />}

        <fieldset className="form-section">
          <legend>{t('customers.sectionIdentity')}</legend>
          <Field
            id={FIELD_IDS.full_name}
            label={t('customers.fullName')}
            hint={t('customers.fullNameHint')}
            required
            error={fieldError('full_name')}
          >
            {(props) => (
              <TextInput
                {...props}
                value={form.full_name}
                onChange={(event) => update('full_name', event.target.value)}
                autoComplete="off"
              />
            )}
          </Field>

          <div className="form-grid">
            <Field id={FIELD_IDS.phone} label={t('customers.phone')} error={fieldError('phone')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="tel"
                  placeholder="+1 416 555 0100"
                  value={form.phone}
                  onChange={(event) => update('phone', event.target.value)}
                />
              )}
            </Field>
            <Field
              id={FIELD_IDS.email}
              label={t('customers.email')}
              hint={emailHeld ? t('customers.emailHeldByAccount') : undefined}
              error={fieldError('email')}
            >
              {(props) => (
                <TextInput
                  {...props}
                  type="email"
                  placeholder="name@example.com"
                  value={form.email}
                  readOnly={emailHeld}
                  onChange={(event) => update('email', event.target.value)}
                />
              )}
            </Field>
          </div>

          {contactMissing && (
            <p className="field__hint">{t('customers.contactRequirement')}</p>
          )}
        </fieldset>

        {candidates.length > 0 && (
          <div className="duplicate-panel">
            <Banner tone="warning" title={t('customers.duplicatePanelTitle')}>
              {t('customers.duplicatePanelBody')}
            </Banner>
            <ul className="duplicate-panel__list">
              {candidates.map((candidate) => (
                <li key={candidate.customer.id}>
                  <div className="row-wrap">
                    <span className="mono">{candidate.customer.public_id}</span>
                    <strong>{candidate.customer.full_name}</strong>
                    <StatusBadge
                      kind="lifecycle"
                      value={candidate.customer.lifecycle_status}
                    />
                  </div>
                  <p className="meta">
                    {t('customers.matchedOn')}: {candidate.matched_on.join(', ')} ·{' '}
                    {t('customers.confidence')} {candidate.confidence}%
                  </p>
                  <p className="meta">
                    {candidate.customer.phone_entered || '—'} · {candidate.customer.email_entered || '—'}
                  </p>
                  <Button
                    compact
                    onClick={() => {
                      onClose();
                      navigate(`/customers/${candidate.customer.id}`);
                    }}
                  >
                    {t('customers.openExisting')}
                  </Button>
                </li>
              ))}
            </ul>
            {!isEdit && (
              <Checkbox
                label={t('customers.createSeparate')}
                checked={acknowledgedDuplicates}
                onChange={(event) => setAcknowledgedDuplicates(event.target.checked)}
              />
            )}
          </div>
        )}

        <fieldset className="form-section">
          <legend>{t('customers.sectionLocation')}</legend>
          <div className="form-grid">
            <Field label={t('customers.city')}>
              {(props) => (
                <TextInput
                  {...props}
                  value={form.city}
                  onChange={(event) => update('city', event.target.value)}
                />
              )}
            </Field>
            <Field label={t('customers.provinceState')}>
              {(props) => (
                <TextInput
                  {...props}
                  value={form.province_state}
                  onChange={(event) => update('province_state', event.target.value)}
                />
              )}
            </Field>
            <Field label={t('customers.country')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.country_code}
                  onChange={(event) => update('country_code', event.target.value)}
                  placeholder={t('common.unknown')}
                  options={COUNTRIES}
                />
              )}
            </Field>
            <Field label={t('customers.preferredLanguage')} hint={t('customers.languageHint')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.preferred_language}
                  onChange={(event) => update('preferred_language', event.target.value)}
                  options={languageOptions}
                />
              )}
            </Field>
          </div>
        </fieldset>

        <fieldset className="form-section">
          <legend>{t('customers.sectionCategory')}</legend>
          <div className="form-grid">
            <Field label={t('customers.category')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.category}
                  onChange={(event) => update('category', event.target.value)}
                  options={[
                    { value: 'individual', label: 'Individual' },
                    { value: 'business', label: 'Business' },
                  ]}
                />
              )}
            </Field>
            {form.category === 'business' && (
              <>
                <Field label={t('customers.businessName')}>
                  {(props) => (
                    <TextInput
                      {...props}
                      value={form.business_name}
                      onChange={(event) => update('business_name', event.target.value)}
                    />
                  )}
                </Field>
                <Field label={t('customers.businessType')}>
                  {(props) => (
                    <Select
                      {...props}
                      value={form.business_type}
                      onChange={(event) => update('business_type', event.target.value)}
                      placeholder={t('common.unknown')}
                      options={[
                        { value: 'online_seller', label: 'Online seller' },
                        { value: 'retailer', label: 'Retailer' },
                        { value: 'other', label: 'Other' },
                      ]}
                    />
                  )}
                </Field>
              </>
            )}
          </div>
        </fieldset>

        <fieldset className="form-section">
          <legend>{t('customers.sectionPreferences')}</legend>
          <div className="form-grid">
            <Field label={t('customers.shippingPurpose')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.primary_shipping_purpose}
                  onChange={(event) => update('primary_shipping_purpose', event.target.value)}
                  options={PURPOSES.map((value) => ({
                    value,
                    label: value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase()),
                  }))}
                />
              )}
            </Field>
            <Field label={t('customers.primaryRoute')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.primary_route_group}
                  onChange={(event) => update('primary_route_group', event.target.value)}
                  placeholder={t('common.unknown')}
                  options={ROUTES.map((value) => ({ value, label: t(`routes.${value}`) }))}
                />
              )}
            </Field>
            <Field
              label={t('customers.shippingFrequency')}
              hint={t('customers.frequencyHint')}
            >
              {(props) => (
                <Select
                  {...props}
                  value={form.shipping_frequency}
                  onChange={(event) => update('shipping_frequency', event.target.value)}
                  options={FREQUENCIES.map((value) => ({
                    value,
                    label: value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase()),
                  }))}
                />
              )}
            </Field>
            <Field
              id={FIELD_IDS.estimated_monthly_shipments}
              label={t('customers.estimatedMonthly')}
              error={fieldError('estimated_monthly_shipments')}
            >
              {(props) => (
                <TextInput
                  {...props}
                  type="number"
                  min="0"
                  step="1"
                  value={form.estimated_monthly_shipments}
                  onChange={(event) => update('estimated_monthly_shipments', event.target.value)}
                />
              )}
            </Field>
          </div>

          <fieldset className="route-interests">
            <legend className="field__label">{t('customers.additionalRoutes')}</legend>
            <div className="row-wrap">
              {ROUTES.map((route) => (
                <Checkbox
                  key={route}
                  label={t(`routes.${route}`)}
                  checked={form.additional_route_interests.includes(route)}
                  onChange={() => toggleRouteInterest(route)}
                />
              ))}
            </div>
          </fieldset>
        </fieldset>

        <fieldset className="form-section">
          <legend>{t('customers.sectionContactPreference')}</legend>
          <div className="form-grid">
            <Field label={t('customers.contactChannel')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.preferred_contact_channel}
                  onChange={(event) => update('preferred_contact_channel', event.target.value)}
                  placeholder={t('common.unknown')}
                  options={CHANNELS.map((value) => ({
                    value,
                    label: value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase()),
                  }))}
                />
              )}
            </Field>
            <Field label={t('customers.bestContactTime')}>
              {(props) => (
                <TextInput
                  {...props}
                  placeholder="Weekday evenings"
                  value={form.best_contact_time}
                  onChange={(event) => update('best_contact_time', event.target.value)}
                />
              )}
            </Field>
          </div>
          <Checkbox
            label={t('customers.doNotContact')}
            hint={t('customers.doNotContactHint')}
            checked={form.do_not_contact}
            onChange={(event) => update('do_not_contact', event.target.checked)}
          />
          {form.do_not_contact && (
            <Field label={t('customers.restrictionNote')}>
              {(props) => (
                <TextInput
                  {...props}
                  value={form.service_restriction_note}
                  onChange={(event) => update('service_restriction_note', event.target.value)}
                />
              )}
            </Field>
          )}
          <p className="field__hint">
            Marketing consent is recorded separately on the customer profile, with its own
            evidence and history.
          </p>
        </fieldset>

        <fieldset className="form-section">
          <legend>{t('customers.sectionOwner')}</legend>
          <Field label={t('customers.owner')}>
            {(props) => (
              <Select
                {...props}
                value={form.owner_user_id}
                onChange={(event) => update('owner_user_id', event.target.value)}
                placeholder={t('common.none')}
                options={(staffQuery.data ?? []).map((member) => ({
                  value: member.id,
                  label: member.full_name,
                }))}
              />
            )}
          </Field>
          {canWriteTags && (
            <fieldset className="route-interests">
              <legend className="field__label">{t('customers.tags')}</legend>
              <p className="field__hint">{t('customers.tagsHint')}</p>
              {tagsQuery.data && tagsQuery.data.length === 0 && (
                <p className="meta">{t('customers.noTagsYet')}</p>
              )}
              <div className="row-wrap">
                {(tagsQuery.data ?? []).map((tag) => (
                  <Checkbox
                    key={tag.id}
                    label={tag.name}
                    checked={form.tag_ids.includes(tag.id)}
                    onChange={() => toggleTag(tag.id)}
                  />
                ))}
              </div>
              <div className="row-wrap">
                <label className="visually-hidden" htmlFor="new-tag-name">
                  {t('customers.newTag')}
                </label>
                <TextInput
                  id="new-tag-name"
                  value={newTagName}
                  placeholder={t('customers.newTag')}
                  maxLength={80}
                  onChange={(event) => setNewTagName(event.target.value)}
                  style={{ maxWidth: 240 }}
                />
                <Button
                  compact
                  disabled={!newTagName.trim() || createTagMutation.isPending}
                  loading={createTagMutation.isPending}
                  onClick={() => createTagMutation.mutate(newTagName)}
                >
                  {t('customers.addTag')}
                </Button>
              </div>
              {createTagMutation.error && (
                <p className="field__error">{createTagMutation.error.message}</p>
              )}
            </fieldset>
          )}
          <Field label={t('customers.notes')} hint={t('customers.notesHint')}>
            {(props) => (
              <TextArea
                {...props}
                value={form.notes}
                onChange={(event) => update('notes', event.target.value)}
                rows={4}
              />
            )}
          </Field>
        </fieldset>
      </form>
    </Drawer>
  );
}
