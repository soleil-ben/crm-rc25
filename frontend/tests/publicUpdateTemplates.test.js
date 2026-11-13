/**
 * The template catalogue, as the two UIs see it.
 *
 * The backend has its own tests for the same file. These exist because the frontend
 * reaches it through a Vite alias: if that alias ever broke, or the JSON moved, the staff
 * picker would quietly offer nothing and the public page would silently fall back to
 * English. Both failures look like "fine" on a screenshot, so they need a test.
 */

import { describe, expect, it } from 'vitest';
import {
  allTemplateKeys,
  publishesByDefault,
  renderTemplate,
  templatesFor,
} from '../src/shared/publicUpdateTemplates.js';

describe('public update templates', () => {
  it('resolves the catalogue through the @templates alias', () => {
    expect(allTemplateKeys().length).toBeGreaterThan(0);
  });

  it('renders a milestone in each language', () => {
    const en = renderTemplate('in_transit.v1', 'en');
    const vi = renderTemplate('in_transit.v1', 'vi');

    expect(en).toBeTruthy();
    expect(vi).toBeTruthy();
    expect(en).not.toBe(vi);
  });

  it('preserves Vietnamese diacritics', () => {
    // A mangled encoding anywhere in the chain shows up here rather than on a customer's
    // screen. "Lô hàng" is the phrase every Vietnamese template opens with.
    expect(renderTemplate('in_transit.v1', 'vi')).toContain('Lô hàng');
  });

  it('falls back to English for a language the catalogue does not carry', () => {
    expect(renderTemplate('in_transit.v1', 'fr')).toBe(renderTemplate('in_transit.v1', 'en'));
  });

  it('returns null for a retired key rather than throwing', () => {
    // A historical event must never be able to take the tracking page down.
    expect(renderTemplate('no.such.key.v1', 'en')).toBeNull();
    expect(renderTemplate(null, 'en')).toBeNull();
    expect(renderTemplate(undefined, 'vi')).toBeNull();
  });

  it('offers templates for an ordinary milestone', () => {
    expect(templatesFor('in_transit').length).toBeGreaterThan(0);
  });

  it('offers nothing for an event type it does not know', () => {
    expect(templatesFor('teleported')).toEqual([]);
    expect(publishesByDefault('teleported')).toBe(false);
  });

  it('publishes ordinary milestones by default and holds back the exception states', () => {
    // DEC-0083. Telling a customer "there is a problem" before anybody has diagnosed one
    // is the failure mode this guards.
    expect(publishesByDefault('in_transit')).toBe(true);
    expect(publishesByDefault('delivered_to_recipient')).toBe(true);

    expect(publishesByDefault('exception')).toBe(false);
    expect(publishesByDefault('delivery_attempted')).toBe(false);
    expect(publishesByDefault('return_in_progress')).toBe(false);
    expect(publishesByDefault('awaiting_parcel')).toBe(false);
  });

  it('only offers a template that belongs to the event type', () => {
    expect(templatesFor('in_transit')).toContain('in_transit.v1');
    expect(templatesFor('delivered_to_recipient')).not.toContain('in_transit.v1');
  });
});
