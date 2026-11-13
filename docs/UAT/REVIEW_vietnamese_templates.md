# Vietnamese review — the 17 customer update templates

> ## ⚠ NOT REVIEWED
>
> **No Vietnamese speaker has reviewed this wording.** Every approval field below is blank
> and must be filled in by the reviewer who actually read the sentence. Claude did not fill
> in any of them and must not.
>
> These sentences go to **customers**, not colleagues. An awkward register is visible
> outside the company and cannot be taken back.

**Owner decision:** OD-09 — open. English was approved by owner feedback on 2026-09-13.
Vietnamese is unapproved.

---

## Field classes on this sheet

Four kinds of field appear below, and they must never be confused with one another.

| Class | What it is | State before review |
|---|---|---|
| **Content under review** | The screen, sentence, template or check being judged. Written in advance as part of this sheet | Prewritten — **not** a reviewer's answer |
| **Reviewer response** | What the reviewer judged, observed or would change | **Blank** |
| **Evidence obtained** | What the reviewer actually captured — recordings, transcripts, screenshots, photographs | **Blank** |
| **Result / sign-off** | The outcome, the signature and the date | **Blank** |

Prewritten content is never evidence that this sheet was reviewed. A sheet is reviewed
only when the **Reviewer response**, **Evidence obtained** and **Result / sign-off**
fields have been filled in by the person who did the work.

---

## Reviewer

| Field | Reviewer response |
|---|---|
| Reviewer name | |
| Date | |
| Fluency (native / professional / conversational) | |
| Business-context familiarity (shipping/logistics) | |
| Reviewed against the live page? (yes/no) | |

---

## How to fill this in

For each template, judge the **Vietnamese** against the English beside it and against how
Solaris would actually speak to a customer.

* **Natural** — does a Vietnamese speaker say it this way, or does it read as translated?
* **Terminology** — is the shipping term the one the trade uses, and the same one used in
  every other template?
* **Tone** — right level of politeness for a customer, neither curt nor obsequious.
* **Correction** — write the sentence you would send instead. Leave blank if none.
* **Approved** — yes / no / needs change. Blank means not reviewed.

Text is shown to customers verbatim and is never machine-translated (DEC-0054). A stored
event records the template **key**, not the sentence (DEC-0084), so wording can be
corrected later without rewriting history — but the key set cannot change freely.

---

## The templates

### 1. `received_at_solaris.v1`

| Content under review | |
|---|---|
| English (approved) | We have received your shipment at our facility. |
| Vietnamese (under review) | Chúng tôi đã nhận lô hàng của bạn tại kho. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 1a. `received_at_solaris.v2` (RC-UAT-25, DEC-0244)

The only standard update now offered for the received event ("Received at warehouse").
`received_at_solaris.v1` above is **retired**: it still renders on events that carry it and is
never offered again. The Vietnamese sentence is unchanged from v1.

| Content under review | |
|---|---|
| English (approved) | We have received your shipment at our warehouse. |
| Vietnamese (under review) | Chúng tôi đã nhận lô hàng của bạn tại kho. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 2. `processing.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is being prepared for departure. |
| Vietnamese (under review) | Lô hàng của bạn đang được chuẩn bị để gửi đi. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 3. `departed_origin.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment has left the origin facility. |
| Vietnamese (under review) | Lô hàng của bạn đã rời kho xuất phát. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 4. `in_transit.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is on its way. |
| Vietnamese (under review) | Lô hàng của bạn đang trên đường vận chuyển. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 5. `in_transit.delayed.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is on its way and is taking longer than usual. |
| Vietnamese (under review) | Lô hàng của bạn đang trên đường vận chuyển và lâu hơn thường lệ. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 6. `customs_processing.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is going through customs clearance. |
| Vietnamese (under review) | Lô hàng của bạn đang làm thủ tục hải quan. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 7. `customs_processing.held.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is being held at customs. We will update you when it is released. |
| Vietnamese (under review) | Lô hàng của bạn đang bị giữ tại hải quan. Chúng tôi sẽ thông báo khi hàng được thông quan. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 8. `arrived_destination.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment has arrived in the destination country. |
| Vietnamese (under review) | Lô hàng của bạn đã đến nước nhận. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 9. `out_for_delivery.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is out for delivery. |
| Vietnamese (under review) | Lô hàng của bạn đang được giao đến bạn. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 10. `delivered_to_collection_point.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is ready to collect at the pickup point. |
| Vietnamese (under review) | Lô hàng của bạn đã sẵn sàng để nhận tại điểm giao nhận. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 11. `delivered_to_recipient.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment has been delivered. |
| Vietnamese (under review) | Lô hàng của bạn đã được giao thành công. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 12. `returned.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment has been returned to the sender. |
| Vietnamese (under review) | Lô hàng của bạn đã được trả về người gửi. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 13. `delivery_attempted.v1`

| Content under review | |
|---|---|
| English (approved) | We tried to deliver your shipment and could not complete it. We will contact you to arrange another time. |
| Vietnamese (under review) | Chúng tôi đã thử giao lô hàng của bạn nhưng chưa thành công. Chúng tôi sẽ liên hệ với bạn để sắp xếp lại. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 14. `exception.v1`

| Content under review | |
|---|---|
| English (approved) | There is a problem with your shipment. Our team is looking into it and will update you. |
| Vietnamese (under review) | Lô hàng của bạn đang gặp sự cố. Bộ phận của chúng tôi đang kiểm tra và sẽ thông báo cho bạn. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 15. `exception.delay.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is delayed. Our team is looking into it and will update you. |
| Vietnamese (under review) | Lô hàng của bạn bị chậm trễ. Bộ phận của chúng tôi đang kiểm tra và sẽ thông báo cho bạn. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 16. `return_in_progress.v1`

| Content under review | |
|---|---|
| English (approved) | Your shipment is on its way back to the sender. |
| Vietnamese (under review) | Lô hàng của bạn đang được chuyển trả về người gửi. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |

### 17. `awaiting_parcel.v1`

| Content under review | |
|---|---|
| English (approved) | We are waiting to receive your parcel. |
| Vietnamese (under review) | Chúng tôi đang chờ nhận kiện hàng của bạn. |

| Question | Reviewer response |
|---|---|
| Natural? | |
| Terminology correct and consistent? | |
| Tone right for a customer? | |
| Suggested correction | |
| Approved (yes / no / needs change) | |
---

## Overall — result / sign-off

| Field | Reviewer response |
|---|---|
| Evidence obtained (the rendered messages reviewed) | |
| Templates approved as written | |
| Templates needing change | |
| Terminology inconsistencies across templates | |
| Is the Vietnamese customer wording approved for launch? (yes/no) | |
| Reviewer signature | |
| Date | |

**Blank is not approval.** Until the last two rows are filled in by a person, the
Vietnamese customer-facing wording remains an explicit launch blocker.
