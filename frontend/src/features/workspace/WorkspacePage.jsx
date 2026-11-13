/**
 * The unified workspace for one master consolidation (Phase 13D; redesigned 2026-11-04,
 * DEC-0272; two panes since 2026-11-06, DEC-0277).
 *
 * A summary bar on top (tracking, service, CW, cost, quote, profit, how many customers are
 * complete, Book); on the left the master's structure — shipment, master piece #1 with its
 * customers, piece #2 …, then the whole master (cost and quote, vendor bill, milestones);
 * on the right the one thing selected. The selection is in the address (`?sel=c123`), so a
 * link opens the same customer.
 *
 * Everything shown is what the 13C API computed; this screen does no pricing arithmetic of
 * its own. Every write refreshes every query under the master's key, because one fee on one
 * customer can move the cost split of every other customer on the same master.
 *
 * Internal: vendor cost, the vendor's names for surcharges and its booking reference are on
 * this screen. It is staff-only and gated by `tariff:read`; nothing here reaches a customer.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi, pricingApi, tariffsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Banner, Button, Card, Modal, StatusBadge } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonCards } from '../../components/state/index.jsx';
import { STATE_TONE } from './WorkspaceListPage.jsx';
import { MasterPanel } from './MasterPanels.jsx';
import { CostQuotePanel } from './CostQuotePanel.jsx';
import { AddCustomerForm, AddPiece, AttachBooking, PieceSection, membersByPiece, piecesOf } from './MasterPieces.jsx';
import { CustomerCard } from './CustomerCard.jsx';
import { VendorBillPanel } from './VendorBillPanel.jsx';
import { MasterActionsPanel } from './MasterActions.jsx';
import { MasterLockBadge, MasterLockPanel, isItemsLocked } from './MasterLockPanel.jsx';
import { SECTION_BY_ORIGIN, wsKey } from './workspaceFormat.js';
import { WorkspaceExpandProvider } from './CollapsibleCard.jsx';
import { buildWorkspaceModel, validSelection } from './workspaceModel.js';
import {
  BookButton,
  Checklist,
  CustomerAlerts,
  PerPieceSurcharges,
  PieceCustomers,
  PlaceInPiece,
  STATUS_TONE,
  SummaryBar,
  WorkspaceTree,
  fill,
} from './WorkspaceTwoPane.jsx';
import './workspace.css';

/**
 * Typed-but-unsaved input on the right pane: any input there marks it; any successful save
 * (a mutation) clears it. Switching to another screen while it is marked asks first.
 */
function useUnsavedGuard() {
  const queryClient = useQueryClient();
  const [dirty, setDirty] = useState(false);
  useEffect(
    () =>
      queryClient.getMutationCache().subscribe((event) => {
        if (event?.type === 'updated' && event.mutation?.state?.status === 'success') setDirty(false);
      }),
    [queryClient],
  );
  const onInput = (event) => {
    const el = event.target;
    if (!el || el.type === 'search' || el.closest?.('[data-ws-nodirty]')) return;
    setDirty(true);
  };
  return { dirty, setDirty, onInput };
}

function AddCustomerPane({ master, sequence, section, versionId, multiPiece, onGo }) {
  const t = useT();
  const [attach, setAttach] = useState(false);
  const before = useRef(new Set(master.members.map((m) => m.shipment_id)));
  return (
    <>
      <p className="ws2-crumb">{fill(t('ws2.addCrumb'), { n: sequence })}</p>
      <div className="row-wrap">
        <Button variant={attach ? 'secondary' : 'primary'} onClick={() => setAttach(false)} aria-pressed={!attach}>
          {fill(t('ws2.addTo'), { n: sequence })}
        </Button>
        <Button variant={attach ? 'primary' : 'tertiary'} onClick={() => setAttach(true)} aria-pressed={attach}>
          {t('ws2.attach')}
        </Button>
      </div>
      {attach ? (
        <AttachBooking
          master={master}
          sequence={sequence}
          multiPiece={multiPiece}
          onDone={(sid) => onGo(sid ? `c${sid}` : `p${sequence}`, true)}
        />
      ) : (
        <AddCustomerForm
          master={master}
          sequence={sequence}
          section={section}
          versionId={versionId}
          onDone={(data) => {
            const added = data?.members?.find((m) => !before.current.has(m.shipment_id));
            onGo(added ? `c${added.shipment_id}` : `p${sequence}`, true);
          }}
        />
      )}
    </>
  );
}

export function WorkspacePage() {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { consolidationId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const guard = useUnsavedGuard();
  const [pending, setPending] = useState(null);

  const masterQuery = useQuery({
    queryKey: wsKey(consolidationId, 'master'),
    queryFn: () => consolidationsApi.get(consolidationId),
  });
  const estimateQuery = useQuery({
    queryKey: wsKey(consolidationId, 'pricing'),
    queryFn: () => consolidationsApi.pricing(consolidationId),
    enabled: masterQuery.isSuccess,
  });
  const settingsQuery = useQuery({ queryKey: ['pricing-settings'], queryFn: pricingApi.settings });
  const versionsQuery = useQuery({ queryKey: ['tariff-versions'], queryFn: tariffsApi.versions });
  const cartonsQuery = useQuery({
    queryKey: wsKey(consolidationId, 'cartons'),
    queryFn: () => consolidationsApi.cartons(consolidationId),
    enabled: masterQuery.isSuccess,
  });
  const packagesQuery = useQuery({
    queryKey: wsKey(consolidationId, 'packages'),
    queryFn: () => consolidationsApi.packages(consolidationId),
    enabled: masterQuery.isSuccess,
  });
  // Each customer's quote versions (the same cache the customer's quote panel reads).
  const members = masterQuery.data?.members ?? [];
  const quotesQueries = useQueries({
    queries: members.map((m) => ({
      queryKey: wsKey(consolidationId, 'quotes', m.shipment_id),
      queryFn: () => pricingApi.quotes(m.shipment_id),
    })),
  });

  if (masterQuery.isLoading) return <SkeletonCards count={3} />;
  if (masterQuery.error) {
    return (
      <Card>
        <ErrorState error={masterQuery.error} onRetry={masterQuery.refetch} />
      </Card>
    );
  }

  const master = masterQuery.data;
  const estimate = estimateQuery.data?.estimate;
  const activeVersion = (versionsQuery.data?.items ?? []).find((v) => v.status === 'active');
  const section = SECTION_BY_ORIGIN[master.origin];
  const editable = master.state === 'open' || master.state === 'booked';
  const settings = settingsQuery.data;
  // Owner decision 8: a booked master's items and fees are locked unless an Admin unlocked it.
  const itemsLocked = isItemsLocked(master);
  const pieces = piecesOf(master, cartonsQuery.data ?? []);
  const { byPiece, unassigned } = membersByPiece(master, pieces, packagesQuery.data?.members ?? {});
  const quotesBySid = Object.fromEntries(
    members.map((m, i) => [m.shipment_id, quotesQueries[i]?.data]).filter(([, v]) => v),
  );
  const model = buildWorkspaceModel({
    master,
    pieces,
    byPiece,
    unassigned,
    estimate,
    quotesBySid,
    hasActiveTariff: !versionsQuery.isSuccess || Boolean(activeVersion),
  });
  const sel = validSelection(searchParams.get('sel'), { pieces, bySid: model.bySid });

  const show = (id) => {
    guard.setDirty(false);
    setPending(null);
    setSearchParams(id === 'ship' ? {} : { sel: id }, { replace: false });
    // Bring the new screen's top into view on a long page (not available in tests).
    document.querySelector('.ws2-bar')?.scrollIntoView?.({ block: 'start' });
  };
  const onGo = (id, force = false) => {
    if (id === sel) return;
    if (guard.dirty && !force) setPending(id);
    else show(id);
  };

  const pieceOfSel = /^(p|add)(\d+)$/.exec(sel);
  const pieceSeq = pieceOfSel ? Number(pieceOfSel[2]) : null;
  const piece = pieces.find((p) => p.sequence === pieceSeq);
  const customer = sel[0] === 'c' && sel !== 'cost' ? model.bySid[Number(sel.slice(1))] : null;
  const idx = customer ? model.order.indexOf(customer.sid) : -1;

  return (
    <WorkspaceExpandProvider>
      <PageHeader
        breadcrumb={<Link to="/workspace">{t('workspace.title')}</Link>}
        title={`${master.public_id} · ${master.solaris_service_label}`}
        actions={
          <>
            <StatusBadge
              tone={STATE_TONE[master.state]}
              label={t(`workspace.states.${master.state}`, master.state)}
            />
            <MasterLockBadge master={master} />
          </>
        }
      />
      <SummaryBar
        master={master}
        estimate={estimate}
        model={model}
        dirty={guard.dirty}
        actions={
          <>
            <Button
              onClick={() => {
                queryClient.invalidateQueries({ queryKey: ['workspace-list'] });
                navigate('/workspace');
              }}
            >
              {t('wsFlow.saveAndClose')}
            </Button>
            <BookButton master={master} model={model} onGo={(id) => onGo(id)} />
          </>
        }
      />
      {settings && !settings.defaults_owner_confirmed && (
        <Banner tone="warning" title={t('workspace.pendingDefaultsTitle')}>
          {t('workspace.pendingDefaultsBody')
            .replace('{rate}', String(Number(settings.air_standard_default_rate_cad)))
            .replace(
              '{share}',
              `${settings.trigger_share_numerator}/${settings.trigger_share_denominator}`,
            )}
        </Banner>
      )}
      {!activeVersion && versionsQuery.isSuccess && (
        <Banner tone="danger">{t('workspace.noActiveTariff')}</Banner>
      )}
      <div className="ws2">
        <WorkspaceTree
          master={master}
          pieces={pieces}
          byPiece={byPiece}
          unassigned={unassigned}
          estimate={estimate}
          model={model}
          sel={sel}
          onGo={onGo}
        />
        {/* The pane remounts per selection, so a half-typed form never follows to the next one. */}
        <div className="ws2-pane" key={sel} onInput={guard.onInput} onChange={guard.onInput}>
          {sel === 'ship' && (
            <>
              <MasterPanel master={master} />
              <MasterLockPanel master={master} />
              <Checklist model={model} onGo={onGo} />
            </>
          )}

          {sel[0] === 'p' && piece && (
            <>
              <p className="ws2-crumb">{t('ws2.pieceCrumb')}</p>
              <PieceSection
                master={master}
                pieces={pieces}
                piece={piece}
                members={byPiece[piece.sequence] ?? []}
                estimate={estimate}
                packagesData={packagesQuery.data}
                section={section}
                versionId={activeVersion?.id}
                editable={editable}
                itemsLocked={itemsLocked}
                showCustomers={false}
                collapsible={false}
              />
              <Card
                title={t('ws2.customersTitle')}
                headingLevel="h3"
                actions={
                  master.state === 'open' && (
                    <Button variant="primary" compact onClick={() => onGo(`add${piece.sequence}`)}>
                      {fill(t('ws2.addTo'), { n: piece.sequence })}
                    </Button>
                  )
                }
              >
                <PieceCustomers members={byPiece[piece.sequence] ?? []} model={model} onGo={onGo} />
              </Card>
              <PerPieceSurcharges estimate={estimate} sequence={piece.sequence} model={model} />
            </>
          )}

          {customer && (
            <>
              <div className="ws2-cust-head">
                <p className="ws2-crumb">
                  {fill(t('ws2.customerCrumb'), {
                    piece: customer.piece ? fill(t('ws2.piece'), { n: customer.piece }) : t('ws2.noPiece'),
                    i: idx + 1,
                    n: model.order.length,
                  })}
                </p>
                <StatusBadge tone={STATUS_TONE[customer.status]} label={t(`ws2.status.${customer.status}`)} />
                <span className="spacer" />
                <Button compact variant="tertiary" disabled={idx <= 0} onClick={() => onGo(`c${model.order[idx - 1]}`)}>
                  {t('ws2.prev')}
                </Button>
                <Button
                  compact
                  variant="tertiary"
                  disabled={idx < 0 || idx >= model.order.length - 1}
                  onClick={() => onGo(`c${model.order[idx + 1]}`)}
                >
                  {t('ws2.next')}
                </Button>
              </div>
              <CustomerAlerts customer={customer} />
              {!customer.piece && pieces.length > 1 && (
                <PlaceInPiece master={master} member={customer.member} pieces={pieces} editable={editable} />
              )}
              <CustomerCard
                key={`${customer.sid}-${master.origin}`}
                consolidationId={master.id}
                member={customer.member}
                estimate={estimate}
                section={section}
                versionId={activeVersion?.id}
                editable={editable}
                itemsLocked={itemsLocked}
                removable={master.state === 'open'}
                pieces={pieces}
                currentPiece={customer.piece}
              />
            </>
          )}

          {sel.startsWith('add') && sel !== 'addpiece' && piece && master.state === 'open' && (
            <AddCustomerPane
              master={master}
              sequence={piece.sequence}
              section={section}
              versionId={activeVersion?.id}
              multiPiece={pieces.length > 1}
              onGo={onGo}
            />
          )}

          {sel === 'addpiece' && master.state === 'open' && cartonsQuery.isSuccess && (
            <AddPiece master={master} pieces={pieces} startOpen onAdded={(seq) => onGo(`p${seq}`, true)} />
          )}

          {sel === 'cost' && <CostQuotePanel master={master} estimateQuery={estimateQuery} />}
          {sel === 'bill' && <VendorBillPanel master={master} estimate={estimate} />}
          {sel === 'mile' && <MasterActionsPanel master={master} />}
        </div>
      </div>
      <Modal
        open={pending !== null}
        onClose={() => setPending(null)}
        title={t('ws2.unsavedTitle')}
        footer={
          <div className="row-wrap">
            <Button variant="primary" onClick={() => setPending(null)}>
              {t('ws2.stay')}
            </Button>
            <Button onClick={() => show(pending)}>{t('ws2.discard')}</Button>
          </div>
        }
      >
        <p>{t('ws2.unsavedBody')}</p>
      </Modal>
    </WorkspaceExpandProvider>
  );
}
