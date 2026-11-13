/**
 * Settings (Design.md section 13).
 *
 * Phase 1 exposes the sections it actually implements: lifecycle thresholds, follow-up
 * automation rules, staff and permissions, brand/tracking, and audit access. Sections
 * belonging to later phases are not shown as empty tabs.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { opsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Checkbox,
  Drawer,
  Field,
  Modal,
  Select,
  StatusBadge,
  TabPanel,
  Tabs,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { IntegrationPanel } from './IntegrationPanel.jsx';
import { NotificationsPanel } from './NotificationsPanel.jsx';
import { TariffUpdatesPanel } from './TariffUpdatesPanel.jsx';
import { PricingSettingsPanel } from './PricingSettingsPanel.jsx';
import { MethodSettingsPanel } from './MethodSettingsPanel.jsx';
import { RateSheetPanel } from './RateSheetPanel.jsx';
import { TariffBrowserPanel } from './TariffBrowserPanel.jsx';
import { TaxRatesPanel } from './TaxRatesPanel.jsx';
import { RetentionPanel } from './RetentionPanel.jsx';
import { useTariffPending } from './useTariffPending.js';
import { formatDateTime, interpolate } from '../../utils/format.js';

/** `app/core/enums.py::Role`, in the order the settings screen offers them. */
const ROLES = ['operations', 'marketing', 'read_only_manager', 'admin'];
const MIN_STAFF_PASSWORD = 12;

const EMPTY_STAFF = { full_name: '', email: '', password: '', role: 'operations' };

export function SettingsPage() {
  const t = useT();
  const { can, user: me } = useSession();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState('lifecycle');
  const [form, setForm] = useState(null);
  const [saved, setSaved] = useState(false);
  const [staffDrawerOpen, setStaffDrawerOpen] = useState(false);
  const [staffForm, setStaffForm] = useState(EMPTY_STAFF);
  const [staffNotice, setStaffNotice] = useState(null);
  const [statusTarget, setStatusTarget] = useState(null); // the member being (de)activated

  // Staff administration (UAT-AD-03). Create and deactivate were API-only until the
  // 2026-10-14 fix pack; the server revokes every session of a deactivated account in the
  // same transaction and audits both acts, so this screen only has to ask.
  const createStaffMutation = useMutation({
    mutationFn: (payload) => opsApi.createStaff(payload),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['staff'] });
      queryClient.invalidateQueries({ queryKey: ['staff-assignable'] });
      setStaffDrawerOpen(false);
      setStaffForm(EMPTY_STAFF);
      setStaffNotice(t('settings.staffCreated').replace('{email}', created.email));
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ member, isActive }) => opsApi.updateStaff(member.id, { is_active: isActive }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['staff'] });
      queryClient.invalidateQueries({ queryKey: ['staff-assignable'] });
      setStatusTarget(null);
      setStaffNotice(
        t(updated.is_active ? 'settings.staffReactivated' : 'settings.staffDeactivated').replace(
          '{email}',
          updated.email,
        ),
      );
    },
  });

  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: opsApi.settings });
  const tariffPending = useTariffPending(can(P.TARIFF_MANAGE));

  useEffect(() => {
    if (settingsQuery.data && !form) setForm(settingsQuery.data);
  }, [settingsQuery.data, form]);

  const saveMutation = useMutation({
    mutationFn: (payload) => opsApi.updateSettings(payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated);
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      queryClient.invalidateQueries({ queryKey: ['segments'] });
      setForm(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    },
  });

  const rulesMutation = useMutation({ mutationFn: opsApi.runRetentionRules });

  const staffQuery = useQuery({
    queryKey: ['staff'],
    queryFn: opsApi.staff,
    enabled: can(P.STAFF_MANAGE) && tab === 'staff',
  });

  const auditQuery = useQuery({
    queryKey: ['audit'],
    queryFn: () => opsApi.audit({ limit: 50 }),
    enabled: can(P.AUDIT_READ) && tab === 'audit',
  });

  if (settingsQuery.isLoading || !form) return <SkeletonRows rows={5} height={80} />;
  if (settingsQuery.error) return <ErrorState error={settingsQuery.error} onRetry={settingsQuery.refetch} />;

  const readOnly = !can(P.SETTINGS_MANAGE);

  const tabs = [
    { id: 'lifecycle', label: t('settings.lifecycle') },
    { id: 'rules', label: t('settings.rules') },
    { id: 'brand', label: t('settings.brand') },
    // Phase 4A. Titled as infrastructure rather than as a provider connection, because
    // there is no provider connection (docs/INTEGRATIONS.md).
    ...(can(P.INTEGRATION_READ)
      ? [{ id: 'integrations', label: t('settings.integrations') }]
      : []),
    // Phase 13F: the milestone email outbox (test capture only, OD-72).
    ...(can(P.SHIPMENT_READ) && can(P.CUSTOMER_READ)
      ? [{ id: 'notifications', label: t('notifications.title') }]
      : []),
    // Phase 14: pricing settings and surcharge policies (edited by Admin), and the
    // read-only tariff browser with the manual workbook import. Vendor cost: tariff:read.
    ...(can(P.TARIFF_READ) ? [{ id: 'pricing', label: t('pricingSettings.title') }] : []),
    // Step 2 (DEC-0270): the confirmed method's settings and the Kango rate-sheet import.
    ...(can(P.TARIFF_READ) ? [{ id: 'pricing-method', label: t('methodSettings.tab') }] : []),
    ...(can(P.TARIFF_MANAGE) ? [{ id: 'rate-sheets', label: t('rateSheet.tab') }] : []),
    ...(can(P.TARIFF_READ) ? [{ id: 'tariff-browser', label: t('tariffBrowser.title') }] : []),
    // RC-UAT-20 (DEC-0227): GST/HST by province; Admin edits.
    ...(can(P.FINANCIAL_READ) ? [{ id: 'tax-rates', label: t('taxRates.title') }] : []),
    // RC-UAT-21 Phase D (DEC-0233): retention machinery, off; Admin only.
    ...(can(P.RETENTION_MANAGE) ? [{ id: 'retention', label: t('retention.title') }] : []),
    // Phase 13H: vendor rate emails and tariff approval (OD-76).
    // Phase 15: the approver sees how many drafts and held senders wait for review.
    ...(can(P.TARIFF_MANAGE)
      ? [
          {
            id: 'tariffs',
            label:
              tariffPending.count > 0
                ? interpolate(t('tariffPending.tabLabel'), {
                    title: t('tariffIntake.title'),
                    count: tariffPending.count,
                  })
                : t('tariffIntake.title'),
          },
        ]
      : []),
    ...(can(P.STAFF_MANAGE) ? [{ id: 'staff', label: t('settings.staff') }] : []),
    ...(can(P.AUDIT_READ) ? [{ id: 'audit', label: t('settings.audit') }] : []),
  ];

  function save(patch) {
    saveMutation.mutate(patch);
  }

  return (
    <>
      <PageHeader title={t('settings.title')} />

      {readOnly && (
        <Banner tone="neutral">
          You can view these settings. Changing them requires an administrator role.
        </Banner>
      )}
      {saved && <Banner tone="info">{t('states.savedSuccess')}</Banner>}
      {saveMutation.error && <ErrorState error={saveMutation.error} />}

      <Tabs tabs={tabs} active={tab} onChange={setTab} label={t('settings.title')} />

      <TabPanel id="lifecycle" active={tab}>
        <Card title={t('settings.lifecycle')}>
          <Banner tone="warning">{t('settings.lifecycleHint')}</Banner>
          <div className="form-grid" style={{ marginTop: 'var(--space-4)' }}>
            <Field label={t('settings.newDays')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="number"
                  min="1"
                  disabled={readOnly}
                  value={form.lifecycle_new_days}
                  onChange={(event) =>
                    setForm({ ...form, lifecycle_new_days: Number(event.target.value) })
                  }
                />
              )}
            </Field>
            <Field label={t('settings.activeDays')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="number"
                  min="1"
                  disabled={readOnly}
                  value={form.lifecycle_active_days}
                  onChange={(event) =>
                    setForm({ ...form, lifecycle_active_days: Number(event.target.value) })
                  }
                />
              )}
            </Field>
            <Field label={t('settings.atRiskDays')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="number"
                  min="1"
                  disabled={readOnly}
                  value={form.lifecycle_at_risk_days}
                  onChange={(event) =>
                    setForm({ ...form, lifecycle_at_risk_days: Number(event.target.value) })
                  }
                />
              )}
            </Field>
          </div>

          <h3 style={{ marginTop: 'var(--space-5)' }}>{t('settings.definitions')}</h3>
          <dl className="detail-list">
            {Object.entries(form.lifecycle_definitions || {}).map(([status, definition]) => (
              <div className="detail-row" key={status}>
                <dt>
                  <StatusBadge kind="lifecycle" value={status} />
                </dt>
                <dd>{definition}</dd>
              </div>
            ))}
          </dl>

          {!readOnly && (
            <Button
              variant="primary"
              loading={saveMutation.isPending}
              onClick={() =>
                save({
                  lifecycle_new_days: form.lifecycle_new_days,
                  lifecycle_active_days: form.lifecycle_active_days,
                  lifecycle_at_risk_days: form.lifecycle_at_risk_days,
                })
              }
            >
              {t('common.save')}
            </Button>
          )}
        </Card>
      </TabPanel>

      <TabPanel id="rules" active={tab}>
        <Card title={t('settings.rules')}>
          <Banner tone="neutral">{t('settings.rulesHint')}</Banner>
          <div className="stack" style={{ marginTop: 'var(--space-4)' }}>
            <Checkbox
              label={t('settings.ruleFirstDelivery')}
              disabled={readOnly}
              checked={form.rule_first_delivery_follow_up_enabled}
              onChange={(event) =>
                setForm({ ...form, rule_first_delivery_follow_up_enabled: event.target.checked })
              }
            />
            <Field label="Days after first delivery">
              {(props) => (
                <TextInput
                  {...props}
                  type="number"
                  min="0"
                  disabled={readOnly}
                  value={form.rule_first_delivery_follow_up_days}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      rule_first_delivery_follow_up_days: Number(event.target.value),
                    })
                  }
                  style={{ maxWidth: 160 }}
                />
              )}
            </Field>
            <Checkbox
              label={t('settings.ruleAtRisk')}
              disabled={readOnly}
              checked={form.rule_at_risk_task_enabled}
              onChange={(event) =>
                setForm({ ...form, rule_at_risk_task_enabled: event.target.checked })
              }
            />
            <Checkbox
              label={t('settings.ruleException')}
              disabled={readOnly}
              checked={form.rule_exception_task_enabled}
              onChange={(event) =>
                setForm({ ...form, rule_exception_task_enabled: event.target.checked })
              }
            />
          </div>

          {!readOnly && (
            <div className="row" style={{ marginTop: 'var(--space-4)' }}>
              <Button
                variant="primary"
                loading={saveMutation.isPending}
                onClick={() =>
                  save({
                    rule_first_delivery_follow_up_enabled: form.rule_first_delivery_follow_up_enabled,
                    rule_first_delivery_follow_up_days: form.rule_first_delivery_follow_up_days,
                    rule_at_risk_task_enabled: form.rule_at_risk_task_enabled,
                    rule_exception_task_enabled: form.rule_exception_task_enabled,
                  })
                }
              >
                {t('common.save')}
              </Button>
              <Button loading={rulesMutation.isPending} onClick={() => rulesMutation.mutate()}>
                {t('settings.runRules')}
              </Button>
            </div>
          )}
          {rulesMutation.data && (
            <Banner tone="info">
              {rulesMutation.data.note} Created:{' '}
              {Object.entries(rulesMutation.data.created)
                .map(([rule, count]) => `${rule.replace(/_/g, ' ')} ${count}`)
                .join(', ')}
            </Banner>
          )}
        </Card>
      </TabPanel>

      <TabPanel id="brand" active={tab}>
        <Card title={t('settings.brand')}>
          <dl className="detail-list">
            <div className="detail-row">
              <dt>Brand</dt>
              <dd>{form.brand_name}</dd>
            </div>
            <div className="detail-row">
              <dt>Legal entity</dt>
              <dd>{form.legal_entity_name}</dd>
            </div>
            <div className="detail-row">
              <dt>Office timezone</dt>
              <dd>{form.office_timezone}</dd>
            </div>
            <div className="detail-row">
              <dt>Default currency</dt>
              <dd>{form.default_currency}</dd>
            </div>
          </dl>
          <Field
            label={t('settings.trackingBaseUrl')}
            hint="Used by the public tracking links and label QR codes in a later phase. The domain is not assumed to exist yet."
          >
            {(props) => (
              <TextInput
                {...props}
                disabled={readOnly}
                value={form.tracking_base_url}
                onChange={(event) => setForm({ ...form, tracking_base_url: event.target.value })}
              />
            )}
          </Field>
          {!readOnly && (
            <Button
              variant="primary"
              loading={saveMutation.isPending}
              onClick={() => save({ tracking_base_url: form.tracking_base_url })}
            >
              {t('common.save')}
            </Button>
          )}
          <Banner tone="neutral">
            No official Solaris logo is bundled. The portal uses a text wordmark until an
            approved brand asset is supplied.
          </Banner>
        </Card>
      </TabPanel>

      {can(P.INTEGRATION_READ) && (
        <TabPanel id="integrations" active={tab}>
          <IntegrationPanel />
        </TabPanel>
      )}

      {can(P.SHIPMENT_READ) && can(P.CUSTOMER_READ) && (
        <TabPanel id="notifications" active={tab}>
          <NotificationsPanel />
        </TabPanel>
      )}

      {can(P.TARIFF_READ) && (
        <TabPanel id="pricing" active={tab}>
          {tab === 'pricing' && <PricingSettingsPanel />}
        </TabPanel>
      )}

      {can(P.TARIFF_READ) && (
        <TabPanel id="pricing-method" active={tab}>
          {tab === 'pricing-method' && <MethodSettingsPanel />}
        </TabPanel>
      )}

      {can(P.TARIFF_MANAGE) && (
        <TabPanel id="rate-sheets" active={tab}>
          {tab === 'rate-sheets' && <RateSheetPanel />}
        </TabPanel>
      )}

      {can(P.TARIFF_READ) && (
        <TabPanel id="tariff-browser" active={tab}>
          {tab === 'tariff-browser' && <TariffBrowserPanel />}
        </TabPanel>
      )}

      {can(P.FINANCIAL_READ) && (
        <TabPanel id="tax-rates" active={tab}>
          {tab === 'tax-rates' && <TaxRatesPanel />}
        </TabPanel>
      )}

      {can(P.RETENTION_MANAGE) && (
        <TabPanel id="retention" active={tab}>
          {tab === 'retention' && <RetentionPanel />}
        </TabPanel>
      )}

      {can(P.TARIFF_MANAGE) && (
        <TabPanel id="tariffs" active={tab}>
          {tab === 'tariffs' && <TariffUpdatesPanel />}
        </TabPanel>
      )}

      {can(P.STAFF_MANAGE) && (
        <TabPanel id="staff" active={tab}>
          {staffNotice && <Banner tone="info">{staffNotice}</Banner>}
          {statusMutation.error && !statusTarget && <ErrorState error={statusMutation.error} />}
          <Card
            title={t('settings.staff')}
            actions={
              <Button variant="primary" onClick={() => setStaffDrawerOpen(true)}>
                {t('settings.addStaff')}
              </Button>
            }
            flush
          >
            {staffQuery.isLoading && (
              <div style={{ padding: 'var(--space-5)' }}>
                <SkeletonRows rows={4} />
              </div>
            )}
            {staffQuery.error && (
              <ErrorState error={staffQuery.error} onRetry={staffQuery.refetch} />
            )}
            {staffQuery.data && (
              <div className="table-wrap">
                <table className="table table--stacked">
                  <caption className="visually-hidden">{t('settings.staff')}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('settings.staffName')}</th>
                      <th scope="col">{t('settings.staffEmail')}</th>
                      <th scope="col">{t('settings.staffRole')}</th>
                      <th scope="col">{t('settings.staffStatus')}</th>
                      <th scope="col">{t('settings.staffLastSignIn')}</th>
                      <th scope="col">
                        <span className="visually-hidden">{t('settings.staffActions')}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {staffQuery.data.map((member) => (
                      <tr key={member.id}>
                        <td data-label={t('settings.staffName')} className="table__primary">
                          {member.full_name}
                          {me && member.id === me.id && (
                            <span className="meta"> · {t('settings.staffYou')}</span>
                          )}
                        </td>
                        <td data-label={t('settings.staffEmail')}>{member.email}</td>
                        <td data-label={t('settings.staffRole')}>
                          {t(`roles.${member.role}`, member.role.replace(/_/g, ' '))}
                        </td>
                        <td data-label={t('settings.staffStatus')}>
                          <StatusBadge
                            tone={member.is_active ? 'success' : 'neutral'}
                            value={member.is_active ? 'active' : 'inactive'}
                            label={
                              member.is_active
                                ? t('settings.staffActive')
                                : t('settings.staffDeactivatedLabel')
                            }
                          />
                        </td>
                        <td data-label={t('settings.staffLastSignIn')}>
                          {formatDateTime(member.last_login_at)}
                        </td>
                        <td data-label={t('settings.staffActions')}>
                          {/* The server refuses a self-deactivation; the control is simply
                              absent here so the refusal is never the first thing seen. */}
                          {me && member.id !== me.id && (
                            <Button
                              compact
                              variant={member.is_active ? 'danger' : 'secondary'}
                              onClick={() => setStatusTarget(member)}
                            >
                              {member.is_active
                                ? t('settings.deactivate')
                                : t('settings.reactivate')}
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Drawer
            open={staffDrawerOpen}
            onClose={() => setStaffDrawerOpen(false)}
            title={t('settings.addStaff')}
            footer={
              <>
                <Button onClick={() => setStaffDrawerOpen(false)}>{t('common.cancel')}</Button>
                <Button
                  variant="primary"
                  type="submit"
                  form="staff-create-form"
                  loading={createStaffMutation.isPending}
                  disabled={
                    !staffForm.full_name.trim() ||
                    !staffForm.email.trim() ||
                    staffForm.password.length < MIN_STAFF_PASSWORD
                  }
                >
                  {t('settings.createStaff')}
                </Button>
              </>
            }
          >
            <form
              id="staff-create-form"
              className="stack"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                createStaffMutation.mutate({
                  full_name: staffForm.full_name.trim(),
                  email: staffForm.email.trim(),
                  password: staffForm.password,
                  role: staffForm.role,
                });
              }}
            >
              {createStaffMutation.error && !createStaffMutation.error.field && (
                <ErrorState error={createStaffMutation.error} />
              )}
              <p className="meta">{t('settings.addStaffHint')}</p>
              <Field
                label={t('settings.staffName')}
                required
                error={
                  createStaffMutation.error?.field === 'full_name'
                    ? createStaffMutation.error.message
                    : undefined
                }
              >
                {(props) => (
                  <TextInput
                    {...props}
                    value={staffForm.full_name}
                    autoComplete="off"
                    onChange={(event) =>
                      setStaffForm({ ...staffForm, full_name: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field
                label={t('settings.staffEmail')}
                required
                error={
                  createStaffMutation.error?.field === 'email'
                    ? createStaffMutation.error.message
                    : undefined
                }
              >
                {(props) => (
                  <TextInput
                    {...props}
                    type="email"
                    value={staffForm.email}
                    autoComplete="off"
                    onChange={(event) => setStaffForm({ ...staffForm, email: event.target.value })}
                  />
                )}
              </Field>
              <Field
                label={t('settings.staffPassword')}
                hint={t('settings.staffPasswordHint').replace('{min}', String(MIN_STAFF_PASSWORD))}
                required
                error={
                  createStaffMutation.error?.field === 'password'
                    ? createStaffMutation.error.message
                    : undefined
                }
              >
                {(props) => (
                  <TextInput
                    {...props}
                    type="password"
                    value={staffForm.password}
                    autoComplete="new-password"
                    minLength={MIN_STAFF_PASSWORD}
                    onChange={(event) =>
                      setStaffForm({ ...staffForm, password: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field label={t('settings.staffRole')}>
                {(props) => (
                  <Select
                    {...props}
                    value={staffForm.role}
                    onChange={(event) => setStaffForm({ ...staffForm, role: event.target.value })}
                    options={ROLES.map((value) => ({
                      value,
                      label: t(`roles.${value}`, value.replace(/_/g, ' ')),
                    }))}
                  />
                )}
              </Field>
            </form>
          </Drawer>

          <Modal
            open={Boolean(statusTarget)}
            onClose={() => setStatusTarget(null)}
            title={
              statusTarget?.is_active
                ? t('settings.deactivateConfirmTitle')
                : t('settings.reactivateConfirmTitle')
            }
            footer={
              <>
                <Button onClick={() => setStatusTarget(null)}>{t('common.cancel')}</Button>
                <span className="spacer" />
                <Button
                  variant={statusTarget?.is_active ? 'danger' : 'primary'}
                  loading={statusMutation.isPending}
                  onClick={() =>
                    statusMutation.mutate({
                      member: statusTarget,
                      isActive: !statusTarget.is_active,
                    })
                  }
                >
                  {statusTarget?.is_active ? t('settings.deactivate') : t('settings.reactivate')}
                </Button>
              </>
            }
          >
            {statusTarget && (
              <div className="stack">
                {statusMutation.error && (
                  <Banner tone="danger">{statusMutation.error.message}</Banner>
                )}
                <p>
                  <strong>{statusTarget.full_name}</strong> · {statusTarget.email}
                </p>
                <p>
                  {statusTarget.is_active
                    ? t('settings.deactivateConfirmBody')
                    : t('settings.reactivateConfirmBody')}
                </p>
              </div>
            )}
          </Modal>
        </TabPanel>
      )}

      {can(P.AUDIT_READ) && (
        <TabPanel id="audit" active={tab}>
          <Card title={t('settings.audit')} flush>
            {auditQuery.isLoading && (
              <div style={{ padding: 'var(--space-5)' }}>
                <SkeletonRows rows={5} />
              </div>
            )}
            {auditQuery.data && auditQuery.data.items.length === 0 && (
              <EmptyState title="No audit entries yet" body="Material changes appear here." />
            )}
            {auditQuery.data && auditQuery.data.items.length > 0 && (
              <div className="table-wrap">
                <table className="table table--stacked">
                  <caption className="visually-hidden">{t('settings.audit')}</caption>
                  <thead>
                    <tr>
                      <th scope="col">When</th>
                      <th scope="col">Actor</th>
                      <th scope="col">Action</th>
                      <th scope="col">Summary</th>
                      <th scope="col">{t('settings.auditDetails')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditQuery.data.items.map((event) => (
                      <tr key={event.id}>
                        <td data-label="When">{formatDateTime(event.occurred_at)}</td>
                        <td data-label="Actor">{event.actor_label}</td>
                        <td data-label="Action" className="mono">
                          {event.action}
                        </td>
                        <td data-label="Summary">{event.summary}</td>
                        <td data-label={t('settings.auditDetails')}>
                          <AuditDetail event={event} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </TabPanel>
      )}
    </>
  );
}

/**
 * The reason code, changed field *names*, Admin-override marker and suppression evidence
 * reference the API derives for an audit row (UAT rounds 3 to 5). The raw `detail_json` is
 * deliberately not read here (UAT round 3). The one row that shows values is an approved
 * Customer Account change request: `changes` carries each field's old and new value, which
 * a reader of the audit can already see on the customer record (UAT round 8).
 */
function AuditDetail({ event }) {
  const t = useT();
  const fields = event.changed_fields ?? [];
  const changes = event.changes ?? [];
  const empty =
    !event.reason_code &&
    fields.length === 0 &&
    changes.length === 0 &&
    !event.admin_override &&
    !event.evidence_reference;
  const shown = (value) => (value == null || value === '' ? t('settings.auditChangeEmpty') : value);
  if (empty) {
    return <span className="meta">—</span>;
  }
  return (
    <dl className="audit-detail">
      {/* An Admin decision on work that is Operations' by default (OD-24, CA-APR-05). */}
      {event.admin_override && (
        <div>
          <dt className="visually-hidden">{t('settings.auditAdminOverride')}</dt>
          <dd>
            <StatusBadge
              tone="warning"
              value="admin_override"
              label={t('settings.auditAdminOverride')}
            />
          </dd>
        </div>
      )}
      {event.reason_code && (
        <div>
          <dt>{t('settings.auditReasonCode')}</dt>
          <dd className="mono">{event.reason_code}</dd>
        </div>
      )}
      {fields.length > 0 && (
        <div>
          <dt>{t('settings.auditChangedFields')}</dt>
          <dd className="mono">{fields.join(', ')}</dd>
        </div>
      )}
      {changes.length > 0 && (
        <div>
          <dt>{t('settings.auditChanges')}</dt>
          <dd>
            <ul className="audit-changes">
              {changes.map((change) => (
                <li key={change.field}>
                  {interpolate(t('settings.auditChangeLine'), {
                    field: change.field,
                    old: shown(change.old),
                    new: shown(change.new),
                  })}
                </li>
              ))}
            </ul>
          </dd>
        </div>
      )}
      {/* What a suppression was recorded against (UAT round 5). */}
      {event.evidence_reference && (
        <div>
          <dt>{t('settings.auditEvidence')}</dt>
          <dd className="mono">{event.evidence_reference}</dd>
        </div>
      )}
    </dl>
  );
}
