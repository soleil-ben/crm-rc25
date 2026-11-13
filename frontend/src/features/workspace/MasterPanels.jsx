/**
 * The master's own panels in the workspace (Phase 13D): header and weights, cartons, and
 * the vendor-cost summary.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi, tariffsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Field, Select, TextInput } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { SERVICE_OPTIONS, compact } from './WorkspaceListPage.jsx';
import { formatCad, formatKg, formatVnd, sumOf, wsKey } from './workspaceFormat.js';

function useRefresh(consolidationId) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: wsKey(consolidationId) });
    queryClient.invalidateQueries({ queryKey: ['workspace-list'] });
  };
}

function Detail({ label, children }) {
  return (
    <div className="ws-detail">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/* --- Master header ------------------------------------------------------------------------ */

function weightForm(master) {
  const text = (value) => (value === null || value === undefined ? '' : String(value));
  return {
    solaris_service: master.solaris_service,
    origin: master.origin,
    vendor_reference: text(master.vendor_reference),
  };
}

export function MasterPanel({ master }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(() => weightForm(master));
  const set = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));

  const save = useMutation({
    mutationFn: () => {
      const before = weightForm(master);
      const payload = Object.fromEntries(
        Object.entries(form)
          .filter(([field, value]) => value !== before[field])
          .map(([field, value]) => [field, value === '' ? null : value]),
      );
      return consolidationsApi.update(master.id, payload);
    },
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const isOpen = master.state === 'open';

  return (
    <Card
      title={t('wsFlow.shipmentTitle')}
      actions={
        isOpen &&
        !editing && (
          <Button
            compact
            onClick={() => {
              setForm(weightForm(master));
              setEditing(true);
            }}
          >
            {t('wsFlow.editShipment')}
          </Button>
        )
      }
    >
      {editing ? (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          {save.error && <Banner tone="danger">{save.error.message}</Banner>}
          <div className="ws-grid">
            <Field label={t('workspace.vendorReference')} hint={t('wsFlow.masterTrackingHint')}>
              {(props) => (
                <TextInput {...props} maxLength={60} value={form.vendor_reference} onChange={set('vendor_reference')} />
              )}
            </Field>
            <Field label={t('workspace.service')} hint={t('costMethod.serviceChangeHint')} required>
              {(props) => (
                <Select
                  {...props}
                  value={form.solaris_service}
                  onChange={set('solaris_service')}
                  options={SERVICE_OPTIONS.map((value) => ({
                    value,
                    label: t(`costMethod.service.${value}`),
                  }))}
                />
              )}
            </Field>
            <Field label={t('workspace.origin')} hint={t('costMethod.originChangeHint')} required>
              {(props) => (
                <Select
                  {...props}
                  value={form.origin}
                  onChange={set('origin')}
                  options={[
                    { value: 'HCM', label: t('workspace.originHcm') },
                    { value: 'HAN', label: t('workspace.originHan') },
                  ]}
                />
              )}
            </Field>
          </div>
          <div className="row-wrap">
            <Button type="submit" variant="primary" loading={save.isPending}>
              {t('common.save')}
            </Button>
            <Button onClick={() => setEditing(false)}>{t('common.cancel')}</Button>
          </div>
        </form>
      ) : (
        <dl className="ws-details">
          <Detail label={t('workspace.vendorReference')}>
            <span className="mono">{master.vendor_reference || '—'}</span>
          </Detail>
          <Detail label={t('workspace.origin')}>
            {master.origin === 'HAN' ? t('workspace.originHan') : t('workspace.originHcm')}
          </Detail>
          <Detail label={t('workspace.service')}>{master.solaris_service_label}</Detail>
          <Detail label={t('workspace.vendorProduct')}>{master.vendor_product_code || '—'}</Detail>
          <Detail label={t('workspace.chargeableWeight')}>
            {formatKg(master.chargeable_weight_kg)}
          </Detail>
        </dl>
      )}
    </Card>
  );
}

/* --- Cartons (OD-62) ---------------------------------------------------------------------- */

const BLANK_CARTON = { weight_kg: '', length_cm: '', width_cm: '', height_cm: '' };

function CartonEditor({ consolidationId, initial, onDone }) {
  const t = useT();
  const refresh = useRefresh(consolidationId);
  const [rows, setRows] = useState(initial.length ? initial : [{ ...BLANK_CARTON }]);
  const setCell = (index, field) => (event) =>
    setRows((current) =>
      current.map((row, i) => (i === index ? { ...row, [field]: event.target.value } : row)),
    );
  const [rowError, setRowError] = useState(null);
  const save = useMutation({
    mutationFn: () =>
      consolidationsApi.replaceCartons(
        consolidationId,
        rows.filter((row) => row.weight_kg !== '').map(compact),
      ),
    onSuccess: () => {
      refresh();
      onDone();
    },
  });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const missing = rows.findIndex(
          (row) => row.weight_kg === '' && (row.length_cm || row.width_cm || row.height_cm),
        );
        if (missing >= 0) {
          setRowError(t('workspace.cartonNeedsWeight').replace('{n}', String(missing + 1)));
          return;
        }
        setRowError(null);
        save.mutate();
      }}
    >
      {rowError && <Banner tone="danger">{rowError}</Banner>}
      {save.error && <Banner tone="danger">{save.error.message}</Banner>}
      <div className="table-wrap">
        <table className="table ws-carton-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">{t('workspace.weightKg')}</th>
              <th scope="col">{t('workspace.lengthCm')}</th>
              <th scope="col">{t('workspace.widthCm')}</th>
              <th scope="col">{t('workspace.heightCm')}</th>
              <th scope="col">
                <span className="visually-hidden">{t('workspace.removeCarton')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              // Rows have no identity until saved; the position is the identity.
              <tr key={index}>
                <td>{index + 1}</td>
                {['weight_kg', 'length_cm', 'width_cm', 'height_cm'].map((field) => (
                  <td key={field}>
                    <TextInput
                      aria-label={`${t(`workspace.carton.${field}`)} ${index + 1}`}
                      inputMode="decimal"
                      value={row[field]}
                      onChange={setCell(index, field)}
                    />
                  </td>
                ))}
                <td>
                  <Button
                    compact
                    variant="tertiary"
                    onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                  >
                    {t('workspace.removeCarton')}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row-wrap">
        <Button onClick={() => setRows((current) => [...current, { ...BLANK_CARTON }])}>
          {t('workspace.addCarton')}
        </Button>
        <Button type="submit" variant="primary" loading={save.isPending}>
          {t('workspace.saveCartons')}
        </Button>
        <Button onClick={onDone}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

export function CartonsPanel({ master, estimate, editable }) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const cartonsQuery = useQuery({
    queryKey: wsKey(master.id, 'cartons'),
    queryFn: () => consolidationsApi.cartons(master.id),
  });
  const cartons = cartonsQuery.data ?? [];
  const text = (value) => (value === null || value === undefined ? '' : String(Number(value)));

  return (
    <Card
      title={t('workspace.cartonsTitle')}
      actions={
        editable &&
        !editing && (
          <Button compact disabled={!cartonsQuery.isSuccess} onClick={() => setEditing(true)}>
            {t('workspace.editCartons')}
          </Button>
        )
      }
    >
      <p className="meta">{t('workspace.cartonsHint')}</p>
      {cartonsQuery.error && <ErrorState error={cartonsQuery.error} />}
      {editing ? (
        <CartonEditor
          consolidationId={master.id}
          initial={cartons.map((c) => ({
            weight_kg: text(c.weight_kg),
            length_cm: text(c.length_cm),
            width_cm: text(c.width_cm),
            height_cm: text(c.height_cm),
          }))}
          onDone={() => setEditing(false)}
        />
      ) : cartons.length === 0 ? (
        <p>{t('workspace.noCartons')}</p>
      ) : (
        <ul className="ws-cartons">
          {cartons.map((c) => (
            <li key={c.sequence}>
              <span className="mono">#{c.sequence}</span> {formatKg(c.weight_kg)}
              {c.length_cm && c.width_cm && c.height_cm
                ? ` · ${Number(c.length_cm)} × ${Number(c.width_cm)} × ${Number(c.height_cm)} cm`
                : ''}
            </li>
          ))}
        </ul>
      )}
      {estimate && (
        <p>
          {t('workspace.pieceFee')}:{' '}
          <strong>{formatVnd(estimate.method_detail?.piece_vnd ?? estimate.piece_fee_vnd)}</strong>
        </p>
      )}
    </Card>
  );
}

/* --- Vendor cost summary ------------------------------------------------------------------ */

export function IssueList({ issues, tone, title }) {
  if (!issues?.length) return null;
  return (
    <Banner tone={tone} title={title}>
      <ul className="ws-issues">
        {issues.map((issue, index) => (
          // Issues carry no id; the engine returns them in a stable order.
          <li key={`${issue.code}-${index}`}>{issue.message}</li>
        ))}
      </ul>
    </Banner>
  );
}

export function CostPanel({ estimateQuery, members }) {
  const t = useT();
  const fxQuery = useQuery({ queryKey: ['fx-latest'], queryFn: tariffsApi.fxLatest });
  const estimate = estimateQuery.data?.estimate;
  const fx = fxQuery.data;
  const nameOf = Object.fromEntries(members.map((m) => [String(m.shipment_id), m]));

  return (
    <Card title={t('workspace.vendorCostTitle')}>
      <p className="meta">{t('workspace.internalOnly')}</p>
      {estimateQuery.isLoading ? (
        <SkeletonRows rows={4} />
      ) : estimateQuery.error ? (
        <ErrorState error={estimateQuery.error} onRetry={estimateQuery.refetch} />
      ) : estimate ? (
        <>
          <dl className="ws-details ws-details--stack">
            <Detail label={t('workspace.vendorProduct')}>{estimate.product_code || '—'}</Detail>
            <Detail label={t('workspace.deliveryPoint')}>
              {estimate.delivery_postal_code} · {t('workspace.zone')} {estimate.zone ?? '—'}
            </Detail>
            <Detail label={t('workspace.chargeableWeight')}>
              {formatKg(estimate.master_chargeable_kg)}
            </Detail>
            <Detail label={t('workspace.baseFreight')}>{formatVnd(estimate.base_freight_vnd)}</Detail>
            <Detail label={t('workspace.pieceFee')}>{formatVnd(estimate.piece_fee_vnd)}</Detail>
            <Detail label={t('workspace.surcharges')}>
              {formatVnd(sumOf(estimate.fees.map((f) => f.vendor_fee_vnd)))}
            </Detail>
            <Detail label={t('workspace.totalVendorCost')}>
              <strong>{formatVnd(estimate.total_cost_vnd)}</strong>
            </Detail>
          </dl>
          {fx?.snapshot && (
            <p className="meta">
              {t('workspace.fxLine')
                .replace('{buy}', formatVnd(fx.snapshot.cash_buy_vnd))
                .replace('{sell}', formatVnd(fx.snapshot.sell_vnd))}{' '}
              ({t(`workspace.fx.${fx.freshness}`, fx.freshness)})
              {fx.snapshot.is_demo && <strong> {t('workspace.fxDemo')}</strong>}
            </p>
          )}
          <h3 className="ws-subtitle">{t('workspace.costByCustomer')}</h3>
          <ul className="ws-split">
            {estimate.members.map((m) => (
              <li key={m.shipment_id}>
                <span>{nameOf[String(m.shipment_id)]?.customer_name || m.public_id}</span>
                <span>{formatCad(sumOf([m.base_cost_cad, m.surcharge_cost_cad]))}</span>
              </li>
            ))}
          </ul>
          <IssueList issues={estimate.blocking} tone="danger" title={t('workspace.blockingTitle')} />
          <IssueList
            issues={estimate.provisional}
            tone="warning"
            title={t('workspace.provisionalTitle')}
          />
        </>
      ) : null}
    </Card>
  );
}
