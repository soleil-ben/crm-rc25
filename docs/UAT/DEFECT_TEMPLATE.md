# Defect report

One per defect. Copy this file, number it `UAT-DEF-001` onward, and attach the evidence.

---

**Defect ID:** UAT-DEF-___
**Date raised:**
**Raised by:**
**Role in use when found:**

## Summary

*One sentence. What is wrong, not what you think causes it.*

## Case

**Case ID:** *e.g. UAT-OP-07, or "found outside the pack"*
**Build / commit:**
**Environment:**
**Browser / device:**

## Steps to reproduce

*Numbered, from a known starting point. Someone who has never seen this must be able to
follow them exactly.*

1.
2.
3.

**Reproducible:** Always · Sometimes · Once only

*If "sometimes", say how many attempts out of how many.*

## Expected

*What should have happened, and — where you can — where that expectation comes from: the
staff guide, the case, or what a customer would reasonably assume.*

## Actual

*What did happen. Quote the exact wording from the screen rather than paraphrasing.*

## Evidence obtained

- [ ] Screenshot / screen recording
- [ ] Exported file
- [ ] Solaris ID or customer reference (**synthetic only**)
- [ ] Correlation ID from the page, if one was shown
- [ ] Approximate time, so the logs can be found

## Severity

**Proposed:** S1 · S2 · S3 · S4 · S5

**Why this severity:**

> S1 data loss, privacy breach, or a core workflow impossible · S2 core workflow wrong, or
> a permission does not hold · S3 works but confusing or incorrect · S4 cosmetic ·
> S5 observation.
>
> **Anything touching customer privacy is S1 until proven otherwise.**

## Impact

**Who is affected:** Staff · Customers · Both

**How often would this happen in real use:**

**Is there a workaround:** Yes / No — *if yes, describe it*

## Privacy

- [ ] **This defect involves customer data being seen by someone who should not see it**

*If ticked: stop, mark it S1, and tell an administrator now. Do not investigate further
yourself, and do not attach real customer data to this report. See* `docs/RUNBOOKS.md`
*section 10.*

---

## For triage — not the reporter

**Triaged by / date:**

**Reproduced:** Yes · No · Partially

**Confirmed severity:**

**Classification:** Product defect · Data problem · Environment · **Expected behaviour** ·
Documentation gap

*If "expected behaviour": say why, and whether the interface or the guide should have made
it clearer. A tester misreading something is evidence about the design, not about the
tester.*

**Assigned to / target:**

## For retest — by the original reporter

**Retested by / date / build:**

**Result:** Pass · Fail (still) · Fail (differently)

**Regression checked nearby:** Yes · No

**Notes:**

**Closed by / date:** *(the reporter, not the person who fixed it)*
