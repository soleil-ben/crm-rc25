/**
 * The verification-link landing page.
 *
 * ## What happens to the token
 *
 * The link arrives as `/account/verify-email#token=<32 bytes of base64url>` (CA-SEC-07;
 * older links use `?token=` and are still accepted). That token is a live credential for
 * somebody's account until it is redeemed, and a URL is the least private place a
 * credential can sit: it is in the address bar, in the session history, in a bookmark if
 * anybody makes one, in the referrer of anything the page loads, and in the page title's
 * history entry.
 *
 * So, in order:
 *
 * 1. `main.jsx` has already run `captureLinkToken()` before React mounted: a fragment
 *    token is in memory and gone from the address bar, by `history.replaceState`, before
 *    the router ever read the location;
 * 2. on first render the token is taken out of that stash — or, for a `?token=` link or
 *    a client-side navigation, out of the router location — into a **ref**: memory, not
 *    state that could be serialised, and never `localStorage` or `sessionStorage`;
 * 3. if the location still carries it, `navigate(pathname, { replace: true })` rewrites
 *    the address bar, **replacing** the history entry rather than pushing a new one, so
 *    pressing Back does not walk onto the token again;
 * 4. only then is the token posted to the server.
 *
 * Step 3 is deliberately before step 4 rather than after it. If the request is slow, or
 * the tab is closed mid-flight, the token should already be gone from the bar.
 *
 * This reduces exposure; it does not eliminate it. The token was in a URL that a mail
 * client, a link scanner and the browser's own history database have all already seen.
 * That is why the token is also single-use, short-lived, and invalidated by the next one
 * issued (`STATE_MACHINES.md` §5) — the URL hygiene is the last layer, not the only one.
 *
 * ## What the outcomes say
 *
 * Unknown, malformed, expired, already-used and replayed tokens are **one** server
 * response with one sentence, and this page renders it. It does not try to be cleverer
 * than the server about which happened, because the server deliberately does not know how
 * to tell the caller.
 *
 * **Verification is not approval.** The success message says so in as many words, because
 * "email confirmed" reads like "you are in" and the next thing the person will do is look
 * for their shipments.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Card, Loading, Notice } from '../components.jsx';
import { accountApi } from '../accountApi.js';
import { useAccountErrorText, useAccountT, useServerSentence } from '../i18n.jsx';
import { locationCarriesToken, takeLinkToken, tokenFromLocation } from '../linkToken.js';

const PENDING = 'pending';
const CONFIRMED = 'confirmed';
const FAILED = 'failed';

export function VerifyEmailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [outcome, setOutcome] = useState(PENDING);
  // CONFIRMED: the server's English sentence (shown as-is in English, replaced by the
  // catalogue's otherwise). FAILED: the error, or `null` for the page's own "link no longer
  // valid" sentence. Both are turned into words at render, so they follow the language.
  const [message, setMessage] = useState(null);
  const headingRef = useRef(null);
  const t = useAccountT();
  const errorText = useAccountErrorText();
  const serverSentence = useServerSentence();
  // `redeemedRef` remembers the **navigation** a token was posted for -- the router's
  // location object, which is a new instance per navigation and the same instance across
  // Strict Mode's double effect run. So the double run cannot redeem a single-use token
  // twice and report failure for a link that had just worked, while the same link opened
  // again -- a new navigation, a new object -- is redeemed again and refused, exactly as
  // a replayed link should be. Not `location.key`: a browser-initiated fragment
  // navigation carries the default key, the same one the first arrival had. The token
  // itself is never kept.
  const redeemedRef = useRef(null);

  // Runs on every location change, not once: a second link opened while this page is
  // already showing differs only by its fragment, which the browser treats as a
  // same-document navigation -- `main.jsx` does not run again, and the token arrives
  // here through the router's location instead.
  useEffect(() => {
    const token = tokenFromLocation(location) ?? takeLinkToken();

    // Out of the address bar before the request goes out, and `replace` so Back does not
    // return to it. Usually already done by `main.jsx`; this covers the other shapes.
    if (locationCarriesToken(location)) {
      navigate('/account/verify-email', { replace: true });
    }

    if (!token) {
      if (redeemedRef.current === null) {
        setOutcome(FAILED);
        setMessage(null);
      }
      return;
    }
    if (redeemedRef.current === location) return;
    redeemedRef.current = location;
    setOutcome(PENDING);

    accountApi
      .verifyEmail(token)
      .then((response) => {
        setOutcome(CONFIRMED);
        setMessage(response?.message ?? null);
      })
      .catch((error) => {
        setOutcome(FAILED);
        setMessage(error);
      });
  }, [navigate, location]);

  // Focus moves to the heading once the outcome is known, so the result is announced
  // rather than left for somebody to go looking for.
  useEffect(() => {
    if (outcome !== PENDING) headingRef.current?.focus();
  }, [outcome]);

  if (outcome === PENDING) {
    return (
      <AccountNarrowPage>
        <Loading label={t('verify.loading')} />
      </AccountNarrowPage>
    );
  }

  if (outcome === CONFIRMED) {
    return (
      <AccountNarrowPage>
        <AccountPageHeader title={t('verify.confirmedTitle')} headingRef={headingRef} />
        <Card>
          <Notice tone="success" title={t('verify.confirmedNotice')}>
            <p>{serverSentence(message, 'verify.confirmedBody')}</p>
          </Notice>
          <p>
            <strong>{t('verify.notApproval')}</strong> {t('verify.notApprovalBody')}
          </p>
          <ul className="ca-links">
            <li>
              <Link to="/account/sign-in">{t('common.signIn')}</Link>
            </li>
          </ul>
        </Card>
      </AccountNarrowPage>
    );
  }

  return (
    <AccountNarrowPage>
      <AccountPageHeader title={t('verify.failedTitle')} headingRef={headingRef} />
      <Card>
        <Notice tone="error" title={t('verify.failedNotice')}>
          <p>{message ? errorText(message) : t('common.linkInvalid')}</p>
        </Notice>
        <p>{t('verify.failedBody')}</p>
        <ul className="ca-links">
          <li>
            <Link to="/account/verification/resend">{t('common.resendConfirmation')}</Link>
          </li>
          <li>
            <Link to="/account/sign-in">{t('common.backToSignIn')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
