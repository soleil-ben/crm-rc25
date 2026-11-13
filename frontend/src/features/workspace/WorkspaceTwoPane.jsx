/**
 * The two-pane workspace (owner, 2026-11-06; DEC-0277): a summary bar on top, the master's
 * structure on the left (shipment → pieces → customers → whole master), and one thing at a
 * time on the right. Every screen on the right is a component the workspace already had
 * (MasterPanel, PieceSection, CustomerCard, AddCustomerForm, CostQuotePanel, VendorBillPanel,
 * MasterActionsPanel), so every function and every rule they carry is unchanged.
 *
 * Data control:
 * - each customer in the tree carries its state (missing information / not quoted / draft /
 *   finalised) and the number of things to fix, from the server's estimate and quotes;
 * - "Check before booking" lists every open problem, each with a link to where it is fixed;
 * - booking with problems open asks for confirmation, listing them;
 * - leaving a screen with typed, unsaved input asks first.
 */

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Field, Modal, Select, StatusBadge } from '../../components/ui/index.jsx';
import { formatCad, formatKg, formatVnd, wsKey } from './workspaceFormat.js';

export const fill = (text, params = {}) =>
  Object.entries(params).reduce((out, [k, v]) => out.split(`{${k}}`).join(String(v ?? '')), text);

export const STATUS_TONE = { error: 'danger', none: 'warning', unknown: 'warning', draft: 'info', final: 'success' };

/* --- Summary bar ---------------------------------------------------------------------------- */

export function SummaryBar({ master, estimate, model, dirty, actions }) {
  const t = useT();
  const totals = estimate?.method_detail?.totals ?? {};
  const cw = estimate?.master_chargeable_kg ?? master.chargeable_weight_kg;
  const total = model.customers.length;
  const pct = total ? Math.round((model.readyCount / total) * 100) : 0;
  const origin = { HCM: 'SGN', HAN: 'HAN' }[master.origin] ?? master.origin;
  return (
    <div className="ws2-bar" role="region" aria-label={t('wsFlow.actionBar')}>
      <div className="ws2-kv">
        <span>{t('ws2.awb')}</span>
        <b className="ws2-num">{master.vendor_reference || '—'}</b>
      </div>
      <div className="ws2-kv">
        <span>{t('ws2.route')}</span>
        <b>
          {origin} → Canada · {master.solaris_service_label}
        </b>
      </div>
      <div className="ws2-kv">
        <span>{t('ws2.cw')}</span>
        <b className="ws2-num">{formatKg(cw)}</b>
      </div>
      <div className="ws2-kv">
        <span>{t('ws2.cost')}</span>
        <b className="ws2-num">{formatCad(totals.cost_cad)}</b>
      </div>
      <div className="ws2-kv">
        <span>{t('ws2.quote')}</span>
        <b className="ws2-num">{formatCad(totals.quote_cad)}</b>
      </div>
      <div className="ws2-kv">
        <span>{t('ws2.profit')}</span>
        <b className="ws2-num ws2-profit">{formatCad(totals.profit_cad)}</b>
      </div>
      <div className="ws2-progress">
        <span>{fill(t('ws2.progress'), { ready: model.readyCount, total })}</span>
        <div className="ws2-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <div className="ws2-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="ws2-bar__actions">
        {dirty && <span className="ws2-dirty">● {t('ws2.unsaved')}</span>}
        {actions}
      </div>
    </div>
  );
}

/* --- Book, with the open problems confirmed first ------------------------------------------ */

export function BookButton({ master, model, onGo }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const book = useMutation({
    mutationFn: () => consolidationsApi.book(master.id),
    onSuccess: () => {
      setConfirming(false);
      queryClient.invalidateQueries({ queryKey: wsKey(master.id) });
      queryClient.invalidateQueries({ queryKey: ['workspace-list'] });
    },
  });
  if (master.state !== 'open') return null;
  const errors = model.checks.filter((c) => c.level === 'error');
  return (
    <>
      {book.error && !confirming && <Banner tone="danger">{book.error.message}</Banner>}
      <Button
        variant="primary"
        disabled={master.members.length === 0}
        loading={book.isPending && !confirming}
        onClick={() => (errors.length ? setConfirming(true) : book.mutate())}
      >
        {errors.length ? fill(t('ws2.bookWithErrors'), { count: errors.length }) : t('workspace.bookMaster')}
      </Button>
      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={t('ws2.bookConfirmTitle')}
        footer={
          <div className="row-wrap">
            <Button
              onClick={() => {
                setConfirming(false);
                onGo(errors[0].target);
              }}
            >
              {t('ws2.goFix')}
            </Button>
            <Button variant="primary" loading={book.isPending} onClick={() => book.mutate()}>
              {t('ws2.bookAnyway')}
            </Button>
          </div>
        }
      >
        <p>{t('ws2.bookConfirmBody')}</p>
        {book.error && <Banner tone="danger">{book.error.message}</Banner>}
        <ul className="ws2-confirm-list">
          {errors.map((c, i) => (
            <li key={i}>
              <CheckText check={c} />
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

/* --- Tree ----------------------------------------------------------------------------------- */

function TreeNode({ sel, id, onGo, level = 0, kind = '', dot, label, sub, badge, badgeTone }) {
  const selected = sel === id;
  return (
    <li>
      <button
        type="button"
        className={`ws2-node ws2-node--l${level} ${kind ? `ws2-node--${kind}` : ''} ${selected ? 'is-selected' : ''}`.trim()}
        aria-current={selected ? 'true' : undefined}
        onClick={() => onGo(id)}
      >
        {dot && <span className={`ws2-dot ws2-dot--${dot}`} aria-hidden="true" />}
        <span className="ws2-node__label">{label}</span>
        {sub && <span className="ws2-node__sub ws2-num">{sub}</span>}
        {badge ? <span className={`ws2-badge ws2-badge--${badgeTone}`}>{badge}</span> : null}
      </button>
    </li>
  );
}

export function WorkspaceTree({ master, pieces, byPiece, unassigned, estimate, model, sel, onGo }) {
  const t = useT();
  const [onlyIssues, setOnlyIssues] = useState(false);
  const detail = estimate?.method_detail;
  const isOpen = master.state === 'open';
  const shipErrors = model.errorCount;
  const custNode = (member) => {
    const c = model.bySid[member.shipment_id];
    if (!c) return null;
    const issues = c.errors.length + c.warnings.length;
    if (onlyIssues && issues === 0) return null;
    return (
      <TreeNode
        key={c.sid}
        sel={sel}
        id={`c${c.sid}`}
        onGo={onGo}
        level={1}
        dot={c.status}
        label={c.name}
        sub={c.quoteCad != null ? formatCad(c.quoteCad).replace('CAD', '').trim() : ''}
        badge={issues || null}
        badgeTone={c.errors.length ? 'error' : 'warning'}
      />
    );
  };
  return (
    <nav className="ws2-tree" aria-label={t('ws2.treeLabel')}>
      <label className="ws2-filter">
        <input type="checkbox" checked={onlyIssues} onChange={(e) => setOnlyIssues(e.target.checked)} />
        {t('ws2.onlyIssues')}
      </label>
      <ul>
        <TreeNode
          sel={sel}
          id="ship"
          onGo={onGo}
          label={t('ws2.shipment')}
          sub={t('ws2.shipmentSub')}
          badge={shipErrors || null}
          badgeTone="error"
        />
        {pieces.map((piece) => {
          const members = byPiece[piece.sequence] ?? [];
          const pkg = (detail?.packages ?? []).find((p) => p.sequence === piece.sequence);
          const errors = members.reduce((n, m) => n + (model.bySid[m.shipment_id]?.errors.length ?? 0), 0);
          return [
            <TreeNode
              key={`p${piece.sequence}`}
              sel={sel}
              id={`p${piece.sequence}`}
              onGo={onGo}
              kind="group"
              label={fill(t('ws2.piece'), { n: piece.sequence })}
              sub={fill(t('ws2.pieceSub'), { kg: formatKg(pkg?.raw_kg ?? piece.weight_kg), count: members.length })}
              badge={errors || null}
              badgeTone="error"
            />,
            ...members.map(custNode),
            isOpen ? (
              <TreeNode
                key={`add${piece.sequence}`}
                sel={sel}
                id={`add${piece.sequence}`}
                onGo={onGo}
                level={1}
                kind="add"
                label={t('ws2.addCustomer')}
              />
            ) : null,
          ];
        })}
        {unassigned.length > 0 && (
          <>
            <li className="ws2-tree__group-label" aria-hidden="true">
              {t('ws2.unplacedGroup')} · {fill(t('ws2.unplacedSub'), { count: unassigned.length })}
            </li>
            {unassigned.map(custNode)}
          </>
        )}
        {isOpen && <TreeNode sel={sel} id="addpiece" onGo={onGo} kind="add" label={t('ws2.addPiece')} />}
        <li className="ws2-tree__sep" aria-hidden="true" />
        <TreeNode
          sel={sel}
          id="cost"
          onGo={onGo}
          label={t('ws2.costQuote')}
          sub={detail?.totals?.quote_cad != null ? formatCad(detail.totals.quote_cad) : ''}
        />
        <TreeNode sel={sel} id="bill" onGo={onGo} label={t('ws2.vendorBill')} />
        <TreeNode
          sel={sel}
          id="mile"
          onGo={onGo}
          label={t('ws2.milestones')}
          sub={t(`workspace.states.${master.state}`, master.state)}
        />
      </ul>
      <div className="ws2-legend" aria-label={t('ws2.legend')}>
        {['none', 'draft', 'final', 'error'].map((s) => (
          <span key={s}>
            <i className={`ws2-dot ws2-dot--${s}`} aria-hidden="true" />
            {t(`ws2.status.${s}`)}
          </span>
        ))}
      </div>
    </nav>
  );
}

/* --- Check before booking ------------------------------------------------------------------ */

function CheckText({ check }) {
  const t = useT();
  if (check.code === 'issue') {
    return (
      <span>
        {check.params.who ? <strong>{check.params.who}: </strong> : null}
        {check.params.text}
      </span>
    );
  }
  return <span>{fill(t(`ws2.check.${check.code}`), check.params)}</span>;
}

const ICON = {
  ok: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.6 2.6L16 9.5" />
    </svg>
  ),
  error: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.5v.2" />
    </svg>
  ),
  warning: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <path d="M12 3.5l9.5 16.5h-19z" />
      <path d="M12 10v4.5M12 17.2v.2" />
    </svg>
  ),
};

export function Checklist({ model, onGo }) {
  const t = useT();
  return (
    <Card
      title={t('ws2.checksTitle')}
      actions={
        <span className="meta">
          {fill(t('ws2.checksSummary'), { errors: model.errorCount, warnings: model.warningCount })}
        </span>
      }
    >
      <ul className="ws2-checks">
        {model.checks.map((check, index) => (
          <li key={index}>
            <button type="button" className={`ws2-check ws2-check--${check.level}`} onClick={() => onGo(check.target)}>
              <span className="ws2-check__icon">{ICON[check.level]}</span>
              <CheckText check={check} />
              {check.level !== 'ok' && <span className="ws2-check__go">{t('ws2.goTo')}</span>}
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/* --- A customer's alerts and its place in a piece ------------------------------------------- */

export function CustomerAlerts({ customer }) {
  const t = useT();
  const rows = [
    ...customer.errors.map((a) => ({ level: 'error', ...a })),
    ...customer.warnings.map((a) => ({ level: 'warning', ...a })),
  ];
  if (!rows.length) {
    return (
      <div className="ws2-alerts">
        <div className="ws2-alert ws2-alert--ok">
          {ICON.ok}
          <span>{t('ws2.allGood')}</span>
        </div>
      </div>
    );
  }
  return (
    <div className="ws2-alerts" role="status">
      {rows.map((row, index) => (
        <div key={index} className={`ws2-alert ws2-alert--${row.level}`}>
          {ICON[row.level]}
          <span>{row.text ?? t(`ws2.custAlert.${row.code}`)}</span>
        </div>
      ))}
    </div>
  );
}

export function PlaceInPiece({ master, member, pieces, editable }) {
  const t = useT();
  const queryClient = useQueryClient();
  const place = useMutation({
    mutationFn: (sequence) => consolidationsApi.setPackageMember(master.id, member.shipment_id, sequence),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: wsKey(master.id) }),
  });
  return (
    <Card title={t('ws2.placeTitle')} headingLevel="h3">
      {place.error && <Banner tone="danger">{place.error.message}</Banner>}
      <Field label={t('ws2.placeLabel')} hint={t('ws2.placeHint')} required>
        {(props) => (
          <Select
            {...props}
            disabled={!editable || place.isPending}
            value=""
            placeholder={t('costMethod.notRecorded')}
            onChange={(event) => place.mutate(event.target.value)}
            options={pieces.map((p) => ({ value: String(p.sequence), label: fill(t('ws2.piece'), { n: p.sequence }) }))}
          />
        )}
      </Field>
    </Card>
  );
}

/* --- The piece pane's tables --------------------------------------------------------------- */

export function PieceCustomers({ members, model, onGo }) {
  const t = useT();
  if (!members.length) return <p className="meta">{t('ws2.noCustomers')}</p>;
  const rows = members.map((m) => model.bySid[m.shipment_id]).filter(Boolean);
  const sum = (key) => rows.reduce((n, c) => (c[key] == null ? n : n + Number(c[key])), 0);
  return (
    <div className="table-wrap">
      <table className="table ws2-table">
        <thead>
          <tr>
            <th scope="col">{t('ws2.colCustomer')}</th>
            <th scope="col" className="num">{t('ws2.colCw')}</th>
            <th scope="col" className="num">{t('ws2.colSurcharges')}</th>
            <th scope="col" className="num">{t('ws2.colQuote')}</th>
            <th scope="col">{t('ws2.colStatus')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.sid}>
              <td>
                <button type="button" className="ws2-link" onClick={() => onGo(`c${c.sid}`)}>
                  {c.name}
                </button>{' '}
                <span className="meta">{c.member.public_id}</span>
              </td>
              <td className="num">{formatKg(c.cwKg)}</td>
              <td className="num">{formatCad(c.surchargeCad)}</td>
              <td className="num">
                <strong>{formatCad(c.quoteCad)}</strong>
              </td>
              <td>
                <StatusBadge tone={STATUS_TONE[c.status]} label={t(`ws2.status.${c.status}`)} />
                {c.errors.length + c.warnings.length > 0 && (
                  <span className="meta"> · {fill(t('ws2.issuesCount'), { count: c.errors.length + c.warnings.length })}</span>
                )}
              </td>
            </tr>
          ))}
          <tr className="ws2-total">
            <td>{t('ws2.total')}</td>
            <td className="num">{formatKg(sum('cwKg'))}</td>
            <td className="num">{formatCad(sum('surchargeCad'))}</td>
            <td className="num">{formatCad(sum('quoteCad'))}</td>
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** Per-piece surcharges of one piece (DEC-0276): the engine's PARCEL lines keyed "P:…:{seq}". */
export function PerPieceSurcharges({ estimate, sequence, model }) {
  const t = useT();
  const lines = (estimate?.method_detail?.lines ?? []).filter(
    (ln) => ln.class === 'PARCEL' && String(ln.key).split(':').pop() === String(sequence),
  );
  return (
    <Card title={t('ws2.perPieceTitle')} headingLevel="h3">
      <p className="meta">{t('ws2.perPieceHint')}</p>
      {lines.length === 0 ? (
        <p className="meta">{t('ws2.noPerPiece')}</p>
      ) : (
        <div className="table-wrap">
          <table className="table ws2-table">
            <thead>
              <tr>
                <th scope="col">{t('ws2.colFee')}</th>
                <th scope="col" className="num">{t('ws2.colKango')}</th>
                <th scope="col">{t('ws2.colBilled')}</th>
                <th scope="col">{t('ws2.colWhy')}</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((ln) => {
                const why = Object.values(ln.why ?? {})[0] ?? '';
                return (
                  <tr key={ln.key}>
                    <td>{ln.name}</td>
                    <td className="num">{formatVnd(ln.vendor_vnd)}</td>
                    <td>
                      {Object.entries(ln.quote_vnd ?? {})
                        .map(([sid, v]) => `${model.bySid[Number(sid)]?.name ?? sid} ${formatVnd(v)}`)
                        .join(' · ')}
                    </td>
                    <td className="meta">{String(why).split(' | ')[0]}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
