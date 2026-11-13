/** Interaction timeline with author, channel, outcome, and source (CRM.md section 4). */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customersApi } from '../../../api/endpoints.js';
import { useT } from '../../../i18n/index.jsx';
import { P, useSession } from '../../../app/SessionContext.jsx';
import {
  Button,
  Card,
  Drawer,
  Field,
  Select,
  TextArea,
  TextInput,
} from '../../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../../components/state/index.jsx';
import { formatDateTime } from '../../../utils/format.js';

const CHANNELS = ['phone', 'email', 'sms', 'messaging_app', 'in_person', 'other'];
const DIRECTIONS = ['outbound', 'inbound', 'internal'];

export function InteractionsTab({ customerId, compact = false }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    subject: '',
    body: '',
    channel: 'phone',
    direction: 'outbound',
    outcome: '',
  });

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['interactions', customerId, compact],
    queryFn: () => customersApi.interactions(customerId, { limit: compact ? 5 : 25 }),
  });

  const createMutation = useMutation({
    mutationFn: (payload) => customersApi.createInteraction(customerId, payload),
    onSuccess: (created) => {
      // The saved note goes straight into every cached timeline for this customer (the
      // compact Overview one and the full tab) before the refetch is asked for. Relying
      // on the refetch alone left the box showing its old, empty state until the server
      // answered, which read as "my note was not saved" (UAT round 3).
      if (created) {
        queryClient.setQueriesData({ queryKey: ['interactions', customerId] }, (current) => {
          if (!current?.items || current.items.some((item) => item.id === created.id)) {
            return current;
          }
          return {
            ...current,
            items: [created, ...current.items].slice(0, current.limit ?? undefined),
            total: (current.total ?? current.items.length) + 1,
          };
        });
      }
      queryClient.invalidateQueries({ queryKey: ['interactions', customerId] });
      queryClient.invalidateQueries({ queryKey: ['customer', String(customerId)] });
      setOpen(false);
      setForm({ subject: '', body: '', channel: 'phone', direction: 'outbound', outcome: '' });
    },
  });

  if (isLoading) return <SkeletonRows rows={compact ? 3 : 5} height={64} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  const items = data?.items ?? [];

  const timeline = (
    <>
      {items.length === 0 ? (
        <EmptyState
          title={t('profile.noActivity')}
          body="Record a call, message, or visit so the next person knows what happened."
          action={
            can(P.INTERACTION_WRITE) ? (
              <Button variant="primary" onClick={() => setOpen(true)}>
                {t('profile.addNote')}
              </Button>
            ) : null
          }
        />
      ) : (
        <ol className="timeline">
          {items.map((item) => (
            <li key={item.id} className="timeline__item">
              <span
                className={
                  item.is_follow_up_completion
                    ? 'timeline__dot timeline__dot--success'
                    : 'timeline__dot'
                }
                aria-hidden="true"
              />
              <div className="timeline__body">
                <div className="row-wrap">
                  <strong>{item.subject}</strong>
                  <span className="badge badge--neutral">{item.channel.replace(/_/g, ' ')}</span>
                  <span className="badge badge--neutral">{item.direction}</span>
                </div>
                {item.body && <p className="timeline__text">{item.body}</p>}
                {item.outcome && <p className="meta">Outcome: {item.outcome}</p>}
                <p className="meta">
                  {formatDateTime(item.occurred_at)}
                  {item.author ? ` · ${item.author.full_name}` : ''}
                  {' · Internal note'}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </>
  );

  return (
    <>
      {compact ? (
        <>
          {timeline}
          {can(P.INTERACTION_WRITE) && items.length > 0 && (
            <Button compact onClick={() => setOpen(true)}>
              {t('profile.addNote')}
            </Button>
          )}
        </>
      ) : (
        <Card
          title={t('profile.interactions')}
          actions={
            can(P.INTERACTION_WRITE) ? (
              <Button variant="primary" compact onClick={() => setOpen(true)}>
                {t('profile.addNote')}
              </Button>
            ) : null
          }
        >
          {timeline}
        </Card>
      )}

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t('profile.addNote')}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              type="submit"
              form="interaction-form"
              loading={createMutation.isPending}
              disabled={!form.subject.trim()}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        <form
          id="interaction-form"
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            createMutation.mutate({
              subject: form.subject,
              body: form.body || null,
              outcome: form.outcome || null,
              channel: form.channel,
              direction: form.direction,
            });
          }}
        >
          {createMutation.error && <ErrorState error={createMutation.error} />}
          <p className="field__hint">{t('customers.notesHint')}</p>
          <Field label={t('profile.noteSubject')} required>
            {(props) => (
              <TextInput
                {...props}
                value={form.subject}
                onChange={(event) => setForm({ ...form, subject: event.target.value })}
              />
            )}
          </Field>
          <div className="form-grid">
            <Field label={t('profile.noteChannel')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.channel}
                  onChange={(event) => setForm({ ...form, channel: event.target.value })}
                  options={CHANNELS.map((value) => ({
                    value,
                    label: value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()),
                  }))}
                />
              )}
            </Field>
            <Field label={t('profile.noteDirection')}>
              {(props) => (
                <Select
                  {...props}
                  value={form.direction}
                  onChange={(event) => setForm({ ...form, direction: event.target.value })}
                  options={DIRECTIONS.map((value) => ({
                    value,
                    label: value.replace(/^./, (c) => c.toUpperCase()),
                  }))}
                />
              )}
            </Field>
          </div>
          <Field label={t('profile.noteBody')}>
            {(props) => (
              <TextArea
                {...props}
                rows={5}
                value={form.body}
                onChange={(event) => setForm({ ...form, body: event.target.value })}
              />
            )}
          </Field>
          <Field label={t('profile.noteOutcome')}>
            {(props) => (
              <TextInput
                {...props}
                value={form.outcome}
                onChange={(event) => setForm({ ...form, outcome: event.target.value })}
              />
            )}
          </Field>
        </form>
      </Drawer>
    </>
  );
}
