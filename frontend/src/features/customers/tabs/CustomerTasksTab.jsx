/** Follow-ups for one customer: open tasks first, then completed history. */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../../api/endpoints.js';
import { useT } from '../../../i18n/index.jsx';
import { P, useSession } from '../../../app/SessionContext.jsx';
import { Button, Card } from '../../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../../components/state/index.jsx';
import { TaskList } from '../../followups/TaskList.jsx';
import { CompleteTaskModal, TaskFormDrawer } from '../../followups/taskForms.jsx';

export function CustomerTasksTab({ customer }) {
  const t = useT();
  const { can } = useSession();
  const [createOpen, setCreateOpen] = useState(false);
  const [editingTask, setEditingTask] = useState(null);
  const [completing, setCompleting] = useState(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['tasks', { customer: customer.id }],
    queryFn: () => tasksApi.list({ customer_id: customer.id, limit: 100 }),
  });

  if (isLoading) return <SkeletonRows rows={4} height={64} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  const tasks = data?.items ?? [];
  const open = tasks.filter((task) => !['completed', 'cancelled'].includes(task.status));
  const closed = tasks.filter((task) => ['completed', 'cancelled'].includes(task.status));

  return (
    <>
      <div className="stack">
        <Card
          title={`${t('tasks.title')} — open`}
          actions={
            can(P.TASK_WRITE) ? (
              <Button variant="primary" compact onClick={() => setCreateOpen(true)}>
                {t('tasks.create')}
              </Button>
            ) : null
          }
          flush
        >
          <TaskList
            tasks={open}
            showCustomer={false}
            onComplete={setCompleting}
            onEdit={(task) => setEditingTask(task)}
            emptyBody="No open follow-up for this customer. Create one when a next action is agreed."
          />
        </Card>

        {closed.length > 0 && (
          <Card title={`${t('tasks.title')} — completed`} flush>
            <TaskList tasks={closed} showCustomer={false} onComplete={() => {}} />
          </Card>
        )}
      </div>

      <TaskFormDrawer
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        customer={customer}
        onSaved={refetch}
      />
      <TaskFormDrawer
        open={Boolean(editingTask)}
        onClose={() => setEditingTask(null)}
        customer={customer}
        task={editingTask}
        onSaved={refetch}
      />
      <CompleteTaskModal
        open={Boolean(completing)}
        onClose={() => setCompleting(null)}
        task={completing}
        onCompleted={refetch}
      />
    </>
  );
}
