#!/usr/bin/env python3
"""Capture a screenshot walkthrough of a running Souq Connect instance.

Reproduces the same walkthrough used to build the Souq Connect Field Guide:
branch configuration, a COD sale order, its delivery, invoice (clearing
account + ZATCA QR), the driver's cash collection, the settlement that
posts the balanced journal entry, and a driver user's access rights.

Requirements
------------
    pip install playwright
    playwright install chromium

Usage
-----
    python scripts/take_screenshots.py \
        --url http://localhost:8069 \
        --db souq_demo \
        --login admin \
        --password admin \
        --out screenshots

Every step is best-effort: if the record it needs doesn't exist yet
(e.g. no COD order has been invoiced yet), that step is skipped with a
warning instead of failing the whole run. Run through the flow manually
once (or via the module's own tests) before running this script if you
want the full set.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from playwright.sync_api import Page, sync_playwright
except ImportError:  # pragma: no cover
    sys.exit(
        "Playwright is not installed. Run:\n"
        "    pip install playwright\n"
        "    playwright install chromium"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8069",
                         help="Base URL of the running Odoo instance")
    parser.add_argument("--db", required=True, help="Database name")
    parser.add_argument("--login", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--out", default="screenshots",
                         help="Output directory for the .png files")
    parser.add_argument("--headed", action="store_true",
                         help="Show the browser window instead of running headless")
    return parser.parse_args()


def settle(page: Page, timeout_ms: int = 2000) -> None:
    """Wait for a navigation to settle, then clear any stray dialog.

    Odoo keeps a long-polling bus connection open at all times, so
    ``wait_for_load_state("networkidle")`` never fires and just times
    out. Waiting for DOM content plus a short fixed pause is what
    actually works against a live Odoo web client.

    A background action (e.g. a report trying to render a PDF thumbnail
    on a system with no wkhtmltopdf installed) can pop an unrelated
    error dialog that then blocks every later click. Dismiss it so one
    environment quirk doesn't take down the rest of the walkthrough.
    """
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(timeout_ms)
    close_btn = page.locator(".o_technical_modal .btn-close, .o_error_dialog .btn-close")
    if close_btn.count():
        close_btn.first.click()
        page.wait_for_timeout(300)
    # Clears any lingering hover popover (e.g. the avatar card that
    # appears over a Salesperson cell) that would otherwise intercept
    # the next click.
    page.keyboard.press("Escape")
    page.mouse.move(0, 0)


def visible_text(page: Page, text: str, exact: bool = False):
    """Return the first *visible, clickable* control containing ``text``.

    Odoo leaves invisible smart buttons and tabs in the DOM (toggled via
    an ``invisible`` attribute rather than removed) inside a wrapping
    container - e.g. ``.o_statusbar_buttons`` - that itself stays
    visible. A plain ``get_by_text(...)`` match can land on that
    wrapper (whose aggregate text content includes the hidden button's
    label) and report it as visible even though the actual button a
    user would see and click is not. Restricting the search to real
    controls (buttons, links, tabs) and checking *that* element's own
    visibility is what actually tells a present control from an absent
    one.
    """
    controls = page.locator("button, a, .nav-link, .o_stat_button")
    loc = controls.filter(has_text=text)
    for i in range(loc.count()):
        candidate = loc.nth(i)
        label = candidate.inner_text().strip()
        if exact and label != text:
            continue
        if candidate.is_visible():
            return candidate
    return None


def login(page: Page, base_url: str, db: str, login: str, password: str) -> None:
    page.goto(f"{base_url}/web/login")
    settle(page)
    # Multi-database selector, only shown if more than one DB exists.
    db_field = page.locator("input[name='db']")
    if db_field.count() and db_field.is_visible():
        db_field.fill(db)
    page.fill("input[name='login']", login)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")
    settle(page)


def shoot(page: Page, out_dir: Path, name: str, wait_ms: int = 1200) -> None:
    """Best-effort screenshot: wait for the SPA to settle, then capture."""
    page.wait_for_timeout(wait_ms)
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"  saved {path}")


def try_step(label: str, fn) -> None:
    print(f"-> {label}")
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - best-effort walkthrough
        print(f"   skipped ({exc.__class__.__name__}: {exc})")


def run(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        print("Logging in...")
        login(page, args.url, args.db, args.login, args.password)

        def branches():
            page.goto(f"{args.url}/odoo/action-souq.action_souq_branch")
            settle(page)
            first_row = page.locator(".o_data_row").first
            if first_row.count():
                first_row.click()
                settle(page)
            shoot(page, out_dir, "01_branch_config")

        def settings():
            page.goto(f"{args.url}/odoo/settings")
            settle(page)
            souq_tab = visible_text(page, "Souq Connect", exact=True)
            if souq_tab:
                souq_tab.click()
                settle(page)
            shoot(page, out_dir, "02_settings_surcharge")

        state = {"order_url": None}

        def sale_orders():
            page.goto(f"{args.url}/odoo/sales")
            settle(page)
            shoot(page, out_dir, "03_quotations_list")

            rows = page.locator(".o_data_row")
            row_count = rows.count()
            if not row_count:
                raise RuntimeError("no sale orders found")

            # Prefer an order that actually has an invoice, so the
            # invoice/QR step further down has something to show - the
            # most recently created order (row 0) may well be a fresh
            # one with nothing posted against it yet.
            for i in range(row_count):
                rows.nth(i).click()
                settle(page)
                if visible_text(page, "Invoices", exact=False):
                    break
                page.goto(f"{args.url}/odoo/sales")
                settle(page)
                rows = page.locator(".o_data_row")
            else:
                raise RuntimeError("no sale order with an invoice found")

            shoot(page, out_dir, "04_order_detail")
            state["order_url"] = page.url

        def delivery():
            delivery_btn = visible_text(page, "Delivery", exact=False)
            if not delivery_btn:
                raise RuntimeError("no Delivery smart button on this order")
            delivery_btn.click()
            settle(page)
            shoot(page, out_dir, "05_delivery")

        def invoice(order_url: str):
            page.goto(order_url)
            settle(page)
            inv_btn = visible_text(page, "Invoices", exact=False)
            if not inv_btn:
                raise RuntimeError("no Invoices smart button on this order")
            inv_btn.click()
            settle(page)
            # A COD order can carry more than one invoice (e.g. a
            # cancelled down payment alongside the real one) - the smart
            # button then opens a list instead of jumping to the form.
            if page.locator(".o_list_view").count():
                row = page.locator(".o_data_row").last
                if not row.count():
                    raise RuntimeError("Invoices list has no rows")
                row.click()
                settle(page)
            shoot(page, out_dir, "06_invoice")

            qr_tab = visible_text(page, "E-Invoice", exact=False)
            if qr_tab:
                qr_tab.click()
                settle(page)
                shoot(page, out_dir, "07_einvoice_qr")

        def cod_collections():
            page.goto(f"{args.url}/odoo/action-souq.action_souq_cod_collection")
            settle(page)
            shoot(page, out_dir, "08_cod_collections_list")

            row = page.locator(".o_data_row").first
            if row.count():
                row.click()
                settle(page)
                shoot(page, out_dir, "09_collection_detail")

        def settlements():
            page.goto(f"{args.url}/odoo/action-souq.action_souq_driver_settlement")
            settle(page)
            shoot(page, out_dir, "10_settlements_list")

            row = page.locator(".o_data_row").first
            if row.count():
                row.click()
                settle(page)
                shoot(page, out_dir, "11_settlement_detail")

        def users():
            page.goto(f"{args.url}/odoo/settings/users")
            settle(page)
            row = page.locator(".o_data_row").last
            if not row.count():
                raise RuntimeError("no users found")
            row.click()
            settle(page)
            groups_tab = visible_text(page, "Access Rights", exact=True)
            if groups_tab:
                groups_tab.click()
            page.mouse.wheel(0, 1400)
            shoot(page, out_dir, "12_user_access_rights")

        try_step("Branch configuration", branches)
        try_step("Souq Connect settings", settings)
        try_step("Sale orders", sale_orders)
        try_step("Delivery", delivery)
        if state["order_url"]:
            try_step("Invoice + QR", lambda: invoice(state["order_url"]))
        try_step("COD collections", cod_collections)
        try_step("Driver settlements", settlements)
        try_step("User access rights", users)

        browser.close()

    print(f"\nDone. Screenshots saved to {out_dir.resolve()}")


if __name__ == "__main__":
    run(parse_args())
