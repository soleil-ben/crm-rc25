/**
 * The required-field marker: a red asterisk beside a field's label, and nothing else.
 *
 * RC-UAT-25 item 1, Ben 2026-10-25: required fields show a red `*` next to the label, in
 * both the Staff Portal and the Customer Account and in both languages; the words
 * "(required)" / "(bắt buộc)" are no longer shown. Optional fields keep their "Optional"
 * helper under the field.
 *
 * Shared by the two component trees (`components/ui` and `account/components`) because it
 * is brand foundation, like `styles/tokens.css`, not a staff assumption.
 *
 * Accessibility: the glyph is `aria-hidden`, and it is rendered **beside** the `<label>`
 * element rather than inside it, so a field's accessible name is its label text alone
 * ("Email address", not "Email address *"). "Required" reaches assistive technology through
 * `aria-required` on the control, which both `Field` components set.
 */
export function RequiredMark() {
  return (
    <span className="required-mark" aria-hidden="true" data-required-mark="">
      *
    </span>
  );
}
