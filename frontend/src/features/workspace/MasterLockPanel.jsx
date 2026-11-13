/**
 * The booked master's edit lock (owner decision 8, Louis Tong, 2026-10-21).
 *
 * Once a master is booked its shipments' items and fees are locked: the server refuses any
 * change (409) and the item and fee controls on this screen are disabled with the reason.
 * Stand-in: an Admin may **Unlock for edits** with a reason (audited); Admin or Operations
 * press **Lock again**, and finalising a member's quote locks it again by itself.
 *
 * Shown only for a master whose state locks (booked or completed).
 */

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi } from '../../api/endpoints.js';
import { P, useOptionalSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Field, Modal, StatusBadge, TextArea } from '../../components/ui/index.jsx';
import { formatDateTime } from '../../utils/format.js';
import { wsKey } from './workspaceFormat.js';

export const REASON_MAX = 400;

/** Whether the master's items and fees are locked right now (booked, no open unlock). */
export function isItemsLocked(master) {
  return Boolean(master?.edit_lock?.locked);
}

/** The lock badge for the page header. */
export function MasterLockBadge({ master }) {
  const t = useT();
  const lock = master?.edit_lock;
  if (!lock?.lockable) return null;
  return lock.locked ? (
    <StatusBadge tone="warning" label={t('masterLock.badgeLocked')} />
  ) : (
    <StatusBadge tone="info" label={t('masterLock.badgeUnlocked')} />
  );
}

function UnlockDialog({ master, onClose, onDone }) {
  const t = useT();
  const [reason, setReason] = useState('');
  const unlock = useMutation({
    mutationFn: () => consolidationsApi.unlock(master.id, reason.trim()),
    onSuccess: onDone,
  });
  const empty = !reason.trim();
  return (
    <Modal
      open
      onClose={onClose}
      title={t('masterLock.dialogTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={unlock.isPending}
            disabled={empty}
            onClick={() => unlock.mutate()}
          >
            {t('masterLock.confirmUnlock')}
          </Button>
        </>
      }
    >
      <p>{t('masterLock.dialogBody')}</p>
      {unlock.error && <Banner tone="danger">{unlock.error.message}</Banner>}
      <Field label={t('masterLock.reason')} hint={t('masterLock.reasonHint')} required>
        {(props) => (
          <TextArea
            {...props}
            rows={3}
            maxLength={REASON_MAX}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        )}
      </Field>
    </Modal>
  );
}

export function MasterLockPanel({ master }) {
  const t = useT();
  const session = useOptionalSession();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: wsKey(String(master.id)) });
  const relock = useMutation({
    mutationFn: () => consolidationsApi.relock(master.id),
    onSuccess: refresh,
  });
  const lock = master.edit_lock;
  if (!lock?.lockable) return null;
  const canUnlock = Boolean(session?.can(P.MASTER_UNLOCK));
  const canRelock = Boolean(session?.can(P.SHIPMENT_WRITE));

  return (
    <section className="ws-lock" aria-label={t('masterLock.title')}>
      {lock.locked ? (
        <Banner
          tone="warning"
          title={t('masterLock.lockedTitle')}
          action={
            canUnlock ? (
              <Button compact onClick={() => setDialog(true)}>
                {t('masterLock.unlock')}
              </Button>
            ) : null
          }
        >
          {t('masterLock.lockedBody')}
          {!canUnlock && <> {t('masterLock.askAdmin')}</>}
        </Banner>
      ) : (
        <Banner
          tone="info"
          title={t('masterLock.unlockedTitle')}
          action={
            canRelock ? (
              <Button compact loading={relock.isPending} onClick={() => relock.mutate()}>
                {t('masterLock.relock')}
              </Button>
            ) : null
          }
        >
          {t('masterLock.unlockedBody')
            .replace('{reason}', lock.unlock?.reason || '')
            .replace('{date}', formatDateTime(lock.unlock?.unlocked_at))}
        </Banner>
      )}
      {relock.error && <Banner tone="danger">{relock.error.message}</Banner>}
      {dialog && (
        <UnlockDialog
          master={master}
          onClose={() => setDialog(false)}
          onDone={() => {
            setDialog(false);
            refresh();
          }}
        />
      )}
    </section>
  );
}
