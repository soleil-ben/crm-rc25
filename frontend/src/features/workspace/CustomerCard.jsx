/**
 * One customer on the master (Phase 13D): the shipment, its items, the fees attached to
 * each item, its share of the vendor cost, and its quote.
 */

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi, itemsApi, pricingApi, shipmentsApi, tariffsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Field, Select, TextInput } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { FeePicker, isManualAmount, suggestRules, usesItemWeight } from './FeePicker.jsx';
import { QuotePanel } from './QuotePanel.jsx';
import { CollapsibleCard } from './CollapsibleCard.jsx';
import { formatCad, formatKg, formatVnd, previewCw, sumOf, wsKey } from './workspaceFormat.js';

/** `app/services/shipment_item_service.py::ALLOWED_UNITS`; the server refuses anything else. */
export const ITEM_UNITS = ['piece', 'pair', 'box', 'bottle', 'set', 'kg', 'carton', 'other'];

function UnitSelect(props) {
  const t = useT();
  const known = ITEM_UNITS.includes(props.value);
  return (
    <Select
      {...props}
      options={[
        ...ITEM_UNITS.map((unit) => ({ value: unit, label: t(`workspace.units.${unit}`) })),
        // An older item stored with a unit outside today's list stays shown as it is.
        ...(known || !props.value ? [] : [{ value: props.value, label: props.value }]),
      ]}
    />
  );
}

const BLANK_ITEM = { description: '', quantity: '1', unit: 'piece', weight_kg: '' };

function AddItemForm({ shipmentId, onDone }) {
  const t = useT();
  const [form, setForm] = useState(BLANK_ITEM);
  const set = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));
  const add = useMutation({
    mutationFn: () =>
      itemsApi.add(shipmentId, {
        description: form.description,
        quantity: form.quantity || '1',
        unit: form.unit || 'piece',
        weight_kg: form.weight_kg || undefined,
      }),
    onSuccess: () => {
      setForm(BLANK_ITEM);
      onDone();
    },
  });
  return (
    <form
      className="ws-form"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate();
      }}
    >
      {add.error && <Banner tone="danger">{add.error.message}</Banner>}
      <div className="ws-grid">
        <Field label={t('workspace.itemDescription')} required>
          {(props) => (
            <TextInput {...props} required value={form.description} onChange={set('description')} />
          )}
        </Field>
        <Field label={t('workspace.itemQuantity')}>
          {(props) => (
            <TextInput {...props} inputMode="decimal" value={form.quantity} onChange={set('quantity')} />
          )}
        </Field>
        <Field label={t('workspace.itemUnit')}>
          {(props) => <UnitSelect {...props} value={form.unit} onChange={set('unit')} />}
        </Field>
        <Field label={t('workspace.itemWeight')}>
          {(props) => (
            <TextInput {...props} inputMode="decimal" value={form.weight_kg} onChange={set('weight_kg')} />
          )}
        </Field>
      </div>
      <Button type="submit" compact variant="primary" loading={add.isPending}>
        {t('workspace.addItem')}
      </Button>
    </form>
  );
}

function itemForm(item) {
  const text = (value) => (value === null || value === undefined ? '' : String(Number(value)));
  return {
    description: item.description,
    quantity: text(item.quantity),
    unit: item.unit || '',
    weight_kg: text(item.weight_kg),
    notes: item.notes || '',
  };
}

const DECIMAL = /^\d+(\.\d+)?$/;

/**
 * Edit one item (Phase 14): description, quantity, unit, weight and notes. Only changed
 * fields are sent; an emptied weight is cleared. The server validates again and audits;
 * a price already finalised does not move (re-price for a new draft).
 */
export function EditItemForm({ shipmentId, item, onDone, onCancel }) {
  const t = useT();
  const [form, setForm] = useState(() => itemForm(item));
  const [errors, setErrors] = useState({});
  const formRef = useRef(null);
  const set = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));

  useEffect(() => {
    formRef.current?.querySelector('input')?.focus();
  }, []);

  const save = useMutation({
    mutationFn: (payload) => itemsApi.update(shipmentId, item.id, payload),
    onSuccess: onDone,
  });
  const serverField = save.error?.field || (save.error?.invalidFields || [])[0];
  const shown = { ...(serverField ? { [serverField]: save.error.message } : {}), ...errors };

  return (
    <form
      ref={formRef}
      className="ws-form"
      aria-label={`${t('workspace.editItem')} — ${item.description}`}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const found = {};
        if (!form.description.trim()) found.description = t('workspace.itemErrors.description');
        if (!DECIMAL.test(form.quantity.trim()) || Number(form.quantity) <= 0) {
          found.quantity = t('workspace.itemErrors.quantity');
        }
        if (form.weight_kg.trim() && (!DECIMAL.test(form.weight_kg.trim()) || Number(form.weight_kg) <= 0)) {
          found.weight_kg = t('workspace.itemErrors.weight');
        }
        setErrors(found);
        const first = ['description', 'quantity', 'weight_kg'].find((field) => found[field]);
        if (first) {
          formRef.current?.querySelector(`[name="${first}"]`)?.focus();
          return;
        }
        const before = itemForm(item);
        const payload = {};
        if (form.description.trim() !== before.description) payload.description = form.description.trim();
        if (form.quantity.trim() !== before.quantity) payload.quantity = form.quantity.trim();
        if (form.unit !== before.unit) payload.unit = form.unit || 'piece';
        if (form.weight_kg.trim() !== before.weight_kg) payload.weight_kg = form.weight_kg.trim() || null;
        if (form.notes.trim() !== before.notes) payload.notes = form.notes.trim() || null;
        if (Object.keys(payload).length === 0) {
          onCancel();
          return;
        }
        save.mutate(payload);
      }}
    >
      {save.error && !serverField && <Banner tone="danger">{save.error.message}</Banner>}
      <div className="ws-grid">
        <Field label={t('workspace.itemDescription')} error={shown.description} required>
          {(props) => (
            <TextInput {...props} name="description" maxLength={300} value={form.description} onChange={set('description')} />
          )}
        </Field>
        <Field label={t('workspace.itemQuantity')} error={shown.quantity} required>
          {(props) => (
            <TextInput {...props} name="quantity" inputMode="decimal" value={form.quantity} onChange={set('quantity')} />
          )}
        </Field>
        <Field label={t('workspace.itemUnit')} error={shown.unit}>
          {(props) => <UnitSelect {...props} name="unit" value={form.unit} onChange={set('unit')} />}
        </Field>
        <Field label={t('workspace.itemWeight')} error={shown.weight_kg}>
          {(props) => (
            <TextInput {...props} name="weight_kg" inputMode="decimal" value={form.weight_kg} onChange={set('weight_kg')} />
          )}
        </Field>
      </div>
      <Field label={t('workspace.itemNotes')} hint={t('common.optional')} error={shown.notes}>
        {(props) => <TextInput {...props} name="notes" maxLength={400} value={form.notes} onChange={set('notes')} />}
      </Field>
      <div className="row-wrap">
        <Button type="submit" compact variant="primary" loading={save.isPending}>
          {t('workspace.saveItem')}
        </Button>
        <Button compact onClick={onCancel}>
          {t('common.cancel')}
        </Button>
      </div>
    </form>
  );
}

/** What a line quoted case by case still needs (owner 2026-10-23, DEC-0228), as an i18n key. */
export function manualNeededKey(line) {
  const cost = Boolean(line.manual_unit_price_vnd);
  const price = Boolean(line.customer_price_cad);
  if (!cost && !price) return 'workspace.manualNeededBoth';
  if (!cost) return 'workspace.manualNeededCost';
  if (!price) return 'workspace.manualNeededPrice';
  return null;
}

const stored = (value) => (value ? String(Number(value)) : '');

/**
 * A line quoted case by case (HCM air row 27; owner 2026-10-22 and 2026-10-23, DEC-0228): staff
 * enter the vendor's cost (VND) and the customer price (CAD), with no kilograms and no
 * quantity. Both start empty (no default); the customer is billed exactly the CAD price. Until
 * both are entered the quote cannot be finalised. Only the values that changed are sent; the
 * server validates them, checks the master lock and audits each change.
 */
function ManualPricesForm({ shipmentId, line, name, disabled, onSaved }) {
  const t = useT();
  const [cost, setCost] = useState(stored(line.manual_unit_price_vnd));
  const [price, setPrice] = useState(stored(line.customer_price_cad));
  const payload = {};
  if (cost.trim() && cost.trim() !== stored(line.manual_unit_price_vnd)) {
    payload.manual_unit_price_vnd = cost.trim();
  }
  if (price.trim() && price.trim() !== stored(line.customer_price_cad)) {
    payload.customer_price_cad = price.trim();
  }
  const changed = Object.keys(payload).length > 0;
  const save = useMutation({
    mutationFn: () => pricingApi.setFeeLinePrices(shipmentId, line.id, payload),
    onSuccess: onSaved,
  });
  return (
    <form
      className="ws-form ws-quoted-amount"
      onSubmit={(event) => {
        event.preventDefault();
        if (changed) save.mutate();
      }}
    >
      {save.error && <Banner tone="danger">{save.error.message}</Banner>}
      <p className="meta">
        {disabled ? t('workspace.quotedAmountLocked') : t('workspace.manualPricesHint')}
      </p>
      <div className="ws-grid">
        <Field label={`${t('workspace.manualCostVnd')} — ${name}`}>
          {(props) => (
            <TextInput
              {...props}
              name="manual_unit_price_vnd"
              inputMode="decimal"
              value={cost}
              disabled={disabled}
              onChange={(event) => setCost(event.target.value)}
            />
          )}
        </Field>
        <Field label={`${t('workspace.manualPriceCad')} — ${name}`}>
          {(props) => (
            <TextInput
              {...props}
              name="customer_price_cad"
              inputMode="decimal"
              value={price}
              disabled={disabled}
              onChange={(event) => setPrice(event.target.value)}
            />
          )}
        </Field>
      </div>
      <Button
        compact
        type="submit"
        loading={save.isPending}
        disabled={disabled || !changed}
        aria-label={`${t('workspace.saveManualPrices')} — ${name}`}
      >
        {t('workspace.saveManualPrices')}
      </Button>
    </form>
  );
}

function FeeLine({ line, item, fee, rule, shipmentId, onRemove, onSaved, removing, editable, locked }) {
  const name = fee?.name || rule?.name || `${line.section} #${line.stt}`;
  const t = useT();
  const manualAmount = isManualAmount(rule);
  return (
    <li className="ws-fee">
      <span>
        {name}
        <span className="meta">
          {manualAmount ? (
            <>
              {' '}
              ·{' '}
              {manualNeededKey(line)
                ? t(manualNeededKey(line))
                : `${t('workspace.manualCostVnd')} ${formatVnd(line.manual_unit_price_vnd)} · ${t(
                    'workspace.manualPriceCad',
                  )} ${formatCad(line.customer_price_cad)}`}
            </>
          ) : (
            <>
              {' '}
              · {t('workspace.feeQuantity')} {Number(line.quantity)}
              {line.weight_kg
                ? ` · ${formatKg(line.weight_kg)}`
                : usesItemWeight(rule) && item?.weight_kg
                  ? ` · ${formatKg(item.weight_kg)} ${t('wsFlow.fromItem')}`
                  : ''}
              {line.manual_unit_price_vnd
                ? ` · ${t('workspace.vendorPrice')} ${formatVnd(line.manual_unit_price_vnd)}`
                : ''}
            </>
          )}
        </span>
      </span>
      <span className="spacer" />
      <span className="meta">{fee ? formatVnd(fee.vendor_fee_vnd) : ''}</span>
      {editable && (
        <Button
          compact
          variant="tertiary"
          loading={removing}
          disabled={locked}
          onClick={onRemove}
          aria-label={`${t('workspace.removeFee')} — ${name}`}
        >
          {t('workspace.removeFee')}
        </Button>
      )}
      {manualAmount && editable && (
        <ManualPricesForm
          shipmentId={shipmentId}
          line={line}
          name={name}
          disabled={locked}
          onSaved={onSaved}
        />
      )}
    </li>
  );
}

/** Take a customer off an open master; the server requires a reason and audits it. */
function RemoveMember({ consolidationId, member, onRemoved }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const remove = useMutation({
    mutationFn: () => consolidationsApi.removeMember(consolidationId, member.shipment_id, reason),
    onSuccess: onRemoved,
  });
  if (!open) {
    return (
      <Button
        compact
        variant="tertiary"
        onClick={() => setOpen(true)}
        aria-label={`${t('workspace.removeCustomer')} ${member.public_id}`}
      >
        {t('workspace.removeCustomer')}
      </Button>
    );
  }
  return (
    <form
      className="ws-form"
      onSubmit={(event) => {
        event.preventDefault();
        remove.mutate();
      }}
    >
      {remove.error && <Banner tone="danger">{remove.error.message}</Banner>}
      <Field label={t('workspace.removeReason')} required>
        {(props) => (
          <TextInput
            {...props}
            required
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        )}
      </Field>
      <div className="row-wrap">
        <Button type="submit" variant="danger" compact loading={remove.isPending}>
          {t('workspace.confirmRemoveCustomer')}
        </Button>
        <Button compact onClick={() => setOpen(false)}>
          {t('common.cancel')}
        </Button>
      </div>
    </form>
  );
}

/* --- Edit a customer's details (owner review, 2026-11-05; DEC-0273) ------------------------ */

const num = (v) => (v === null || v === undefined ? '' : String(Number(v)));

export function EditCustomerForm({ consolidationId, member, pieces, currentPiece, weightsLocked, onDone }) {
  const t = useT();
  const queryClient = useQueryClient();
  const sid = member.shipment_id;
  const shipment = useQuery({ queryKey: ['workspace-shipment', sid], queryFn: () => shipmentsApi.get(sid) });
  const packages = useQuery({ queryKey: ['workspace-packages', sid], queryFn: () => shipmentsApi.packages(sid) });
  const active = (packages.data ?? []).filter((p) => p.is_active);
  const [form, setForm] = useState(null);
  const [placement, setPlacement] = useState(currentPiece ? String(currentPiece) : '');
  useEffect(() => {
    if (form || !shipment.isSuccess || !packages.isSuccess) return;
    const pkg = active.length === 1 ? active[0] : null;
    setForm({
      reference_code: shipment.data.booking_reference ?? '',
      weight_kg: num(pkg?.weight_kg),
      length_cm: num(pkg?.length_cm),
      width_cm: num(pkg?.width_cm),
      height_cm: num(pkg?.height_cm),
    });
  }, [form, shipment.isSuccess, packages.isSuccess, shipment.data, active]);
  const set = (field) => (event) => setForm((f) => ({ ...f, [field]: event.target.value }));
  const save = useMutation({
    mutationFn: () => {
      const payload = { reference_code: form.reference_code.trim() || null };
      if (!weightsLocked && active.length === 1) {
        for (const field of ['weight_kg', 'length_cm', 'width_cm', 'height_cm']) {
          if (form[field].trim()) payload[field] = form[field].trim();
        }
        if (pieces && pieces.length > 1 && placement) payload.carton_sequence = Number(placement);
      }
      return consolidationsApi.updateCustomer(consolidationId, sid, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: wsKey(consolidationId) });
      queryClient.invalidateQueries({ queryKey: ['workspace-shipment', sid] });
      queryClient.invalidateQueries({ queryKey: ['workspace-packages', sid] });
      onDone();
    },
  });
  if (!form) {
    return shipment.error || packages.error ? (
      <ErrorState error={shipment.error || packages.error} />
    ) : (
      <SkeletonRows rows={2} />
    );
  }
  const { cw } = previewCw(form);
  const measuresEditable = !weightsLocked && active.length === 1;
  return (
    <form
      className="ws-form ws-edit-customer"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h4 className="ws-subtitle">{t('wsFlow.editCustomerTitle')}</h4>
      {save.error && <Banner tone="danger">{save.error.message}</Banner>}
      {weightsLocked && <p className="meta">{t('wsFlow.weightsLocked')}</p>}
      {!weightsLocked && active.length !== 1 && <p className="meta">{t('wsFlow.severalPackages')}</p>}
      <div className="ws-grid">
        <Field label={t('wsFlow.referenceCode')}>
          {(props) => (
            <TextInput {...props} maxLength={60} value={form.reference_code} onChange={set('reference_code')} />
          )}
        </Field>
        {[
          ['weight_kg', 'wsFlow.grossWeight'],
          ['length_cm', 'workspace.lengthCm'],
          ['width_cm', 'workspace.widthCm'],
          ['height_cm', 'workspace.heightCm'],
        ].map(([field, key]) => (
          <Field key={field} label={t(key)}>
            {(props) => (
              <TextInput
                {...props}
                inputMode="decimal"
                readOnly={!measuresEditable}
                value={form[field]}
                onChange={set(field)}
              />
            )}
          </Field>
        ))}
        {pieces && pieces.length > 1 && (
          <Field label={t('wsFlow.piece')}>
            {(props) => (
              <Select
                {...props}
                disabled={!measuresEditable}
                value={placement}
                placeholder={t('costMethod.notRecorded')}
                onChange={(event) => setPlacement(event.target.value)}
                options={pieces.map((p) => ({
                  value: String(p.sequence),
                  label: t('wsFlow.pieceTitle').replace('{n}', String(p.sequence)),
                }))}
              />
            )}
          </Field>
        )}
      </div>
      {measuresEditable && (
        <p className="meta" role="status">
          {t('wsFlow.customerCwPreview').replace('{cw}', cw === null ? '—' : formatKg(cw))}
        </p>
      )}
      <p className="meta">{t('wsFlow.partiesLocked')}</p>
      <div className="row-wrap">
        <Button type="submit" variant="primary" compact loading={save.isPending}>
          {t('wsFlow.saveCustomer')}
        </Button>
        <Button compact onClick={onDone}>
          {t('common.cancel')}
        </Button>
      </div>
    </form>
  );
}

/** Remove an item; its fees go first, so nothing is left charged on a removed item. */
function RemoveItem({ shipmentId, item, itemLines, disabled, describedBy, onRemoved }) {
  const t = useT();
  const [asking, setAsking] = useState(false);
  const remove = useMutation({
    mutationFn: async () => {
      for (const line of itemLines) await pricingApi.removeFeeLine(shipmentId, line.id);
      await itemsApi.remove(shipmentId, item.id);
    },
    onSuccess: () => {
      setAsking(false);
      onRemoved();
    },
  });
  if (!asking) {
    return (
      <Button
        compact
        variant="tertiary"
        disabled={disabled}
        aria-describedby={describedBy}
        onClick={() => setAsking(true)}
        aria-label={`${t('wsFlow.removeItem')} — ${item.description}`}
      >
        {t('wsFlow.removeItem')}
      </Button>
    );
  }
  return (
    <span className="row-wrap ws-confirm" role="group" aria-label={t('wsFlow.removeItem')}>
      <span className="meta">
        {itemLines.length
          ? t('wsFlow.removeItemWithFees').replace('{n}', String(itemLines.length))
          : t('wsFlow.removeItemConfirm')}
      </span>
      {remove.error && <Banner tone="danger">{remove.error.message}</Banner>}
      <Button compact variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>
        {t('wsFlow.removeItemYes')}
      </Button>
      <Button compact onClick={() => setAsking(false)}>
        {t('common.cancel')}
      </Button>
    </span>
  );
}

export function CustomerCard({
  consolidationId,
  member,
  estimate,
  section,
  versionId,
  editable,
  itemsLocked = false,
  removable,
  collapsible = false,
  defaultOpen = true,
  pieces = null,
  currentPiece = null,
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const sid = member.shipment_id;
  const refresh = () => queryClient.invalidateQueries({ queryKey: wsKey(consolidationId) });
  const [pickerFor, setPickerFor] = useState(null);
  const [pickerQuery, setPickerQuery] = useState('');
  const [addingItem, setAddingItem] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [editingCustomer, setEditingCustomer] = useState(false);
  const focusEditButton = (itemId) =>
    setTimeout(() => document.querySelector(`[data-item-edit="${itemId}"]`)?.focus(), 0);

  const itemsQuery = useQuery({
    queryKey: wsKey(consolidationId, 'items', sid),
    queryFn: () => itemsApi.list(sid),
  });
  const linesQuery = useQuery({
    queryKey: wsKey(consolidationId, 'fee-lines', sid),
    queryFn: () => pricingApi.feeLines(sid),
  });
  const removeLine = useMutation({
    mutationFn: (lineId) => pricingApi.removeFeeLine(sid, lineId),
    onSuccess: refresh,
  });
  // The section's rules (shared with the fee picker's cache): a line's rule says whether it
  // takes a quoted amount (owner, 2026-10-22).
  const rulesQuery = useQuery({
    queryKey: ['workspace-rules', versionId, section],
    queryFn: () => tariffsApi.surcharges(versionId, { section }),
    enabled: Boolean(versionId && section),
  });
  const ruleFor = (line) =>
    (rulesQuery.data?.items ?? []).find((r) => r.section === line.section && r.stt === line.stt);

  const customerLabel = member.customer_name || member.public_id;
  const items = (itemsQuery.data ?? []).filter((item) => item.is_active);
  const lines = linesQuery.data ?? [];
  const result = estimate?.members.find((m) => m.shipment_id === sid);
  const quoteRow = estimate?.method_detail?.members?.[String(sid)];
  // The engine's vendor-fee instance for a fee line: a direct line has its own, a
  // master-wide rule one shared instance listing every triggering line.
  const feeFor = (lineId) =>
    estimate?.fees.find((f) => Object.values(f.triggers || {}).some((ids) => ids.includes(lineId)));

  return (
    <CollapsibleCard
      headingLevel="h3"
      collapsible={collapsible}
      defaultOpen={defaultOpen}
      className="ws-customer"
      summary={t('wsFlow.customerSummary')
        .replace('{kg}', formatKg(result?.billable_kg))
        .replace('{items}', String(items.length))
        .replace('{quote}', formatCad(quoteRow?.quote_cad))}
      title={`${member.customer_name || member.customer_public_id || ''} · ${member.public_id}`}
      actions={
        <div className="row-wrap">
        {editable && !editingCustomer && (
          <Button
            compact
            onClick={() => setEditingCustomer(true)}
            aria-label={`${t('wsFlow.editCustomer')} ${member.public_id}`}
          >
            {t('wsFlow.editCustomer')}
          </Button>
        )}
        {removable && (
          <RemoveMember
            consolidationId={consolidationId}
            member={member}
            onRemoved={() => {
              refresh();
              queryClient.invalidateQueries({ queryKey: ['workspace-list'] });
            }}
          />
        )}
        <Link
          to={`/shipments/${sid}`}
          className="meta"
          aria-label={`${t('workspace.openShipment')} ${member.public_id}`}
        >
          {t('workspace.openShipment')}
        </Link>
        </div>
      }
    >
      {editingCustomer && (
        <EditCustomerForm
          consolidationId={consolidationId}
          member={member}
          pieces={pieces}
          currentPiece={currentPiece}
          weightsLocked={itemsLocked}
          onDone={() => setEditingCustomer(false)}
        />
      )}
      <dl className="ws-details">
        <div className="ws-detail">
          <dt>{t('workspace.billableWeight')}</dt>
          <dd>{formatKg(result?.billable_kg)}</dd>
        </div>
        {/* Quote figures only (owner review, 2026-11-05; DEC-0274): the vendor's cost is the
            master's, shown once in "Cost and quote", not split onto each small box. */}
        <div className="ws-detail">
          <dt>{t('wsFlow.rate')}</dt>
          <dd>{quoteRow?.rate_cad_kg ? `${formatCad(quoteRow.rate_cad_kg)}/kg` : '—'}</dd>
        </div>
        <div className="ws-detail">
          <dt>{t('wsFlow.freightQuote')}</dt>
          <dd>{formatCad(quoteRow?.freight_cad)}</dd>
        </div>
        <div className="ws-detail">
          <dt>{t('wsFlow.surchargeQuote')}</dt>
          <dd>{formatCad(quoteRow?.surcharge_quote_cad)}</dd>
        </div>
        <div className="ws-detail">
          <dt>{t('wsFlow.quoteTotal')}</dt>
          <dd>
            <strong>{formatCad(quoteRow?.quote_cad)}</strong>
          </dd>
        </div>
      </dl>

      <h4 className="ws-subtitle">{t('workspace.items')}</h4>
      {editable && itemsLocked && (
        <p className="meta ws-locked-note" id={`ws-locked-${sid}`}>
          {t('masterLock.controlsDisabled')}
        </p>
      )}
      {itemsQuery.isLoading ? (
        <SkeletonRows rows={2} />
      ) : itemsQuery.error ? (
        <ErrorState error={itemsQuery.error} onRetry={itemsQuery.refetch} />
      ) : items.length === 0 ? (
        <p className="meta">{t('workspace.noItems')}</p>
      ) : (
        <ul className="ws-items">
          {items.map((item) => {
            const itemLines = lines.filter((line) => line.item_id === item.id);
            return (
              <li key={item.id} className="ws-item">
                <div className="ws-item__head">
                  <span>
                    <strong>{item.description}</strong>{' '}
                    <span className="meta">
                      {Number(item.quantity)} {item.unit}
                      {item.weight_kg ? ` · ${formatKg(item.weight_kg)}` : ''}
                    </span>
                  </span>
                  <span className="spacer" />
                  {editable && editingItem !== item.id && (
                    <Button
                      compact
                      variant="tertiary"
                      disabled={itemsLocked}
                      aria-describedby={itemsLocked ? `ws-locked-${sid}` : undefined}
                      data-item-edit={item.id}
                      onClick={() => setEditingItem(item.id)}
                      aria-label={`${t('workspace.editItem')} — ${item.description}`}
                    >
                      {t('workspace.editItem')}
                    </Button>
                  )}
                  {editable && editingItem !== item.id && (
                    <RemoveItem
                      shipmentId={sid}
                      item={item}
                      itemLines={itemLines}
                      disabled={itemsLocked}
                      describedBy={itemsLocked ? `ws-locked-${sid}` : undefined}
                      onRemoved={refresh}
                    />
                  )}
                  {editable && pickerFor !== item.id && (
                    <Button
                      compact
                      disabled={itemsLocked}
                      aria-describedby={itemsLocked ? `ws-locked-${sid}` : undefined}
                      onClick={() => {
                        setPickerQuery('');
                        setPickerFor(item.id);
                      }}
                      aria-label={`${t('workspace.addFee')} — ${item.description}`}
                    >
                      {t('workspace.addFee')}
                    </Button>
                  )}
                </div>
                {editingItem === item.id && (
                  <EditItemForm
                    shipmentId={sid}
                    item={item}
                    onCancel={() => {
                      setEditingItem(null);
                      focusEditButton(item.id);
                    }}
                    onDone={() => {
                      setEditingItem(null);
                      refresh();
                      focusEditButton(item.id);
                    }}
                  />
                )}
                {itemLines.length > 0 && (
                  <ul className="ws-fees" aria-label={t('workspace.feesOnItem')}>
                    {itemLines.map((line) => (
                      <FeeLine
                        key={line.id}
                        line={line}
                        item={item}
                        fee={feeFor(line.id)}
                        rule={ruleFor(line)}
                        shipmentId={sid}
                        onSaved={refresh}
                        editable={editable}
                        locked={itemsLocked}
                        removing={removeLine.isPending && removeLine.variables === line.id}
                        onRemove={() => removeLine.mutate(line.id)}
                      />
                    ))}
                  </ul>
                )}
                {editable &&
                  !itemsLocked &&
                  pickerFor !== item.id &&
                  itemLines.length === 0 &&
                  suggestRules(item.description, rulesQuery.data?.items ?? []).map(({ rule, why }) => (
                    <div className="ws-suggest" key={`${rule.section}-${rule.stt}`} role="note">
                      <span>
                        {t('wsFlow.suggested')}: <strong>{rule.name}</strong>{' '}
                        <span className="meta">{t('wsFlow.suggestedWhy').replace('{word}', why)}</span>
                      </span>
                      <Button
                        compact
                        onClick={() => {
                          setPickerQuery(rule.name);
                          setPickerFor(item.id);
                        }}
                        aria-label={`${t('wsFlow.reviewSuggestion')} — ${rule.name}`}
                      >
                        {t('wsFlow.reviewSuggestion')}
                      </Button>
                    </div>
                  ))}
                {pickerFor === item.id && (
                  <FeePicker
                    key={`${item.id}-${pickerQuery}`}
                    initialQuery={pickerQuery}
                    shipmentId={sid}
                    item={item}
                    section={section}
                    versionId={versionId}
                    onCancel={() => setPickerFor(null)}
                    onAdded={() => {
                      setPickerFor(null);
                      refresh();
                    }}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
      {removeLine.error && <Banner tone="danger">{removeLine.error.message}</Banner>}
      {editable &&
        (addingItem ? (
          <AddItemForm
            shipmentId={sid}
            onDone={() => {
              setAddingItem(false);
              refresh();
            }}
          />
        ) : (
          <Button
            compact
            disabled={itemsLocked}
            aria-describedby={itemsLocked ? `ws-locked-${sid}` : undefined}
            onClick={() => setAddingItem(true)}
          >
            {t('workspace.addItem')}
          </Button>
        ))}

      <QuotePanel
        consolidationId={consolidationId}
        shipmentId={sid}
        refresh={refresh}
        editable={editable}
        customerLabel={customerLabel}
        currentCostCad={result ? sumOf([result.base_cost_cad, result.surcharge_cost_cad]) : null}
      />
    </CollapsibleCard>
  );
}
