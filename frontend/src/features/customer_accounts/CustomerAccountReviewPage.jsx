/**
 * One Customer Account application: the proposal, the duplicates, the preview, the
 * acknowledgement, and the four decisions.
 *
 * ## The order is the point
 *
 * A reviewer cannot approve until they have taken a preview and acknowledged it. That is
 * enforced by the server — `approve_*` refuses with a 409 when no acknowledgement matches
 * the current fingerprint — and this screen makes the order visible rather than letting
 * somebody discover it by pressing a button. The approve controls do not exist until an
 * acknowledgement for the *current* fingerprint does.
 *
 * ## The fingerprint, and why a stale one is not an error to route around
 *
 * The preview carries a digest over the facts it showed: the proposed values, the current
 * canonical values, the duplicate classification, the target customer and the five
 * disclosure figures. The decision sends it back. If anything moved in between — somebody
 * edited the customer, the applicant submitted again, a shipment was booked — the server
 * recomputes a different digest and refuses with a 409.
 *
 * When that happens this screen **discards the acknowledgement and takes a fresh
 * preview**. It does not retry with the new fingerprint, and it does not ask "approve
 * anyway?". The acknowledgement is a statement that a person read a specific set of
 * figures; a fingerprint that no longer matches means they read different ones.
 *
 * ## What is deliberately absent
 *
 * No password or token information, no session data, no raw captured mail, no shipment
 * beyond the five OD-29 figures, no financial value, and no proposal field that the
 * decision does not need. None of it is in the response to render — the Phase 10 schemas
 * are allowlists — and `tests/customerAccountReview.test.jsx` plants sentinels to prove
 * the screen would not render them if they were.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Checkbox,
  Field,
  Modal,
  Select,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { ApiError } from '../../api/client.js';
import { customerAccountReviewApi } from '../../api/endpoints.js';
import { formatDate, formatDateTime } from '../../utils/format.js';
import { SignInEmailChange } from './SignInEmailChange.jsx';
import './customer_accounts.css';


/**
 * One label/value pair. The staff profile page has its own; this is a second because the
 * two live in different features and a shared one would be a shared one somebody has to
 * change for both.
 */
function DetailRow({ label, children }) {
  return (
    <div className="ca-review-row">
      <dt>{label}</dt>
      <dd>{children ?? '—'}</dd>
    </div>
  );
}

/** `app/core/account_enums.py::ApprovalAction`. */
const CREATE_NEW = 'create_new';
const LINK_EXISTING = 'link_existing';

/** `SeparateCustomerReason`. Bounded, never prose. */
const OVERRIDE_REASONS = ['different_party', 'candidate_not_usable', 'shared_contact_detail'];

/** `RejectionReason`. Bounded, and never shown to the customer. */
const REJECTION_REASONS = [
  'unverifiable_details',
  'duplicate_application',
  'identity_not_established',
  'service_restriction',
  'abuse_or_test',
];

/** Classifications that make creating a separate customer a decision rather than a default. */
const OVERRIDE_REQUIRED = new Set(['exact', 'probable']);

function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `dec-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

/** Bounded reason codes, mirrored from `app/schemas/customer_account_review.py`. */
const SUSPEND_REASONS = ['security_concern', 'customer_request', 'staff_review', 'abuse_or_test'];
const REINSTATE_REASONS = ['review_complete', 'customer_request', 'suspended_in_error'];
/** RC-UAT-21 Phase B (DEC-0231): `REACTIVATE_REASON_CODES`. */
const REACTIVATE_REASONS = ['deactivated_in_error', 'customer_request', 'review_complete'];
const DEACTIVATE_REASONS = [
  'customer_request',
  'privacy_request',
  'security_concern',
  'duplicate_account',
  'abuse_or_test',
];

/**
 * The account's lifecycle state and the two controls that change it: suspend and
 * reinstate (Sprint 13 Lane A, A-1; fix pack of 2026-10-14).
 *
 * Rendered for every account the reference resolves to -- pending, active or already
 * suspended -- which is why it has its own read rather than riding on the registration:
 * the registration routes refuse an identity with no pending proposal, and an account
 * approved months ago is exactly the one a suspension is about.
 *
 * Deactivation (DEC-0126, UAT round 4) is offered only to a holder of
 * `customer_account:deactivate`, which is Admin alone, and only after a reason code and a
 * confirmation: it is permanent for the account. The server checks the same permission.
 */
export function AccountStatusCard({ accountReference, mayApprove }) {
  const t = useT();
  const { can } = useSession();
  const mayDeactivate = can(P.CUSTOMER_ACCOUNT_DEACTIVATE);
  const queryClient = useQueryClient();
  const [reason, setReason] = useState('');
  const [deactivateReason, setDeactivateReason] = useState('');
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [reactivateReason, setReactivateReason] = useState('');
  const [reactivateNote, setReactivateNote] = useState('');
  const [notice, setNotice] = useState(null);

  const identity = useQuery({
    queryKey: ['customer-account', 'identity', accountReference],
    queryFn: () => customerAccountReviewApi.identity(accountReference),
  });

  /**
   * Re-read the registration beside this card so its status line agrees -- but only when
   * there is one on screen. On a decided account that read is a 409 with no data, and a
   * refetch puts it back to "pending", which unmounts this card and its confirmation.
   */
  function refreshRegistration() {
    const key = ['customer-account', 'registration', accountReference];
    const shown = queryClient.getQueryData(key) !== undefined;
    queryClient.invalidateQueries({ queryKey: key, refetchType: shown ? 'active' : 'none' });
  }

  const change = useMutation({
    mutationFn: (kind) =>
      kind === 'suspend'
        ? customerAccountReviewApi.suspend(accountReference, { reason_code: reason })
        : customerAccountReviewApi.reinstate(accountReference, { reason_code: reason }),
    onSuccess: (updated, kind) => {
      // The server's own answer is the state; the registration beside it is re-read so
      // its status line agrees.
      queryClient.setQueryData(['customer-account', 'identity', accountReference], updated);
      refreshRegistration();
      setReason('');
      setNotice(t(kind === 'suspend' ? 'customerAccounts.suspended' : 'customerAccounts.reinstated'));
    },
  });

  const deactivate = useMutation({
    mutationFn: () =>
      customerAccountReviewApi.deactivate(accountReference, { reason_code: deactivateReason }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['customer-account', 'identity', accountReference], updated);
      refreshRegistration();
      setDeactivateReason('');
      setConfirmDeactivate(false);
      setNotice(t('customerAccounts.deactivated'));
    },
  });

  const reactivate = useMutation({
    mutationFn: () =>
      customerAccountReviewApi.reactivate(accountReference, {
        reason_code: reactivateReason,
        note: reactivateNote.trim() || null,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['customer-account', 'identity', accountReference], updated);
      queryClient.invalidateQueries({ queryKey: ['customer-account', 'deactivated'] });
      refreshRegistration();
      setReactivateReason('');
      setReactivateNote('');
      setNotice(t('customerAccounts.reactivated'));
    },
  });

  if (identity.isPending) return <SkeletonRows rows={2} />;
  if (identity.error) {
    return <ErrorState error={identity.error} onRetry={() => identity.refetch()} />;
  }

  const account = identity.data;
  const action = account.can_suspend ? 'suspend' : account.can_reinstate ? 'reinstate' : null;
  const reasons = action === 'suspend' ? SUSPEND_REASONS : REINSTATE_REASONS;

  return (
    <Card title={t('customerAccounts.statusTitle')}>
      {notice && <Banner tone="info">{notice}</Banner>}
      <dl className="ca-review-list">
        <DetailRow label={t('customerAccounts.statusLabel')}>
          <StatusBadge
            tone={account.status === 'active' ? 'success' : account.status === 'suspended' ? 'warning' : 'neutral'}
            value={account.status}
            label={t(`customerAccounts.status.${account.status}`, account.status)}
          />
        </DetailRow>
        <DetailRow label={t('customerAccounts.loginAddress')}>{account.account_email_entered}</DetailRow>
        <DetailRow label={t('customerAccounts.statusLinkedCustomer')}>
          {account.linked_customer_public_id ? (
            <span className="mono">{account.linked_customer_public_id}</span>
          ) : (
            t('customerAccounts.statusNotLinked')
          )}
        </DetailRow>
        {account.suspended_at && (
          <DetailRow label={t('customerAccounts.suspendedSince')}>
            {formatDateTime(account.suspended_at)}
          </DetailRow>
        )}
        {account.deactivated_at && (
          <DetailRow label={t('customerAccounts.deactivatedSince')}>
            {formatDateTime(account.deactivated_at)}
          </DetailRow>
        )}
        {account.status_reason_code && (
          <DetailRow label={t('customerAccounts.statusReason')}>
            {t(`customerAccounts.statusReasonCode.${account.status_reason_code}`, account.status_reason_code)}
          </DetailRow>
        )}
      </dl>

      {mayApprove && action && (
        <div className="stack">
          <p className="meta">
            {action === 'suspend'
              ? t('customerAccounts.suspendHint')
              : t('customerAccounts.reinstateHint')}
          </p>
          {change.error && <Banner tone="danger">{change.error.message}</Banner>}
          <Field
            label={
              action === 'suspend'
                ? t('customerAccounts.suspendReason')
                : t('customerAccounts.reinstateReason')
            }
          >
            {(fieldProps) => (
              <Select
                {...fieldProps}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t('customerAccounts.chooseReason')}
                options={reasons.map((value) => ({
                  value,
                  label: t(`customerAccounts.statusReasonCode.${value}`, value),
                }))}
              />
            )}
          </Field>
          <div className="row-wrap">
            <Button
              variant={action === 'suspend' ? 'danger' : 'primary'}
              disabled={!reason || change.isPending}
              loading={change.isPending}
              onClick={() => change.mutate(action)}
            >
              {action === 'suspend'
                ? t('customerAccounts.suspendAction')
                : t('customerAccounts.reinstateAction')}
            </Button>
          </div>
        </div>
      )}

      {mayDeactivate && account.can_deactivate && (
        <div className="stack">
          <h3 className="card__title">{t('customerAccounts.deactivateTitle')}</h3>
          <p className="meta">{t('customerAccounts.deactivateHint')}</p>
          {deactivate.error && !confirmDeactivate && (
            <Banner tone="danger">{deactivate.error.message}</Banner>
          )}
          <Field label={t('customerAccounts.deactivateReason')}>
            {(fieldProps) => (
              <Select
                {...fieldProps}
                value={deactivateReason}
                onChange={(event) => setDeactivateReason(event.target.value)}
                placeholder={t('customerAccounts.chooseReason')}
                options={DEACTIVATE_REASONS.map((value) => ({
                  value,
                  label: t(`customerAccounts.statusReasonCode.${value}`, value),
                }))}
              />
            )}
          </Field>
          <div className="row-wrap">
            <Button
              variant="danger"
              disabled={!deactivateReason || deactivate.isPending}
              onClick={() => setConfirmDeactivate(true)}
            >
              {t('customerAccounts.deactivateAction')}
            </Button>
          </div>
        </div>
      )}

      {/* RC-UAT-25 item 2: only an Admin changes a sign-in email. */}
      {mayDeactivate && <SignInEmailChange account={account} onChanged={setNotice} />}

      {mayDeactivate && account.status === 'deactivated' && (
        <div className="stack">
          <h3 className="card__title">{t('customerAccounts.reactivateTitle')}</h3>
          {account.can_reactivate ? (
            <>
              <p className="meta">{t('customerAccounts.reactivateHint')}</p>
              {reactivate.error && <Banner tone="danger">{reactivate.error.message}</Banner>}
              <Field label={t('customerAccounts.reactivateReason')}>
                {(fieldProps) => (
                  <Select
                    {...fieldProps}
                    value={reactivateReason}
                    onChange={(event) => setReactivateReason(event.target.value)}
                    placeholder={t('customerAccounts.chooseReason')}
                    options={REACTIVATE_REASONS.map((value) => ({
                      value,
                      label: t(`customerAccounts.statusReasonCode.${value}`, value),
                    }))}
                  />
                )}
              </Field>
              <Field label={t('customerAccounts.reactivateNote')}>
                {(fieldProps) => (
                  <TextArea
                    {...fieldProps}
                    rows={2}
                    maxLength={500}
                    value={reactivateNote}
                    onChange={(event) => setReactivateNote(event.target.value)}
                  />
                )}
              </Field>
              <div className="row-wrap">
                <Button
                  variant="primary"
                  disabled={!reactivateReason || reactivate.isPending}
                  loading={reactivate.isPending}
                  onClick={() => reactivate.mutate()}
                >
                  {t('customerAccounts.reactivateAction')}
                </Button>
              </div>
            </>
          ) : (
            <p className="meta">{t('customerAccounts.reactivateRefused')}</p>
          )}
        </div>
      )}

      <Modal
        open={confirmDeactivate}
        onClose={() => setConfirmDeactivate(false)}
        title={t('customerAccounts.deactivateConfirmTitle').replace('{reference}', accountReference)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDeactivate(false)}>
              {t('common.cancel')}
            </Button>
            <span className="spacer" />
            <Button
              variant="danger"
              loading={deactivate.isPending}
              disabled={deactivate.isPending}
              onClick={() => deactivate.mutate()}
            >
              {t('customerAccounts.deactivateConfirm')}
            </Button>
          </>
        }
      >
        {deactivate.error && <Banner tone="danger">{deactivate.error.message}</Banner>}
        <p>{t('customerAccounts.deactivateConfirmBody')}</p>
      </Modal>
    </Card>
  );
}

export function CustomerAccountReviewPage() {
  const t = useT();
  const { accountReference } = useParams();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const mayApprove = can(P.CUSTOMER_ACCOUNT_APPROVE);

  const [action, setAction] = useState(CREATE_NEW);
  const [targetCustomer, setTargetCustomer] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [acknowledgedFingerprint, setAcknowledgedFingerprint] = useState(null);
  const [overrideReason, setOverrideReason] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');
  const [internalDetail, setInternalDetail] = useState('');
  const [conflict, setConflict] = useState(null);
  const [outcome, setOutcome] = useState(null);
  const outcomeRef = useRef(null);
  const conflictRef = useRef(null);

  // One key per mounted screen. A double-click, a slow response or a retry after a
  // network blip reaches the server as one decision, and the server reports `replayed`
  // rather than writing a second time.
  const idempotencyKey = useMemo(newIdempotencyKey, []);

  const registration = useQuery({
    queryKey: ['customer-account', 'registration', accountReference],
    queryFn: () => customerAccountReviewApi.registration(accountReference),
  });

  /**
   * The three reads are **chained, not parallel**, and that is not a preference.
   *
   * Each of them writes an audit row and commits — looking at an application, running the
   * duplicate calculation and taking a preview are three accesses to personal data, and
   * Phase 10 records each one. Issued at once against SQLite they are three write
   * transactions racing, and the loser gets `database is locked`. The first version of
   * this screen fired all three on mount and produced exactly that, twenty-nine times, in
   * one Playwright run.
   *
   * Chaining also happens to be the order a reviewer reads them in.
   */
  const duplicates = useQuery({
    queryKey: ['customer-account', 'duplicates', accountReference],
    queryFn: () => customerAccountReviewApi.duplicateCandidates(accountReference),
    enabled: registration.isSuccess,
  });

  const previewParams = useMemo(
    () => ({
      action,
      customer_public_id: action === LINK_EXISTING ? targetCustomer || undefined : undefined,
    }),
    [action, targetCustomer],
  );

  const preview = useQuery({
    queryKey: ['customer-account', 'preview', accountReference, previewParams],
    queryFn: () => customerAccountReviewApi.preview(accountReference, previewParams),
    // Third in the chain, and only once there is something to preview: a link-existing
    // preview needs a customer, and asking for one without it would be a 422 the reviewer
    // did not cause.
    enabled: duplicates.isSuccess && (action === CREATE_NEW || Boolean(targetCustomer)),
  });

  const fingerprint = preview.data?.fingerprint ?? null;

  // The acknowledgement belongs to one fingerprint. When the preview changes — because the
  // reviewer switched action, chose a different customer, or refreshed after a conflict —
  // the acknowledgement is withdrawn and has to be given again.
  useEffect(() => {
    if (acknowledgedFingerprint && acknowledgedFingerprint !== fingerprint) {
      setAcknowledged(false);
      setAcknowledgedFingerprint(null);
    }
  }, [fingerprint, acknowledgedFingerprint]);

  useEffect(() => {
    if (conflict) conflictRef.current?.focus();
  }, [conflict]);

  useEffect(() => {
    if (outcome) outcomeRef.current?.focus();
  }, [outcome]);

  /** A 409 withdraws the acknowledgement and refetches the preview. Always, no exceptions. */
  const handleFailure = useCallback(
    (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setAcknowledged(false);
        setAcknowledgedFingerprint(null);
        setConflict(error.message);
        preview.refetch();
        return;
      }
      setConflict(error.message);
    },
    [preview],
  );

  const acknowledge = useMutation({
    mutationFn: () =>
      customerAccountReviewApi.acknowledgeDisclosure(accountReference, {
        action,
        customer_public_id: action === LINK_EXISTING ? targetCustomer : null,
        fingerprint,
      }),
    onSuccess: (response) => {
      setConflict(null);
      setAcknowledged(true);
      // The fingerprint the **server** confirmed, not the one the client sent. If they
      // differ, the client's is the stale one.
      setAcknowledgedFingerprint(response.fingerprint);
    },
    onError: handleFailure,
  });

  const decide = useMutation({
    mutationFn: async (kind) => {
      if (kind === 'reject') {
        return customerAccountReviewApi.reject(accountReference, {
          reason_code: rejectionReason,
          idempotency_key: `${idempotencyKey}-reject`,
          internal_detail: internalDetail || null,
        });
      }
      if (action === LINK_EXISTING) {
        return customerAccountReviewApi.approveLinkExisting(accountReference, {
          customer_public_id: targetCustomer,
          preview_fingerprint: fingerprint,
          idempotency_key: `${idempotencyKey}-link`,
        });
      }
      return customerAccountReviewApi.approveCreateNew(accountReference, {
        preview_fingerprint: fingerprint,
        idempotency_key: `${idempotencyKey}-create`,
        override_reason_code: overrideReason || null,
      });
    },
    onSuccess: (result) => {
      setConflict(null);
      setOutcome(result);
      // UAT round 3: the Application card kept saying "Waiting for review" after a
      // decision. Refetching this account's registration cannot fix that -- a decided
      // account has no pending proposal, so the read answers 409 (after retries) and the
      // screen would swap the outcome banner for the "already decided" page. The
      // server's own answer is the state, so it is written in directly.
      queryClient.setQueryData(
        ['customer-account', 'registration', accountReference],
        (current) =>
          current && {
            ...current,
            status: result.status,
            has_active_link: result.status === 'active' ? true : current.has_active_link,
          },
      );
      // Everything under the prefix -- the queue, this account's identity, registration,
      // duplicates and preview -- is marked stale without a refetch now, so the next
      // screen that shows any of them reads it again (and a revisit of this one lands on
      // the "already decided" page). Nothing is refetched on this screen: this account's
      // own reads would each 409 for the same reason.
      queryClient.invalidateQueries({ queryKey: ['customer-account'], refetchType: 'none' });
      // An approval creates or links a customer record; both lists and every cached
      // record are re-read so the customer side agrees.
      if (result.customer_public_id) {
        queryClient.invalidateQueries({ queryKey: ['customer'] });
        queryClient.invalidateQueries({ queryKey: ['customers'] });
      }
    },
    onError: handleFailure,
  });

  if (registration.isPending) return <SkeletonRows rows={8} />;

  // An application that has already been decided is **not an error**. The server refuses
  // it with a 409 — there is no pending proposal to review — and the first version of
  // this screen rendered that through `ErrorState`, which says "Something went wrong"
  // above a sentence explaining that nothing had. A reviewer who opens a decided
  // application from a bookmark, from the browser's history, or by pressing Back after
  // approving needs to read what happened, not an apology (§11's idempotent completion
  // state). Found by the Phase 12 browser suite.
  if (registration.error instanceof ApiError && registration.error.status === 409) {
    return (
      <>
        <PageHeader
          title={accountReference}
          subtitle={t('customerAccounts.decidedSubtitle')}
          breadcrumb={<Link to="/customer-accounts">{t('customerAccounts.backToQueue')}</Link>}
        />
        <Card>
          <Banner tone="neutral" title={t('customerAccounts.decidedTitle')}>
            <p>{registration.error.message}</p>
            <p>{t('customerAccounts.decidedBody')}</p>
          </Banner>
          <p>
            <Link to="/customer-accounts">{t('customerAccounts.backToQueue')}</Link>
          </p>
        </Card>
        {/* A decided account is exactly the one a suspension is about. */}
        <AccountStatusCard accountReference={accountReference} mayApprove={mayApprove} />
      </>
    );
  }

  if (registration.error) {
    return <ErrorState error={registration.error} onRetry={() => registration.refetch()} />;
  }

  const application = registration.data;
  const classification = duplicates.data?.duplicate_classification ?? 'none';
  const candidates = duplicates.data?.candidates ?? [];
  const overrideNeeded = action === CREATE_NEW && OVERRIDE_REQUIRED.has(classification);
  const previewData = preview.data;
  const writesCanonical = action === CREATE_NEW;

  const canApprove =
    mayApprove &&
    acknowledged &&
    acknowledgedFingerprint === fingerprint &&
    Boolean(fingerprint) &&
    !previewData?.mapping_refusal &&
    (action === CREATE_NEW ? !overrideNeeded || Boolean(overrideReason) : Boolean(targetCustomer));

  return (
    <>
      <PageHeader
        title={application.account_reference}
        subtitle={t('customerAccounts.reviewSubtitle')}
        breadcrumb={
          <Link to="/customer-accounts">{t('customerAccounts.backToQueue')}</Link>
        }
      />

      {outcome ? (
        <div tabIndex={-1} ref={outcomeRef}>
          <Banner
            tone={outcome.outcome === 'rejected' ? 'warning' : 'success'}
            title={t(`customerAccounts.outcome.${outcome.outcome}`)}
          >
            <p>
              {outcome.replayed
                ? t('customerAccounts.outcomeReplayed')
                : t('customerAccounts.outcomeRecorded')}
            </p>
            {outcome.customer_public_id ? (
              <p>
                {t('customerAccounts.outcomeCustomer')}{' '}
                <strong>{outcome.customer_public_id}</strong>
              </p>
            ) : null}
            <p>
              <Link to="/customer-accounts">{t('customerAccounts.backToQueue')}</Link>
            </p>
          </Banner>
        </div>
      ) : null}

      {conflict ? (
        <div tabIndex={-1} ref={conflictRef}>
          <Banner tone="warning" title={t('customerAccounts.conflictTitle')}>
            <p>{conflict}</p>
            <p>{t('customerAccounts.conflictBody')}</p>
          </Banner>
        </div>
      ) : null}

      <Card title={t('customerAccounts.applicationTitle')}>
        <dl className="ca-review-list">
          <DetailRow label={t('customerAccounts.state')}>
            {t(`customerAccounts.status.${application.status}`)}
          </DetailRow>
          <DetailRow label={t('customerAccounts.submitted')}>
            {formatDateTime(application.submitted_at)}
          </DetailRow>
          <DetailRow label={t('customerAccounts.emailConfirmed')}>
            {application.email_verified_at
              ? formatDateTime(application.email_verified_at)
              : t('customerAccounts.notConfirmed')}
          </DetailRow>
          <DetailRow label={t('customerAccounts.loginAddress')}>
            {application.account_email_entered}
          </DetailRow>
          <DetailRow label={t('customerAccounts.normalizedAddress')}>
            {application.account_email_normalized}
          </DetailRow>
          <DetailRow label={t('customerAccounts.alreadyLinked')}>
            {application.has_active_link ? t('common.yes') : t('common.no')}
          </DetailRow>
        </dl>
      </Card>

      <Card title={t('customerAccounts.proposalTitle')} flush>
        <div className="table-wrap">
          <table className="table table--stacked">
            <caption className="visually-hidden">{t('customerAccounts.proposalTitle')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('customerAccounts.field')}</th>
                <th scope="col">{t('customerAccounts.submittedValue')}</th>
                <th scope="col">{t('customerAccounts.normalizedValue')}</th>
              </tr>
            </thead>
            <tbody>
              {application.fields.map((field) => (
                <tr key={field.field_key}>
                  <td data-label={t('customerAccounts.field')} className="table__primary">
                    {field.field_key}
                  </td>
                  <td data-label={t('customerAccounts.submittedValue')}>
                    {field.proposed_value ?? '—'}
                  </td>
                  <td data-label={t('customerAccounts.normalizedValue')}>
                    {field.proposed_value_normalized ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={t('customerAccounts.duplicatesTitle')}>
        {duplicates.isPending && <SkeletonRows rows={3} />}
        {duplicates.error && (
          <ErrorState error={duplicates.error} onRetry={() => duplicates.refetch()} />
        )}
        {duplicates.data && (
          <>
            <p>
              <StatusBadge
                tone={classification === 'none' ? 'neutral' : 'warning'}
                value={classification}
                label={t(`customerAccounts.classification.${classification}`)}
              />
            </p>
            {candidates.length === 0 ? (
              <p>{t('customerAccounts.noCandidates')}</p>
            ) : (
              <div className="table-wrap">
                <table className="table table--stacked">
                  <caption className="visually-hidden">
                    {t('customerAccounts.duplicatesTitle')}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('customerAccounts.customer')}</th>
                      <th scope="col">{t('customerAccounts.name')}</th>
                      <th scope="col">{t('customerAccounts.location')}</th>
                      <th scope="col">{t('customerAccounts.matchedOn')}</th>
                      <th scope="col">{t('customerAccounts.confidence')}</th>
                      <th scope="col">{t('customerAccounts.linkable')}</th>
                      <th scope="col">{t('customerAccounts.rowActions')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((candidate) => (
                      <tr key={candidate.customer_public_id}>
                        <td data-label={t('customerAccounts.customer')} className="table__id">
                          {candidate.customer_public_id}
                        </td>
                        <td data-label={t('customerAccounts.name')} className="table__primary">
                          {candidate.full_name}
                        </td>
                        <td data-label={t('customerAccounts.location')}>
                          {[candidate.city, candidate.country_code].filter(Boolean).join(', ') ||
                            '—'}
                        </td>
                        <td data-label={t('customerAccounts.matchedOn')}>
                          {candidate.matched_on.join(', ')}
                        </td>
                        <td data-label={t('customerAccounts.confidence')}>
                          {candidate.confidence}
                        </td>
                        <td data-label={t('customerAccounts.linkable')}>
                          {candidate.linkable ? t('common.yes') : t('common.no')}
                        </td>
                        <td data-label={t('customerAccounts.rowActions')}>
                          <Button
                            variant="tertiary"
                            disabled={!candidate.linkable}
                            onClick={() => {
                              setAction(LINK_EXISTING);
                              setTargetCustomer(candidate.customer_public_id);
                            }}
                          >
                            {t('customerAccounts.chooseForLink')}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Card>

      {/* Once decided, the outcome banner is the answer and the decision forms are gone
          (UAT round 4): a form under the outcome invites a second decision that the server
          would only refuse. */}
      {!outcome && (
        <Card title={t('customerAccounts.decisionTitle')}>
          <Field label={t('customerAccounts.actionLabel')}>
            {(fieldProps) => (
              <Select
                {...fieldProps}
                value={action}
                onChange={(event) => {
                  setAction(event.target.value);
                  setOverrideReason('');
                }}
                options={[
                  { value: CREATE_NEW, label: t('customerAccounts.actionCreateNew') },
                  { value: LINK_EXISTING, label: t('customerAccounts.actionLinkExisting') },
                ]}
              />
            )}
          </Field>

          {action === LINK_EXISTING && (
            <Field
              label={t('customerAccounts.targetCustomer')}
              hint={t('customerAccounts.targetCustomerHint')}
            >
              {(fieldProps) => (
                <TextInput
                  {...fieldProps}
                  value={targetCustomer}
                  maxLength={20}
                  onChange={(event) => setTargetCustomer(event.target.value.trim())}
                />
              )}
            </Field>
          )}

          {preview.isPending && preview.isFetching && <SkeletonRows rows={4} />}
          {preview.error && <ErrorState error={preview.error} onRetry={() => preview.refetch()} />}

          {previewData ? (
            <ApprovalPreview
              preview={previewData}
              writesCanonical={writesCanonical}
              classification={classification}
              t={t}
            />
          ) : null}

          {previewData?.mapping_refusal ? (
            <Banner tone="danger" title={t('customerAccounts.mappingRefusedTitle')}>
              <p>{previewData.mapping_refusal}</p>
            </Banner>
          ) : null}

          {previewData && !previewData.mapping_refusal ? (
            <>
              <Checkbox
                label={t('customerAccounts.acknowledgeLabel')}
                hint={t('customerAccounts.acknowledgeHint')}
                checked={acknowledged}
                disabled={!mayApprove || acknowledge.isPending}
                onChange={(event) => {
                  if (event.target.checked) acknowledge.mutate();
                  else {
                    setAcknowledged(false);
                    setAcknowledgedFingerprint(null);
                  }
                }}
              />

              {overrideNeeded && (
                <Field
                  label={t('customerAccounts.overrideLabel')}
                  hint={t('customerAccounts.overrideHint')}
                >
                  {(fieldProps) => (
                    <Select
                      {...fieldProps}
                      value={overrideReason}
                      onChange={(event) => setOverrideReason(event.target.value)}
                      placeholder={t('customerAccounts.chooseReason')}
                      options={OVERRIDE_REASONS.map((value) => ({
                        value,
                        label: t(`customerAccounts.overrideReason.${value}`),
                      }))}
                    />
                  )}
                </Field>
              )}

              <div className="row-wrap">
                <Button
                  onClick={() => decide.mutate('approve')}
                  disabled={!canApprove || decide.isPending || Boolean(outcome)}
                >
                  {action === CREATE_NEW
                    ? t('customerAccounts.approveCreateNew')
                    : t('customerAccounts.approveLinkExisting')}
                </Button>
              </div>

              {!mayApprove && (
                <p className="meta">{t('customerAccounts.readOnlyNotice')}</p>
              )}
            </>
          ) : null}
        </Card>
      )}

      {/* Not while the outcome banner is on screen: the banner already says what was
          just decided, and a second "Declined" beside it would be a second thing saying
          the same. A reload lands on the decided path above, which shows the card. */}
      {!outcome && (
        <AccountStatusCard accountReference={accountReference} mayApprove={mayApprove} />
      )}

      {mayApprove && !outcome && (
        <Card title={t('customerAccounts.rejectTitle')}>
          <p>{t('customerAccounts.rejectBody')}</p>
          <Field label={t('customerAccounts.rejectReason')}>
            {(fieldProps) => (
              <Select
                {...fieldProps}
                value={rejectionReason}
                onChange={(event) => setRejectionReason(event.target.value)}
                placeholder={t('customerAccounts.chooseReason')}
                options={REJECTION_REASONS.map((value) => ({
                  value,
                  label: t(`customerAccounts.rejectionReason.${value}`),
                }))}
              />
            )}
          </Field>
          <Field
            label={t('customerAccounts.internalDetail')}
            hint={t('customerAccounts.internalDetailHint')}
          >
            {(fieldProps) => (
              <TextArea
                {...fieldProps}
                value={internalDetail}
                maxLength={500}
                rows={3}
                onChange={(event) => setInternalDetail(event.target.value)}
              />
            )}
          </Field>
          <div className="row-wrap">
            <Button
              variant="danger"
              onClick={() => decide.mutate('reject')}
              disabled={!rejectionReason || decide.isPending || Boolean(outcome)}
            >
              {t('customerAccounts.rejectAction')}
            </Button>
          </div>
        </Card>
      )}
    </>
  );
}

/**
 * The preview, with the six things OD-29 and OD-28 require it to state **visibly**.
 *
 * The count, the oldest and newest dates, whether cancelled and rebooked shipments are
 * included, the intended canonical customer, the duplicate classification, and whether
 * proposal data will overwrite an existing customer. The last one is derived from the
 * action rather than sent: a link-existing approval writes no canonical value at all
 * (OD-28), and saying so plainly is the difference between a reviewer who knows that and
 * one who assumes the differences table will be applied.
 *
 * Two owner decisions of 2026-10-15 add what a link-existing approval *does* write, shown
 * before the acknowledgement so nothing in it is a surprise: the record's email becoming
 * the account's sign-in email (one email per customer), and the end of a deactivated
 * account's link when this account takes the customer over. Both are server facts in the
 * preview's fingerprint, not something this screen works out.
 */
function ApprovalPreview({ preview, writesCanonical, classification, t }) {
  const disclosure = preview.disclosure;
  const emailChange = preview.email_change;
  const customer = preview.target_customer_public_id;
  let writesLabel = t('customerAccounts.willWriteCanonicalNo');
  if (writesCanonical) writesLabel = t('customerAccounts.willWriteCanonicalYes');
  else if (emailChange) writesLabel = t('customerAccounts.willWriteCanonicalEmailOnly');
  return (
    <div className="ca-preview">
      <h3 className="ca-preview__title">{t('customerAccounts.previewTitle')}</h3>

      {preview.ends_link_of ? (
        <Banner tone="warning" title={t('customerAccounts.takeoverTitle')}>
          <p>
            {t('customerAccounts.takeoverBody')
              .replace('{customer}', customer)
              .replace('{account}', preview.ends_link_of)}
          </p>
        </Banner>
      ) : null}

      {emailChange ? (
        <Banner tone="warning" title={t('customerAccounts.emailChangeTitle')}>
          <p>{t('customerAccounts.emailChangeBody').replace('{customer}', customer)}</p>
          <dl className="ca-review-list">
            <DetailRow label={t('customerAccounts.emailChangeFrom')}>
              {emailChange.current || t('customerAccounts.noEmailOnRecord')}
            </DetailRow>
            <DetailRow label={t('customerAccounts.emailChangeTo')}>
              <strong>{emailChange.new}</strong>
            </DetailRow>
          </dl>
        </Banner>
      ) : null}

      <dl className="ca-review-list">
        <DetailRow label={t('customerAccounts.disclosureCount')}>
          <strong>{disclosure.shipment_count}</strong>
        </DetailRow>
        <DetailRow label={t('customerAccounts.disclosureOldest')}>
          {disclosure.oldest_booked_at ? formatDate(disclosure.oldest_booked_at) : null}
        </DetailRow>
        <DetailRow label={t('customerAccounts.disclosureNewest')}>
          {disclosure.newest_booked_at ? formatDate(disclosure.newest_booked_at) : null}
        </DetailRow>
        <DetailRow label={t('customerAccounts.disclosureCancelled')}>
          {disclosure.includes_cancelled ? t('common.yes') : t('common.no')}
        </DetailRow>
        <DetailRow label={t('customerAccounts.disclosureRebooked')}>
          {disclosure.includes_rebooked ? t('common.yes') : t('common.no')}
        </DetailRow>
        <DetailRow label={t('customerAccounts.intendedCustomer')}>
          {preview.target_customer_public_id || t('customerAccounts.newCustomerWillBeCreated')}
        </DetailRow>
        <DetailRow label={t('customerAccounts.duplicateClassification')}>
          {t(`customerAccounts.classification.${classification}`)}
        </DetailRow>
        <DetailRow label={t('customerAccounts.willWriteCanonical')}>{writesLabel}</DetailRow>
        <DetailRow label={t('customerAccounts.disclosureRuleVersion')}>
          {disclosure.definition_version}
        </DetailRow>
      </dl>

      {preview.differences.length > 0 && (
        <div className="table-wrap">
          <table className="table table--stacked">
            <caption className="visually-hidden">
              {t('customerAccounts.differencesTitle')}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t('customerAccounts.field')}</th>
                <th scope="col">{t('customerAccounts.proposedValue')}</th>
                <th scope="col">{t('customerAccounts.currentValue')}</th>
              </tr>
            </thead>
            <tbody>
              {preview.differences.map((row) => (
                <tr key={row.field}>
                  <td data-label={t('customerAccounts.field')} className="table__primary">
                    {row.field}
                  </td>
                  <td data-label={t('customerAccounts.proposedValue')}>{row.proposed ?? '—'}</td>
                  <td data-label={t('customerAccounts.currentValue')}>{row.current ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
