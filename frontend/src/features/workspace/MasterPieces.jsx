/**
 * The workspace in the owner's order (2026-11-04; DEC-0272):
 *
 *   master (tracking · origin · service)  →  master piece #1  →  its customers
 *   →  add customer  →  master piece #2  →  its customers  →  …
 *
 * A master piece is one carton of the master (`consolidation_cartons`). Its CW is the
 * server's (VW against GW); the customers inside it are the ones placed in that piece
 * (`consolidation_package_members`). On a one-piece master every customer is in piece 1. A
 * piece's CW may be lower than the total of its customers' CW (the small boxes never fill the
 * master box): that is shown as information, not as a problem.
 *
 * Adding a customer books the customer's shipment, joins it to the master and places it in
 * the piece in one request (`POST /consolidations/{id}/customers`); nothing is kept if the
 * server refuses. An existing booking can still be attached instead.
 */

import { useCallback, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi, customersApi, shipmentsApi, tariffsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Field, Modal, Select, TextInput } from '../../components/ui/index.jsx';
import { CollapsibleCard } from './CollapsibleCard.jsx';
import { suggestRules } from './FeePicker.jsx';
import { ErrorState } from '../../components/state/index.jsx';
import { CustomerCard } from './CustomerCard.jsx';
import { BaseCostPanel } from './CostQuotePanel.jsx';
import { compact } from './WorkspaceListPage.jsx';
import { formatKg, previewCw, wsKey } from './workspaceFormat.js';

export { previewCw };

function useRefresh(consolidationId) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: wsKey(consolidationId) });
    queryClient.invalidateQueries({ queryKey: ['workspace-list'] });
  };
}

const text = (value) => (value === null || value === undefined ? '' : String(Number(value)));

/** The pieces of a master: its cartons, or one piece from the master's own weights. */
export function piecesOf(master, cartons) {
  if (cartons.length) return cartons;
  return [
    {
      sequence: 1,
      weight_kg: master.actual_weight_kg,
      length_cm: master.length_cm,
      width_cm: master.width_cm,
      height_cm: master.height_cm,
      legacy: true,
    },
  ];
}

/** Which members ride in which piece; unplaced ones on a multi-piece master are returned apart. */
export function membersByPiece(master, pieces, placement) {
  const sequences = new Set(pieces.map((p) => p.sequence));
  const byPiece = Object.fromEntries(pieces.map((p) => [p.sequence, []]));
  const unassigned = [];
  for (const member of master.members) {
    const seq = pieces.length <= 1 ? pieces[0].sequence : Number(placement[String(member.shipment_id)]);
    if (sequences.has(seq)) byPiece[seq].push(member);
    else unassigned.push(member);
  }
  return { byPiece, unassigned };
}

/* --- Piece dimensions --------------------------------------------------------------------- */

function PieceEditor({ master, pieces, sequence, onDone }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const current = pieces.find((p) => p.sequence === sequence);
  const [form, setForm] = useState({
    weight_kg: text(current?.weight_kg),
    length_cm: text(current?.length_cm),
    width_cm: text(current?.width_cm),
    height_cm: text(current?.height_cm),
  });
  const set = (field) => (event) => setForm((f) => ({ ...f, [field]: event.target.value }));
  const save = useMutation({
    mutationFn: () => {
      const rows = pieces.map((p) =>
        p.sequence === sequence
          ? compact(form)
          : compact({
              weight_kg: text(p.weight_kg),
              length_cm: text(p.length_cm),
              width_cm: text(p.width_cm),
              height_cm: text(p.height_cm),
            }),
      );
      if (!pieces.some((p) => p.sequence === sequence)) rows.push(compact(form));
      // A master with no cartons yet shows its own weights as piece 1; a piece with no weight
      // cannot be saved, so it is left out.
      return consolidationsApi.replaceCartons(master.id, rows.filter((row) => row.weight_kg));
    },
    onSuccess: () => {
      refresh();
      onDone(true);
    },
  });
  const { vw, cw } = previewCw(form);
  return (
    <form
      className="ws-form"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      {save.error && <Banner tone="danger">{save.error.message}</Banner>}
      <div className="ws-grid">
        {[
          ['weight_kg', 'wsFlow.grossWeight', true],
          ['length_cm', 'workspace.lengthCm'],
          ['width_cm', 'workspace.widthCm'],
          ['height_cm', 'workspace.heightCm'],
        ].map(([field, key, required]) => (
          <Field key={field} label={t(key)} required={required}>
            {(props) => (
              <TextInput {...props} inputMode="decimal" value={form[field]} onChange={set(field)} />
            )}
          </Field>
        ))}
      </div>
      <p className="meta" role="status">
        {t('wsFlow.cwPreview')
          .replace('{vw}', vw === null ? '—' : formatKg(vw))
          .replace('{cw}', cw === null ? '—' : formatKg(cw))}
      </p>
      <div className="row-wrap">
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!form.weight_kg}>
          {t('wsFlow.savePiece')}
        </Button>
        <Button onClick={() => onDone()}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

function TrackingEditor({ master, sequence, value, editable }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const [draft, setDraft] = useState(value ?? '');
  useEffect(() => setDraft(value ?? ''), [value]);
  const save = useMutation({
    mutationFn: () => consolidationsApi.setPieceTracking(master.id, sequence, draft.trim()),
    onSuccess: refresh,
  });
  return (
    <form
      className="row-wrap ws-tracking"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Field
        label={t('wsFlow.lastMileTracking').replace('{n}', String(sequence))}
        hint={t('wsFlow.lastMileHint')}
        error={save.error?.message}
      >
        {(props) => (
          <TextInput
            {...props}
            maxLength={60}
            readOnly={!editable}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        )}
      </Field>
      {editable && (
        <Button type="submit" compact loading={save.isPending} disabled={draft === (value ?? '')}>
          {t('wsFlow.saveTracking')}
        </Button>
      )}
    </form>
  );
}

/* --- Quick customer profile ------------------------------------------------------------- */

const BLANK_PROFILE = { full_name: '', phone: '', email: '', city: '', province_state: '', country_code: 'CA' };

export function QuickCustomerDialog({ open, initialName, onClose, onCreated }) {
  const t = useT();
  const [form, setForm] = useState({ ...BLANK_PROFILE, full_name: initialName || '' });
  useEffect(() => {
    if (open) setForm({ ...BLANK_PROFILE, full_name: initialName || '' });
  }, [open, initialName]);
  const set = (field) => (event) => setForm((f) => ({ ...f, [field]: event.target.value }));
  const create = useMutation({
    mutationFn: () => customersApi.create({ ...compact(form), primary_route_group: 'VCA' }),
    onSuccess: (customer) => onCreated(customer),
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('wsFlow.newCustomerTitle')}
      footer={
        <div className="row-wrap">
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!form.full_name.trim()}
            onClick={() => create.mutate()}
          >
            {t('wsFlow.createCustomer')}
          </Button>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
        </div>
      }
    >
      <p className="meta">{t('wsFlow.newCustomerIntro')}</p>
      {create.error && <Banner tone="danger">{create.error.message}</Banner>}
      <div className="ws-grid">
        {[
          ['full_name', 'wsFlow.customerName', true],
          ['phone', 'wsFlow.phone'],
          ['email', 'wsFlow.email'],
          ['city', 'wsFlow.city'],
          ['province_state', 'wsFlow.province'],
          ['country_code', 'wsFlow.country'],
        ].map(([field, key, required]) => (
          <Field key={field} label={t(key)} required={required}>
            {(props) => (
              <TextInput
                {...props}
                maxLength={field === 'country_code' ? 2 : undefined}
                value={form[field]}
                onChange={set(field)}
              />
            )}
          </Field>
        ))}
      </div>
    </Modal>
  );
}

/* --- Add a customer to a piece ------------------------------------------------------------- */

function addressDefaults(customer, addresses) {
  const live = (addresses ?? []).filter((a) => !a.is_archived);
  const pick = (role, flag) =>
    live.find((a) => a[flag]) || live.find((a) => a.role === role) || live.find((a) => a.role === 'both');
  const sender = pick('sender', 'is_default_sender');
  const recipient = pick('recipient', 'is_default_recipient');
  return {
    sender_address_id: sender?.id ?? null,
    sender_name: sender?.contact_name ?? '',
    sender_country: sender?.country_code || 'VN',
    recipient_address_id: recipient?.id ?? null,
    recipient_name: recipient?.contact_name ?? customer.full_name ?? '',
    recipient_city: recipient?.city ?? customer.city ?? '',
    recipient_country: recipient?.country_code || customer.country_code || 'CA',
  };
}

const BLANK_SHIPMENT = {
  reference_code: '',
  weight_kg: '',
  length_cm: '',
  width_cm: '',
  height_cm: '',
};

const BLANK_ITEM = { description: '', quantity: '1', weight_kg: '' };

export function AddCustomerForm({ master, sequence, section, versionId, onDone }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const [query, setQuery] = useState('');
  const [customer, setCustomer] = useState(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(BLANK_SHIPMENT);
  const [parties, setParties] = useState(null);
  const [items, setItems] = useState([{ ...BLANK_ITEM }]);
  const setItem = (index, field) => (event) =>
    setItems((rows) => rows.map((row, i) => (i === index ? { ...row, [field]: event.target.value } : row)));
  const rulesQuery = useQuery({
    queryKey: ['workspace-rules', versionId, section],
    queryFn: () => tariffsApi.surcharges(versionId, { section }),
    enabled: Boolean(versionId && section),
  });
  const set = (field) => (event) => setForm((f) => ({ ...f, [field]: event.target.value }));
  const setParty = (field) => (event) => setParties((p) => ({ ...p, [field]: event.target.value }));
  // Stable, so the dialog's focus trap does not re-run (and move focus) on every keystroke.
  const closeDialog = useCallback(() => setCreating(false), []);

  const search = useQuery({
    queryKey: ['workspace-customer-search', query],
    queryFn: () => customersApi.list({ q: query.trim(), limit: 8 }),
    enabled: !customer && query.trim().length >= 2,
  });
  const addresses = useQuery({
    queryKey: ['workspace-customer-addresses', customer?.id],
    queryFn: () => customersApi.addresses(customer.id),
    enabled: Boolean(customer),
  });
  useEffect(() => {
    if (customer && addresses.isSuccess) setParties(addressDefaults(customer, addresses.data));
  }, [customer, addresses.isSuccess, addresses.data]);

  const add = useMutation({
    mutationFn: () =>
      consolidationsApi.addCustomer(master.id, {
        customer_id: customer.id,
        carton_sequence: sequence,
        ...compact(form),
        items: items
          .filter((row) => row.description.trim())
          .map((row) =>
            compact({
              description: row.description.trim(),
              quantity: row.quantity.trim(),
              weight_kg: row.weight_kg.trim(),
            }),
          ),
        sender: {
          ...(parties.sender_address_id ? { address_id: parties.sender_address_id } : {}),
          name: parties.sender_name.trim() || undefined,
          country_code: parties.sender_country.trim() || undefined,
        },
        recipient: {
          ...(parties.recipient_address_id ? { address_id: parties.recipient_address_id } : {}),
          name: parties.recipient_name.trim() || undefined,
          city: parties.recipient_city.trim() || undefined,
          country_code: parties.recipient_country.trim() || undefined,
        },
      }),
    // The server answers with the master; the pane opens the customer just added.
    onSuccess: (data) => {
      refresh();
      onDone(data);
    },
  });
  const { cw } = previewCw(form);
  const results = search.data?.items ?? [];

  return (
    <Card title={t('wsFlow.addCustomerTitle').replace('{n}', String(sequence))} headingLevel="h3">
      {!customer ? (
        <>
          <Field label={t('wsFlow.findCustomer')} hint={t('wsFlow.findCustomerHint')}>
            {(props) => (
              <TextInput
                {...props}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            )}
          </Field>
          {results.length > 0 && (
            <ul className="ws-results" aria-label={t('wsFlow.customerResults')}>
              {results.map((c) => (
                <li key={c.id}>
                  <span className="mono">{c.public_id}</span>
                  <span>{c.full_name}</span>
                  <span className="meta">{[c.phone_entered, c.city].filter(Boolean).join(' · ')}</span>
                  <Button compact onClick={() => setCustomer(c)}>
                    {t('wsFlow.choose')}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {query.trim().length >= 2 && search.isSuccess && results.length === 0 && (
            <p className="meta" role="status">
              {t('wsFlow.noCustomerFound')}
            </p>
          )}
          <div className="row-wrap">
            <Button onClick={() => setCreating(true)}>{t('wsFlow.newCustomer')}</Button>
            <Button variant="tertiary" onClick={onDone}>
              {t('common.cancel')}
            </Button>
          </div>
          <QuickCustomerDialog
            open={creating}
            initialName={query.trim()}
            onClose={closeDialog}
            onCreated={(created) => {
              setCreating(false);
              setCustomer(created);
            }}
          />
        </>
      ) : (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          <p>
            <strong>{customer.full_name}</strong> <span className="mono">{customer.public_id}</span>{' '}
            <Button
              compact
              variant="tertiary"
              onClick={() => {
                setCustomer(null);
                setParties(null);
              }}
            >
              {t('wsFlow.changeCustomer')}
            </Button>
          </p>
          {add.error && <Banner tone="danger">{add.error.message}</Banner>}
          {addresses.error && <ErrorState error={addresses.error} />}
          <div className="ws-grid">
            <Field label={t('wsFlow.referenceCode')} hint={t('wsFlow.referenceHint')}>
              {(props) => (
                <TextInput {...props} maxLength={60} value={form.reference_code} onChange={set('reference_code')} />
              )}
            </Field>
            {[
              ['weight_kg', 'wsFlow.grossWeight', true],
              ['length_cm', 'workspace.lengthCm'],
              ['width_cm', 'workspace.widthCm'],
              ['height_cm', 'workspace.heightCm'],
            ].map(([field, key, required]) => (
              <Field key={field} label={t(key)} required={required}>
                {(props) => (
                  <TextInput {...props} inputMode="decimal" value={form[field]} onChange={set(field)} />
                )}
              </Field>
            ))}
          </div>
          <p className="meta" role="status">
            {t('wsFlow.customerCwPreview').replace('{cw}', cw === null ? '—' : formatKg(cw))}
          </p>
          <fieldset className="ws-items-editor">
            <legend>{t('wsFlow.itemList')}</legend>
            <p className="meta">{t('wsFlow.itemListHint')}</p>
            {items.map((row, index) => {
              const hints = suggestRules(row.description, rulesQuery.data?.items ?? []);
              return (
                // Rows have no identity until saved; the position is the identity.
                <div key={index} className="ws-item-row">
                  <Field label={t('wsFlow.itemName').replace('{n}', String(index + 1))} required={index === 0}>
                    {(props) => (
                      <TextInput {...props} maxLength={300} value={row.description} onChange={setItem(index, 'description')} />
                    )}
                  </Field>
                  <Field label={t('wsFlow.itemQty')}>
                    {(props) => (
                      <TextInput {...props} inputMode="decimal" value={row.quantity} onChange={setItem(index, 'quantity')} />
                    )}
                  </Field>
                  <Field label={t('wsFlow.itemKg')}>
                    {(props) => (
                      <TextInput {...props} inputMode="decimal" value={row.weight_kg} onChange={setItem(index, 'weight_kg')} />
                    )}
                  </Field>
                  {items.length > 1 && (
                    <Button
                      compact
                      variant="tertiary"
                      onClick={() => setItems((rows) => rows.filter((_, i) => i !== index))}
                      aria-label={`${t('wsFlow.removeItem')} ${index + 1}`}
                    >
                      {t('wsFlow.removeItem')}
                    </Button>
                  )}
                  {hints.length > 0 && (
                    <p className="meta ws-item-hint" role="note">
                      {t('wsFlow.suggestedAfterAdd').replace('{names}', hints.map((h) => h.rule.name).join('; '))}
                    </p>
                  )}
                </div>
              );
            })}
            <Button compact onClick={() => setItems((rows) => [...rows, { ...BLANK_ITEM }])}>
              {t('wsFlow.addItemRow')}
            </Button>
          </fieldset>
          {parties && (
            <div className="ws-grid">
              <Field label={t('wsFlow.senderName')} required>
                {(props) => (
                  <TextInput {...props} value={parties.sender_name} onChange={setParty('sender_name')} />
                )}
              </Field>
              <Field label={t('wsFlow.senderCountry')} required>
                {(props) => (
                  <TextInput
                    {...props}
                    maxLength={2}
                    value={parties.sender_country}
                    onChange={setParty('sender_country')}
                  />
                )}
              </Field>
              <Field label={t('wsFlow.recipientName')} required>
                {(props) => (
                  <TextInput {...props} value={parties.recipient_name} onChange={setParty('recipient_name')} />
                )}
              </Field>
              <Field label={t('wsFlow.recipientCity')} required>
                {(props) => (
                  <TextInput {...props} value={parties.recipient_city} onChange={setParty('recipient_city')} />
                )}
              </Field>
              <Field label={t('wsFlow.recipientCountry')} required>
                {(props) => (
                  <TextInput
                    {...props}
                    maxLength={2}
                    value={parties.recipient_country}
                    onChange={setParty('recipient_country')}
                  />
                )}
              </Field>
            </div>
          )}
          <p className="meta">{t('wsFlow.addCustomerNote')}</p>
          <div className="row-wrap">
            <Button
              type="submit"
              variant="primary"
              loading={add.isPending}
              disabled={!parties || !form.weight_kg || !items.some((row) => row.description.trim())}
            >
              {t('wsFlow.addCustomerSubmit')}
            </Button>
            <Button onClick={onDone}>{t('common.cancel')}</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

/** Attach a booking already confirmed on the Shipments tab, as before. */
export function AttachBooking({ master, sequence, multiPiece, onDone }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const [query, setQuery] = useState('');
  const searchQuery = useQuery({
    queryKey: ['workspace-member-search', query],
    queryFn: () => shipmentsApi.search(query, 8),
    enabled: query.trim().length >= 2,
  });
  const add = useMutation({
    mutationFn: async (shipmentId) => {
      await consolidationsApi.addMember(master.id, shipmentId);
      if (multiPiece) await consolidationsApi.setPackageMember(master.id, shipmentId, sequence);
      return shipmentId;
    },
    onSuccess: (shipmentId) => {
      refresh();
      onDone(shipmentId);
    },
  });
  const memberIds = new Set(master.members.map((m) => m.shipment_id));
  const results = (searchQuery.data?.items ?? []).filter((s) => !memberIds.has(s.id));
  return (
    <div className="ws-add-member">
      <Field label={t('wsFlow.attachBooking')} hint={t('workspace.addCustomerHint')}>
        {(props) => (
          <TextInput {...props} type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
        )}
      </Field>
      {add.error && <Banner tone="danger">{add.error.message}</Banner>}
      {results.length > 0 && (
        <ul className="ws-results" aria-label={t('workspace.searchResults')}>
          {results.map((shipment) => (
            <li key={shipment.id}>
              <span className="mono">{shipment.public_id || shipment.booking_reference}</span>
              <span>{shipment.customer?.full_name || '—'}</span>
              <Button
                compact
                onClick={() => add.mutate(shipment.id)}
                loading={add.isPending && add.variables === shipment.id}
              >
                {t('workspace.addToMaster')}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Button variant="tertiary" onClick={onDone}>
        {t('common.cancel')}
      </Button>
    </div>
  );
}

/* --- One master piece ---------------------------------------------------------------------- */

export function PieceSection({
  master,
  pieces,
  piece,
  members,
  estimate,
  packagesData,
  section,
  versionId,
  editable,
  itemsLocked,
  // The two-pane workspace (DEC-0277) shows the piece's details alone; its customers are
  // listed by the piece pane and opened one at a time.
  showCustomers = true,
  collapsible = true,
}) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(null); // 'new' | 'attach'
  const detail = estimate?.method_detail;
  const pkg = (detail?.packages ?? []).find((p) => p.sequence === piece.sequence);
  const isOpen = master.state === 'open';
  const single = pieces.length <= 1;
  const customersCw = members.reduce(
    (sum, m) => sum + Number(detail?.members?.[String(m.shipment_id)]?.cw_kg ?? 0),
    0,
  );
  const pieceCw = pkg ? Number(pkg.raw_kg) : null;
  const remove = useMutation({
    mutationFn: () =>
      consolidationsApi.replaceCartons(
        master.id,
        pieces
          .filter((p) => p.sequence !== piece.sequence)
          .map((p) =>
            compact({
              weight_kg: text(p.weight_kg),
              length_cm: text(p.length_cm),
              width_cm: text(p.width_cm),
              height_cm: text(p.height_cm),
            }),
          ),
      ),
    onSuccess: refresh,
  });

  return (
    <section className="ws-piece" aria-labelledby={`ws-piece-${piece.sequence}`}>
      <CollapsibleCard
        headingLevel="h2"
        collapsible={collapsible}
        summary={t('wsFlow.pieceSummary')
          .replace('{gw}', formatKg(piece.weight_kg))
          .replace('{cw}', formatKg(pkg?.raw_kg))
          .replace('{count}', String(members.length))}
        title={
          <span id={`ws-piece-${piece.sequence}`}>
            {t('wsFlow.pieceTitle').replace('{n}', String(piece.sequence))}
          </span>
        }
        actions={
          editable &&
          !editing && (
            <div className="row-wrap">
              <Button compact onClick={() => setEditing(true)}>
                {t('wsFlow.editPiece')}
              </Button>
              {!single && members.length === 0 && (
                <Button compact variant="tertiary" loading={remove.isPending} onClick={() => remove.mutate()}>
                  {t('wsFlow.removePiece')}
                </Button>
              )}
            </div>
          )
        }
      >
        {remove.error && <Banner tone="danger">{remove.error.message}</Banner>}
        {editing ? (
          <PieceEditor
            master={master}
            pieces={pieces}
            sequence={piece.sequence}
            onDone={() => setEditing(false)}
          />
        ) : (
          <dl className="ws-details">
            <div className="ws-detail">
              <dt>{t('wsFlow.grossWeight')}</dt>
              <dd>{formatKg(piece.weight_kg)}</dd>
            </div>
            <div className="ws-detail">
              <dt>{t('workspace.dimensions')}</dt>
              <dd>
                {piece.length_cm && piece.width_cm && piece.height_cm
                  ? `${Number(piece.length_cm)} × ${Number(piece.width_cm)} × ${Number(piece.height_cm)} cm`
                  : '—'}
              </dd>
            </div>
            <div className="ws-detail">
              <dt>{t('wsFlow.pieceCw')}</dt>
              <dd>{formatKg(pkg?.raw_kg)}</dd>
            </div>
            <div className="ws-detail">
              <dt>{t('wsFlow.billedKg')}</dt>
              <dd>{formatKg(pkg?.billed_kg)}</dd>
            </div>
          </dl>
        )}
        <TrackingEditor
          master={master}
          sequence={piece.sequence}
          value={packagesData?.tracking?.[String(piece.sequence)]}
          editable={master.state !== 'cancelled'}
        />
        {piece.sequence === pieces[0].sequence && estimate && (
          <BaseCostPanel master={master} estimate={estimate} editable={editable} embedded />
        )}
        {pieceCw !== null && members.length > 0 && customersCw > pieceCw && (
          <p className="meta ws-cw-note" role="note">
            {t('wsFlow.cwGapNote')
              .replace('{piece}', formatKg(pieceCw))
              .replace('{customers}', formatKg(customersCw))}
          </p>
        )}
      </CollapsibleCard>

      {showCustomers && (
      <div className="ws-piece__customers">
        <h3 className="ws-section-title">
          {t('wsFlow.customersInPiece')
            .replace('{n}', String(piece.sequence))
            .replace('{count}', String(members.length))}
        </h3>
        {members.length === 0 && <p className="meta">{t('wsFlow.noCustomersYet')}</p>}
        {members.map((member) => (
          <CustomerCard
            // A new origin means another surcharge list: remount so nothing stale stays open.
            key={`${member.shipment_id}-${master.origin}`}
            consolidationId={master.id}
            member={member}
            estimate={estimate}
            section={section}
            versionId={versionId}
            editable={editable}
            itemsLocked={itemsLocked}
            removable={isOpen}
            collapsible
            defaultOpen={members.length === 1}
            pieces={pieces}
            currentPiece={piece.sequence}
          />
        ))}
        {isOpen &&
          (adding === 'new' ? (
            <AddCustomerForm
              master={master}
              sequence={piece.sequence}
              section={section}
              versionId={versionId}
              onDone={() => setAdding(null)}
            />
          ) : adding === 'attach' ? (
            <AttachBooking
              master={master}
              sequence={piece.sequence}
              multiPiece={!single}
              onDone={() => setAdding(null)}
            />
          ) : (
            <div className="row-wrap">
              <Button variant="primary" onClick={() => setAdding('new')}>
                {t('wsFlow.addCustomerTo').replace('{n}', String(piece.sequence))}
              </Button>
              <Button variant="tertiary" onClick={() => setAdding('attach')}>
                {t('wsFlow.attachExisting')}
              </Button>
            </div>
          ))}
      </div>
      )}
    </section>
  );
}

/** Customers on a multi-piece master not yet placed in a piece (older masters). */
export function UnassignedCustomers({ master, members, pieces, estimate, section, versionId, editable, itemsLocked }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const place = useMutation({
    mutationFn: ({ shipmentId, sequence }) => consolidationsApi.setPackageMember(master.id, shipmentId, sequence),
    onSuccess: refresh,
  });
  if (!members.length) return null;
  return (
    <section className="ws-piece" aria-labelledby="ws-unassigned">
      <h2 id="ws-unassigned" className="ws-section-title">
        {t('wsFlow.unassignedTitle')}
      </h2>
      <p className="meta">{t('wsFlow.unassignedHint')}</p>
      {place.error && <Banner tone="danger">{place.error.message}</Banner>}
      {members.map((member) => (
        <div key={member.shipment_id} className="ws-unassigned">
          <Field label={`${member.public_id} · ${member.customer_name || ''}`}>
            {(props) => (
              <Select
                {...props}
                disabled={!editable}
                value=""
                placeholder={t('costMethod.notRecorded')}
                onChange={(event) => place.mutate({ shipmentId: member.shipment_id, sequence: event.target.value })}
                options={pieces.map((p) => ({
                  value: String(p.sequence),
                  label: t('wsFlow.pieceTitle').replace('{n}', String(p.sequence)),
                }))}
              />
            )}
          </Field>
          <CustomerCard
            consolidationId={master.id}
            member={member}
            estimate={estimate}
            section={section}
            versionId={versionId}
            editable={editable}
            itemsLocked={itemsLocked}
            removable={master.state === 'open'}
          />
        </div>
      ))}
    </section>
  );
}

/** "Add master piece": one more carton on the same master tracking. */
export function AddPiece({ master, pieces, startOpen = false, onAdded }) {
  const t = useT();
  const [open, setOpen] = useState(startOpen);
  const next = Math.max(...pieces.map((p) => p.sequence)) + 1;
  if (!open) {
    return (
      <div className="row-wrap ws-add-piece">
        <Button onClick={() => setOpen(true)}>{t('wsFlow.addPiece')}</Button>
        <span className="meta">{t('wsFlow.addPieceHint')}</span>
      </div>
    );
  }
  return (
    <Card title={t('wsFlow.pieceTitle').replace('{n}', String(next))} headingLevel="h2">
      <PieceEditor
        master={master}
        pieces={pieces}
        sequence={next}
        onDone={(saved) => {
          setOpen(false);
          if (saved && onAdded) onAdded(next);
        }}
      />
    </Card>
  );
}
