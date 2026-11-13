/**
 * Change a Customer Account's sign-in email (RC-UAT-25 item 2, Ben 2026-10-25).
 *
 * Customers can no longer change it themselves; an Admin does it here, on the staff account
 * screen. Offered only to a holder of `customer_account:deactivate` (Admin alone) and only
 * when the account's status allows it (`can_change_sign_in_email`: pending approval, active or
 * suspended). A bounded reason, an optional note, and a confirmation that names both
 * addresses. The server repeats every rule: the address is normalized, an address held by
 * another account or customer record is refused, the linked customer follows, every session
 * ends, both addresses are told.
 */

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Banner, Button, Field, Modal, Select, TextArea, TextInput } from '../../components/ui/index.jsx';
import { useT } from '../../i18n/index.jsx';
import { customerAccountReviewApi } from '../../api/endpoints.js';
import { interpolate } from '../../utils/format.js';

/** `customer_account_security_service.CHANGE_EMAIL_REASON_CODES`. */
export const SIGN_IN_EMAIL_REASONS = ['customer_request', 'mailbox_lost', 'entered_in_error'];

export function SignInEmailChange({ account, onChanged }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [address, setAddress] = useState('');
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState(false);
  const reference = account.account_reference;

  const change = useMutation({
    mutationFn: () =>
      customerAccountReviewApi.changeSignInEmail(reference, {
        new_email: address.trim(),
        reason_code: reason,
        note: note.trim() || null,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['customer-account', 'identity', reference], updated);
      setAddress('');
      setReason('');
      setNote('');
      setConfirming(false);
      onChanged?.(t('customerAccounts.signInEmail.done'));
    },
  });

  if (!account.can_change_sign_in_email) {
    return (
      <div className="stack">
        <h3 className="card__title">{t('customerAccounts.signInEmail.title')}</h3>
        <p className="meta">{t('customerAccounts.signInEmail.notOffered')}</p>
      </div>
    );
  }

  const ready = address.trim().includes('@') && Boolean(reason);

  return (
    <div className="stack">
      <h3 className="card__title">{t('customerAccounts.signInEmail.title')}</h3>
      <p className="meta">{t('customerAccounts.signInEmail.hint')}</p>
      {change.error && !confirming && <Banner tone="danger">{change.error.message}</Banner>}
      <Field label={t('customerAccounts.signInEmail.newEmail')}>
        {(fieldProps) => (
          <TextInput
            {...fieldProps}
            type="email"
            autoComplete="off"
            maxLength={320}
            value={address}
            onChange={(event) => setAddress(event.target.value)}
          />
        )}
      </Field>
      <Field label={t('customerAccounts.signInEmail.reason')}>
        {(fieldProps) => (
          <Select
            {...fieldProps}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t('customerAccounts.chooseReason')}
            options={SIGN_IN_EMAIL_REASONS.map((value) => ({
              value,
              label: t(`customerAccounts.signInEmail.reasonCode.${value}`, value),
            }))}
          />
        )}
      </Field>
      <Field label={t('customerAccounts.signInEmail.note')}>
        {(fieldProps) => (
          <TextArea
            {...fieldProps}
            rows={2}
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        )}
      </Field>
      <div className="row-wrap">
        <Button
          variant="primary"
          disabled={!ready || change.isPending}
          onClick={() => setConfirming(true)}
        >
          {t('customerAccounts.signInEmail.action')}
        </Button>
      </div>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={interpolate(t('customerAccounts.signInEmail.confirmTitle'), { reference })}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)}>
              {t('common.cancel')}
            </Button>
            <span className="spacer" />
            <Button
              variant="primary"
              loading={change.isPending}
              disabled={change.isPending}
              onClick={() => change.mutate()}
            >
              {t('customerAccounts.signInEmail.confirm')}
            </Button>
          </>
        }
      >
        {change.error && <Banner tone="danger">{change.error.message}</Banner>}
        <p>
          {interpolate(t('customerAccounts.signInEmail.confirmBody'), {
            old: account.account_email_entered,
            new: address.trim(),
          })}
        </p>
      </Modal>
    </div>
  );
}
