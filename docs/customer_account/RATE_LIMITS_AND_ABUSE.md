# Customer Account — rate-limit and abuse-control design

**Status:** proposed. **Authority:** OD-23, OD-24, DEC-0006, DEC-0007.

---

## 1. What is being defended, and against what

| Route | Abuse it invites |
|---|---|
| Register | Enumeration, mail-bombing a third party, junk identities |
| Resend verification | Mail-bombing, enumeration |
| Sign in | Credential stuffing, spraying, lockout-as-denial-of-service |
| Forgot password | Enumeration, mail-bombing |
| Reset password (token) | Token brute force |
| Verify email (token) | Token brute force |
| Shipment list / detail | Scraping after a session compromise |
| Profile proposal | Queue flooding — an attack on staff time, not on data |

---

## 2. Separate buckets, and why that is not a detail

The existing limiter — `app.core.security.SlidingWindowRateLimiter`, in-process, bounded —
is reused. Its **keys are namespaced per surface**, and the Customer Account gets its own
namespace:

```
staff:login:<ip>            staff:login:<email>          (existing)
public:tracking:<ip>                                     (existing)
account:signin:<ip>         account:signin:<addr-hash>   (new)
account:register:<ip>       account:register:<addr-hash> (new)
account:reset:<ip>          account:reset:<addr-hash>    (new)
account:verify:<ip>         account:token:<identity>     (new)
account:read:<identity>                                  (new)
```

Shared buckets would make each surface a denial-of-service lever against the others: a
registration flood that consumed the staff login allowance would lock operations out of the
CRM during exactly the incident they need to respond to. **A customer-side flood must never
be able to stop staff signing in, and must never stop Public Tracking answering.** That is
an acceptance criterion, not an aspiration.

Address keys are **hashed** (`account:signin:<sha256(email_normalized)>`) so the limiter's
in-memory state and any diagnostic output hold no address list.

---

## 3. Proposed limits

Starting values, to be tuned against real traffic. Every one is configuration, not a
constant in code, following the existing settings pattern.

| Bucket | Limit | Window | On refusal |
|---|---:|---:|---|
| `account:signin:<ip>` | 10 | 5 min | 429 + `Retry-After` |
| `account:signin:<addr-hash>` | 6 | 15 min | 429 + `Retry-After` |
| `account:register:<ip>` | 5 | 60 min | 429, generic body |
| `account:register:<addr-hash>` | 2 | 24 h | **Generic success body**, no message sent |
| `account:reset:<ip>` | 5 | 60 min | 429, generic body |
| `account:reset:<addr-hash>` | 3 | 60 min | **Generic success body**, no message sent |
| `account:verify:<ip>` (token redemption) | 20 | 10 min | 429 |
| `account:token:<identity>` (failed redemptions) | 10 | 60 min | 429 |
| `account:read:<identity>` | 300 | 5 min | 429 |

Two of these refuse **while still returning the ordinary generic body**. That is deliberate:
on the register and reset paths a 429 is itself an enumeration signal if it only appears for
addresses that exist. The mail is suppressed; the answer is unchanged.

### 3.1 Per-identity lockout

After **10** failed sign-ins inside 15 minutes, `locked_until` is set 15 minutes ahead.
A locked account returns the **same generic failure** as a wrong password — a distinct
"account locked" message would confirm the address exists and would tell an attacker their
spraying worked.

Lockout is bounded in time and never permanent, because a permanent lockout hands an
attacker a way to disable any customer they can name.

---

## 4. Client identity

The rate-limit key is the **directly observed peer address**, exactly as the public surface
already does it. `X-Forwarded-For` and friends are not believed unless a trusted proxy is
explicitly configured (DEC-0007), and when the trusted-proxy setting is absent every request
carrying a forwarding header folds into **one shared bucket** rather than being given a
bucket of its own — the public surface's existing behaviour, reused, because the alternative
lets a caller pick their own bucket and thereby remove the limit.

---

## 5. Abuse controls that are not rate limits

| Control | What it stops |
|---|---|
| **Generic responses everywhere** | Enumeration (T-02). The single most effective control here |
| **Cooling-off on outbound mail** | One verification or reset message per address per window regardless of how many requests arrive |
| **One notice to an existing address** | An already-registered address gets at most one "somebody tried to register" notice per window |
| **Single-use, short-lived, hashed tokens** | Replay and brute force (T-05) |
| **No claim-by-reference flow** | Removes the whole class of "I know a tracking number" attacks (T-04) |
| **Staff approval before any history** | A flood of registrations creates queue work, never disclosure |
| **Server-enforced page size** | Bulk scraping through a compromised session |
| **Proposal quota per identity** | Queue flooding: a small number of pending proposals per identity, older ones superseded |
| **Password policy** | Minimum length with a rejected-common-password check. No composition rules that push people toward `Password1!` |

---

## 6. What is deliberately not built in release 1

| Not built | Why | Revisit when |
|---|---|---|
| CAPTCHA or proof of work | A third-party dependency, a privacy question and an accessibility cost, all before any evidence of abuse | Registration abuse is observed |
| IP reputation or geo-blocking | Blocks real customers — this business ships Canada ↔ Vietnam | Never, without evidence |
| Device fingerprinting | Privacy cost out of proportion to the threat | Not planned |
| Shared-store rate limiting | The deployment is single-process; DEC-0006 already records this limit and the production gate | PostgreSQL / multi-worker |
| Email-domain allow or deny lists | Arbitrary, and wrong for a customer base that uses many providers | Not planned |

---

## 7. Detection and what an operator should watch

| Signal | Means |
|---|---|
| Failed sign-ins per address-hash | Targeted attack on one account |
| Distinct address-hashes per IP | Spraying or enumeration |
| Register/resend refusals per window | Mail-bombing attempt |
| Token redemption failures per identity | Token brute force |
| Not-found rates per identity on shipment routes | Probing after a session compromise (T-03) |
| Approval queue growth without verification | Junk registration flood |

These extend `docs/MONITORING.md`; none of them is implemented by this phase.

---

## 8. Test obligations

1. Each customer bucket refuses at its limit and recovers after its window.
2. **A customer-side flood does not consume the staff login allowance or the public tracking
   allowance** — asserted directly, because it is the reason the namespaces are separate.
3. A refused register or reset returns the **ordinary generic body**, and no message is
   produced by the capture transport.
4. Lockout engages, returns the standard generic failure, and expires.
5. Limiter state holds no raw address — asserted over the limiter's keys.
6. `Retry-After` is present and sane wherever a 429 is returned.
