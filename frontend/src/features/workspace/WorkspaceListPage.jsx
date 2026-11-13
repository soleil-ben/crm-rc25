/**
 * Workspace → masters (Phase 13D).
 *
 * The list of vendor bookings (consolidations) and the form that opens a new one, in the
 * owner's order (DEC-0272): the master first -- master tracking, origin, service -- then
 * master piece #1 (weight and dimensions). Origin and service select the base rate. Opening
 * a master leads to its workspace, where pieces and the customers inside them are added.
 */

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Field,
  Pagination,
  Select,
  StatusBadge,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatKg, previewCw } from './workspaceFormat.js';
import './workspace.css';

/** Origin + service select the base rate (cost-quote-method.md §4). */
export const SERVICE_OPTIONS = ['air_standard', 'air_express', 'ups', 'air_cargo', 'sea'];

export const STATE_TONE = { open: 'info', booked: 'warning', completed: 'success', cancelled: 'neutral' };

/** Masters per page; the API allows up to 200. */
export const PAGE_SIZE = 50;

const EMPTY_FORM = {
  solaris_service: 'air_standard',
  origin: 'HCM',
  vendor_reference: '',
};

const BLANK_PIECE = { weight_kg: '', length_cm: '', width_cm: '', height_cm: '' };
const PIECE_LABELS = {
  weight_kg: 'wsFlow.grossWeight',
  length_cm: 'workspace.lengthCm',
  width_cm: 'workspace.widthCm',
  height_cm: 'workspace.heightCm',
};

/** Blank inputs are left out rather than sent as empty strings. */
export function compact(form) {
  return Object.fromEntries(
    Object.entries(form).filter(([, value]) => value !== '' && value !== null && value !== undefined),
  );
}

/**
 * New master in two parts (owner review, 2026-11-05): part 1 is the shipment itself --
 * master tracking, origin, service; part 2 is its list of master pieces, as many as it has.
 * The first piece's weight and size are also sent as the master's own (the server keeps them
 * as before); every piece becomes a carton of the master.
 */
function NewMasterForm({ onCancel }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState(EMPTY_FORM);
  const [pieces, setPieces] = useState([{ ...BLANK_PIECE }]);
  const [pieceError, setPieceError] = useState(null);
  const set = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));
  const setPiece = (index, field) => (event) =>
    setPieces((rows) => rows.map((row, i) => (i === index ? { ...row, [field]: event.target.value } : row)));
  const filled = pieces.filter((p) => p.weight_kg.trim());
  const totals = filled.reduce(
    (sum, p) => {
      const { cw } = previewCw(p);
      return { gw: sum.gw + Number(p.weight_kg), cw: sum.cw + (cw ?? 0) };
    },
    { gw: 0, cw: 0 },
  );

  const create = useMutation({
    mutationFn: async () => {
      const first = filled[0] ?? BLANK_PIECE;
      const master = await consolidationsApi.create({
        ...compact(form),
        ...compact({
          actual_weight_kg: first.weight_kg,
          length_cm: first.length_cm,
          width_cm: first.width_cm,
          height_cm: first.height_cm,
        }),
        carton_count: Math.max(filled.length, 1),
      });
      if (filled.length) {
        await consolidationsApi.replaceCartons(master.id, filled.map((p) => compact(p)));
      }
      return master;
    },
    onSuccess: (master) => {
      queryClient.invalidateQueries({ queryKey: ['workspace-list'] });
      navigate(`/workspace/${master.id}`);
    },
  });

  return (
    <Card title={t('workspace.newMasterTitle')}>
      <form
        className="ws-form"
        onSubmit={(event) => {
          event.preventDefault();
          const missing = pieces.findIndex(
            (p) => !p.weight_kg.trim() && (p.length_cm || p.width_cm || p.height_cm),
          );
          if (missing >= 0) {
            setPieceError(t('workspace.cartonNeedsWeight').replace('{n}', String(missing + 1)));
            return;
          }
          setPieceError(null);
          create.mutate();
        }}
      >
        {create.error && <Banner tone="danger">{create.error.message}</Banner>}
        <fieldset className="ws-part">
          <legend>{t('wsFlow.part1')}</legend>
          <div className="ws-grid">
            <Field label={t('workspace.vendorReference')} hint={t('wsFlow.masterTrackingHint')}>
              {(props) => (
                <TextInput {...props} maxLength={60} value={form.vendor_reference} onChange={set('vendor_reference')} />
              )}
            </Field>
            <Field label={t('workspace.origin')} required>
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
            <Field label={t('workspace.service')} required>
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
          </div>
          <p className="meta">{t('costMethod.serviceNote')}</p>
        </fieldset>

        <fieldset className="ws-part">
          <legend>{t('wsFlow.part2')}</legend>
          <p className="meta">{t('wsFlow.part2Hint')}</p>
          {pieceError && <Banner tone="danger">{pieceError}</Banner>}
          <div className="table-wrap">
            <table className="table ws-carton-table">
              <thead>
                <tr>
                  <th scope="col">{t('wsFlow.piece')}</th>
                  <th scope="col">{t('wsFlow.grossWeight')}</th>
                  <th scope="col">{t('workspace.lengthCm')}</th>
                  <th scope="col">{t('workspace.widthCm')}</th>
                  <th scope="col">{t('workspace.heightCm')}</th>
                  <th scope="col">{t('wsFlow.pieceCw')}</th>
                  <th scope="col">
                    <span className="visually-hidden">{t('wsFlow.removePiece')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {pieces.map((piece, index) => {
                  const { cw } = previewCw(piece);
                  return (
                    // Rows have no identity until saved; the position is the identity.
                    <tr key={index}>
                      <th scope="row">#{index + 1}</th>
                      {['weight_kg', 'length_cm', 'width_cm', 'height_cm'].map((field) => (
                        <td key={field}>
                          <TextInput
                            aria-label={`${t(PIECE_LABELS[field])} — ${t('wsFlow.pieceTitle').replace('{n}', String(index + 1))}`}
                            inputMode="decimal"
                            value={piece[field]}
                            onChange={setPiece(index, field)}
                          />
                        </td>
                      ))}
                      <td>{cw === null ? '—' : formatKg(cw)}</td>
                      <td>
                        {pieces.length > 1 && (
                          <Button
                            compact
                            variant="tertiary"
                            onClick={() => setPieces((rows) => rows.filter((_, i) => i !== index))}
                          >
                            {t('wsFlow.removePiece')}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="row-wrap">
            <Button compact onClick={() => setPieces((rows) => [...rows, { ...BLANK_PIECE }])}>
              {t('wsFlow.addPiece')}
            </Button>
            <span className="meta" role="status">
              {t('wsFlow.piecesTotal')
                .replace('{n}', String(filled.length))
                .replace('{gw}', formatKg(totals.gw))
                .replace('{cw}', formatKg(totals.cw))}
            </span>
          </div>
        </fieldset>
        <div className="row-wrap">
          <Button type="submit" variant="primary" loading={create.isPending}>
            {t('workspace.createMaster')}
          </Button>
          <Button onClick={onCancel}>{t('common.cancel')}</Button>
        </div>
      </form>
    </Card>
  );
}

export function WorkspaceListPage() {
  const t = useT();
  const [creating, setCreating] = useState(false);
  const [offset, setOffset] = useState(0);
  const listQuery = useQuery({
    queryKey: ['workspace-list', offset],
    queryFn: () => consolidationsApi.list({ limit: PAGE_SIZE, offset }),
  });
  const masters = listQuery.data?.items ?? [];

  return (
    <>
      <PageHeader
        title={t('workspace.title')}
        subtitle={t('workspace.subtitle')}
        actions={
          !creating && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              {t('workspace.newMaster')}
            </Button>
          )
        }
      />
      {creating && <NewMasterForm onCancel={() => setCreating(false)} />}
      <Card title={t('workspace.mastersTitle')} flush>
        {listQuery.isLoading ? (
          <SkeletonRows rows={4} />
        ) : listQuery.error ? (
          <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
        ) : masters.length === 0 ? (
          <EmptyState title={t('workspace.noMastersTitle')} body={t('workspace.noMastersBody')} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('workspace.master')}</th>
                  <th scope="col">{t('workspace.service')}</th>
                  <th scope="col">{t('workspace.origin')}</th>
                  <th scope="col">{t('workspace.vendorReference')}</th>
                  <th scope="col">{t('workspace.state')}</th>
                  <th scope="col">{t('workspace.customers')}</th>
                  <th scope="col">{t('workspace.chargeableWeight')}</th>
                </tr>
              </thead>
              <tbody>
                {masters.map((master) => (
                  <tr key={master.id}>
                    <td>
                      <Link to={`/workspace/${master.id}`} className="mono">
                        {master.public_id}
                      </Link>
                    </td>
                    <td>{master.solaris_service_label}</td>
                    <td>{master.origin}</td>
                    <td className="mono">{master.vendor_reference || '—'}</td>
                    <td>
                      <StatusBadge
                        tone={STATE_TONE[master.state]}
                        label={t(`workspace.states.${master.state}`, master.state)}
                      />
                    </td>
                    <td>{master.member_count}</td>
                    <td>{formatKg(master.chargeable_weight_kg)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination
          total={listQuery.data?.total ?? 0}
          limit={PAGE_SIZE}
          offset={offset}
          onChange={setOffset}
        />
      </Card>
    </>
  );
}
