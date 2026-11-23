-- Schema v3: protect invoice creation against double submission (double click, browser
-- re-send). Each "new invoice" form carries a one-time token; a second submission with the
-- same token is recognised instead of creating a duplicate invoice.

ALTER TABLE invoices ADD COLUMN request_token TEXT;

CREATE UNIQUE INDEX ux_invoices_request_token ON invoices (request_token) WHERE request_token IS NOT NULL;
