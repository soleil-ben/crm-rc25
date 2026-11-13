/**
 * The two-pane workspace's view model (owner, 2026-11-06; DEC-0277): what the tree, the
 * summary bar and the "check before booking" list show. Pure: it reads what the API already
 * returned (the master, its pieces, the server's estimate, each customer's quote versions)
 * and does no pricing of its own.
 *
 * A customer's state:
 *   error  — the server's estimate has a blocking issue for it, or it is not in a piece
 *   none   — no quote yet
 *   draft  — a draft quote
 *   final  — a finalised quote
 */

/** Selection keys: 'ship', 'p{seq}', 'c{shipmentId}', 'add{seq}', 'addpiece', 'cost', 'bill', 'mile'. */
export const STATIC_PANES = ['ship', 'addpiece', 'cost', 'bill', 'mile'];

function quoteState(versions) {
  if (!versions) return 'unknown';
  if (versions.some((v) => v.status === 'finalized')) return 'final';
  if (versions.some((v) => v.status === 'draft')) return 'draft';
  return 'none';
}

function uniqueByMessage(issues) {
  const seen = new Set();
  return issues.filter((issue) => {
    const key = `${issue.code}|${issue.message}|${issue.shipment_id ?? ''}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function buildWorkspaceModel({
  master,
  pieces,
  byPiece,
  unassigned,
  estimate,
  quotesBySid = {},
  hasActiveTariff = true,
}) {
  const detail = estimate?.method_detail;
  const blocking = uniqueByMessage(estimate?.blocking ?? []);
  const provisional = uniqueByMessage(estimate?.provisional ?? []);
  const multiPiece = pieces.length > 1;
  const unplacedIds = new Set(unassigned.map((m) => m.shipment_id));

  const pieceOf = {};
  for (const piece of pieces) {
    for (const m of byPiece[piece.sequence] ?? []) pieceOf[m.shipment_id] = piece.sequence;
  }

  const customers = master.members.map((member) => {
    const sid = member.shipment_id;
    const row = detail?.members?.[String(sid)];
    const errors = blocking.filter((i) => i.shipment_id === sid).map((i) => ({ text: i.message }));
    if (unplacedIds.has(sid)) errors.unshift({ code: 'unplaced' });
    const warnings = provisional.filter((i) => i.shipment_id === sid).map((i) => ({ text: i.message }));
    const quote = quoteState(quotesBySid[sid]);
    if (quote === 'none') warnings.push({ code: 'notQuoted' });
    if (quote === 'draft') warnings.push({ code: 'draftQuote' });
    const status = errors.length ? 'error' : quote === 'unknown' ? 'none' : quote;
    return {
      sid,
      member,
      name: member.customer_name || member.customer_public_id || member.public_id,
      piece: pieceOf[sid] ?? null,
      cwKg: row?.cw_kg ?? null,
      quoteCad: row?.quote_cad ?? null,
      surchargeCad: row?.surcharge_quote_cad ?? null,
      errors,
      warnings,
      quote,
      status,
    };
  });
  const bySid = Object.fromEntries(customers.map((c) => [c.sid, c]));

  // Tree order: piece by piece, then the customers not in a piece.
  const order = [
    ...pieces.flatMap((p) => (byPiece[p.sequence] ?? []).map((m) => m.shipment_id)),
    ...unassigned.map((m) => m.shipment_id),
  ].filter((sid) => bySid[sid]);

  const nameOf = (sid) => bySid[sid]?.name ?? String(sid);
  const checks = [];
  const add = (level, code, params = {}, target = 'ship') => checks.push({ level, code, params, target });

  if (!hasActiveTariff) add('error', 'noTariff', {}, 'cost');
  if (master.members.length === 0) add('error', 'noCustomers', {}, `add${pieces[0]?.sequence ?? 1}`);
  add(master.vendor_reference ? 'ok' : 'warning', master.vendor_reference ? 'awbOk' : 'awbMissing', { awb: master.vendor_reference }, 'ship');

  const noWeight = pieces.filter((p) => !p.weight_kg);
  const noSize = pieces.filter((p) => p.weight_kg && !(p.length_cm && p.width_cm && p.height_cm));
  noWeight.forEach((p) => add('error', 'pieceWeightMissing', { n: p.sequence }, `p${p.sequence}`));
  noSize.forEach((p) => add('warning', 'pieceSizeMissing', { n: p.sequence }, `p${p.sequence}`));
  if (!noWeight.length && !noSize.length) add('ok', 'piecesOk', { count: pieces.length }, `p${pieces[0]?.sequence ?? 1}`);

  if (multiPiece) {
    if (unassigned.length) {
      add('error', 'unplaced', { names: unassigned.map((m) => nameOf(m.shipment_id)).join(', ') }, `c${unassigned[0].shipment_id}`);
    } else if (master.members.length) {
      add('ok', 'allPlaced', {}, `p${pieces[0].sequence}`);
    }
  }

  if (estimate) {
    blocking.forEach((issue) =>
      add('error', 'issue', { text: issue.message, who: issue.shipment_id ? nameOf(issue.shipment_id) : '' },
        issue.shipment_id && bySid[issue.shipment_id] ? `c${issue.shipment_id}` : 'cost'),
    );
    if (!blocking.length && master.members.length) add('ok', 'pricingOk', {}, 'cost');
    provisional.forEach((issue) =>
      add('warning', 'issue', { text: issue.message, who: issue.shipment_id ? nameOf(issue.shipment_id) : '' },
        issue.shipment_id && bySid[issue.shipment_id] ? `c${issue.shipment_id}` : 'cost'),
    );
    if (detail?.reconciled === true) add('ok', 'reconciled', {}, 'cost');
  }

  const notFinal = customers.filter((c) => c.quote === 'none' || c.quote === 'draft');
  if (notFinal.length) {
    add('warning', 'notQuoted', { count: notFinal.length, names: notFinal.map((c) => c.name).join(', ') }, `c${notFinal[0].sid}`);
  } else if (customers.length && customers.every((c) => c.quote === 'final')) {
    add('ok', 'allQuoted', {}, 'cost');
  }

  const rank = { error: 0, warning: 1, ok: 2 };
  checks.sort((a, b) => rank[a.level] - rank[b.level]);
  const errorCount = checks.filter((c) => c.level === 'error').length;
  const warningCount = checks.filter((c) => c.level === 'warning').length;
  const readyCount = customers.filter((c) => c.errors.length === 0).length;

  return { customers, bySid, order, checks, errorCount, warningCount, readyCount };
}

/** A selection key the page can show, or 'ship'. */
export function validSelection(sel, { pieces, bySid }) {
  if (!sel) return 'ship';
  if (STATIC_PANES.includes(sel)) return sel;
  const m = /^(p|c|add)(\d+)$/.exec(sel);
  if (!m) return 'ship';
  const n = Number(m[2]);
  if (m[1] === 'c') return bySid[n] ? sel : 'ship';
  return pieces.some((p) => p.sequence === n) ? sel : 'ship';
}
