import { describe, expect, it } from 'vitest';
import { buildWorkspaceModel, validSelection } from '../src/features/workspace/workspaceModel.js';

const member = (id, name) => ({ shipment_id: id, public_id: `SX-${id}`, customer_name: name });
const pieces = [
  { sequence: 1, weight_kg: '20', length_cm: '60', width_cm: '50', height_cm: '40' },
  { sequence: 2, weight_kg: '10' },
];

function model(extra = {}) {
  const a = member(1, 'Anh');
  const b = member(2, 'Bình');
  const c = member(3, 'Châu');
  return buildWorkspaceModel({
    master: { vendor_reference: null, members: [a, b, c] },
    pieces,
    byPiece: { 1: [a], 2: [b] },
    unassigned: [c],
    estimate: {
      blocking: [{ code: 'fee_unpriced', message: 'enter the weight', shipment_id: 2 }],
      provisional: [{ code: 'x', message: 'check this', shipment_id: null }],
      method_detail: { members: { 1: { quote_cad: '10.00', cw_kg: '3' } }, reconciled: true },
    },
    quotesBySid: { 1: [{ status: 'finalized' }], 2: [{ status: 'draft' }], 3: [] },
    ...extra,
  });
}

describe('workspace model (DEC-0277)', () => {
  it('gives each customer its state from the estimate, the quotes and its piece', () => {
    const m = model();
    expect(m.bySid[1].status).toBe('final');
    expect(m.bySid[2].status).toBe('error');
    expect(m.bySid[2].errors).toEqual([{ text: 'enter the weight' }]);
    expect(m.bySid[3].status).toBe('error');
    expect(m.bySid[3].errors[0]).toEqual({ code: 'unplaced' });
    expect(m.order).toEqual([1, 2, 3]);
    expect(m.readyCount).toBe(1);
  });

  it('lists the checks, errors first, each with where to fix it', () => {
    const m = model();
    const codes = m.checks.map((c) => [c.level, c.code, c.target]);
    expect(codes.slice(0, 2)).toEqual([
      ['error', 'unplaced', 'c3'],
      ['error', 'issue', 'c2'],
    ]);
    expect(codes).toContainEqual(['warning', 'awbMissing', 'ship']);
    expect(codes).toContainEqual(['warning', 'pieceSizeMissing', 'p2']);
    expect(codes).toContainEqual(['warning', 'issue', 'cost']);
    expect(codes).toContainEqual(['warning', 'notQuoted', 'c2']);
    expect(codes).toContainEqual(['ok', 'reconciled', 'cost']);
    expect(m.errorCount).toBe(2);
  });

  it('keeps a selection only when what it names exists', () => {
    const m = model();
    expect(validSelection('c2', { pieces, bySid: m.bySid })).toBe('c2');
    expect(validSelection('c99', { pieces, bySid: m.bySid })).toBe('ship');
    expect(validSelection('p2', { pieces, bySid: m.bySid })).toBe('p2');
    expect(validSelection('add3', { pieces, bySid: m.bySid })).toBe('ship');
    expect(validSelection('cost', { pieces, bySid: m.bySid })).toBe('cost');
    expect(validSelection(null, { pieces, bySid: m.bySid })).toBe('ship');
  });
});
