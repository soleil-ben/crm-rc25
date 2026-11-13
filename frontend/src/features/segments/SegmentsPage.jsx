/**
 * Segments list and builder (Design.md section 8).
 *
 * The list shows the plain-language definition, the live matching count, and — where
 * the role allows a marketing export — the separate eligible count with its warning.
 */

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { opsApi, segmentsApi } from '../../api/endpoints.js';
import { downloadUrl } from '../../api/client.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Drawer,
  Field,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, InlineSpinner, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';
import { SegmentBuilder, newCondition } from './SegmentBuilder.jsx';
import './segments.css';

export function SegmentsPage() {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [builderOpen, setBuilderOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: '', description: '', definition: null });

  const segmentsQuery = useQuery({ queryKey: ['segments'], queryFn: segmentsApi.list });
  const fieldsQuery = useQuery({ queryKey: ['segment-fields'], queryFn: segmentsApi.fields });
  const tagsQuery = useQuery({ queryKey: ['tags'], queryFn: opsApi.tags });
  const staffQuery = useQuery({ queryKey: ['staff-assignable'], queryFn: opsApi.assignableStaff });

  const fields = useMemo(() => fieldsQuery.data?.fields ?? [], [fieldsQuery.data]);

  // Live preview: the count refreshes as the definition changes.
  const previewQuery = useQuery({
    queryKey: ['segment-preview', form.definition],
    queryFn: () => segmentsApi.preview(form.definition, 5),
    enabled: builderOpen && Boolean(form.definition),
  });

  const saveMutation = useMutation({
    mutationFn: (payload) =>
      editing ? segmentsApi.update(editing.id, payload) : segmentsApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['segments'] });
      setBuilderOpen(false);
      setEditing(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => segmentsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['segments'] }),
  });

  useEffect(() => {
    if (!builderOpen || fields.length === 0 || form.definition) return;
    setForm((current) => ({
      ...current,
      definition: { match: 'all', conditions: [newCondition(fields)] },
    }));
  }, [builderOpen, fields, form.definition]);

  function startNew() {
    setEditing(null);
    setForm({
      name: '',
      description: '',
      definition: fields.length ? { match: 'all', conditions: [newCondition(fields)] } : null,
    });
    setBuilderOpen(true);
  }

  function startEdit(segment, asCopy = false) {
    setEditing(asCopy ? null : segment);
    setForm({
      name: asCopy ? `${segment.name} (copy)` : segment.name,
      description: segment.description ?? '',
      definition: segment.definition,
    });
    setBuilderOpen(true);
  }

  const selectedId = params.get('segment');
  const membersQuery = useQuery({
    queryKey: ['segment-members', selectedId],
    queryFn: () => segmentsApi.members(selectedId, { limit: 25 }),
    enabled: Boolean(selectedId),
  });

  return (
    <>
      <PageHeader
        title={t('segments.title')}
        subtitle="Dynamic views that update as customers, shipments, and follow-ups change."
        actions={
          can(P.SEGMENT_WRITE) ? (
            <Button variant="primary" onClick={startNew} disabled={fields.length === 0}>
              {t('segments.create')}
            </Button>
          ) : null
        }
      />

      {segmentsQuery.isLoading && <SkeletonRows rows={5} height={90} />}
      {segmentsQuery.error && (
        <ErrorState error={segmentsQuery.error} onRetry={segmentsQuery.refetch} />
      )}

      {segmentsQuery.data && segmentsQuery.data.length === 0 && (
        <Card>
          <EmptyState
            title={t('segments.emptyTitle')}
            body={t('segments.emptyBody')}
            action={
              can(P.SEGMENT_WRITE) ? (
                <Button variant="primary" onClick={startNew}>
                  {t('segments.create')}
                </Button>
              ) : null
            }
          />
        </Card>
      )}

      {segmentsQuery.data && segmentsQuery.data.length > 0 && (
        <div className="segment-grid">
          {segmentsQuery.data.map((segment) => (
            <Card key={segment.id} title={segment.name} headingLevel="h3">
              <div className="row-wrap">
                <StatusBadge tone="info" value="dynamic" label={t('segments.dynamic')} />
                {segment.is_system && (
                  <StatusBadge tone="neutral" value="system" label={t('segments.systemSegment')} />
                )}
              </div>
              {segment.description && <p className="meta">{segment.description}</p>}
              <p className="segment-definition">{segment.plain_language}</p>
              <div className="segment-counts">
                <div>
                  <span className="metric__label">{t('segments.memberCount')}</span>
                  <span className="metric__value">{segment.member_count}</span>
                </div>
                {segment.marketing_eligible_email_count !== null && (
                  <div>
                    <span className="metric__label">{t('segments.eligibleCount')}</span>
                    <span className="metric__value">{segment.marketing_eligible_email_count}</span>
                  </div>
                )}
              </div>
              {segment.marketing_eligible_email_count !== null &&
                segment.marketing_eligible_email_count < segment.member_count && (
                  <Banner tone="warning">{t('segments.eligibleHint')}</Banner>
                )}
              <p className="meta">
                {t('segments.updatedAt')} {formatDateTime(segment.updated_at)}
                {segment.owner ? ` · ${segment.owner.full_name}` : ''}
              </p>
              <div className="row-wrap">
                <Button
                  compact
                  onClick={() => {
                    const next = new URLSearchParams(params);
                    next.set('segment', String(segment.id));
                    setParams(next);
                  }}
                >
                  {t('segments.members')}
                </Button>
                {/* Shown to every role holding the marketing export, not to a fixed role
                    name, so widening the permission later needs no screen change. The
                    file holds only the contactable members; the server enforces the
                    permission and the consent filtering again (UAT round 3). */}
                {can(P.EXPORT_MARKETING_SEGMENT) && (
                  <Button
                    compact
                    aria-label={`${t('segments.exportAudience')}: ${segment.name}`}
                    onClick={() => {
                      window.location.href = downloadUrl(
                        `/exports/segments/${segment.id}/audience.csv`,
                        { channel: 'email' },
                      );
                    }}
                  >
                    {t('segments.exportAudience')}
                  </Button>
                )}
                {can(P.SEGMENT_WRITE) && !segment.is_system && (
                  <>
                    <Button compact variant="tertiary" onClick={() => startEdit(segment)}>
                      {t('common.edit')}
                    </Button>
                    <Button
                      compact
                      variant="tertiary"
                      onClick={() => deleteMutation.mutate(segment.id)}
                    >
                      Delete
                    </Button>
                  </>
                )}
                {can(P.SEGMENT_WRITE) && segment.is_system && (
                  <Button compact variant="tertiary" onClick={() => startEdit(segment, true)}>
                    {t('segments.saveAsCopy')}
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {selectedId && (
        <Card title={t('segments.members')} flush>
          {membersQuery.isLoading && (
            <div style={{ padding: 'var(--space-5)' }}>
              <SkeletonRows rows={4} />
            </div>
          )}
          {membersQuery.data && (
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">{t('segments.members')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('customers.columnId')}</th>
                    <th scope="col">{t('customers.columnName')}</th>
                    <th scope="col">{t('customers.columnLifecycle')}</th>
                    <th scope="col">{t('customers.columnShipments')}</th>
                  </tr>
                </thead>
                <tbody>
                  {membersQuery.data.items.map((customer) => (
                    <tr key={customer.id}>
                      <td data-label={t('customers.columnId')} className="table__id">
                        {customer.public_id}
                      </td>
                      <td data-label={t('customers.columnName')} className="table__primary">
                        <Link to={`/customers/${customer.id}`}>{customer.full_name}</Link>
                      </td>
                      <td data-label={t('customers.columnLifecycle')}>
                        <StatusBadge kind="lifecycle" value={customer.lifecycle_status} />
                      </td>
                      <td data-label={t('customers.columnShipments')}>
                        {customer.total_qualifying_shipments}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <Drawer
        open={builderOpen}
        onClose={() => setBuilderOpen(false)}
        title={editing ? 'Edit segment' : t('segments.create')}
        footer={
          <>
            <Button onClick={() => setBuilderOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={saveMutation.isPending}
              disabled={!form.name.trim() || !form.definition}
              onClick={() =>
                saveMutation.mutate({
                  name: form.name,
                  description: form.description || null,
                  definition: form.definition,
                })
              }
            >
              {t('segments.saveSegment')}
            </Button>
          </>
        }
      >
        <div className="stack">
          {saveMutation.error && <ErrorState error={saveMutation.error} />}
          <Field label={t('segments.name')} required>
            {(props) => (
              <TextInput
                {...props}
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            )}
          </Field>
          <Field label={t('segments.description')}>
            {(props) => (
              <TextArea
                {...props}
                rows={2}
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
            )}
          </Field>

          <h3>{t('segments.builderTitle')}</h3>
          {form.definition && fields.length > 0 && (
            <SegmentBuilder
              definition={form.definition}
              fields={fields}
              tags={tagsQuery.data ?? []}
              staff={staffQuery.data ?? []}
              onChange={(definition) => setForm({ ...form, definition })}
            />
          )}

          <Card title={t('segments.preview')} headingLevel="h3">
            {previewQuery.isFetching && <InlineSpinner />}
            {previewQuery.error && <ErrorState error={previewQuery.error} />}
            {previewQuery.data && (
              <>
                <p>
                  <strong>{previewQuery.data.member_count}</strong> {t('segments.memberCount').toLowerCase()}
                  {previewQuery.data.marketing_eligible_email_count !== null && (
                    <>
                      {' · '}
                      <strong>{previewQuery.data.marketing_eligible_email_count}</strong>{' '}
                      {t('segments.eligibleCount').toLowerCase()}
                    </>
                  )}
                </p>
                <p className="meta">
                  {t('segments.plainLanguage')}: {previewQuery.data.plain_language}
                </p>
                {previewQuery.data.sample.length > 0 && (
                  <ul className="preview-list">
                    {previewQuery.data.sample.map((customer) => (
                      <li key={customer.id}>
                        <span className="mono">{customer.public_id}</span> {customer.full_name}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </Card>

          <Banner tone="neutral">{fieldsQuery.data?.note}</Banner>
        </div>
      </Drawer>
    </>
  );
}
