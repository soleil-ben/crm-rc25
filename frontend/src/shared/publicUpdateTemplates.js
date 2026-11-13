/**
 * Approved public wording for shipment timeline updates.
 *
 * Thin accessors over the catalogue the backend owns and validates
 * (`backend/app/data/public_update_templates.json`, imported through the `@templates`
 * alias). Both the staff event form and the public tracking page read from here, so there
 * is one copy of every customer-facing sentence in the repository.
 *
 * Why the public page needs this at all: a timeline entry carries a template *key*, not a
 * sentence, precisely so the page can render it in whichever language the reader chose.
 * Resolving that key needs the wording locally — asking the server for it would mean
 * refetching the whole tracking result on every language switch, which would both defeat
 * the page's deliberate no-refetch design and spend the customer's public rate limit on
 * pressing a language button (DEC-0084).
 */

import catalogue from '@templates';

export const TEMPLATE_VERSION = catalogue.version;

/** Ordered template keys offered for an event type. Catalogue order is the UI's order. */
export function templatesFor(eventType) {
  const entry = catalogue.event_types[eventType];
  return entry ? entry.templates : [];
}

/**
 * Whether the "publish to the customer" box starts ticked for this event type.
 *
 * True for ordinary milestones, false for the states where canned wording could tell a
 * customer something staff do not yet know to be true — an exception nobody has diagnosed,
 * a failed delivery attempt, a return in progress (DEC-0083).
 */
export function publishesByDefault(eventType) {
  const entry = catalogue.event_types[eventType];
  return entry ? Boolean(entry.default_public) : false;
}

/**
 * The approved sentence for `key` in `language`.
 *
 * Falls back to English when a language is missing, and returns `null` for a key the
 * catalogue no longer carries. A historical event whose template was retired must not take
 * the tracking page down.
 */
export function renderTemplate(key, language = 'en') {
  const entry = key ? catalogue.templates[key] : undefined;
  if (!entry) return null;
  return entry.text[language] || entry.text.en || null;
}

/** Every key in the catalogue, for tests that assert the two sides agree. */
export function allTemplateKeys() {
  return Object.keys(catalogue.templates);
}
