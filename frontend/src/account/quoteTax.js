/**
 * The GST/HST sentence a customer quote prints (RC-UAT-21, P-9 stand-in pending Ben).
 *
 * The quote follows the RC-UAT-20 invoice rule: a domestic route's price **includes** GST/HST
 * at the destination province's rate ("Giá đã bao gồm HST 13 %"), an international one is
 * zero-rated ("Thuế suất 0 (0 %)"). The server sends the band, the label and the rate
 * (`tax` on the quote); the words are this surface's, in the reader's language. A domestic
 * route whose province is unknown names no rate. Replaces OD-108's "Taxes, if any, are added
 * on the invoice".
 */
export function quoteTaxSentence(t, tax) {
  if (!tax) return null;
  if (tax.band === 'international') return t('quotes.taxZeroRated');
  if (tax.rate_percent === null || tax.rate_percent === undefined) {
    return t('quotes.taxIncludedNoRate');
  }
  return t('quotes.taxIncluded', { label: tax.label || 'GST/HST', rate: tax.rate_percent });
}
