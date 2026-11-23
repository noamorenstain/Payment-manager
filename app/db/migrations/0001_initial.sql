-- Payment Manager — schema v1 (complete v1 data model).
--
-- Conventions
--   * Money: INTEGER minor units (agorot/cents) with an explicit currency. Never REAL.
--   * Dates: TEXT 'YYYY-MM-DD', strictly validated: SQLite normalises impossible dates
--     (date('2026-02-30') = '2026-03-02'), so "date(x) IS x" rejects them.
--   * Timestamps: TEXT 'YYYY-MM-DD HH:MM:SS' (Windows local time).
--   * No hard deletes of user data in v1: DELETE is blocked by triggers.
--   * Derived values (paid / outstanding / canceled / transferred) are never stored;
--     they come from v_obligation_balance.
--   * change_counter.seq is bumped only by writes to USER-DATA tables (see bottom).
--     backup_log, backup_settings, system_state and change_counter are never tracked.

-- ======================================================================= lookups

CREATE TABLE currencies (
    code          TEXT PRIMARY KEY CHECK (code GLOB '[A-Z][A-Z][A-Z]'),
    symbol        TEXT NOT NULL CHECK (length(trim(symbol)) > 0),
    name_he       TEXT NOT NULL CHECK (length(trim(name_he)) > 0),
    minor_digits  INTEGER NOT NULL DEFAULT 2 CHECK (minor_digits = 2),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at)
);

CREATE TABLE properties (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL CHECK (length(trim(name)) > 0),
    country       TEXT,
    is_general    INTEGER NOT NULL DEFAULT 0 CHECK (is_general IN (0, 1)),
    notes         TEXT,
    archived_at   TEXT CHECK (archived_at IS NULL OR datetime(archived_at) IS archived_at),
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at),
    CHECK (is_general = 0 OR archived_at IS NULL)
);
CREATE UNIQUE INDEX ux_properties_single_general ON properties (is_general) WHERE is_general = 1;
CREATE INDEX ix_properties_name ON properties (name COLLATE NOCASE);

CREATE TABLE suppliers (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL CHECK (length(trim(name)) > 0),
    contact          TEXT,
    customer_number  TEXT,
    notes            TEXT,
    archived_at      TEXT CHECK (archived_at IS NULL OR datetime(archived_at) IS archived_at),
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at)
);
CREATE INDEX ix_suppliers_name ON suppliers (name COLLATE NOCASE);

CREATE TABLE categories (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) > 0),
    archived_at   TEXT CHECK (archived_at IS NULL OR datetime(archived_at) IS archived_at),
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at)
);

-- ======================================================================= invoices

CREATE TABLE invoices (
    id                         INTEGER PRIMARY KEY,
    supplier_id                INTEGER NOT NULL REFERENCES suppliers (id),
    property_id                INTEGER NOT NULL REFERENCES properties (id),
    category_id                INTEGER REFERENCES categories (id),
    invoice_number             TEXT,
    issue_date                 TEXT CHECK (issue_date IS NULL OR (issue_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(issue_date) IS issue_date AND issue_date BETWEEN '2000-01-01' AND '2100-12-31')),
    received_date              TEXT CHECK (received_date IS NULL OR (received_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(received_date) IS received_date AND received_date BETWEEN '2000-01-01' AND '2100-12-31')),
    currency                   TEXT NOT NULL REFERENCES currencies (code),
    -- NULL only while a variable recurring occurrence is still missing its amount
    total_minor                INTEGER CHECK (total_minor IS NULL OR (typeof(total_minor) = 'integer' AND total_minor > 0)),
    notes                      TEXT,
    canceled_at                TEXT CHECK (canceled_at IS NULL OR datetime(canceled_at) IS canceled_at),
    cancel_reason              TEXT,
    duplicate_override_reason  TEXT,
    created_at                 TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at                 TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at),
    CHECK ((canceled_at IS NULL) = (cancel_reason IS NULL))
);
CREATE INDEX ix_invoices_supplier ON invoices (supplier_id);
CREATE INDEX ix_invoices_property ON invoices (property_id);
CREATE INDEX ix_invoices_number ON invoices (invoice_number COLLATE NOCASE);

-- ======================================================================= recurring

CREATE TABLE recurring_templates (
    id                  INTEGER PRIMARY KEY,
    supplier_id         INTEGER NOT NULL REFERENCES suppliers (id),
    property_id         INTEGER NOT NULL REFERENCES properties (id),
    category_id         INTEGER REFERENCES categories (id),
    currency            TEXT NOT NULL REFERENCES currencies (code),
    frequency           TEXT NOT NULL CHECK (frequency IN ('monthly', 'bimonthly', 'quarterly', 'annual')),
    due_day             INTEGER NOT NULL CHECK (typeof(due_day) = 'integer' AND due_day BETWEEN 1 AND 31),
    start_date          TEXT NOT NULL CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(start_date) IS start_date AND start_date BETWEEN '2000-01-01' AND '2100-12-31'),
    end_date            TEXT CHECK (end_date IS NULL OR (end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(end_date) IS end_date AND end_date BETWEEN '2000-01-01' AND '2100-12-31')),
    generate_from_date  TEXT NOT NULL CHECK (generate_from_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(generate_from_date) IS generate_from_date AND generate_from_date BETWEEN '2000-01-01' AND '2100-12-31'),
    amount_mode         TEXT NOT NULL CHECK (amount_mode IN ('fixed', 'variable')),
    fixed_amount_minor  INTEGER,
    reminder_lead_days  INTEGER CHECK (reminder_lead_days IS NULL OR (typeof(reminder_lead_days) = 'integer' AND reminder_lead_days BETWEEN 0 AND 365)),
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'ended')),
    ended_at            TEXT CHECK (ended_at IS NULL OR datetime(ended_at) IS ended_at),
    notes               TEXT,
    archived_at         TEXT CHECK (archived_at IS NULL OR datetime(archived_at) IS archived_at),
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at),
    CHECK (end_date IS NULL OR end_date >= start_date),
    CHECK (generate_from_date >= start_date),
    CHECK ((amount_mode = 'fixed' AND typeof(fixed_amount_minor) = 'integer' AND fixed_amount_minor > 0)
        OR (amount_mode = 'variable' AND fixed_amount_minor IS NULL)),
    CHECK ((status = 'ended') = (ended_at IS NOT NULL))
);

CREATE TABLE recurring_pauses (
    id           INTEGER PRIMARY KEY,
    template_id  INTEGER NOT NULL REFERENCES recurring_templates (id),
    paused_on    TEXT NOT NULL CHECK (paused_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(paused_on) IS paused_on AND paused_on BETWEEN '2000-01-01' AND '2100-12-31'),
    resumed_on   TEXT CHECK (resumed_on IS NULL OR (resumed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(resumed_on) IS resumed_on AND resumed_on BETWEEN '2000-01-01' AND '2100-12-31')),
    reason       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    CHECK (resumed_on IS NULL OR resumed_on >= paused_on)
);
-- at most one open pause per template
CREATE UNIQUE INDEX ux_recurring_pauses_open ON recurring_pauses (template_id) WHERE resumed_on IS NULL;

CREATE TABLE recurring_skipped_periods (
    id                INTEGER PRIMARY KEY,
    template_id       INTEGER NOT NULL REFERENCES recurring_templates (id),
    period_key        TEXT NOT NULL CHECK (period_key GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(period_key, 6, 2) BETWEEN '01' AND '12'),
    pause_id          INTEGER NOT NULL REFERENCES recurring_pauses (id),
    nominal_due_date  TEXT NOT NULL CHECK (nominal_due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(nominal_due_date) IS nominal_due_date),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    UNIQUE (template_id, period_key)
);

-- ======================================================================= obligations

CREATE TABLE obligations (
    id                     INTEGER PRIMARY KEY,
    invoice_id             INTEGER REFERENCES invoices (id),
    recurring_template_id  INTEGER REFERENCES recurring_templates (id),
    period_key             TEXT CHECK (period_key IS NULL OR (period_key GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(period_key, 6, 2) BETWEEN '01' AND '12')),
    installment_no         INTEGER,
    installment_count      INTEGER,
    supplier_id            INTEGER NOT NULL REFERENCES suppliers (id),
    property_id            INTEGER NOT NULL REFERENCES properties (id),
    category_id            INTEGER REFERENCES categories (id),
    currency               TEXT NOT NULL REFERENCES currencies (code),
    -- original scheduled amount; NULL = amount missing (variable recurring only);
    -- never reduced by cancel or split
    amount_minor           INTEGER CHECK (amount_minor IS NULL OR (typeof(amount_minor) = 'integer' AND amount_minor > 0)),
    original_due_date      TEXT NOT NULL CHECK (original_due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(original_due_date) IS original_due_date AND original_due_date BETWEEN '2000-01-01' AND '2100-12-31'),
    current_due_date       TEXT NOT NULL CHECK (current_due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(current_due_date) IS current_due_date AND current_due_date BETWEEN '2000-01-01' AND '2100-12-31'),
    reminder_lead_days     INTEGER CHECK (reminder_lead_days IS NULL OR (typeof(reminder_lead_days) = 'integer' AND reminder_lead_days BETWEEN 0 AND 365)),
    lifecycle              TEXT NOT NULL DEFAULT 'active' CHECK (lifecycle IN ('active', 'canceled', 'restructured')),
    closed_at              TEXT CHECK (closed_at IS NULL OR datetime(closed_at) IS closed_at),
    close_reason           TEXT,
    closed_paid_minor      INTEGER CHECK (closed_paid_minor IS NULL OR (typeof(closed_paid_minor) = 'integer' AND closed_paid_minor >= 0)),
    parent_obligation_id   INTEGER REFERENCES obligations (id),
    notes                  TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at),
    UNIQUE (recurring_template_id, period_key),
    CHECK ((recurring_template_id IS NULL) = (period_key IS NULL)),
    CHECK (amount_minor IS NOT NULL OR recurring_template_id IS NOT NULL),
    CHECK (lifecycle <> 'restructured' OR amount_minor IS NOT NULL),
    CHECK ((lifecycle = 'active') = (closed_at IS NULL)),
    CHECK ((installment_no IS NULL) = (installment_count IS NULL)),
    CHECK (installment_no IS NULL OR (installment_no >= 1 AND installment_count >= 1 AND installment_no <= installment_count)),
    CHECK (parent_obligation_id IS NULL OR parent_obligation_id <> id)
);
CREATE INDEX ix_obligations_invoice ON obligations (invoice_id);
CREATE INDEX ix_obligations_due ON obligations (lifecycle, current_due_date);
CREATE INDEX ix_obligations_parent ON obligations (parent_obligation_id);
CREATE INDEX ix_obligations_supplier ON obligations (supplier_id);

CREATE TABLE postponements (
    id                      INTEGER PRIMARY KEY,
    obligation_id           INTEGER NOT NULL REFERENCES obligations (id),
    old_due_date            TEXT NOT NULL CHECK (old_due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(old_due_date) IS old_due_date),
    new_due_date            TEXT NOT NULL CHECK (new_due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(new_due_date) IS new_due_date AND new_due_date BETWEEN '2000-01-01' AND '2100-12-31'),
    reason                  TEXT,
    moved_manual_reminders  INTEGER NOT NULL DEFAULT 0 CHECK (moved_manual_reminders IN (0, 1)),
    created_at              TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    CHECK (new_due_date <> old_due_date)
);
CREATE INDEX ix_postponements_obligation ON postponements (obligation_id);

-- ======================================================================= payments

CREATE TABLE payment_entries (
    id                 INTEGER PRIMARY KEY,
    obligation_id      INTEGER NOT NULL REFERENCES obligations (id),
    amount_minor       INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer' AND amount_minor > 0),
    paid_on            TEXT NOT NULL CHECK (paid_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(paid_on) IS paid_on AND paid_on BETWEEN '2000-01-01' AND '2100-12-31'),
    method             TEXT NOT NULL CHECK (method IN ('bank_transfer', 'card', 'cash', 'check', 'other')),
    reference          TEXT,
    notes              TEXT,
    voided_at          TEXT CHECK (voided_at IS NULL OR datetime(voided_at) IS voided_at),
    void_reason        TEXT,
    corrects_entry_id  INTEGER REFERENCES payment_entries (id),
    request_token      TEXT UNIQUE,
    created_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at),
    CHECK ((voided_at IS NULL) = (void_reason IS NULL)),
    CHECK (void_reason IS NULL OR length(trim(void_reason)) > 0)
);
CREATE INDEX ix_payment_entries_obligation ON payment_entries (obligation_id);
CREATE INDEX ix_payment_entries_paid_on ON payment_entries (paid_on);

-- ======================================================================= reminders

CREATE TABLE reminders (
    id               INTEGER PRIMARY KEY,
    obligation_id    INTEGER NOT NULL REFERENCES obligations (id),
    remind_on        TEXT NOT NULL CHECK (remind_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(remind_on) IS remind_on AND remind_on BETWEEN '2000-01-01' AND '2100-12-31'),
    note             TEXT,
    status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'handled', 'cleared')),
    resolved_at      TEXT CHECK (resolved_at IS NULL OR datetime(resolved_at) IS resolved_at),
    resolution_note  TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at),
    CHECK ((status = 'pending') = (resolved_at IS NULL))
);
CREATE INDEX ix_reminders_obligation ON reminders (obligation_id);
CREATE INDEX ix_reminders_pending ON reminders (status, remind_on);

-- ======================================================================= attachments

CREATE TABLE attachments (
    id                  INTEGER PRIMARY KEY,
    invoice_id          INTEGER REFERENCES invoices (id),
    obligation_id       INTEGER REFERENCES obligations (id),
    payment_entry_id    INTEGER REFERENCES payment_entries (id),
    kind                TEXT NOT NULL CHECK (kind IN ('invoice', 'receipt', 'other')),
    original_name       TEXT NOT NULL CHECK (length(trim(original_name)) > 0),
    -- relative to live\, app-generated; never absolute, never "..", never a drive or UNC path
    stored_path         TEXT NOT NULL UNIQUE CHECK (
                            length(stored_path) > 0
                            AND stored_path NOT GLOB '*..*'
                            AND stored_path NOT GLOB '[A-Za-z]:*'
                            AND substr(stored_path, 1, 1) NOT IN ('/', '\')
                            AND (stored_path GLOB 'invoices/*' OR stored_path GLOB 'receipts/*')),
    mime                TEXT NOT NULL CHECK (mime IN ('application/pdf', 'image/jpeg', 'image/png')),
    size_bytes          INTEGER NOT NULL CHECK (typeof(size_bytes) = 'integer' AND size_bytes > 0),
    sha256              TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    superseded_by       INTEGER REFERENCES attachments (id),
    duplicate_override  INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_override IN (0, 1)),
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(created_at) IS created_at),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')) CHECK (datetime(updated_at) IS updated_at),
    CHECK ((invoice_id IS NOT NULL) + (obligation_id IS NOT NULL) + (payment_entry_id IS NOT NULL) = 1),
    CHECK (superseded_by IS NULL OR superseded_by <> id)
);
CREATE INDEX ix_attachments_sha ON attachments (sha256);
CREATE INDEX ix_attachments_invoice ON attachments (invoice_id);
CREATE INDEX ix_attachments_obligation ON attachments (obligation_id);
CREATE INDEX ix_attachments_payment ON attachments (payment_entry_id);

-- ======================================================================= audit

CREATE TABLE audit_events (
    id           INTEGER PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    entity_id    INTEGER,
    action       TEXT NOT NULL,
    occurred_at  TEXT NOT NULL CHECK (datetime(occurred_at) IS occurred_at),
    old_json     TEXT CHECK (old_json IS NULL OR json_valid(old_json)),
    new_json     TEXT CHECK (new_json IS NULL OR json_valid(new_json)),
    details      TEXT
);
CREATE INDEX ix_audit_entity ON audit_events (entity_type, entity_id);
CREATE INDEX ix_audit_time ON audit_events (occurred_at);

-- ======================================================================= settings & system

-- user preferences (tracked: part of the user's data)
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- backup configuration (NOT tracked)
CREATE TABLE backup_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- runtime markers such as last_backup_seq (NOT tracked)
CREATE TABLE system_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- single-row user-data change counter (NOT tracked; has no triggers of its own)
CREATE TABLE change_counter (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    seq  INTEGER NOT NULL CHECK (seq >= 0)
);

-- backup bookkeeping (NOT tracked)
CREATE TABLE backup_log (
    id              INTEGER PRIMARY KEY,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    slot_date       TEXT,
    kind            TEXT NOT NULL,
    file_name       TEXT,
    sha256          TEXT,
    change_seq      INTEGER,
    db_fingerprint  TEXT,
    status          TEXT NOT NULL,
    details         TEXT
);

-- ======================================================================= derived view

CREATE VIEW v_obligation_balance AS
SELECT
    o.id                                    AS obligation_id,
    o.invoice_id,
    o.parent_obligation_id,
    o.currency,
    o.lifecycle,
    o.amount_minor,
    COALESCE(p.paid, 0)                     AS paid_minor,
    o.amount_minor - COALESCE(p.paid, 0)    AS remaining_minor,
    CASE WHEN o.lifecycle = 'active'       THEN o.amount_minor - COALESCE(p.paid, 0) ELSE 0 END AS outstanding_minor,
    CASE WHEN o.lifecycle = 'canceled'     THEN o.amount_minor - COALESCE(p.paid, 0) ELSE 0 END AS canceled_minor,
    CASE WHEN o.lifecycle = 'restructured' THEN o.amount_minor - COALESCE(p.paid, 0) ELSE 0 END AS transferred_minor,
    CASE
        WHEN o.lifecycle = 'canceled'          THEN 'canceled'
        WHEN o.lifecycle = 'restructured'      THEN 'restructured'
        WHEN o.amount_minor IS NULL            THEN 'missing_amount'
        WHEN COALESCE(p.paid, 0) = o.amount_minor THEN 'paid'
        WHEN COALESCE(p.paid, 0) > 0           THEN 'partial'
        ELSE 'open'
    END                                     AS primary_state
FROM obligations o
LEFT JOIN (
    SELECT obligation_id, SUM(amount_minor) AS paid
    FROM payment_entries
    WHERE voided_at IS NULL
    GROUP BY obligation_id
) p ON p.obligation_id = o.id;

-- ======================================================================= integrity triggers

-- ---- payments: only payable obligations, never more than the remaining balance
CREATE TRIGGER trg_payment_insert_guard
BEFORE INSERT ON payment_entries
BEGIN
    SELECT RAISE(ABORT, 'pm:payment_on_inactive_obligation')
    WHERE (SELECT lifecycle FROM obligations WHERE id = NEW.obligation_id) IS NOT 'active';
    SELECT RAISE(ABORT, 'pm:payment_on_missing_amount')
    WHERE (SELECT amount_minor FROM obligations WHERE id = NEW.obligation_id) IS NULL;
    SELECT RAISE(ABORT, 'pm:payment_inserted_voided')
    WHERE NEW.voided_at IS NOT NULL;
    SELECT RAISE(ABORT, 'pm:overpayment')
    WHERE NEW.amount_minor > (
        SELECT o.amount_minor - COALESCE((SELECT SUM(pe.amount_minor) FROM payment_entries pe
                                          WHERE pe.obligation_id = o.id AND pe.voided_at IS NULL), 0)
        FROM obligations o WHERE o.id = NEW.obligation_id);
END;

-- ---- payments: immutable except a single void
CREATE TRIGGER trg_payment_update_guard
BEFORE UPDATE ON payment_entries
BEGIN
    SELECT RAISE(ABORT, 'pm:payment_immutable')
    WHERE NEW.id IS NOT OLD.id
       OR NEW.obligation_id IS NOT OLD.obligation_id
       OR NEW.amount_minor IS NOT OLD.amount_minor
       OR NEW.paid_on IS NOT OLD.paid_on
       OR NEW.method IS NOT OLD.method
       OR NEW.reference IS NOT OLD.reference
       OR NEW.notes IS NOT OLD.notes
       OR NEW.corrects_entry_id IS NOT OLD.corrects_entry_id
       OR NEW.request_token IS NOT OLD.request_token
       OR NEW.created_at IS NOT OLD.created_at;
    SELECT RAISE(ABORT, 'pm:payment_already_voided')
    WHERE OLD.voided_at IS NOT NULL;
    SELECT RAISE(ABORT, 'pm:void_on_restructured')
    WHERE NEW.voided_at IS NOT NULL
      AND (SELECT lifecycle FROM obligations WHERE id = OLD.obligation_id) = 'restructured';
END;

-- ---- obligations: lifecycle is final once closed; amount frozen once closed;
--      amount can never drop below what was already paid
CREATE TRIGGER trg_obligation_update_guard
BEFORE UPDATE ON obligations
BEGIN
    SELECT RAISE(ABORT, 'pm:obligation_identity_immutable')
    WHERE NEW.id IS NOT OLD.id
       OR NEW.original_due_date IS NOT OLD.original_due_date
       OR NEW.currency IS NOT OLD.currency
       OR NEW.recurring_template_id IS NOT OLD.recurring_template_id
       OR NEW.period_key IS NOT OLD.period_key
       OR NEW.created_at IS NOT OLD.created_at;
    SELECT RAISE(ABORT, 'pm:obligation_closed')
    WHERE OLD.lifecycle <> 'active' AND (
           NEW.lifecycle IS NOT OLD.lifecycle
        OR NEW.amount_minor IS NOT OLD.amount_minor
        OR NEW.current_due_date IS NOT OLD.current_due_date
        OR NEW.closed_at IS NOT OLD.closed_at
        OR NEW.closed_paid_minor IS NOT OLD.closed_paid_minor);
    SELECT RAISE(ABORT, 'pm:amount_cannot_be_removed')
    WHERE OLD.amount_minor IS NOT NULL AND NEW.amount_minor IS NULL;
    SELECT RAISE(ABORT, 'pm:amount_below_paid')
    WHERE NEW.amount_minor IS NOT NULL
      AND NEW.amount_minor < COALESCE((SELECT SUM(amount_minor) FROM payment_entries
                                       WHERE obligation_id = OLD.id AND voided_at IS NULL), 0);
END;

-- ---- attachments: content metadata immutable; superseded_by may be set once
CREATE TRIGGER trg_attachment_update_guard
BEFORE UPDATE ON attachments
BEGIN
    SELECT RAISE(ABORT, 'pm:attachment_immutable')
    WHERE NEW.id IS NOT OLD.id
       OR NEW.invoice_id IS NOT OLD.invoice_id
       OR NEW.obligation_id IS NOT OLD.obligation_id
       OR NEW.payment_entry_id IS NOT OLD.payment_entry_id
       OR NEW.kind IS NOT OLD.kind
       OR NEW.original_name IS NOT OLD.original_name
       OR NEW.stored_path IS NOT OLD.stored_path
       OR NEW.mime IS NOT OLD.mime
       OR NEW.size_bytes IS NOT OLD.size_bytes
       OR NEW.sha256 IS NOT OLD.sha256
       OR NEW.duplicate_override IS NOT OLD.duplicate_override
       OR NEW.created_at IS NOT OLD.created_at;
    SELECT RAISE(ABORT, 'pm:attachment_already_superseded')
    WHERE OLD.superseded_by IS NOT NULL AND NEW.superseded_by IS NOT OLD.superseded_by;
END;

-- ---- append-only history tables
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'pm:history_immutable'); END;

CREATE TRIGGER trg_postponements_no_update BEFORE UPDATE ON postponements
BEGIN SELECT RAISE(ABORT, 'pm:history_immutable'); END;

CREATE TRIGGER trg_skipped_no_update BEFORE UPDATE ON recurring_skipped_periods
BEGIN SELECT RAISE(ABORT, 'pm:history_immutable'); END;

-- ---- pauses: only resumed_on may be set, exactly once
CREATE TRIGGER trg_pause_update_guard
BEFORE UPDATE ON recurring_pauses
BEGIN
    SELECT RAISE(ABORT, 'pm:pause_immutable')
    WHERE NEW.id IS NOT OLD.id
       OR NEW.template_id IS NOT OLD.template_id
       OR NEW.paused_on IS NOT OLD.paused_on
       OR NEW.reason IS NOT OLD.reason
       OR NEW.created_at IS NOT OLD.created_at;
    SELECT RAISE(ABORT, 'pm:pause_already_resumed')
    WHERE OLD.resumed_on IS NOT NULL;
END;

-- ---- no hard deletion of user data in v1
CREATE TRIGGER trg_no_delete_currencies          BEFORE DELETE ON currencies          BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_properties          BEFORE DELETE ON properties          BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_suppliers           BEFORE DELETE ON suppliers           BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_categories          BEFORE DELETE ON categories          BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_invoices            BEFORE DELETE ON invoices            BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_obligations         BEFORE DELETE ON obligations         BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_postponements       BEFORE DELETE ON postponements       BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_payment_entries     BEFORE DELETE ON payment_entries     BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_recurring_templates BEFORE DELETE ON recurring_templates BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_recurring_pauses    BEFORE DELETE ON recurring_pauses    BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_skipped_periods     BEFORE DELETE ON recurring_skipped_periods BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_reminders           BEFORE DELETE ON reminders           BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_attachments         BEFORE DELETE ON attachments         BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_audit_events        BEFORE DELETE ON audit_events        BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;
CREATE TRIGGER trg_no_delete_change_counter      BEFORE DELETE ON change_counter      BEGIN SELECT RAISE(ABORT, 'pm:delete_forbidden'); END;

-- ======================================================================= change tracking
-- Bumps change_counter.seq on every write to a USER-DATA table. Exactly these 15 tables
-- are tracked (asserted by a test). Untracked: backup_log, backup_settings, system_state,
-- change_counter. recursive_triggers stays OFF, so these updates cannot cascade.

INSERT INTO change_counter (id, seq) VALUES (1, 0);

CREATE TRIGGER trg_track_ins_currencies AFTER INSERT ON currencies BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_currencies AFTER UPDATE ON currencies BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_properties AFTER INSERT ON properties BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_properties AFTER UPDATE ON properties BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_suppliers AFTER INSERT ON suppliers BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_suppliers AFTER UPDATE ON suppliers BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_categories AFTER INSERT ON categories BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_categories AFTER UPDATE ON categories BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_invoices AFTER INSERT ON invoices BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_invoices AFTER UPDATE ON invoices BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_obligations AFTER INSERT ON obligations BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_obligations AFTER UPDATE ON obligations BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_postponements AFTER INSERT ON postponements BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_postponements AFTER UPDATE ON postponements BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_payment_entries AFTER INSERT ON payment_entries BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_payment_entries AFTER UPDATE ON payment_entries BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_recurring_templates AFTER INSERT ON recurring_templates BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_recurring_templates AFTER UPDATE ON recurring_templates BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_recurring_pauses AFTER INSERT ON recurring_pauses BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_recurring_pauses AFTER UPDATE ON recurring_pauses BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_recurring_skipped_periods AFTER INSERT ON recurring_skipped_periods BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_recurring_skipped_periods AFTER UPDATE ON recurring_skipped_periods BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_reminders AFTER INSERT ON reminders BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_reminders AFTER UPDATE ON reminders BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_attachments AFTER INSERT ON attachments BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_attachments AFTER UPDATE ON attachments BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_audit_events AFTER INSERT ON audit_events BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_audit_events AFTER UPDATE ON audit_events BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_ins_settings AFTER INSERT ON settings BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_upd_settings AFTER UPDATE ON settings BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
CREATE TRIGGER trg_track_del_settings AFTER DELETE ON settings BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

-- ======================================================================= seed (system data, not demo data)

INSERT INTO currencies (code, symbol, name_he) VALUES
    ('ILS', '₪', 'שקל חדש'),
    ('EUR', '€', 'אירו'),
    ('USD', '$', 'דולר אמריקאי');

INSERT INTO properties (name, is_general) VALUES ('הוצאה כללית', 1);

INSERT INTO settings (key, value) VALUES
    ('default_reminder_lead_days', '7'),
    ('max_upload_mb', '25');
