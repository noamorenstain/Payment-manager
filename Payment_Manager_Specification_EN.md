# Payment Manager — Product and Technical Specification (Version 1.0)

**Status:** Approved product scope for planning an MVP  
**Date:** November 12, 2026  
**Purpose:** A personal, local Windows application to track invoices, payment obligations, completed payments, and reminders.

> **Important:** The application UI must be entirely in **Hebrew (RTL)**. This document is written in English so that Claude Code can use it as its implementation specification.

## 1. Product goal

Create a simple, reliable application that prevents missed payments and makes financial obligations easy to find and manage. The user manually enters invoices and payment commitments, attaches PDF/image files when available, tracks postponements and installments, records actual payments, and sees actionable items on a dashboard.

**Core rule:** An unpaid balance must never disappear merely because its due date or reminder date has passed. A fully paid obligation must disappear from the **action-required dashboard**, but **remain permanently accessible** in the Payments, Paid, and History views with all associated documents and payment records.

The application is for **one person on one Windows computer**. It is a web application served locally and viewed in a desktop browser, without cloud hosting, external integrations, paid APIs, or recurring software fees.

## 2. Confirmed product decisions

- **Platform:** Local browser application launched on Windows; suggested local URL `http://127.0.0.1:8000`.
- **Language:** Hebrew throughout the interface, with full right-to-left layout. English or other Latin-character supplier/property names, file names, currencies, dates, and invoice numbers must render correctly.
- **Visual style:** Modern, professional, light theme; white/light-gray backgrounds, blue accent color, clear urgency colors.
- **Users:** One local user; no team roles, shared accounts, mobile interface, remote access, or multi-device synchronization.
- **Entry:** **Manual only.** The user adds invoices/obligations and optionally uploads a PDF or image. No Gmail connection, automated email ingestion, AI invoice parsing, OCR requirement, or Excel import in v1.0.
- **Reminders:** **Inside the dashboard only.** By default, a reminder becomes actionable seven days before payment due; the user can customize the lead time and add multiple manual reminder dates. No email, Windows desktop notifications, push, or background reminder agent is required.
- **Dashboard:** Show **only items requiring action**. All other payments live in a separate comprehensive view.
- **Recurring payments:** Support automatically generated obligations with either a **fixed amount** or an **unknown/variable amount** that must later be entered manually.
- **Payment completion records:** Amount, actual payment date, and method are required. Transaction/reference number and receipt/payment confirmation attachment are optional.
- **Backups:** Automatic local backup once per day **on days when the app is used**, plus an explicit manual-backup button. Support safe recovery.
- **Financial history:** Paid invoices, payment entries, receipts, original documents, installment schedules, and audit history remain searchable and viewable indefinitely unless the user explicitly carries out a controlled archival/deletion operation. Do **not** auto-delete paid data when it is no longer actionable.
- **Cost:** No additional paid services. Existing Claude/ChatGPT subscriptions may help with development, but the finished app must not require paid services, subscriptions, model APIs, or an internet connection for core usage.

## 3. Navigation and screens

### 3.1 Dashboard — action required

Display only obligations that need the user's attention:

1. **Overdue:** Current due date has passed and an unpaid amount remains.
2. **Due soon:** Due in seven days or less (or within its individually configured reminder period), with an unpaid amount.
3. **Manual reminder reached:** A manually configured reminder date is today or earlier and its associated obligation is still actionable.
4. **Amount missing:** A variable recurring obligation still has no amount, and its due date is within the actionable window or a manual reminder has been triggered.

Include clear summary counts and an actionable list sorted by urgency and due date. Supported quick actions: open details, record payment, postpone, enter missing amount, and attach a document. The dashboard must not show fully paid or canceled obligations simply as reminders. A partially paid obligation may also be overdue.

Show monetary totals **by currency**, never add EUR, ILS, USD, etc. together without a currency conversion mechanism (out of scope). Unknown amounts must not be treated as zero in totals; clearly identify those records as **Amount missing**.

Dashboard conditions are recalculated from the stored data and the local date whenever the user opens or refreshes the app. The app must catch up correctly after many days without use.

### 3.2 All Payments

A desktop-friendly, wide table with tabs **Open / Paid / All**, plus free-text search and filters by property, country, supplier, category, currency, state, and date range. Sort by due date, amount, supplier, etc.

Columns should include supplier, property, invoice number (if any), category, amount, outstanding balance, currency, due date, status, attached document indicator, and actions.

**Paid records must remain available** here. The user can open any paid record and inspect the original invoice, payment dates, amounts, methods, references, optional receipts, and change history. Provide a separate History view as well.

Allow export of payment data to **Excel (.xlsx)** without any paid library or service. **Excel import is out of scope**.

### 3.3 Add Invoice / Add Obligation

Simple, entirely manual form with:

- Supplier (required, chosen or created from a searchable list).
- Property (required, or a special **General expense** option).
- Amount and currency (required for one-off invoices; missing amount permitted for variable recurring obligations).
- Due date (required).
- Category, invoice number, invoice issue/received date, notes (optional).
- PDF/JPG/PNG invoice attachment (optional).
- Payment type: one-time, installments, or recurring.
- Reminder settings: default seven days before due date, editable and with optional extra manual dates.

The user may create an obligation **without any invoice file** and attach the document later.

If an obligation has already been generated by a recurring rule, the user must be able to attach the newly received invoice to that existing obligation instead of making a duplicate.

### 3.4 Invoice / Obligation Details

Display the complete record:

- Original invoice information and attachment.
- Original amount, paid amount, outstanding balance, currency, and progress indicator.
- Original due date and current due date, including postponement history.
- Individual scheduled installments, if any.
- Actual payment entries, dates, methods, references, and receipts.
- Manual reminders and automatic reminder configuration.
- Audit events and notes.

Actions: edit details, add/view/replace supporting documents without destroying audit history, record payment, postpone an unpaid balance, split a remaining balance into new scheduled installments, cancel with a reason, and archive if appropriate.

A record that is **fully paid must be fully viewable, not locked away, hidden, or deleted**. It should remain accessible through Paid, All Payments, search, and History even years later.

### 3.5 Recurring Payments

Recurring templates store supplier, property, category, frequency, schedule, start date, optional end date, currency, amount mode, and (when fixed) amount.

Supported frequencies: monthly, every two months, quarterly, and annually. Due day should be configurable.

- **Fixed amount:** Generate a new obligation for each period using the fixed amount.
- **Variable amount:** Generate a new obligation with an unknown amount and a clear **Amount missing** state until the user fills in the actual amount and attaches a document if available.
- On opening the app, generate missed periods up to the current date, plus the next upcoming occurrence. Do not produce duplicate occurrences, even when the app is opened repeatedly or generation is interrupted.
- For monthly dates not present in a month (e.g., day 31 in February), use the last day of that month.
- Pausing or ending a recurring template prevents future occurrences but **must not delete historical obligations or payments**.
- Editing a template must not retroactively change paid records or previously confirmed historical periods.

### 3.6 History

Searchable permanent records of completed payments and meaningful changes, including dates of invoice creation, payment registration, partial payment, postponement, invoice correction, cancellation, and attachment changes.

This is not just an audit feed: there must be a straightforward **Paid Payments** view with the ability to reopen a paid invoice and every associated PDF/receipt at any time.

### 3.7 Settings

Manage properties (name, country, active/archived), suppliers, categories, default reminder lead time, local file storage and backup settings, and backup/restore operations.

## 4. Core payment logic and rules

### 4.1 Separate the three financial concepts

- **Invoice:** The source document or record containing supplier information and the total amount.
- **Obligation / installment:** A specific amount due on a specific date. An invoice may have several obligations.
- **Actual payment entry:** Money that was actually paid. An obligation may have multiple actual payment entries.

Do not flatten these into a single row in a way that loses installment/payment history.

### 4.2 Amounts and balances

- Store monetary amounts as exact decimal amounts or integer minor currency units (e.g., cents) with explicit currency. **Never use binary floating point for money.**
- `Outstanding balance = obligation amount - sum(valid actual payments allocated to it)`.
- A negative balance is forbidden; a payment greater than outstanding balance must be rejected or require an explicit correction flow.
- An actual payment must have positive amount, payment date, and method (bank transfer, card, cash, other).
- Payment reference/transaction number and uploaded receipt are **optional**.
- A fully paid status is reached only when the outstanding balance is exactly zero.
- A partially paid obligation may also be due soon or overdue. Payment progress and urgency should be independently represented.
- If an invoice has multiple scheduled obligations, the overall invoice balance equals the sum of all remaining obligation balances.

### 4.3 Installments and partial payments

- The sum of scheduled installment amounts must equal the original invoice total, accounting for rounding in exact minor units.
- Each installment has its own scheduled/current due date, amount, paid amount, and outstanding balance.
- Recording a partial payment updates the correct installment and invoice balances but does not automatically change another installment.
- Postponing an installment changes only the due date of its **unpaid remainder**, without overwriting already paid entries or other installment due dates.
- Record the original and new dates, timestamp, and optional reason in the audit log.

### 4.4 Reminders and urgency

- Default automatic reminder: seven calendar days before the current due date; the lead time can be modified globally or per obligation.
- Permit multiple manual reminder dates per obligation.
- A reminder is not a one-time dismissible notification that makes an unpaid debt disappear. Outstanding obligations meeting overdue/due-soon conditions remain visible.
- Recalculate automatic reminder timing after postponement. Preserve the old due date and reminder changes in history; avoid incorrectly keeping a postponed obligation urgent solely because its **old automatic** reminder happened.
- A triggered manual reminder should remain actionable until it is addressed, explicitly moved/cleared, or the obligation is fully paid or canceled.
- Reminders exist **only within the website/dashboard**, not as emails, operating-system notifications, or background push.

### 4.5 Duplicate detection and correction

- Warn when the same supplier, invoice number, and property appear again.
- Compute SHA-256 file hashes to warn about uploading an identical attachment again.
- Do not silently create duplicate recurring obligations or duplicate payments.
- For legitimate duplicates, allow explicit override with clear confirmation.
- Do not silently delete past payment entries. Correction should use a documented reversal/correction operation preserving the audit trail.
- Prefer **archive / soft-delete** rather than destructive removal for invoices, obligations, and suppliers with history. Any truly destructive deletion must be explicit, guarded, and never automatic.

### 4.6 States

Use independently derived indicators where appropriate:

- Open / waiting.
- Due soon.
- Overdue.
- Partially paid.
- Paid in full.
- Canceled.
- Missing amount (for variable recurring obligations).

Do not model **Partially paid** and **Overdue** as mutually exclusive when both are true.

## 5. Recommended SQLite data model

Claude Code should propose exact table definitions and migrations, with constraints and tests. Suggested entities:

| Table | Purpose |
|---|---|
| `properties` | Property identifier, name, country, active/archive status. |
| `suppliers` | Supplier identifier, name, optional contact/customer details. |
| `categories` | Expense categories. |
| `invoices` | Invoice/source record, supplier/property, number, dates, currency, original amount, notes, cancellation/archive metadata. |
| `obligations` | Scheduled amounts and dates, optional invoice link, optional recurring-template link, occurrence/period key, current and original due date, status fields. |
| `payment_entries` | Actual payments with exact amount, payment date, method, optional reference and notes; corrections/reversals must be auditable. |
| `recurring_templates` | Frequency, schedule, supplier, property, fixed/variable amount mode, effective dates, active status. |
| `reminders` | Custom manual reminder dates and/or relative rules, resolution/adjustment information. |
| `attachments` | Linked invoice/payment documents, original file name, safe relative managed path, MIME type, checksum, size. |
| `audit_events` | Immutable historical events: entity, action, timestamp, old/new values, details. |
| `settings` | Application preferences and backup configuration. |

Mandatory design principles:

- Stable primary keys and created/updated timestamps.
- Foreign keys enabled using `PRAGMA foreign_keys=ON`.
- A database-level uniqueness guarantee for recurring occurrence `(recurring_template_id, period_key)`.
- Explicit schema migrations for upgrades **without dropping existing user data**.
- Transactional updates for installments, actual payments, and recurring occurrence generation.
- Clear separation of editable current state from historical records.
- Paid entries must persist after restarts, updates, backup/restore, and archiving of their parent recurring template.

## 6. Local files, backup, and restore

Use a dedicated user data folder, for example `Documents/PaymentManagerData`, separate from the source code repository:

```text
PaymentManagerData/
  payment_manager.sqlite3
  invoices/
  receipts/
  backups/
```

All uploaded documents must be copied into app-managed storage using safe unique names. The app must not depend on the original file remaining in Downloads or another user folder. Store relative paths and metadata in SQLite.

### Backup behavior

- Automatically create a consistent local backup once per day **on days when the app is used**. Trigger after local startup/initialization and make sure the backup includes valid current data; avoid multiple backups on repeated page refreshes.
- Retain the last **seven daily** and **four weekly** backups, while avoiding unnecessary duplication. Backup retention applies to **backup archives only**, **not** to paid invoices, actual payments, or original supporting documents.
- The **Back Up Now** action creates a portable ZIP containing a consistent SQLite snapshot, invoices, receipts, necessary application settings, and a manifest/version description.
- Use SQLite's backup API or an equivalent consistency-safe snapshot; do not naively copy a live SQLite database file.
- To restore: validate archive contents, version, paths, and file integrity; back up the current state first; require confirmation; restore atomically when possible; show clear success/failure messages. Test restore before trusting it.
- Mention in the interface/help that backup files on the same computer do not protect against total disk failure. The user should occasionally copy a manual ZIP to a different drive.
- Never delete historical paid records just because old backup ZIP files are being rotated.

### File safety

Validate extensions and actual file types, enforce sensible maximum upload sizes, avoid path traversal and unsafe path concatenation, do not serve arbitrary filesystem paths, and ensure PDFs/images can be reopened from the browser later. Store/copy original documents unmodified.

## 7. Technical architecture and Windows setup

Proposed stack (Claude may suggest a simpler fully free alternative if it fits every requirement):

- **Backend:** Python + FastAPI.
- **Database:** SQLite.
- **Frontend:** HTML/CSS/vanilla JavaScript, optionally Jinja2 templates, with minimal dependencies.
- **Local address:** Bind **only** to `127.0.0.1` and open in the default browser (not `0.0.0.0`).
- **Launch:** A one-click Windows launcher script/shortcut starts the local server and opens the site.
- **Networking:** Once dependencies are installed, core features must work offline and make no runtime network calls to third-party services.
- **Security:** Local-only binding; safe upload and attachment routes; parameterized DB queries/ORM; safe input handling; no wildcard exposure to the local network; no secrets stored in code; meaningful Hebrew errors.
- **Dates:** Store as ISO dates (`YYYY-MM-DD`), present as `DD/MM/YYYY`, calculate using the user's Windows local date/time.
- **Cost:** Free open-source components only, without mandatory subscriptions, hosting, cloud databases, external payment services, or paid AI APIs.

Claude Code is used only during development. A consumer Claude or ChatGPT plan must **not** be assumed to provide a free production API for extracting invoices or running the application.

## 8. UI/UX

- Entire UI in **Hebrew** and **RTL**; treat English names, invoice IDs, currencies, and numbers with localized LTR spans as needed.
- Light theme, clean layout: white/light gray, blue primary actions, red overdue, orange due soon, green paid.
- Permanent navigation sidebar on the **right**: Dashboard, All Payments, New Invoice, Recurring Payments, History, Settings.
- Desktop-first wide tables, readable typography, quick payment/postpone actions, prominent **New Invoice** button.
- Clear empty states, confirm destructive actions, display understandable Hebrew validation errors.
- Avoid displaying fictitious demo records as real data. New installations start with an empty database, with optional onboarding to create properties/suppliers.
- Clicking a paid invoice opens its complete details, including attached source invoice and receipt(s) even if the due date is long in the past.

## 9. Acceptance tests — required before using real work data

1. Enter a €1,200 invoice split into three €400 installments. Overall initial outstanding balance is €1,200.
2. Record a €150 payment against one installment. That installment's remaining balance is €250; overall invoice balance is €1,050.
3. Postpone an installment after partial payment. The payment history, other installments, and original due date remain intact.
4. A partially paid installment due yesterday remains visible and explicitly marked overdue on the dashboard.
5. An open payment due in 30 days does **not** appear on the dashboard absent a triggered manual reminder, but it appears in All Payments.
6. A manual reminder due today makes the relevant open obligation actionable; after full payment it disappears from Dashboard but remains visible under Paid/History.
7. Repeated starts and refreshes do not duplicate recurring monthly obligations; a missed period is generated exactly once.
8. Variable recurring payment creates a **Missing amount** obligation, without treating an unknown amount as €0 or adding it to totals.
9. Uploading the same PDF or same supplier/invoice number warns about duplicates; a legitimate override remains possible with confirmation.
10. An invoice may be created without an attachment and have an invoice PDF added later.
11. Actual payment with date and method but without receipt/reference saves successfully; overpayment is rejected.
12. ZIP backup and restore preserve every original PDF, receipt, invoice, obligation, actual payment, recurring occurrence, and audit event.
13. Core functionality continues without an internet connection once installed.
14. EUR, ILS, and USD are stored and summarized separately.
15. Closing/reopening the server or restarting Windows does not lose any entries or hide overdue obligations.
16. **A fully paid invoice remains searchable and viewable in Paid, All Payments, and History, with its PDF, receipt, reference, and original/payment dates.** It is absent from the action-required Dashboard.
17. **A fully paid invoice from a previous year is still present after current-month filtering, a recurring-template edit, backup rotation, and application restart.**
18. Archive/soft-delete does not destroy already-paid payment entries or their document history.
19. Daily backup is created at most once per use day and can be restored safely without corrupting a live database.
20. New UI is in Hebrew RTL, including validation messages and navigation; English supplier names and currency symbols display correctly.

## 10. Out of scope for version 1.0

Gmail integration, automatic invoice discovery, OCR/AI extraction, paid APIs, cloud hosting and synchronization, mobile app, Windows/toast/email/push notifications, Excel **import**, automatic currency conversion, bank/payment processing, formal accounting software features, multiple users, and team permissions.

**Excel export is included**; Excel import is not.

## 11. Suggested phased delivery plan

**Phase A — Foundation:** Project setup, SQLite schema and migrations, filesystem layout, one-click Windows launch, light RTL design shell.

**Phase B — Core data and persistence:** Properties, suppliers, categories, manual invoice/obligation creation, attachments, detailed record view, actual payment registration, postponements, paid archive/history.

**Phase C — Work queue:** Dashboard action rules, default/manual reminders, comprehensive All Payments filters/search, reliable due-date status computation.

**Phase D — Advanced obligations:** Installment schedules, partial payments, fixed/variable recurring templates, idempotent occurrence generation, duplicate warnings.

**Phase E — Reliability:** Consistent daily/manual ZIP backups, safe restore, Excel export, error handling, automated tests and Windows run instructions.

Implement in small, testable slices. Before coding, Claude should identify data-integrity risks and propose an appropriate development order. Do not add cloud services, AI features, or unrequested complexity to the first version.

---

## Instructions for Claude Code

Treat this specification as the single source of truth. **Start in Plan Mode and do not write or modify application code.** Read all sections, produce a technical implementation plan, identify any contradictions or uncovered failure modes, and explain how you will ensure permanent access to historical paid invoices and documents. Include proposed database schema, backend routes, UI screens, payment logic, recurring generation, reminder calculations, safe local file storage, backups, acceptance tests, and Windows installation/launch steps.

**Do not implement anything until the user explicitly approves the plan.**
