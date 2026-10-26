"""Playwright E2E coverage for the dashboard: real clicks against the real
single-file SPA served by the real FastAPI app — offline, backed by fixtures.

Scenarios
---------
  1.  Overview KPIs render with fixture stats
  2.  Sidebar navigation switches views
  3.  Hash deep links open the right view directly
  4.  Meter Index filtering (status -> 90 faulty) and its footer counts
  5.  Detail slide-over opens with data and closes on Escape
  6.  Load curve renders the 48-interval chart + summary chips
  7.  Transformers browser lists all 40 DTs and drills into DT-001
  8.  Hierarchy tree nodes toggle expand/collapse
  9.  Live map draws proximity markers for the default radius
  10. Meter Index CSV export downloads the complete filtered set
  11. Load-curve CSV export mirrors the 48 readings (incl. kVAh)
"""

import pytest
from playwright.sync_api import expect


# -- 1. Overview -------------------------------------------------------------

def test_overview_kpis_render_with_fixture_stats(page, server_url):
    page.goto(server_url + "/")
    values = page.locator("#stat-grid .stat-value")
    expect(values.nth(0)).to_have_text("403")        # total meters
    expect(values.nth(1)).to_have_text("238")        # installed
    expect(values.nth(2)).to_have_text("90")         # faulty

    legend = page.locator("#status-legend")
    expect(legend).to_contain_text("Installed")
    expect(legend.first).to_contain_text("59.1%")    # 238 / 403

    expect(page.locator("#env-meter-count")).to_contain_text("403")


# -- 2. Sidebar navigation ---------------------------------------------------

def test_sidebar_navigation(page, server_url):
    page.goto(server_url + "/")
    for nav, attr in [
        ("Live Asset Map", "#view-map"),
        ("Load Curve", "#view-consumption"),
        ("Transformers", "#view-transformers"),
        ("Meter Index", "#view-meters"),
    ]:
        page.get_by_role("button", name=nav).click()
        expect(page.locator(attr)).to_be_visible()

    active = page.locator('.nav-item[aria-current="page"]')
    expect(active).to_have_text("Meter Index")


# -- 3. Deep links -----------------------------------------------------------

def test_hash_deep_link_opens_view(page, server_url):
    page.goto(server_url + "/#/meters")
    expect(page.locator("#view-meters")).to_be_visible()
    expect(page.locator("#meters-table-body tr").first).to_contain_text("J")  # real meter rows

    page.goto(server_url + "/#/transformers")
    expect(page.locator("#view-transformers")).to_be_visible()
    expect(page.locator("#dt-list .dt-row").first).to_be_visible()


# -- 4. Meter Index filtering ------------------------------------------------

def test_meter_index_status_filter_and_counts(page, server_url):
    page.goto(server_url + "/#/meters")
    expect(page.locator("#filter-count")).to_contain_text("403")  # full fleet loads

    page.select_option("#filter-status", "Faulty")
    expect(page.locator("#filter-count")).to_contain_text("90")
    expect(page.locator("#meters-table-body .pill-faulty").first).to_contain_text("Faulty")

    page.select_option("#filter-status", "")
    expect(page.locator("#filter-count")).to_contain_text("403")


# -- 5. Detail slide-over ----------------------------------------------------

def test_detail_slideover_opens_and_closes_on_escape(page, server_url):
    page.goto(server_url + "/#/meters")
    expect(page.locator("#meters-table-body tr").first).to_be_visible()

    page.locator("#meters-table-body").get_by_role("button", name="Details").first.click()
    slideover = page.locator("#slideover")
    expect(slideover).to_have_class("slideover open")
    expect(page.locator("#slideover-title")).to_contain_text("J")   # meter id in header
    expect(page.locator("#slideover-body .kv-list").first).to_be_visible()

    page.keyboard.press("Escape")
    expect(slideover).to_have_class("slideover")


# -- 6. Load curve -----------------------------------------------------------

def test_load_curve_renders_chart_and_summary(page, server_url):
    page.goto(server_url + "/#/consumption")
    expect(page.locator("#consumptionChart")).to_be_visible()
    expect(page.locator("#cons-summary")).to_contain_text("48")           # intervals
    expect(page.locator("#chart-title")).to_contain_text("J100000")
    expect(page.locator("#export-cons-btn")).to_be_enabled()


# -- 7. Transformers -----------------------------------------------------------

def test_transformers_list_and_dt_detail(page, server_url):
    page.goto(server_url + "/#/transformers")
    expect(page.locator("#dt-list .dt-row")).to_have_count(40)            # both portal pages

    page.locator("#dt-list .dt-row").first.click()
    expect(page.locator("#dt-meter-count")).to_have_text("10")            # DT-001 -> 10 meters
    expect(page.locator("#dt-stack")).to_be_visible()
    expect(page.locator("#dt-meters .meter-chip").first).to_contain_text("J")


# -- 8. Hierarchy tree ---------------------------------------------------------

def test_hierarchy_tree_toggles(page, server_url):
    page.goto(server_url + "/#/hierarchy")
    zone_row = page.locator("#hierarchy-tree-container .tree-row").first
    expect(zone_row).to_be_visible()

    expect(zone_row).to_have_attribute("aria-expanded", "true")
    zone_row.click()
    expect(zone_row).to_have_attribute("aria-expanded", "false")
    zone_row.click()
    expect(zone_row).to_have_attribute("aria-expanded", "true")


# -- 9. Live map ----------------------------------------------------------------

def test_live_map_draws_proximity_markers(page, server_url):
    page.goto(server_url + "/#/map")
    expect(page.locator("#map-count")).to_contain_text("meters within")   # not "Locating…"
    expect(page.locator("#map .leaflet-overlay-pane path").first).to_be_visible()


# -- 10. Meter CSV export -------------------------------------------------------

def test_meter_index_csv_export_full_set(page, server_url, tmp_path):
    page.goto(server_url + "/#/meters")
    expect(page.locator("#filter-count")).to_contain_text("403")          # fleet loaded

    with page.expect_download() as dl_info:
        page.click("#export-meters-btn")
    download = dl_info.value
    target = tmp_path / download.suggested_filename
    download.save_as(target)

    assert download.suggested_filename.startswith("meter-index-")
    lines = target.read_bytes().decode("utf-8-sig").split("\r\n")
    assert lines[0] == "Meter ID,Serial No,Make,Phase,Install Status,DT Code"
    assert len(lines) == 1 + 403                                          # header + full fleet
    assert any("J100000" in ln for ln in lines[1:])


# -- 11. Load-curve CSV export ---------------------------------------------------

def test_load_curve_csv_export(page, server_url, tmp_path):
    page.goto(server_url + "/#/consumption")
    expect(page.locator("#export-cons-btn")).to_be_enabled()

    with page.expect_download() as dl_info:
        page.click("#export-cons-btn")
    download = dl_info.value
    target = tmp_path / download.suggested_filename
    download.save_as(target)

    assert download.suggested_filename.startswith("load-curve-J100000")
    lines = target.read_bytes().decode("utf-8-sig").split("\r\n")
    assert lines[0] == "Timestamp,Active Energy (kWh),Apparent Energy (kVAh),Voltage R-Phase (V)"
    assert len(lines) == 1 + 48                                           # header + 48 intervals
