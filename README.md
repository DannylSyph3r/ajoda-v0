# Ajoda

**Cooperative savings on WhatsApp — collections in, verified disbursements out.**

Ajoda is a WhatsApp-native financial platform for Nigerian cooperative savings groups
(_ajo_ / _esusu_). Members contribute through a payment link in WhatsApp; executives
(exco) disburse pooled funds through **real, verified, OTP-authorized bank transfers** —
from the bot or a web dashboard — and every member sees exactly where the money went.

Most entries in a payments hackathon do collections and stop. Ajoda closes the loop:
money in **and** money out, both on Monnify, with a verified recipient and a transfer
reference every member can check.

---

## What it does with Monnify

Ajoda uses **five** Monnify products across the full money loop:

| Product | Where it's used |
|---|---|
| **Checkout / Initialize Transaction** | Member contributions — a hosted-checkout link sent in WhatsApp (card, transfer, USSD) |
| **Verify Transaction** | Server-side settlement — value is never delivered on a browser callback alone |
| **Get Banks** | The bank picker in the withdrawal flow (dashboard + bot search) |
| **Name Enquiry (Validate Account)** | Recipient verification — the holder's name is confirmed before any money moves |
| **Single Transfer + Authorize (OTP) + Wallet Balance** | Exco disbursements — a real transfer, OTP-authorized, gated on the wallet balance |

Both sides are webhook-driven with idempotent settlement, and both webhook signatures are
verified (HMAC-SHA512, keyed with the Secret Key).

---

## The loop

1. **Collect** — A member taps a WhatsApp link, pays via Monnify checkout, and the payment
   reconciles to the correct contribution period.
2. **Verify** — Before a withdrawal, the recipient's account name is confirmed with their
   bank (Name Enquiry). No wrong-account disasters.
3. **Disburse** — An exco authorizes with an emailed OTP; a real Monnify transfer moves the
   pool's money. The pool is debited exactly once, only when the transfer completes.
4. **Broadcast** — Every member receives the proof: amount, reason, who authorized it, and
   the real Monnify transfer reference.

---

## Demo path (≈4 minutes)

1. **Land on the dashboard** — sign in as the seeded exco (below). The **Withdrawals** page
   shows past payouts with their Monnify references and the disbursement wallet balance.
2. **Contribute (money in)** — from WhatsApp, a member taps a payment link and pays with a
   Monnify sandbox method; it settles to the right period.
3. **Disburse (money out)** — as the exco, tap **New withdrawal** → enter amount, reason,
   account number, pick a bank → **the recipient's name is verified** → confirm → an OTP is
   emailed to the Monnify account owner → enter it → watch the transfer go
   `Awaiting OTP → Processing → Completed` with its reference.
4. **Failure path** — repeat with the sandbox **failure account** (below): it resolves
   `Failed` with a clean, specific message, the pool is **not** debited, and **no** member
   broadcast is sent.
5. **Transparency** — every member receives the completed-transfer broadcast carrying the
   real reference. On the bot, an exco can type "disbursement history" to list past payouts.

> **OTP choreography:** the OTP is emailed to the Monnify account owner (not shown in
> WhatsApp) — a short, deliberate pause in the demo. This is Monnify's MFA, kept on.

### Sandbox test accounts

| Purpose | Account | Bank code |
|---|---|---|
| Success recipient | any valid sandbox NUBAN (Name Enquiry resolves it) | e.g. `058` (GTBank) |
| **Failure recipient** | `0035785417` | `044` (Access) |

---

## Run it locally

**Seed a ready-to-demo cooperative** (funded pool, loginable exco, members, contribution
history, and sample completed/failed disbursements):

```bash
cd backend
python -m scripts.seed_demo        # or --reset to rebuild
```

It prints the sign-in credentials (exco phone + PIN, member phones, and a WhatsApp join code).

**Backend** (needs a populated `backend/.env` — see `backend/.env.example`):

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend**:

```bash
cd frontend
npm install
npm run dev
```

**Health & smoke test:**

```bash
curl localhost:8000/health                       # {"status":"ok","database":"ok",...}
python -m scripts.smoke_test http://localhost:8000
```

---

## Stack

FastAPI (async) · SQLAlchemy (async) · PostgreSQL · Alembic · Next.js 16 / React 19 /
TypeScript / Tailwind v4 · Meta WhatsApp Cloud API · Gemini (intent + advisor) · **Monnify**
(collections + disbursement, sandbox).

---

## Known limitations (prototype)

- **Sandbox only** — no live PSP keys, no live disbursement. Disbursement is activated on the
  sandbox account by Monnify support (done for this build).
- **Transparency broadcast delivery** — the enriched, referenced notice is sent as a
  **free-form** WhatsApp message (so no Meta template re-approval is needed), which WhatsApp
  only delivers to members active within the last 24 hours. The registered `coop_withdrawal_alert`
  template remains available for guaranteed delivery if needed.
- **Meta template residuals** — transactional messages use Meta-registered templates
  (`payment_receipt`, `coop_withdrawal_alert`, `coop_contribution_reminder`,
  `coop_broadcast_message`). Their bodies live in Meta Business Manager and can't be edited
  without a re-approval cycle; any legacy wording inside them stays until V1 by design.
- **Reversal after completion** — a `REVERSED_DISBURSEMENT` arriving after a transfer already
  completed is a no-op (the pool stays debited); it's flagged for manual reconciliation.

---

Built for the cooperative communities that keep Nigeria's informal economy running.
