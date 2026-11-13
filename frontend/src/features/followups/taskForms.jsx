/**
 * Shared follow-up task forms (Design.md section 11).
 *
 * Completing a task opens a small form for completion time, outcome, and an optional
 * next task. It never closes another task — the copy says so and the server enforces it.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { opsApi, tasksApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import {
  Banner,
  Button,
  Checkbox,
  Drawer,
  Field,
  Modal,
  Select,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { ErrorState } from '../../components/state/index.jsx';
import { fromLocalInputValue, toLocalInputValue } from '../../utils/format.js';

const PURPOSES = [
  'general',
  'first_shipment_follow_up',
  'at_risk_check_in',
  'delivery_exception',
  'quote_request',
  'document_request',
  'service_recovery',
];
const PRIORITIES = ['low', 'normal', 'high', 'urgent'];
const STATUSES = ['scheduled', 'in_progress', 'waiting_for_customer', 'not_scheduled'];

function humanize(value) {
  return value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
}

export function TaskFormDrawer({ open, onClose, customer, task = null, onSaved }) {
  const t = useT();
  const queryClient = useQueryClient();
  const isEdit = Boolean(task);

  const [form, setForm] = useState({
    subject: '',
    detail: '',
    purpose: 'general',
    priority: 'normal',
    status: 'scheduled',
    due_at: toLocalInputValue(new Date(Date.now() + 86_400_000)),
    assignee_user_id: '',
  });

  useEffect(() => {
    if (!open) return;
    setForm({
      subject: task?.subject ?? '',
      detail: task?.detail ?? '',
      purpose: task?.purpose ?? 'general',
      priority: task?.priority ?? 'normal',
      status: task?.status ?? 'scheduled',
      due_at: toLocalInputValue(task?.due_at ?? new Date(Date.now() + 86_400_000)),
      assignee_user_id: task?.assignee?.id ?? '',
    });
  }, [open, task]);

  const staffQuery = useQuery({
    queryKey: ['staff-assignable'],
    queryFn: opsApi.assignableStaff,
    enabled: open,
  });

  const saveMutation = useMutation({
    mutationFn: (payload) => (isEdit ? tasksApi.update(task.id, payload) : tasksApi.create(payload)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      if (customer) {
        queryClient.invalidateQueries({ queryKey: ['customer', String(customer.id)] });
      }
      onSaved?.();
      onClose();
    },
  });

  const needsDueDate = form.status === 'scheduled' || form.status === 'in_progress';

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={isEdit ? 'Edit follow-up' : t('tasks.create')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            type="submit"
            form="task-form"
            loading={saveMutation.isPending}
            disabled={!form.subject.trim() || (needsDueDate && !form.due_at)}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form
        id="task-form"
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          const payload = {
            subject: form.subject,
            detail: form.detail || null,
            purpose: form.purpose,
            priority: form.priority,
            status: form.status,
            due_at: form.due_at ? fromLocalInputValue(form.due_at) : null,
            assignee_user_id: form.assignee_user_id ? Number(form.assignee_user_id) : null,
          };
          if (!isEdit) payload.customer_id = customer.id;
          saveMutation.mutate(payload);
        }}
      >
        {saveMutation.error && <ErrorState error={saveMutation.error} />}
        {customer && (
          <p className="field__hint">
            {t('tasks.customer')}: {customer.full_name} ({customer.public_id})
          </p>
        )}
        <Field label={t('tasks.subject')} required>
          {(props) => (
            <TextInput
              {...props}
              value={form.subject}
              onChange={(event) => setForm({ ...form, subject: event.target.value })}
            />
          )}
        </Field>
        <div className="form-grid">
          <Field label={t('tasks.purpose')}>
            {(props) => (
              <Select
                {...props}
                value={form.purpose}
                onChange={(event) => setForm({ ...form, purpose: event.target.value })}
                options={PURPOSES.map((value) => ({ value, label: humanize(value) }))}
              />
            )}
          </Field>
          <Field label={t('tasks.priority')}>
            {(props) => (
              <Select
                {...props}
                value={form.priority}
                onChange={(event) => setForm({ ...form, priority: event.target.value })}
                options={PRIORITIES.map((value) => ({ value, label: humanize(value) }))}
              />
            )}
          </Field>
          <Field label={t('tasks.status')}>
            {(props) => (
              <Select
                {...props}
                value={form.status}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
                options={STATUSES.map((value) => ({ value, label: t(`taskStatus.${value}`) }))}
              />
            )}
          </Field>
          <Field
            label={t('tasks.dueAt')}
            required={needsDueDate}
            hint={needsDueDate ? 'A scheduled task needs a due date and time.' : undefined}
          >
            {(props) => (
              <TextInput
                {...props}
                type="datetime-local"
                value={form.due_at}
                onChange={(event) => setForm({ ...form, due_at: event.target.value })}
              />
            )}
          </Field>
        </div>
        <Field label={t('tasks.assignee')}>
          {(props) => (
            <Select
              {...props}
              value={form.assignee_user_id}
              onChange={(event) => setForm({ ...form, assignee_user_id: event.target.value })}
              placeholder="Assign to me"
              options={(staffQuery.data ?? []).map((member) => ({
                value: member.id,
                label: member.full_name,
              }))}
            />
          )}
        </Field>
        <Field label={t('tasks.detail')}>
          {(props) => (
            <TextArea
              {...props}
              rows={4}
              value={form.detail}
              onChange={(event) => setForm({ ...form, detail: event.target.value })}
            />
          )}
        </Field>
      </form>
    </Drawer>
  );
}

export function CompleteTaskModal({ open, onClose, task, onCompleted }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [outcome, setOutcome] = useState('');
  const [scheduleNext, setScheduleNext] = useState(false);
  const [nextSubject, setNextSubject] = useState('');
  const [nextDue, setNextDue] = useState(toLocalInputValue(new Date(Date.now() + 7 * 86_400_000)));

  useEffect(() => {
    if (!open) return;
    setOutcome('');
    setScheduleNext(false);
    setNextSubject('');
  }, [open]);

  const completeMutation = useMutation({
    mutationFn: () =>
      tasksApi.complete(task.id, {
        outcome,
        log_interaction: true,
        next_task: scheduleNext
          ? { subject: nextSubject, due_at: fromLocalInputValue(nextDue) }
          : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['customer'] });
      queryClient.invalidateQueries({ queryKey: ['interactions'] });
      onCompleted?.();
      onClose();
    },
  });

  if (!task) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('tasks.completeTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={completeMutation.isPending}
            disabled={!outcome.trim() || (scheduleNext && !nextSubject.trim())}
            onClick={() => completeMutation.mutate()}
          >
            {t('tasks.complete')}
          </Button>
        </>
      }
    >
      <div className="stack">
        {completeMutation.error && <ErrorState error={completeMutation.error} />}
        <Banner tone="neutral">{t('tasks.completedNote')}</Banner>
        <p>
          <strong>{task.subject}</strong>
          <br />
          <span className="meta">
            {task.customer.full_name} · {task.customer.public_id}
          </span>
        </p>
        <Field label={t('tasks.outcome')} required>
          {(props) => (
            <TextArea
              {...props}
              rows={3}
              value={outcome}
              onChange={(event) => setOutcome(event.target.value)}
            />
          )}
        </Field>
        <Checkbox
          label={t('tasks.scheduleNext')}
          checked={scheduleNext}
          onChange={(event) => setScheduleNext(event.target.checked)}
        />
        {scheduleNext && (
          <>
            <Field label={t('tasks.nextSubject')} required>
              {(props) => (
                <TextInput
                  {...props}
                  value={nextSubject}
                  onChange={(event) => setNextSubject(event.target.value)}
                />
              )}
            </Field>
            <Field label={t('tasks.nextDue')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="datetime-local"
                  value={nextDue}
                  onChange={(event) => setNextDue(event.target.value)}
                />
              )}
            </Field>
          </>
        )}
      </div>
    </Modal>
  );
}
