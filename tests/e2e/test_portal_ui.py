"""End-to-end UI tests for the portal, driven by Playwright."""

import pytest

pytestmark = pytest.mark.e2e


def test_portal_loads_and_shows_user(page, base_url):
    page.goto(f"{base_url}/app01/")
    assert page.title() == "社内ポータル"
    # /api/me makes the admin tab visible for FileAdmin users.
    page.wait_for_selector("#adminTabBtn:visible")
    assert "tester@example.com" in page.inner_text("#user")


def test_tab_navigation(page, base_url):
    page.goto(f"{base_url}/app01/")
    page.click("nav button[data-tab='announce']")
    assert page.locator("#announce").is_visible()
    assert not page.locator("#home").is_visible()


def test_release_notes_render_newest_first(page, base_url):
    page.goto(f"{base_url}/app01/")
    page.click("nav button[data-tab='announce']")
    page.wait_for_selector(".release-note")

    notes = page.locator(".release-note")
    assert notes.count() == 2
    assert "2026-08-20" in notes.nth(0).inner_text()
    assert "最新のお知らせ" in notes.nth(0).inner_text()
    assert "2026-08-01" in notes.nth(1).inner_text()


def test_admin_files_render_and_search(page, base_url):
    page.goto(f"{base_url}/app01/")
    page.click("#adminTabBtn")
    page.wait_for_selector("#fileBody tr")
    assert page.locator("#fileBody tr").count() == 2
    page.fill("#search", "setup")
    assert page.locator("#fileBody tr").count() == 1
    assert "setup.pdf" in page.inner_text("#fileBody")


def test_delete_with_confirm(page, base_url):
    page.goto(f"{base_url}/app01/")
    page.click("#adminTabBtn")
    page.wait_for_selector("#fileBody tr")
    page.on("dialog", lambda d: d.accept())
    page.locator("#fileBody button.act").first.click()
    page.wait_for_timeout(200)


def test_health_check_page(page, base_url):
    page.goto(f"{base_url}/app01/health_check.html")
    page.wait_for_selector("#api.ok")
    assert page.locator("#api").get_attribute("class") == "dot ok"
