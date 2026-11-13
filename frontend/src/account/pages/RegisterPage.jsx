/**
 * Register.
 *
 * **Only the allowlisted fields.** `FIELD_MATRIX.md` §2 says "a registration form field
 * not in this table is a defect", and `app/core/account_fields.py` is that table as code.
 * Every key this form sends appears in `SUBMITTED_FIELD_KEYS` below, and
 * `backend/tests/test_account_registration_form.py` compares that list against the backend
 * allowlist — on the Python side, because that is where both lists can be read — so a
 * field added to one and not the other fails rather than 400s in front of a customer.
 *
 * **Three kinds of control, visibly separated** (OD-27, OD-37, OD-38):
 *
 * * *required* — a red asterisk beside the label, no words (RC-UAT-25 item 1, Ben
 *   2026-10-25; it was "(required)" in words before), and `aria-required` on the control;
 * * *optional* — "Optional" in words under the field, because a field with neither
 *   marking is a field people guess about;
 * * *consent* — the terms and privacy acknowledgement and the marketing choice, in their
 *   own fieldset, **separate from each other** and **both unchecked**. There is no
 *   `defaultChecked` anywhere in this file and the component library has no default either.
 *
 * **Address first, then billing** (UAT rounds 8, 9 and 11). The address (the pickup
 * address, `pickup_address.1`) is asked for first, and the billing address second, behind
 * "Billing address is the same as the address above". The box starts ticked (UAT round 11,
 * DEC-0158), so an untouched form shows no billing errors; ticked, the billing fields are
 * hidden and none is sent, and the server copies the address (`billing_same_as_shipping`).
 * Unticking shows empty billing fields. It is not a consent box: those start unchecked.
 *
 * **Both addresses are required** (UAT rounds 9 and 11): country, line 1, city, and
 * province or state for the address, and the same four for billing when the box is
 * unticked. The postal code is optional in every country (DEC-0159). One that is typed
 * for Canada or the United States must have a lenient shape (UAT round 12, DEC-0165);
 * other countries' are not checked. Each missing part or misshapen code gets its own
 * sentence beside the field and in the summary; the server refuses the first one with the
 * same words.
 *
 * **The password is typed twice** (UAT round 8), and a mismatch is an inline error beside
 * the second box before anything is sent. The server refuses it too.
 *
 * **The completion message discloses nothing.** The server answers every outcome —
 * created, already registered, suppressed, throttled — with one sentence, and this screen
 * navigates to the same confirmation for all of them. It never says an account exists, it
 * never reports a duplicate match, and it never shows a canonical customer id. It also
 * does **not** sign the person in: a session at this point would imply the application had
 * been approved, and approval is a staff act that has not happened.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import {
  Button,
  Card,
  CheckboxField,
  ErrorSummary,
  Field,
  Notice,
  SelectInput,
  TextInput,
} from '../components.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { isValidEmail } from '../../shared/email.js';
import { englishT, useAccountErrorText, useAccountLocale, useAccountT } from '../i18n.jsx';

/** Mirrors `app/core/enums.py::CustomerCategory`. */
const CUSTOMER_TYPES = [
  { value: 'individual', labelKey: 'register.typeIndividual' },
  { value: 'business', labelKey: 'register.typeBusiness' },
];

/** Mirrors `app/core/enums.py::BusinessType`. */
const BUSINESS_TYPES = [
  { value: 'online_seller', labelKey: 'register.businessOnlineSeller' },
  { value: 'retailer', labelKey: 'register.businessRetailer' },
  { value: 'other', labelKey: 'register.businessOther' },
];

/**
 * The countries the form offers guidance for.
 *
 * Three, because those are the three `app/core/countries.py` and the shipping routes
 * actually cover. A full ISO list would be a longer menu with no more meaning, and a free
 * text box would be refused by the normalizer.
 */
const COUNTRIES = [
  { value: 'CA', labelKey: 'register.countryCA' },
  { value: 'VN', labelKey: 'register.countryVN' },
  { value: 'US', labelKey: 'register.countryUS' },
];

/** `{value, labelKey}` options as the `{value, label}` pairs `SelectInput` renders. */
function translated(options, t) {
  return options.map(({ value, labelKey }) => ({ value, label: t(labelKey) }));
}

/**
 * What a phone number looks like in each country, and what the postal field is called.
 *
 * Guidance, not validation: the server parses the number against the country code that
 * arrived with it (`account_fields.normalize_field`, `region_from`), and this is so a
 * person types something that parses on the first attempt.
 */
const COUNTRY_GUIDANCE = {
  CA: {
    phone: 'register.phoneExampleCA',
    postal: 'register.postalCode',
    postalHint: 'register.postalExampleCA',
  },
  VN: {
    phone: 'register.phoneExampleVN',
    postal: 'register.postalCode',
    postalHint: 'register.postalExampleVN',
  },
  US: {
    phone: 'register.phoneExampleUS',
    postal: 'register.zipCode',
    postalHint: 'register.postalExampleUS',
  },
};

/**
 * Every `customer.*` key this form can send.
 *
 * Kept as data so a test can compare it with the backend allowlist. The billing and pickup
 * address prefixes are expanded here rather than built by string concatenation at submit
 * time, because a concatenated key is a key nobody can grep for.
 */
export const SUBMITTED_FIELD_KEYS = [
  'customer_type',
  'business_type',
  'legal_name',
  'display_name',
  'primary_contact_name',
  'email',
  'phone_country_code',
  'phone',
  'preferred_language',
  'marketing_consent',
  'billing_address.address_line1',
  'billing_address.address_line2',
  'billing_address.city',
  'billing_address.province_state',
  'billing_address.postal_code',
  'billing_address.country_code',
  'pickup_address.1.address_line1',
  'pickup_address.1.address_line2',
  'pickup_address.1.city',
  'pickup_address.1.province_state',
  'pickup_address.1.postal_code',
  'pickup_address.1.country_code',
  'pickup_address.1.contact_name',
  'pickup_address.1.phone',
  'pickup_address.1.delivery_note',
];

/** The operational topics a customer may switch on (`CUSTOMER_SETTABLE_TOPICS`). */
const NOTIFICATION_TOPICS = [
  { value: 'shipment_milestones', labelKey: 'register.topicMilestones' },
  { value: 'delivery_outcome', labelKey: 'register.topicDelivered' },
];

const MIN_PASSWORD_LENGTH = 12;

/**
 * The sentences the server uses for the second password box (`customer_auth_service`).
 * These exported constants are the **English** copy, which the tests compare against; the
 * screen renders the catalogue entry for the active language.
 */
export const PASSWORD_CONFIRMATION_MISSING = englishT('common.passwordMissing');
export const PASSWORD_CONFIRMATION_MISMATCH = englishT('common.passwordMismatch');

export const ADDRESS_LEGEND = englishT('register.addressLegend');
export const BILLING_SAME_LABEL = englishT('register.billingSame');
export const DRIVER_NOTE_LABEL = englishT('register.driverNote');

const SHIPPING_PREFIX = 'pickup_address.1.';
const BILLING_PREFIX = 'billing_address.';

/**
 * The address parts registration requires (UAT rounds 9 and 11), in screen order. Mirrors
 * `REQUIRED_ADDRESS_PARTS` in `app/api/account/routes.py`. Line 2 and the postal code stay
 * optional.
 */
export const REQUIRED_ADDRESS_PARTS = ['country_code', 'address_line1', 'city', 'province_state'];

/**
 * The server's sentence for a missing part (`address_part_missing_message`). English unless
 * a translator is passed.
 */
export function addressPartMissingMessage(part, { billing = false, t = englishT } = {}) {
  const which = billing ? 'Billing' : '';
  if (part === 'country_code') return t(`register.missing${which}Country`);
  if (part === 'address_line1') return t(`register.missing${which}Line1`);
  if (part === 'city') return t(`register.missing${which}City`);
  return t(`register.missing${which}Province`);
}

/**
 * The lenient shape a typed postal code must have (UAT round 12, DEC-0165). Mirrors
 * `POSTAL_CODE_SHAPES` in `app/core/account_fields.py`: Canada is letter, digit, letter,
 * an optional space, digit, letter, digit, in any case; the United States is five digits or
 * ZIP+4. Other countries have no entry and are not checked.
 */
export const POSTAL_CODE_SHAPES = {
  CA: /^[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9]$/,
  US: /^[0-9]{5}(?:-[0-9]{4})?$/,
};

/**
 * The server's sentence for a misshapen code (`postal_code_format_message`). English unless
 * a translator is passed.
 */
export function postalCodeFormatMessage(countryCode, { billing = false, t = englishT } = {}) {
  if (countryCode === 'US') {
    return t(billing ? 'register.billingZipFormat' : 'register.zipFormat');
  }
  return t(billing ? 'register.billingPostalFormat' : 'register.postalFormat');
}

/**
 * The sentence for a typed postal code that does not fit its country, or null. A blank one
 * is always fine (DEC-0159). Spaces are collapsed first, as the server does.
 */
export function postalCodeError(countryCode, value, { billing = false, t = englishT } = {}) {
  const typed = (value || '').trim().replace(/\s+/g, ' ');
  const shape = POSTAL_CODE_SHAPES[countryCode];
  if (!typed || !shape || shape.test(typed)) return null;
  return postalCodeFormatMessage(countryCode, { billing, t });
}

/** The fields this form can show an error beside, and so link to from the summary. */
const LINKED_FIELDS = [
  'email',
  'password',
  'password_confirmation',
  'business_type',
  'legal_name',
  ...REQUIRED_ADDRESS_PARTS.map((part) => `${SHIPPING_PREFIX}${part}`),
  `${SHIPPING_PREFIX}postal_code`,
  'billing_same_as_shipping',
  ...REQUIRED_ADDRESS_PARTS.map((part) => `${BILLING_PREFIX}${part}`),
  `${BILLING_PREFIX}postal_code`,
  'accept_terms',
];

/** The billing fields as they are when the box is unticked: empty, country Canada. */
const EMPTY_BILLING = {
  'billing_address.address_line1': '',
  'billing_address.address_line2': '',
  'billing_address.city': '',
  'billing_address.province_state': '',
  'billing_address.postal_code': '',
  'billing_address.country_code': 'CA',
};

const EMPTY = {
  email: '',
  password: '',
  password_confirmation: '',
  customer_type: 'individual',
  business_type: '',
  legal_name: '',
  display_name: '',
  primary_contact_name: '',
  phone_country_code: 'CA',
  phone: '',
  'billing_address.address_line1': '',
  'billing_address.address_line2': '',
  'billing_address.city': '',
  'billing_address.province_state': '',
  'billing_address.postal_code': '',
  'billing_address.country_code': 'CA',
  'pickup_address.1.address_line1': '',
  'pickup_address.1.address_line2': '',
  'pickup_address.1.city': '',
  'pickup_address.1.province_state': '',
  'pickup_address.1.postal_code': '',
  'pickup_address.1.country_code': 'CA',
  'pickup_address.1.contact_name': '',
  'pickup_address.1.phone': '',
  'pickup_address.1.delivery_note': '',
};

/**
 * A stable key for the submission.
 *
 * Minted once per mounted form and reused on every retry, so a double-click, a slow
 * network or a refresh-and-resubmit reaches the server as one registration. It is a random
 * value with no meaning, generated in the browser; the server mints its own when a client
 * sends none, so this is a courtesy rather than a requirement.
 */
function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `ca-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export function RegisterPage() {
  const navigate = useNavigate();
  const t = useAccountT();
  const { locale } = useAccountLocale();
  const errorText = useAccountErrorText();
  const [values, setValues] = useState(EMPTY);
  // Both start false, and there is no code path that starts either true (OD-27, OD-38).
  const [acceptTerms, setAcceptTerms] = useState(false);
  const [marketingConsent, setMarketingConsent] = useState(false);
  const [topics, setTopics] = useState([]);
  // Starts ticked (UAT round 11, DEC-0158). Not a consent control.
  const [billingSame, setBillingSame] = useState(true);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [unavailable, setUnavailable] = useState(null);
  const summaryRef = useRef(null);
  const idempotencyKey = useMemo(newIdempotencyKey, []);

  // Focus the summary **after** it has rendered. Calling `focus()` in the submit handler
  // reaches a ref that is still null, because the summary only exists once `errors` is
  // non-empty and that state has not been committed yet. An effect keyed on `errors` runs
  // at the right moment, and `errors` is only ever set by a submit attempt, so this does
  // not steal focus at any other time.
  useEffect(() => {
    if (Object.keys(errors).length > 0) summaryRef.current?.focus();
  }, [errors]);

  const isBusiness = values.customer_type === 'business';
  const phoneGuidance = COUNTRY_GUIDANCE[values.phone_country_code] || COUNTRY_GUIDANCE.CA;
  const billingGuidance =
    COUNTRY_GUIDANCE[values['billing_address.country_code']] || COUNTRY_GUIDANCE.CA;
  const pickupGuidance =
    COUNTRY_GUIDANCE[values['pickup_address.1.country_code']] || COUNTRY_GUIDANCE.CA;

  /**
   * The page's own sentence for a field the server refused, in the screen's language. The
   * server sends the same sentences in English; here they come from the catalogue.
   */
  function serverFieldMessage(field) {
    for (const prefix of [SHIPPING_PREFIX, BILLING_PREFIX]) {
      if (!field.startsWith(prefix)) continue;
      const part = field.slice(prefix.length);
      const billing = prefix === BILLING_PREFIX;
      if (REQUIRED_ADDRESS_PARTS.includes(part)) {
        return addressPartMissingMessage(part, { billing, t });
      }
      if (part === 'postal_code') {
        return postalCodeFormatMessage(values[`${prefix}country_code`], { billing, t });
      }
      return null;
    }
    const direct = {
      email: t('register.invalidEmail'),
      password: t('common.useAtLeast', { count: MIN_PASSWORD_LENGTH }),
      password_confirmation: t('common.passwordMismatch'),
      legal_name: isBusiness ? t('register.enterBusinessName') : t('register.enterLegalName'),
      business_type: t('register.chooseBusiness'),
      accept_terms: t('register.acceptTermsError'),
    };
    return direct[field] ?? null;
  }

  // Local checks are sentences already; a server refusal is the error, worded here.
  const shownErrors = Object.fromEntries(
    Object.entries(errors).map(([key, value]) => [
      key,
      typeof value === 'string' ? value : errorText(value, { fieldMessage: serverFieldMessage }),
    ]),
  );

  function set(key, value) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function chooseBillingSame(on) {
    setBillingSame(on);
    // Unticking shows empty billing fields rather than a copy of the address above.
    if (!on) setValues((current) => ({ ...current, ...EMPTY_BILLING }));
  }

  function toggleTopic(topic, on) {
    setTopics((current) =>
      on ? [...new Set([...current, topic])] : current.filter((item) => item !== topic),
    );
  }

  /**
   * Client-side checks are **format only**, and only where the answer is obvious without a
   * lookup. Anything that needs the database — whether an address is registered, whether a
   * customer matches — is not checked here and is not reported by the server either.
   */
  function localErrors() {
    const found = {};
    if (!values.email.trim()) found.email = t('register.enterEmail');
    // The same shape the server checks, and its sentence, so a mistyped address is in the
    // summary with everything else rather than coming back alone after a round trip (UAT
    // round 5).
    // (`register.invalidEmail` is `INVALID_EMAIL_MESSAGE` from `shared/email.js` in English.)
    else if (!isValidEmail(values.email)) found.email = t('register.invalidEmail');
    if (values.password.length < MIN_PASSWORD_LENGTH) {
      found.password = t('common.useAtLeast', { count: MIN_PASSWORD_LENGTH });
    }
    if (!values.password_confirmation) {
      found.password_confirmation = t('common.passwordMissing');
    } else if (values.password_confirmation !== values.password) {
      found.password_confirmation = t('common.passwordMismatch');
    }
    if (!values.legal_name.trim()) {
      found.legal_name = isBusiness ? t('register.enterBusinessName') : t('register.enterLegalName');
    }
    if (isBusiness && !values.business_type) {
      found.business_type = t('register.chooseBusiness');
    }
    // Screen order, so the summary reads top to bottom: the address, then billing when
    // the box is unticked (UAT round 9). A blank postal code is not an error (round 11); a
    // typed one must fit its own block's country (round 12).
    const prefixes = billingSame ? [SHIPPING_PREFIX] : [SHIPPING_PREFIX, BILLING_PREFIX];
    prefixes.forEach((prefix) => {
      const billing = prefix === BILLING_PREFIX;
      REQUIRED_ADDRESS_PARTS.forEach((part) => {
        if (!values[`${prefix}${part}`].trim()) {
          found[`${prefix}${part}`] = addressPartMissingMessage(part, { billing, t });
        }
      });
      const postalProblem = postalCodeError(
        values[`${prefix}country_code`],
        values[`${prefix}postal_code`],
        { billing, t },
      );
      if (postalProblem) found[`${prefix}postal_code`] = postalProblem;
    });
    if (!acceptTerms) {
      found.accept_terms = t('register.acceptTermsError');
    }
    return found;
  }

  function buildCustomerPayload() {
    const customer = {};
    SUBMITTED_FIELD_KEYS.forEach((key) => {
      if (key === 'marketing_consent' || key === 'preferred_language') return;
      if (key === 'business_type' && !isBusiness) return;
      // Ticked: no billing key is sent, and the server copies the address above.
      if (billingSame && key.startsWith(BILLING_PREFIX)) return;
      const value = values[key];
      if (typeof value === 'string' && value.trim()) customer[key] = value.trim();
    });
    // The account address is also the customer's contact address. Sent under its own
    // allowlisted key rather than inferred by the server from the login address.
    if (values.email.trim()) customer.email = values.email.trim();
    // The language the form was filled in (OD-71: Vietnamese first, English as an option;
    // under OD-39 this was always 'en'). Sent explicitly so the stored preference is a
    // recorded answer rather than a column default.
    customer.preferred_language = locale;
    // Always sent, true or false. The absence of a key and an explicit `false` mean the
    // same thing to the server, and sending the explicit value makes the record say that
    // the question was asked and answered.
    customer.marketing_consent = marketingConsent ? 'true' : 'false';
    return customer;
  }

  async function onSubmit(event) {
    event.preventDefault();
    const found = localErrors();
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    try {
      await accountApi.register({
        email: values.email.trim(),
        password: values.password,
        password_confirmation: values.password_confirmation,
        billing_same_as_shipping: billingSame,
        accept_terms: acceptTerms,
        accept_privacy: acceptTerms,
        customer: buildCustomerPayload(),
        notification_topics: topics,
        idempotency_key: idempotencyKey,
      });
      // One destination for every outcome. The confirmation says the same sentence the
      // server said, and the server says the same sentence whatever happened.
      navigate('/account/check-your-email', { replace: true, state: { from: 'register' } });
    } catch (error) {
      if (error instanceof AccountApiError && error.isRateLimited) {
        // A refused registration reads exactly as an accepted one (UAT round 3). The
        // per-address limit already answers with the ordinary body; the per-IP limit
        // answers 429, and showing "Too many requests" here would be the one screen that
        // differs. Same destination, same words.
        navigate('/account/check-your-email', { replace: true, state: { from: 'register' } });
        return;
      }
      if (error instanceof AccountApiError && error.status === 503) {
        // Registration is switched off by configuration — no email provider (OD-34) or no
        // approved terms version (OD-37). The message is the server's and says nothing
        // about which gate is closed or how it is configured.
        setUnavailable(error);
        return;
      }
      if (error instanceof AccountApiError && error.field) {
        // A field the form shows gets its error beside it and a linked summary entry; a
        // field it does not show is reported for the whole form, so no link goes nowhere.
        setErrors(
          LINKED_FIELDS.includes(error.field)
            ? { [error.field]: error }
            : { form: error },
        );
        return;
      }
      setErrors({ form: error });
    } finally {
      setSubmitting(false);
    }
  }

  if (unavailable) {
    return (
      <AccountNarrowPage>
        <AccountPageHeader title={t('register.unavailableTitle')} />
        <Card>
          <Notice tone="info" title={t('register.unavailableNotice')}>
            <p>{errorText(unavailable)}</p>
          </Notice>
          <p>
            {t('register.unavailableBefore')}{' '}
            <Link to="/track">{t('register.unavailableLink')}</Link>
            {t('register.unavailableAfter')}
          </p>
        </Card>
      </AccountNarrowPage>
    );
  }

  return (
    <AccountNarrowPage>
      <AccountPageHeader
        title={t('register.title')}
        intro={t('register.intro')}
      />

      <Card>
        <Notice tone="info" title={t('register.reviewNotice')}>
          <p>{t('register.reviewBody')}</p>
        </Notice>

        <ErrorSummary
          errors={shownErrors}
          headingId="ca-register-errors"
          summaryRef={summaryRef}
          linkedFields={LINKED_FIELDS}
        />

        <form className="ca-form" onSubmit={onSubmit} noValidate>
          <fieldset className="ca-fieldset">
            <legend className="ca-fieldset__legend">{t('register.signInDetails')}</legend>

            <Field label={t('common.emailAddress')} required fieldKey="email" error={shownErrors.email}>
              {({ id, describedBy, invalid }) => (
                <TextInput
                  id={id}
                  describedBy={describedBy}
                  invalid={invalid}
                  type="email"
                  name="email"
                  autoComplete="username"
                  inputMode="email"
                  maxLength={320}
                  value={values.email}
                  onChange={(event) => set('email', event.target.value)}
                />
              )}
            </Field>

            <Field
              label={t('common.password')}
              required
              fieldKey="password"
              error={shownErrors.password}
              hint={t('register.passwordHint', { count: MIN_PASSWORD_LENGTH })}
            >
              {({ id, describedBy, invalid }) => (
                <TextInput
                  id={id}
                  describedBy={describedBy}
                  invalid={invalid}
                  type="password"
                  name="new-password"
                  autoComplete="new-password"
                  minLength={MIN_PASSWORD_LENGTH}
                  maxLength={200}
                  value={values.password}
                  onChange={(event) => set('password', event.target.value)}
                />
              )}
            </Field>

            <Field
              label={t('register.confirmPassword')}
              required
              fieldKey="password_confirmation"
              error={shownErrors.password_confirmation}
              hint={t('register.confirmPasswordHint')}
            >
              {({ id, describedBy, invalid }) => (
                <TextInput
                  id={id}
                  describedBy={describedBy}
                  invalid={invalid}
                  type="password"
                  name="confirm-password"
                  autoComplete="new-password"
                  maxLength={200}
                  value={values.password_confirmation}
                  onChange={(event) => set('password_confirmation', event.target.value)}
                />
              )}
            </Field>
          </fieldset>

          <fieldset className="ca-fieldset">
            <legend className="ca-fieldset__legend">{t('register.aboutYou')}</legend>

            <Field label={t('register.shippingAs')} required>
              {({ id, describedBy }) => (
                <SelectInput
                  id={id}
                  describedBy={describedBy}
                  options={translated(CUSTOMER_TYPES, t)}
                  value={values.customer_type}
                  onChange={(event) => set('customer_type', event.target.value)}
                />
              )}
            </Field>

            {isBusiness ? (
              <Field
                label={t('register.kindOfBusiness')}
                required
                fieldKey="business_type"
                error={shownErrors.business_type}
              >
                {({ id, describedBy, invalid }) => (
                  <SelectInput
                    id={id}
                    describedBy={describedBy}
                    invalid={invalid}
                    options={translated(BUSINESS_TYPES, t)}
                    placeholder={t('register.chooseOne')}
                    value={values.business_type}
                    onChange={(event) => set('business_type', event.target.value)}
                  />
                )}
              </Field>
            ) : null}

            <Field
              label={isBusiness ? t('register.businessName') : t('register.legalName')}
              required
              fieldKey="legal_name"
              error={shownErrors.legal_name}
              hint={
                isBusiness ? t('register.businessNameHint') : t('register.legalNameHint')
              }
            >
              {({ id, describedBy, invalid }) => (
                <TextInput
                  id={id}
                  describedBy={describedBy}
                  invalid={invalid}
                  name="legal-name"
                  autoComplete={isBusiness ? 'organization' : 'name'}
                  maxLength={200}
                  value={values.legal_name}
                  onChange={(event) => set('legal_name', event.target.value)}
                />
              )}
            </Field>

            <Field
              label={t('register.displayName')}
              optional
              hint={t('register.displayNameHint')}
            >
              {({ id, describedBy }) => (
                <TextInput
                  id={id}
                  describedBy={describedBy}
                  name="display-name"
                  autoComplete="nickname"
                  maxLength={200}
                  value={values.display_name}
                  onChange={(event) => set('display_name', event.target.value)}
                />
              )}
            </Field>

            {isBusiness ? (
              <Field label={t('register.mainContact')} optional>
                {({ id, describedBy }) => (
                  <TextInput
                    id={id}
                    describedBy={describedBy}
                    name="contact-name"
                    autoComplete="name"
                    maxLength={200}
                    value={values.primary_contact_name}
                    onChange={(event) => set('primary_contact_name', event.target.value)}
                  />
                )}
              </Field>
            ) : null}

            <div className="ca-field-pair">
              <Field label={t('register.phoneCountry')} optional>
                {({ id, describedBy }) => (
                  <SelectInput
                    id={id}
                    describedBy={describedBy}
                    options={translated(COUNTRIES, t)}
                    value={values.phone_country_code}
                    onChange={(event) => set('phone_country_code', event.target.value)}
                  />
                )}
              </Field>
              <Field label={t('register.phoneNumber')} optional hint={t(phoneGuidance.phone)}>
                {({ id, describedBy }) => (
                  <TextInput
                    id={id}
                    describedBy={describedBy}
                    type="tel"
                    name="phone"
                    autoComplete="tel"
                    inputMode="tel"
                    maxLength={60}
                    value={values.phone}
                    onChange={(event) => set('phone', event.target.value)}
                  />
                )}
              </Field>
            </div>
          </fieldset>

          {/* The address first, billing second (UAT rounds 8 and 9). */}
          <AddressFieldset
            legend={t('register.addressLegend')}
            description={t('register.addressDescription')}
            prefix={SHIPPING_PREFIX}
            section="section-shipping shipping"
            values={values}
            set={set}
            guidance={pickupGuidance}
            errors={shownErrors}
            withContact
          />

          <AddressFieldset
            legend={t('register.billingLegend')}
            description={t('register.billingDescription')}
            prefix={BILLING_PREFIX}
            section="section-billing billing"
            values={values}
            set={set}
            guidance={billingGuidance}
            errors={shownErrors}
            hidden={billingSame}
            lead={
              <CheckboxField
                name="billing-same-as-shipping"
                label={t('register.billingSame')}
                hint={billingSame ? t('register.billingSameOn') : t('register.billingSameOff')}
                checked={billingSame}
                onChange={chooseBillingSame}
                fieldKey="billing_same_as_shipping"
                error={shownErrors.billing_same_as_shipping}
              />
            }
          />

          <fieldset className="ca-fieldset">
            <legend className="ca-fieldset__legend">{t('register.emailLegend')}</legend>
            <p className="ca-fieldset__description">{t('register.emailDescription')}</p>
            {NOTIFICATION_TOPICS.map((topic) => (
              <CheckboxField
                key={topic.value}
                name={`topic-${topic.value}`}
                label={t(topic.labelKey)}
                checked={topics.includes(topic.value)}
                onChange={(on) => toggleTopic(topic.value, on)}
              />
            ))}
            <p className="ca-fieldset__note">{t('register.emailNote')}</p>
          </fieldset>

          <fieldset className="ca-fieldset ca-fieldset--consent">
            <legend className="ca-fieldset__legend">{t('register.termsLegend')}</legend>

            <CheckboxField
              name="accept-terms"
              label={t('register.acceptTerms')}
              hint={t('register.acceptTermsHint')}
              checked={acceptTerms}
              onChange={setAcceptTerms}
              fieldKey="accept_terms"
              error={shownErrors.accept_terms}
            />

            <Notice tone="warning" title={t('register.termsDraftTitle')}>
              <p>{t('register.termsDraftBody')}</p>
            </Notice>

            <CheckboxField
              name="marketing-consent"
              label={t('register.marketing')}
              hint={t('register.marketingHint')}
              checked={marketingConsent}
              onChange={setMarketingConsent}
            />
          </fieldset>

          {shownErrors.form ? (
            <Notice tone="error" title={t('register.failed')}>
              <p>{shownErrors.form}</p>
            </Notice>
          ) : null}

          <div className="ca-form__actions">
            <Button type="submit" busy={submitting}>
              {t('register.submit')}
            </Button>
          </div>
        </form>

        <ul className="ca-links">
          <li>
            <Link to="/account/sign-in">{t('register.haveAccount')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}

/**
 * One address block. Used twice, with different prefixes, so the two cannot drift apart.
 *
 * Country, line 1, city, and province or state are required (UAT rounds 9 and 11, owner
 * decisions): for the address always, and for billing whenever the block is shown, which
 * is whenever the "same" box is unticked. Line 2, the postal code and the pickup-only
 * parts stay optional; a typed Canadian or United States postal code is shape-checked.
 *
 * `section` is the autofill section token, so a phone's address autofill can fill the
 * address and billing blocks separately rather than writing one address into both.
 */
function AddressFieldset({
  legend,
  description,
  prefix,
  section,
  values,
  set,
  guidance,
  errors = {},
  withContact,
  lead = null,
  hidden = false,
}) {
  return (
    <fieldset className="ca-fieldset">
      <legend className="ca-fieldset__legend">{legend}</legend>
      <p className="ca-fieldset__description">{description}</p>
      {lead}
      {hidden ? null : (
        <AddressFields
          prefix={prefix}
          section={section}
          values={values}
          set={set}
          guidance={guidance}
          errors={errors}
          withContact={withContact}
        />
      )}
    </fieldset>
  );
}

/** A required address part: a red asterisk, its error beside it, linked from the summary. */
function RequiredAddressText({
  prefix,
  part,
  label,
  hint,
  section,
  autoComplete,
  maxLength,
  values,
  set,
  errors,
}) {
  const key = `${prefix}${part}`;
  return (
    <Field label={label} required fieldKey={key} error={errors[key]} hint={hint}>
      {({ id, describedBy, invalid }) => (
        <TextInput
          id={id}
          describedBy={describedBy}
          invalid={invalid}
          autoComplete={`${section} ${autoComplete}`}
          maxLength={maxLength}
          value={values[key]}
          onChange={(event) => set(key, event.target.value)}
        />
      )}
    </Field>
  );
}

function AddressFields({ prefix, section, values, set, guidance, errors, withContact }) {
  const t = useAccountT();
  const shared = { prefix, section, values, set, errors };
  const countryKey = `${prefix}country_code`;
  const postalKey = `${prefix}postal_code`;
  return (
    <>
      <Field label={t('register.country')} required fieldKey={countryKey} error={errors[countryKey]}>
        {({ id, describedBy, invalid }) => (
          <SelectInput
            id={id}
            describedBy={describedBy}
            invalid={invalid}
            options={translated(COUNTRIES, t)}
            value={values[countryKey]}
            onChange={(event) => set(countryKey, event.target.value)}
          />
        )}
      </Field>

      <RequiredAddressText
        {...shared}
        part="address_line1"
        label={t('register.line1')}
        autoComplete="address-line1"
        maxLength={255}
      />

      <Field label={t('register.line2')} optional>
        {({ id, describedBy }) => (
          <TextInput
            id={id}
            describedBy={describedBy}
            autoComplete={`${section} address-line2`}
            maxLength={255}
            value={values[`${prefix}address_line2`]}
            onChange={(event) => set(`${prefix}address_line2`, event.target.value)}
          />
        )}
      </Field>

      <div className="ca-field-pair">
        <RequiredAddressText
          {...shared}
          part="city"
          label={t('register.city')}
          autoComplete="address-level2"
          maxLength={120}
        />
        <RequiredAddressText
          {...shared}
          part="province_state"
          label={t('register.province')}
          autoComplete="address-level1"
          maxLength={120}
        />
      </div>

      {/* Optional in every country (UAT round 11, DEC-0159). A typed one is shape-checked
          for Canada and the United States only (UAT round 12, DEC-0165). */}
      <Field
        label={t(guidance.postal)}
        optional
        fieldKey={postalKey}
        error={errors[postalKey]}
        hint={t(guidance.postalHint)}
      >
        {({ id, describedBy, invalid }) => (
          <TextInput
            id={id}
            describedBy={describedBy}
            invalid={invalid}
            autoComplete={`${section} postal-code`}
            maxLength={30}
            value={values[postalKey]}
            onChange={(event) => set(postalKey, event.target.value)}
          />
        )}
      </Field>

      {withContact ? (
        <>
          <Field label={t('register.driverAsk')} optional>
            {({ id, describedBy }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                maxLength={200}
                value={values[`${prefix}contact_name`]}
                onChange={(event) => set(`${prefix}contact_name`, event.target.value)}
              />
            )}
          </Field>
          <Field label={t('register.pickupPhone')} optional hint={t(guidance.phone)}>
            {({ id, describedBy }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                type="tel"
                inputMode="tel"
                maxLength={60}
                value={values[`${prefix}phone`]}
                onChange={(event) => set(`${prefix}phone`, event.target.value)}
              />
            )}
          </Field>
          <Field label={t('register.driverNote')} optional>
            {({ id, describedBy }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                maxLength={400}
                value={values[`${prefix}delivery_note`]}
                onChange={(event) => set(`${prefix}delivery_note`, event.target.value)}
              />
            )}
          </Field>
        </>
      ) : null}
    </>
  );
}
