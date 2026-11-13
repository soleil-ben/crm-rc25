/**
 * My profile (fix pack 2; CA-PRF-01 … CA-PRF-04; FIELD_MATRIX.md §3 and §4).
 *
 * Four things, and the difference between them is the point of the screen:
 *
 * * **What is on file** — read-only. The customer reference, names, phone, email and
 *   pickup address exactly as Solaris Express holds them.
 * * **Preferred language** — the language Solaris Express uses to contact the customer.
 *   It changes at once. It is **not** the language of these screens, which the header
 *   switch chooses (OD-71); a saved preference is applied to the screens at the next
 *   sign-in or reload, and this page says where the switch is.
 * * **Request a change** — a name, phone or pickup-address correction becomes a request a
 *   member of staff reviews. Nothing on file changes until then, and the page says that
 *   before and after the request is sent. Email is not offered: it is the sign-in address,
 *   and changing it needs a verification step that is not built.
 * * **Marketing messages** — an explicit choice, never pre-ticked, recorded with a time.
 *   Withdrawing always takes effect. When an opt-in cannot be delivered the response says
 *   so with one boolean, `delivery_blocked`, and the screen says so plainly. It never says
 *   why: the response carries no reason to say (UAT round 3).
 *
 * Nothing staff-only is rendered because nothing staff-only is in the response.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AccountPageHeader } from '../AccountLayout.jsx';
import { accountApi } from '../accountApi.js';
import {
  Button,
  Card,
  DetailRow,
  Field,
  Loading,
  Notice,
  SelectInput,
  TextInput,
} from '../components.jsx';
import {
  useAccountErrorText,
  useAccountFormat,
  useAccountT,
  useServerSentence,
} from '../i18n.jsx';

const PROFILE_KEY = ['account', 'profile'];

/** Language names, in the language of the screen. */
const LANGUAGE_NAMES = {
  en: 'profile.languageEn',
  vi: 'profile.languageVi',
  fr: 'profile.languageFr',
  other: 'profile.languageOther',
};

/** The form's fields, in the order a person reads an address. */
const CHANGE_FIELDS = [
  { key: 'legal_name', labelKey: 'profile.legalName', autoComplete: 'name' },
  { key: 'display_name', labelKey: 'profile.preferredCalled', autoComplete: 'nickname' },
  { key: 'phone', labelKey: 'profile.phone', autoComplete: 'tel', type: 'tel' },
];

const ADDRESS_FIELDS = [
  { part: 'contact_name', labelKey: 'profile.addrContact', autoComplete: 'name' },
  { part: 'address_line1', labelKey: 'profile.addrLine1', autoComplete: 'address-line1' },
  { part: 'address_line2', labelKey: 'profile.addrLine2', autoComplete: 'address-line2' },
  { part: 'city', labelKey: 'profile.addrCity', autoComplete: 'address-level2' },
  { part: 'province_state', labelKey: 'profile.addrProvince', autoComplete: 'address-level1' },
  { part: 'postal_code', labelKey: 'profile.addrPostal', autoComplete: 'postal-code' },
  { part: 'country_code', labelKey: 'profile.addrCountry', autoComplete: 'country' },
];

/** A proposal field's label, as the request list shows it. */
function fieldLabel(fieldKey, t) {
  const direct = {
    legal_name: 'profile.legalName',
    display_name: 'profile.preferredName',
    phone: 'profile.phone',
    phone_country_code: 'profile.phoneCountry',
  }[fieldKey];
  if (direct) return t(direct);
  const prefix = 'pickup_address.1.';
  if (!fieldKey.startsWith(prefix)) return fieldKey;
  const part = fieldKey.slice(prefix.length);
  const labelKey =
    ADDRESS_FIELDS.find((item) => item.part === part)?.labelKey ??
    { phone: 'profile.addrPhone', delivery_note: 'profile.addrNote' }[part];
  if (!labelKey) return fieldKey;
  return t('profile.pickupField', { field: t(labelKey).toLowerCase() });
}

const STATUS_WORDS = {
  pending: 'profile.statusPending',
  approved: 'profile.statusApproved',
  rejected: 'profile.statusRejected',
  withdrawn: 'profile.statusWithdrawn',
  superseded: 'profile.statusSuperseded',
};

const MARKETING_WORDS = {
  granted: 'profile.marketingGranted',
  withdrawn: 'profile.marketingWithdrawn',
  not_given: 'profile.marketingNotGiven',
};

function marketingBlocked(marketing) {
  return marketing.status === 'granted' && marketing.delivery_blocked === true;
}

function addressLines(address, notRecorded) {
  if (!address) return notRecorded;
  const lines = [
    address.contact_name,
    address.address_line1,
    address.address_line2,
    [address.city, address.province_state, address.postal_code].filter(Boolean).join(', '),
    address.country_code,
  ].filter(Boolean);
  return lines.length ? lines.join(' · ') : notRecorded;
}

export function ProfilePage() {
  const queryClient = useQueryClient();
  const headingRef = useRef(null);
  const [language, setChosenLanguage] = useState('');
  const [change, setChange] = useState({});
  // `{tone, key}` for the screen's own sentences, `{tone, text}` for the server's.
  const [notice, setNotice] = useState(null);
  const t = useAccountT();
  const { formatDateTime, notRecorded } = useAccountFormat();
  const errorText = useAccountErrorText();
  const serverSentence = useServerSentence();

  const profile = useQuery({ queryKey: PROFILE_KEY, queryFn: () => accountApi.profile() });

  useEffect(() => {
    if (profile.data) setChosenLanguage(profile.data.details.preferred_language);
  }, [profile.data]);

  const languageOptions = useMemo(
    () =>
      (profile.data?.languages ?? []).map((value) => ({
        value,
        label: LANGUAGE_NAMES[value] ? t(LANGUAGE_NAMES[value]) : value,
      })),
    [profile.data, t],
  );

  function settle(message) {
    setNotice(message);
    queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
  }

  const languageMutation = useMutation({
    mutationFn: () => accountApi.updateProfileDirect({ preferred_language: language }),
    onSuccess: (data) => {
      queryClient.setQueryData(PROFILE_KEY, data);
      setNotice({ tone: 'success', key: 'profile.languageSaved' });
    },
  });

  const proposalMutation = useMutation({
    mutationFn: () => {
      const fields = Object.fromEntries(
        Object.entries(change).filter(([, value]) => String(value ?? '').trim() !== ''),
      );
      return accountApi.proposeProfileChange(fields);
    },
    onSuccess: (data) => {
      setChange({});
      settle({ tone: 'success', text: data.message, key: 'profile.proposalSent', server: true });
    },
  });

  const withdrawMutation = useMutation({
    mutationFn: () => accountApi.withdrawProfileChange(),
    onSuccess: (data) => {
      queryClient.setQueryData(PROFILE_KEY, data);
      setNotice({ tone: 'success', key: 'profile.withdrawn' });
    },
  });

  const marketingMutation = useMutation({
    mutationFn: (granted) => accountApi.recordMarketingChoice(granted),
    onSuccess: (data) =>
      settle({ tone: 'success', key: MARKETING_WORDS[data.marketing.status] }),
  });

  if (profile.isPending) return <Loading label={t('profile.loading')} />;
  if (profile.error) {
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('profile.title')} headingRef={headingRef} />
        <Notice tone="error" title={t('profile.loadFailed')}>
          <p>{errorText(profile.error)}</p>
        </Notice>
      </div>
    );
  }

  const data = profile.data;
  const details = data.details;
  const pending = data.proposals.find((item) => item.status === 'pending');
  const changeField = (key) => ({
    value: change[key] ?? '',
    onChange: (event) => setChange((current) => ({ ...current, [key]: event.target.value })),
  });
  const fieldError = (mutation, key) =>
    mutation.error?.field === key ? errorText(mutation.error) : undefined;

  return (
    <div className="ca-wide">
      <AccountPageHeader
        title={t('profile.title')}
        headingRef={headingRef}
        intro={t('profile.intro')}
      />

      {notice ? (
        <Notice
          tone={notice.tone}
          title={notice.server ? serverSentence(notice.text, notice.key) : t(notice.key)}
        />
      ) : null}

      <Card title={t('profile.onFile')}>
        <dl className="ca-detail-grid">
          <DetailRow label={t('profile.customerReference')}>
            <span className="ca-mono">{details.customer_reference}</span>
          </DetailRow>
          <DetailRow label={t('profile.legalName')}>{details.legal_name || notRecorded}</DetailRow>
          <DetailRow label={t('profile.preferredName')}>
            {details.display_name || notRecorded}
          </DetailRow>
          <DetailRow label={t('profile.emailSignIn')}>{details.email || notRecorded}</DetailRow>
          <DetailRow label={t('profile.phone')}>{details.phone || notRecorded}</DetailRow>
          <DetailRow label={t('profile.pickupAddress')}>
            {addressLines(details.pickup_address, notRecorded)}
          </DetailRow>
        </dl>
      </Card>

      <Card title={t('profile.languageCard')}>
        <p>{t('profile.languageBody')}</p>
        {languageMutation.error ? (
          <Notice tone="error" title={t('common.couldNotSave')}>
            <p>{errorText(languageMutation.error)}</p>
          </Notice>
        ) : null}
        <form
          className="ca-form"
          onSubmit={(event) => {
            event.preventDefault();
            languageMutation.mutate();
          }}
        >
          <Field label={t('profile.contactIn')} error={fieldError(languageMutation, 'preferred_language')}>
            {({ id, describedBy, invalid }) => (
              <SelectInput
                id={id}
                describedBy={describedBy}
                invalid={invalid}
                value={language}
                onChange={(event) => setChosenLanguage(event.target.value)}
                options={languageOptions}
              />
            )}
          </Field>
          <div className="ca-form__actions">
            <Button
              type="submit"
              busy={languageMutation.isPending}
              disabled={language === details.preferred_language}
            >
              {t('profile.saveLanguage')}
            </Button>
          </div>
        </form>
      </Card>

      <Card title={t('profile.changeCard')}>
        <p>{t('profile.changeBody')}</p>
        {pending ? (
          <Notice tone="info" title={t('profile.alreadyPending')}>
            <p>{t('profile.alreadyPendingBody')}</p>
          </Notice>
        ) : null}
        {proposalMutation.error && !proposalMutation.error.field ? (
          <Notice tone="error" title={t('common.couldNotSend')}>
            <p>{errorText(proposalMutation.error)}</p>
          </Notice>
        ) : null}
        <form
          className="ca-form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            proposalMutation.mutate();
          }}
        >
          {CHANGE_FIELDS.map(({ key, labelKey, autoComplete, type }) => (
            <Field key={key} label={t(labelKey)} optional error={fieldError(proposalMutation, key)}>
              {({ id, describedBy, invalid }) => (
                <TextInput
                  id={id}
                  describedBy={describedBy}
                  invalid={invalid}
                  type={type || 'text'}
                  autoComplete={autoComplete}
                  maxLength={200}
                  {...changeField(key)}
                />
              )}
            </Field>
          ))}
          <fieldset className="ca-fieldset">
            <legend>{t('profile.newPickup')}</legend>
            {ADDRESS_FIELDS.map(({ part, labelKey, autoComplete }) => {
              const key = `pickup_address.1.${part}`;
              return (
                <Field key={key} label={t(labelKey)} optional error={fieldError(proposalMutation, key)}>
                  {({ id, describedBy, invalid }) => (
                    <TextInput
                      id={id}
                      describedBy={describedBy}
                      invalid={invalid}
                      autoComplete={autoComplete}
                      maxLength={part === 'country_code' ? 2 : 255}
                      {...changeField(key)}
                    />
                  )}
                </Field>
              );
            })}
          </fieldset>
          <div className="ca-form__actions">
            <Button
              type="submit"
              busy={proposalMutation.isPending}
              disabled={!Object.values(change).some((value) => String(value ?? '').trim())}
            >
              {t('profile.sendForReview')}
            </Button>
          </div>
        </form>
      </Card>

      <Card title={t('profile.requestsCard')}>
        {data.proposals.length === 0 ? (
          <p>{t('profile.noRequests')}</p>
        ) : (
          <ul className="ca-request-list">
            {data.proposals.map((proposal) => (
              <li key={`${proposal.submitted_at}-${proposal.status}`} className="ca-request">
                <p className="ca-request__head">
                  <strong>
                    {STATUS_WORDS[proposal.status] ? t(STATUS_WORDS[proposal.status]) : proposal.status}
                  </strong>
                  {t('profile.sentOn')}
                  {formatDateTime(proposal.submitted_at, data.timezone)}
                </p>
                <ul className="ca-request__fields">
                  {proposal.fields.map((item) => (
                    <li key={item.field_key}>
                      {fieldLabel(item.field_key, t)}: {item.proposed_value}
                      {proposal.status === 'approved' || proposal.status === 'rejected'
                        ? item.applied
                          ? t('profile.changed')
                          : t('profile.notChanged')
                        : ''}
                    </li>
                  ))}
                </ul>
                {proposal.status === 'pending' ? (
                  <Button
                    variant="secondary"
                    busy={withdrawMutation.isPending}
                    onClick={() => withdrawMutation.mutate()}
                  >
                    {t('profile.withdraw')}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t('profile.marketingCard')}>
        <p>{t(MARKETING_WORDS[data.marketing.status])}</p>
        {/* Beside the choice it qualifies, and a status region, so it is announced when an
            opt-in brings it into view. */}
        {marketingBlocked(data.marketing) ? (
          <Notice tone="info" title={t('profile.marketingBlocked')} />
        ) : null}
        {data.marketing.changed_at ? (
          <p className="ca-meta">
            {t('profile.lastChanged', {
              date: formatDateTime(data.marketing.changed_at, data.timezone),
            })}
          </p>
        ) : null}
        <p>{t('profile.marketingExplain')}</p>
        {marketingMutation.error ? (
          <Notice tone="error" title={t('common.couldNotSave')}>
            <p>{errorText(marketingMutation.error)}</p>
          </Notice>
        ) : null}
        <div className="ca-form__actions">
          {data.marketing.status === 'granted' ? (
            <Button
              variant="secondary"
              busy={marketingMutation.isPending}
              onClick={() => marketingMutation.mutate(false)}
            >
              {t('profile.stopMarketing')}
            </Button>
          ) : (
            <Button busy={marketingMutation.isPending} onClick={() => marketingMutation.mutate(true)}>
              {t('profile.startMarketing')}
            </Button>
          )}
        </div>
        {data.marketing_history.length > 0 ? (
          <details className="ca-history">
            <summary>{t('profile.marketingHistory')}</summary>
            <ul>
              {data.marketing_history.map((entry) => (
                <li key={`${entry.recorded_at}-${entry.status}`}>
                  {entry.status === 'granted' ? t('profile.agreed') : t('profile.withdrew')} —{' '}
                  {formatDateTime(entry.recorded_at, data.timezone)}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </Card>
    </div>
  );
}
