/**
 * Shipment detail (Design.md section 9).
 *
 * A prominent monospace Solaris Shipment ID with a copy button, route, operational badge,
 * package progress, and booking date; then the peer tabs. The selected tab lives in the
 * URL so a view is shareable and survives a reload.
 *
 * The primary action changes by state: an unconfirmed draft offers Confirm, a confirmed
 * shipment offers Print labels.
 */

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { shipmentsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  CopyableId,
  Field,
  Modal,
  RouteBadge,
  TabPanel,
  Tabs,
  TextInput,
} from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { PanelErrorBoundary } from '../../components/state/PanelErrorBoundary.jsx';
import { formatDate } from '../../utils/format.js';
import { LabelPrintDrawer } from './LabelPrintDrawer.jsx';
import { BookingStateBadge, OperationalBadge, PackageProgress } from './shipmentTokens.jsx';
import {
  DetailsTab,
  FinancialsTab,
  LegsTab,
  NotesTab,
  PackagesTab,
  TrackingTab,
} from './shipmentTabs.jsx';
import './shipments.css';

export function ShipmentDetailPage() {
  const t = useT();
  const { shipmentId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [printOpen, setPrintOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [rebookOpen, setRebookOpen] = useState(false);
  const [reason, setReason] = useState('');

  const shipmentQuery = useQuery({
    queryKey: ['shipment', shipmentId],
    queryFn: () => shipmentsApi.get(shipmentId),
  });
  const legsQuery = useQuery({
    queryKey: ['shipment-legs', shipmentId],
    queryFn: () => shipmentsApi.legs(shipmentId),
    enabled: Boolean(shipmentQuery.data),
  });

  const shipment = shipmentQuery.data;
  const packages = shipment?.packages ?? [];
  const legs = legsQuery.data ?? [];

  const confirmMutation = useMutation({
    mutationFn: () =>
      shipmentsApi.confirm(shipment.id, `detail-${shipment.id}-${Date.now().toString(36)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment', shipmentId] });
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => shipmentsApi.cancel(shipment.id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment', shipmentId] });
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
      setCancelOpen(false);
      setReason('');
    },
  });

  const rebookMutation = useMutation({
    mutationFn: () => shipmentsApi.rebook(shipment.id, { reason }),
    onSuccess: (replacement) => {
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
      setRebookOpen(false);
      setReason('');
      navigate(`/shipments/${replacement.id}`);
    },
  });

  const tabs = useMemo(
    () =>
      [
        { id: 'tracking', label: t('shipmentDetail.tabTracking') },
        { id: 'details', label: t('shipmentDetail.tabDetails') },
        { id: 'packages', label: t('shipmentDetail.tabPackages'), count: packages.length },
        { id: 'legs', label: t('shipmentDetail.tabLegs'), count: legs.length },
        { id: 'financials', label: t('shipmentDetail.tabFinancials') },
        { id: 'notes', label: t('shipmentDetail.tabNotes') },
      ].filter(Boolean),
    [t, packages.length, legs.length],
  );

  const activeTab = params.get('tab') || 'tracking';

  function selectTab(id) {
    const next = new URLSearchParams(params);
    next.set('tab', id);
    setParams(next, { replace: true });
  }

  if (shipmentQuery.isLoading) {
    return <SkeletonRows rows={6} />;
  }
  if (shipmentQuery.error) {
    return <ErrorState error={shipmentQuery.error} onRetry={shipmentQuery.refetch} />;
  }

  const isDraft = shipment.booking_state === 'draft';

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link to="/shipments">{t('shipmentDetail.breadcrumb')}</Link>
            <span aria-hidden="true"> / </span>
            <span>{shipment.public_id || t('shipments.draftNoId')}</span>
          </>
        }
        title={shipment.public_id || t('shipments.draftNoId')}
        actions={
          <>
            {isDraft && can(P.SHIPMENT_WRITE) && (
              <Button
                variant="primary"
                loading={confirmMutation.isPending}
                onClick={() => confirmMutation.mutate()}
              >
                {t('booking.confirmBooking')}
              </Button>
            )}
            {!isDraft && shipment.public_id && can(P.LABEL_GENERATE) && (
              <Button variant="primary" onClick={() => setPrintOpen(true)}>
                {t('labels.open')}
              </Button>
            )}
            {/* RC-UAT-25 item 8 (Ben 2026-10-25): from any tab, straight to the quote,
                the cost and invoicing the client. */}
            {can(P.FINANCIAL_READ) && activeTab !== 'financials' && (
              <Button onClick={() => selectTab('financials')}>
                {t('shipmentDetail.headerInvoiceAction')}
              </Button>
            )}
            {can(P.SHIPMENT_CANCEL) && shipment.booking_state !== 'cancelled' && (
              <>
                <Button onClick={() => setRebookOpen(true)}>{t('shipmentDetail.rebook')}</Button>
                <Button onClick={() => setCancelOpen(true)}>
                  {t('shipmentDetail.cancelBooking')}
                </Button>
              </>
            )}
          </>
        }
      />

      <Card>
        <div className="shipment-header">
          <div className="shipment-header__id">
            {shipment.public_id ? (
              <CopyableId value={shipment.public_id} />
            ) : (
              <span className="meta">{t('shipments.draftNoId')}</span>
            )}
          </div>
          <div className="row-wrap">
            <RouteBadge route={shipment.route_group} />
            <BookingStateBadge value={shipment.booking_state} />
            <OperationalBadge value={shipment.operational_state} />
            {shipment.route_is_locked && (
              <span className="chip" title={t('shipmentDetail.routeLockedHint')}>
                {t('shipmentDetail.routeLocked')}
              </span>
            )}
            {shipment.is_demo_record && (
              <span className="chip chip--demo">{t('shipments.demoRecord')}</span>
            )}
          </div>
          <div className="shipment-header__meta">
            <PackageProgress progress={shipment.package_progress} />
            <span className="meta">
              {t('shipmentDetail.booked')} {formatDate(shipment.booking_date)}
            </span>
            {shipment.customer && (
              <Link to={`/customers/${shipment.customer.id}`}>{shipment.customer.full_name}</Link>
            )}
          </div>
        </div>

        {shipment.rebooked_to_public_id && (
          <Banner tone="warning" title={t('shipmentDetail.rebookedTo')}>
            <span className="mono">{shipment.rebooked_to_public_id}</span>
          </Banner>
        )}
        {shipment.rebooked_from_public_id && (
          <Banner tone="neutral" title={t('shipmentDetail.rebookedFrom')}>
            <span className="mono">{shipment.rebooked_from_public_id}</span>
          </Banner>
        )}
      </Card>

      <Tabs tabs={tabs} active={activeTab} onChange={selectTab} label={t('shipments.title')} />

      {/* RC-UAT-25 item 7 (Ben 2026-10-25): a render error in one tab shows a message and
          Try again here instead of unmounting the page (it went blank). */}
      <PanelErrorBoundary
        resetKey={`${activeTab}:${shipment.updated_at}`}
        onRetry={() => shipmentQuery.refetch()}
      >
        <TabPanel id="tracking" active={activeTab}>
          <TrackingTab
            shipment={shipment}
            packages={packages}
            legs={legs}
            onPrint={() => setPrintOpen(true)}
          />
        </TabPanel>
        <TabPanel id="details" active={activeTab}>
          <DetailsTab shipment={shipment} />
        </TabPanel>
        <TabPanel id="packages" active={activeTab}>
          <PackagesTab
            shipment={shipment}
            packages={packages}
            onPrint={() => setPrintOpen(true)}
          />
        </TabPanel>
        <TabPanel id="legs" active={activeTab}>
          <LegsTab
            shipment={shipment}
            packages={packages}
            legs={legs}
            isLoading={legsQuery.isLoading}
          />
        </TabPanel>
        <TabPanel id="financials" active={activeTab}>
          <FinancialsTab shipment={shipment} />
        </TabPanel>
        <TabPanel id="notes" active={activeTab}>
          <NotesTab shipment={shipment} />
        </TabPanel>
      </PanelErrorBoundary>

      <LabelPrintDrawer
        open={printOpen}
        onClose={() => setPrintOpen(false)}
        shipmentId={shipment.id}
      />

      <Modal
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        title={t('shipmentDetail.cancelBooking')}
        footer={
          <>
            <Button onClick={() => setCancelOpen(false)}>{t('common.cancel')}</Button>
            <span className="spacer" />
            <Button
              variant="primary"
              disabled={!reason.trim()}
              loading={cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
            >
              {t('shipmentDetail.cancelBooking')}
            </Button>
          </>
        }
      >
        {cancelMutation.error && <Banner tone="danger">{cancelMutation.error.message}</Banner>}
        <p>
          <span className="mono">{shipment.public_id}</span> — this Solaris ID is retired with the
          record and is never reused.
        </p>
        <Field label={t('shipmentDetail.cancelBookingReason')} required>
          {(props) => (
            <TextInput
              {...props}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
      </Modal>

      <Modal
        open={rebookOpen}
        onClose={() => setRebookOpen(false)}
        title={t('shipmentDetail.rebook')}
        footer={
          <>
            <Button onClick={() => setRebookOpen(false)}>{t('common.cancel')}</Button>
            <span className="spacer" />
            <Button
              variant="primary"
              disabled={!reason.trim()}
              loading={rebookMutation.isPending}
              onClick={() => rebookMutation.mutate()}
            >
              {t('shipmentDetail.rebook')}
            </Button>
          </>
        }
      >
        {rebookMutation.error && <Banner tone="danger">{rebookMutation.error.message}</Banner>}
        <p>
          Cancelling <span className="mono">{shipment.public_id}</span> and opening a linked
          replacement draft. Confirming the replacement issues a new Solaris ID; both records keep
          a link to each other.
        </p>
        <Field label={t('shipmentDetail.cancelBookingReason')} required>
          {(props) => (
            <TextInput
              {...props}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
      </Modal>
    </>
  );
}
