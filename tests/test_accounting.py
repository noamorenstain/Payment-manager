"""Accounting model (plan §3.3): pure functions, SQL view parity, integrity checks."""

import random

import pytest

from app.domain import accounting as a
from app.services.integrity import run_integrity_checks
from tests import factories as f


def ob(amount, payments=(), lifecycle="active", child=False):
    return a.obligation_balance(amount, payments, lifecycle, child)


# ====================================================================== pure obligation values

def test_spec_example_installments_and_partial_payment():
    # €1,200 split into three €400 installments; €150 paid on the first
    first, second, third = ob(40000, [15000]), ob(40000), ob(40000)
    assert first.remaining_minor == first.outstanding_minor == 25000
    assert first.primary_state == "partial" and first.is_partially_paid
    summary = a.invoice_summary(120000, [first, second, third])
    assert summary.outstanding_minor == 105000 and summary.paid_minor == 15000
    assert summary.state == "partial"
    assert a.invoice_invariant_holds(120000, [first, second, third])


def test_cancel_after_partial_payment_is_not_paid():
    b = ob(40000, [15000], "canceled")
    assert (b.paid_minor, b.canceled_minor, b.outstanding_minor, b.transferred_minor) == (15000, 25000, 0, 0)
    assert b.primary_state == "canceled"
    assert not b.is_paid_in_full
    assert b.is_partially_paid  # independent flag → "שולם חלקית לפני ביטול"


def test_cancel_with_nothing_paid():
    b = ob(40000, [], "canceled")
    assert b.canceled_minor == 40000 and b.paid_minor == 0 and not b.is_paid_in_full


def test_cancel_missing_amount_is_unknown_not_zero():
    b = ob(None, [], "canceled")
    assert b.canceled_minor is None and b.outstanding_minor == 0


def test_restructured_parent():
    b = ob(40000, [15000], "restructured")
    assert (b.paid_minor, b.transferred_minor, b.outstanding_minor, b.canceled_minor) == (15000, 25000, 0, 0)
    assert b.primary_state == "restructured" and not b.is_paid_in_full


def test_paid_in_full_only_when_active():
    assert ob(40000, [40000]).is_paid_in_full
    assert ob(40000, [10000, 30000]).primary_state == "paid"
    assert not ob(40000, [39999]).is_paid_in_full
    assert not ob(None).is_paid_in_full and ob(None).primary_state == "missing_amount"


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        ob(100, [101])
    with pytest.raises(ValueError):
        ob(100, [0])
    with pytest.raises(ValueError):
        ob(100, [1.5])
    with pytest.raises(ValueError):
        ob(None, [100])
    with pytest.raises(ValueError):
        ob(100, [], "deleted")


# ====================================================================== invoice summaries

def test_invoice_with_canceled_remainder_is_never_paid():
    parts = [ob(40000, [40000]), ob(40000, [40000]), ob(40000, [15000], "canceled")]
    s = a.invoice_summary(120000, parts)
    assert (s.paid_minor, s.canceled_minor, s.outstanding_minor) == (95000, 25000, 0)
    assert s.state == "closed_partly_canceled" and not s.is_paid_in_full
    assert a.invoice_invariant_holds(120000, parts)


def test_invoice_fully_canceled_without_payments():
    s = a.invoice_summary(120000, [ob(40000, [], "canceled")] * 3)
    assert s.state == "canceled" and s.canceled_minor == 120000


def test_invoice_fully_paid():
    s = a.invoice_summary(120000, [ob(40000, [40000])] * 3)
    assert s.state == "paid" and s.is_paid_in_full and s.outstanding_minor == 0


def test_restructure_keeps_invoice_totals():
    # €400 installment, €150 paid, remainder €250 split into 2 × €125
    before = [ob(40000, [15000]), ob(40000), ob(40000)]
    after = [ob(40000, [15000], "restructured"), ob(12500, child=True), ob(12500, child=True), ob(40000), ob(40000)]
    s_before, s_after = a.invoice_summary(120000, before), a.invoice_summary(120000, after)
    assert s_after.outstanding_minor == s_before.outstanding_minor == 105000
    assert s_after.paid_minor == 15000 and s_after.state == "partial"
    assert a.invoice_invariant_holds(120000, after)


def test_invariant_detects_mismatch():
    assert not a.invoice_invariant_holds(120000, [ob(40000), ob(40000)])


def test_invoice_missing_amount_state():
    s = a.invoice_summary(None, [ob(None)])
    assert s.state == "missing_amount" and s.outstanding_minor is None


def test_random_sequences_keep_invariant():
    """Property-style: random pay / void / cancel / split sequences never break the invariant."""
    for seed in range(200):
        rng = random.Random(seed)
        total = rng.randint(3, 500000)
        amounts = [total // 3, total // 3, total - 2 * (total // 3)]
        items = [{"amount": x, "payments": [], "life": "active", "child": False} for x in amounts]
        for _ in range(rng.randint(1, 12)):
            item = rng.choice(items)
            remaining = item["amount"] - sum(item["payments"])
            action = rng.choice(["pay", "pay", "void", "cancel", "split"])
            if item["life"] != "active":
                continue
            if action == "pay" and remaining > 0:
                item["payments"].append(rng.randint(1, remaining))
            elif action == "void" and item["payments"]:
                item["payments"].pop(rng.randrange(len(item["payments"])))
            elif action == "cancel" and remaining > 0:
                item["life"] = "canceled"
            elif action == "split" and remaining >= 2:
                item["life"] = "restructured"
                first = rng.randint(1, remaining - 1)
                items += [{"amount": first, "payments": [], "life": "active", "child": True},
                          {"amount": remaining - first, "payments": [], "life": "active", "child": True}]
        balances = [ob(i["amount"], i["payments"], i["life"], i["child"]) for i in items]
        assert a.invoice_invariant_holds(total, balances), seed
        s = a.invoice_summary(total, balances)
        if s.state == "paid":
            assert s.canceled_minor == 0 and s.outstanding_minor == 0


# ====================================================================== SQL view parity

def _view_matches_python(conn, ob_id, amount, payments, lifecycle):
    row = f.balance(conn, ob_id)
    py = ob(amount, payments, lifecycle)
    assert row["paid_minor"] == py.paid_minor
    assert row["remaining_minor"] == py.remaining_minor
    assert row["outstanding_minor"] == py.outstanding_minor
    assert row["canceled_minor"] == py.canceled_minor
    assert row["transferred_minor"] == py.transferred_minor
    assert row["primary_state"] == py.primary_state


@pytest.mark.parametrize("payments, lifecycle", [
    ([], "active"), ([15000], "active"), ([15000, 25000], "active"),
    ([], "canceled"), ([15000], "canceled"), ([15000], "restructured"),
])
def test_sql_view_agrees_with_python(conn, payments, lifecycle):
    ob_id = f.obligation(conn, amount_minor=40000)
    for p in payments:
        f.pay(conn, ob_id, p)
    if lifecycle != "active":
        f.close(conn, ob_id, lifecycle)
    _view_matches_python(conn, ob_id, 40000, payments, lifecycle)


def test_sql_view_ignores_voided_payments(conn):
    ob_id = f.obligation(conn, amount_minor=40000)
    e1 = f.pay(conn, ob_id, 15000)
    f.pay(conn, ob_id, 5000)
    f.void(conn, e1)
    _view_matches_python(conn, ob_id, 40000, [5000], "active")


def test_void_on_canceled_increases_canceled_amount(conn):
    ob_id = f.obligation(conn, amount_minor=40000)
    entry = f.pay(conn, ob_id, 15000)
    f.close(conn, ob_id, "canceled")
    assert f.balance(conn, ob_id)["canceled_minor"] == 25000
    f.void(conn, entry)
    assert f.balance(conn, ob_id)["canceled_minor"] == 40000
    assert f.balance(conn, ob_id)["paid_minor"] == 0


# ====================================================================== integrity checks

def _spec_invoice(conn):
    inv = f.invoice(conn, total_minor=120000)
    obs = [f.obligation(conn, invoice_id=inv, amount_minor=40000, installment=(i, 3)) for i in (1, 2, 3)]
    return inv, obs


def test_clean_database_has_no_issues(conn):
    _spec_invoice(conn)
    assert run_integrity_checks(conn, full=True) == []


def test_invoice_sum_mismatch_detected(conn):
    inv = f.invoice(conn, total_minor=120000)
    f.obligation(conn, invoice_id=inv, amount_minor=40000)
    issues = run_integrity_checks(conn)
    assert [i.code for i in issues] == ["invoice_invariant"]
    assert issues[0].message  # Hebrew


def test_invariant_holds_after_cancel_and_restructure_in_sql(conn):
    inv, (o1, o2, o3) = _spec_invoice(conn)
    f.pay(conn, o1, 15000)
    f.close(conn, o1, "restructured")
    f.obligation(conn, invoice_id=inv, amount_minor=12500, parent_id=o1)
    f.obligation(conn, invoice_id=inv, amount_minor=12500, parent_id=o1)
    f.pay(conn, o2, 10000)
    f.close(conn, o2, "canceled")
    assert run_integrity_checks(conn) == []
    totals = conn.execute("SELECT SUM(paid_minor), SUM(canceled_minor), SUM(outstanding_minor) "
                          "FROM v_obligation_balance WHERE invoice_id = ?", (inv,)).fetchone()
    assert tuple(totals) == (25000, 30000, 65000)
    assert sum(totals) == 120000


def test_restructure_children_mismatch_detected(conn):
    inv, (o1, _, _) = _spec_invoice(conn)
    f.close(conn, o1, "restructured")
    f.obligation(conn, invoice_id=inv, amount_minor=20000, parent_id=o1)  # should total 40000
    codes = {i.code for i in run_integrity_checks(conn)}
    assert "restructure_sum" in codes


def test_legacy_missing_amount_violation_detected(conn):
    """Data that predates the v2 triggers (simulated by dropping them) is flagged at startup."""
    conn.execute("DROP TRIGGER trg_obligation_missing_amount_insert")
    fixed = f.template(conn, amount_mode="fixed", fixed=10000)
    f.obligation(conn, amount_minor=None, template_id=fixed, period_key="2026-11")
    assert {i.code for i in run_integrity_checks(conn)} == {"missing_amount_rule"}


def test_pause_state_mismatch_detected(conn):
    tid = f.template(conn)
    conn.execute("INSERT INTO recurring_pauses (template_id, paused_on) VALUES (?, '2026-03-10')", (tid,))
    assert {i.code for i in run_integrity_checks(conn)} == {"pause_state"}
    conn.execute("UPDATE recurring_templates SET status = 'paused' WHERE id = ?", (tid,))
    assert run_integrity_checks(conn) == []
