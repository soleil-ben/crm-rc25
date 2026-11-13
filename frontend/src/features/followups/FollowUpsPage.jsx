/**
 * Follow-ups page (Design.md section 11).
 *
 * Two views: My tasks, grouped Overdue / Today / Upcoming, and All tasks as a
 * permission-aware table. The calendar view is deliberately deferred until the list
 * workflows are stable.
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { opsApi, tasksApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Card, Checkbox, Pagination, Select, TabPanel, Tabs } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { TaskList } from './TaskList.jsx';
import { CompleteTaskModal, TaskFormDrawer } from './taskForms.jsx';

const PAGE_SIZE = 25;

function groupTasks(tasks) {
  const now = Date.now();
  const endOfToday = new Date();
  endOfToday.setHours(23, 59, 59, 999);

  const overdue = [];
  const today = [];
  const upcoming = [];

  tasks.forEach((task) => {
    if (!task.due_at) {
      upcoming.push(task);
      return;
    }
    const due = new Date(task.due_at.endsWith('Z') ? task.due_at : `${task.due_at}Z`).getTime();
    if (due < now) overdue.push(task);
    else if (due <= endOfToday.getTime()) today.push(task);
    else upcoming.push(task);
  });

  return { overdue, today, upcoming };
}

export function FollowUpsPage() {
  const t = useT();
  const { user } = useSession();
  const [params, setParams] = useSearchParams();
  const [completing, setCompleting] = useState(null);
  const [editing, setEditing] = useState(null);

  const view = params.get('view') || 'mine';
  const offset = Number(params.get('offset') || 0);

  const mineQuery = useQuery({
    queryKey: ['tasks', 'mine'],
    queryFn: () => tasksApi.mine({ limit: 100 }),
    enabled: view === 'mine',
  });

  const allFilters = {
    limit: PAGE_SIZE,
    offset,
    only_open: params.get('only_open') !== 'false' ? 'true' : undefined,
    only_overdue: params.get('only_overdue') === 'true' ? 'true' : undefined,
    assignee_user_id: params.get('assignee_user_id') || undefined,
  };

  const allQuery = useQuery({
    queryKey: ['tasks', 'all', allFilters],
    queryFn: () => tasksApi.list(allFilters),
    enabled: view === 'all',
    placeholderData: (previous) => previous,
  });

  const staffQuery = useQuery({ queryKey: ['staff-assignable'], queryFn: opsApi.assignableStaff });

  const groups = useMemo(() => groupTasks(mineQuery.data?.items ?? []), [mineQuery.data]);

  function setParam(key, value) {
    const next = new URLSearchParams(params);
    next.delete('offset');
    if (!value) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  function refetchAll() {
    mineQuery.refetch();
    allQuery.refetch();
  }

  return (
    <>
      <PageHeader
        title={t('tasks.title')}
        subtitle={
          view === 'mine'
            ? `${groups.overdue.length} overdue · ${groups.today.length} due today`
            : undefined
        }
      />

      <Tabs
        label={t('tasks.title')}
        active={view}
        onChange={(id) => setParam('view', id)}
        tabs={[
          { id: 'mine', label: t('tasks.myTasks') },
          { id: 'all', label: t('tasks.allTasks') },
        ]}
      />

      <TabPanel id="mine" active={view}>
        {mineQuery.isLoading && <SkeletonRows rows={5} height={64} />}
        {mineQuery.error && <ErrorState error={mineQuery.error} onRetry={mineQuery.refetch} />}
        {mineQuery.data && (
          <div className="stack">
            <Card title={`${t('tasks.overdue')} (${groups.overdue.length})`} flush>
              <TaskList
                tasks={groups.overdue}
                onComplete={setCompleting}
                onEdit={setEditing}
                emptyBody={`Nothing is overdue for ${user?.full_name}. `}
              />
            </Card>
            <Card title={`${t('tasks.today')} (${groups.today.length})`} flush>
              <TaskList
                tasks={groups.today}
                onComplete={setCompleting}
                onEdit={setEditing}
                emptyBody="No follow-up is due today."
              />
            </Card>
            <Card title={`${t('tasks.upcoming')} (${groups.upcoming.length})`} flush>
              <TaskList
                tasks={groups.upcoming}
                onComplete={setCompleting}
                onEdit={setEditing}
                emptyBody="Nothing scheduled ahead."
              />
            </Card>
          </div>
        )}
      </TabPanel>

      <TabPanel id="all" active={view}>
        <Card flush>
          <div className="filter-bar">
            <div className="filter-bar__row">
              <Select
                aria-label={t('tasks.assignee')}
                value={params.get('assignee_user_id') || ''}
                onChange={(event) => setParam('assignee_user_id', event.target.value)}
                placeholder={`${t('tasks.assignee')}: all`}
                options={(staffQuery.data ?? []).map((member) => ({
                  value: member.id,
                  label: member.full_name,
                }))}
                style={{ maxWidth: 240 }}
              />
              <Checkbox
                label="Open only"
                checked={params.get('only_open') !== 'false'}
                onChange={(event) => setParam('only_open', event.target.checked ? '' : 'false')}
              />
              <Checkbox
                label={`${t('tasks.overdue')} only`}
                checked={params.get('only_overdue') === 'true'}
                onChange={(event) => setParam('only_overdue', event.target.checked ? 'true' : '')}
              />
            </div>
          </div>

          {allQuery.isLoading && (
            <div style={{ padding: 'var(--space-5)' }}>
              <SkeletonRows rows={5} height={64} />
            </div>
          )}
          {allQuery.error && <ErrorState error={allQuery.error} onRetry={allQuery.refetch} />}
          {allQuery.data && (
            <>
              <TaskList
                tasks={allQuery.data.items}
                onComplete={setCompleting}
                onEdit={setEditing}
              />
              <Pagination
                total={allQuery.data.total}
                limit={PAGE_SIZE}
                offset={offset}
                onChange={(next) => setParam('offset', String(next))}
              />
            </>
          )}
        </Card>
      </TabPanel>

      <CompleteTaskModal
        open={Boolean(completing)}
        onClose={() => setCompleting(null)}
        task={completing}
        onCompleted={refetchAll}
      />
      <TaskFormDrawer
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
        task={editing}
        customer={editing?.customer}
        onSaved={refetchAll}
      />
    </>
  );
}
