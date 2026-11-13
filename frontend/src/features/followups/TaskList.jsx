/** Shared follow-up task table, grouped overdue first (Design.md section 11). */

import { Link } from 'react-router-dom';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { Button, StatusBadge } from '../../components/ui/index.jsx';
import { EmptyState } from '../../components/state/index.jsx';
import { formatDateTime, relativeDays } from '../../utils/format.js';

const PRIORITY_TONE = { urgent: 'danger', high: 'warning', normal: 'neutral', low: 'neutral' };

function humanize(value) {
  return String(value).replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
}

export function TaskList({ tasks, onComplete, onEdit, showCustomer = true, emptyBody }) {
  const t = useT();
  const { can } = useSession();

  if (!tasks || tasks.length === 0) {
    return <EmptyState title={t('tasks.emptyTitle')} body={emptyBody || t('tasks.emptyBody')} />;
  }

  return (
    <div className="table-wrap">
      <table className="table table--stacked">
        <caption className="visually-hidden">{t('tasks.title')}</caption>
        <thead>
          <tr>
            <th scope="col">{t('tasks.subject')}</th>
            {showCustomer && <th scope="col">{t('tasks.customer')}</th>}
            <th scope="col">{t('tasks.status')}</th>
            <th scope="col">{t('tasks.priority')}</th>
            <th scope="col">{t('tasks.dueAt')}</th>
            <th scope="col">{t('tasks.assignee')}</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id}>
              <td data-label={t('tasks.subject')} className="table__primary">
                {task.subject}
                <div className="meta">{humanize(task.purpose)}</div>
              </td>
              {showCustomer && (
                <td data-label={t('tasks.customer')}>
                  <Link to={`/customers/${task.customer.id}`}>{task.customer.full_name}</Link>
                  <div className="meta mono">{task.customer.public_id}</div>
                </td>
              )}
              <td data-label={t('tasks.status')}>
                {task.is_overdue ? (
                  <StatusBadge tone="danger" value="overdue" label={t('tasks.overdue')} />
                ) : (
                  <StatusBadge kind="task" value={task.status} />
                )}
              </td>
              <td data-label={t('tasks.priority')}>
                <StatusBadge
                  tone={PRIORITY_TONE[task.priority]}
                  value={task.priority}
                  label={humanize(task.priority)}
                />
              </td>
              <td data-label={t('tasks.dueAt')}>
                {task.due_at ? (
                  <>
                    {formatDateTime(task.due_at)}
                    <div className="meta">{relativeDays(task.due_at)}</div>
                  </>
                ) : (
                  <span className="meta">{t('tasks.noDueDate')}</span>
                )}
              </td>
              <td data-label={t('tasks.assignee')}>{task.assignee?.full_name || '—'}</td>
              <td data-label="Actions">
                {can(P.TASK_WRITE) && task.status !== 'completed' && task.status !== 'cancelled' && (
                  <div className="row">
                    <Button compact variant="secondary" onClick={() => onComplete(task)}>
                      {t('tasks.complete')}
                    </Button>
                    {onEdit && (
                      <Button compact variant="tertiary" onClick={() => onEdit(task)}>
                        {t('common.edit')}
                      </Button>
                    )}
                  </div>
                )}
                {task.status === 'completed' && task.outcome && (
                  <span className="meta">{task.outcome}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
