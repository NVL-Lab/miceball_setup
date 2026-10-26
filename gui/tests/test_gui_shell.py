from html.parser import HTMLParser
from pathlib import Path
import unittest


STATIC = Path(__file__).parents[1] / "src" / "miceball_gui" / "static"
SECTIONS = ("setup", "session", "parameters", "experiment", "analysis", "services")


class ShellParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.navigation = []
        self.panels = []
        self.pin_button = None
        self.section_title = None
        self.alerts_trigger = None
        self.alerts_panel = None
        self.theme_toggle = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "button" and "data-section" in values:
            self.navigation.append(values)
        if tag == "section" and "data-panel" in values:
            self.panels.append(values)
        if values.get("id") == "pin-button":
            self.pin_button = values
        if values.get("id") == "section-title":
            self.section_title = values
        if values.get("id") == "alerts-trigger":
            self.alerts_trigger = values
        if values.get("id") == "alerts-panel":
            self.alerts_panel = values
        if values.get("id") == "theme-toggle":
            self.theme_toggle = values


class GuiShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.css = (STATIC / "styles.css").read_text(encoding="utf-8")
        cls.javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.parser = ShellParser()
        cls.parser.feed(cls.html)

    def test_six_permanent_sections_have_navigation_and_workspaces(self):
        self.assertEqual(tuple(item["data-section"] for item in self.parser.navigation), SECTIONS)
        self.assertEqual(tuple(panel["data-panel"] for panel in self.parser.panels), SECTIONS)
        for item in self.parser.navigation:
            self.assertEqual(item["aria-controls"], f"panel-{item['data-section']}")
            self.assertIn("title", item)

    def test_shell_exposes_accessible_pin_and_selected_section_controls(self):
        self.assertEqual(self.parser.pin_button["aria-pressed"], "false")
        self.assertEqual(self.parser.pin_button["title"], "Pin sidebar")
        self.assertIsNotNone(self.parser.section_title)
        selected = [item for item in self.parser.navigation if item.get("aria-current") == "page"]
        self.assertEqual([item["data-section"] for item in selected], ["setup"])

    def test_sidebar_dimensions_and_pinned_workspace_behavior_are_explicit(self):
        self.assertIn("--sidebar-collapsed: 58px", self.css)
        self.assertIn("--sidebar-expanded: 205px", self.css)
        self.assertIn(".app-shell.is-pinned .workspace", self.css)
        self.assertIn("prefers-reduced-motion", self.css)

    def test_interaction_script_handles_navigation_pin_and_temporary_expansion(self):
        for behavior in (
            "function setSection(sectionId)",
            "function setPinned(pinned)",
            'sidebar.addEventListener("pointerenter"',
            'sidebar.addEventListener("pointerleave"',
            'document.addEventListener("pointerdown"',
            'item.addEventListener("keydown"',
        ):
            self.assertIn(behavior, self.javascript)

    def test_alert_indicator_and_panel_are_accessible_from_the_shell(self):
        self.assertEqual(self.parser.alerts_trigger["aria-expanded"], "false")
        self.assertEqual(self.parser.alerts_trigger["aria-controls"], "alerts-panel")
        self.assertEqual(self.parser.alerts_panel["role"], "dialog")
        self.assertEqual(self.parser.alerts_panel["aria-label"], "Warnings and errors")
        self.assertIn("hidden", self.parser.alerts_panel)
        self.assertLess(self.html.index('id="alerts"'), self.html.index('id="pin-button"'))
        self.assertIn('class="alerts__label">Warnings &amp; Errors</span>', self.html)
        self.assertIn('class="alerts__badge" id="alerts-badge"', self.html)
        self.assertIn('id="alerts-badge" aria-hidden="true" hidden', self.html)
        self.assertIn("bottom: 0", self.css)
        self.assertIn("left: calc(100% + 10px)", self.css)

    def test_demonstration_alerts_support_acknowledgment_restore_and_dismissal(self):
        for expected in (
            'source: "StorageManager"',
            'source: "AcquisitionNode"',
            'source: "Controller"',
            "function renderNotifications()",
            "function setAlertsPanelOpen(open, returnFocus = false)",
            'event.key === "Escape"',
            'restoreAlerts.addEventListener("click"',
            'acknowledgeNotification(button.dataset.notificationId)',
            "alertsBadge.hidden = totalCount === 0",
        ):
            self.assertIn(expected, self.javascript)

    def test_setup_screen_exposes_the_approved_two_column_workflow(self):
        for expected in (
            'class="setup-layout"',
            "Experimenter / Project / Animal",
            "Session name &amp; identity",
            "Session template selection",
            "Session notes",
            "Device selection",
            "Storage information",
            "Readiness summary",
            "Launch Session",
        ):
            self.assertIn(expected, self.html)
        self.assertIn("grid-template-columns: minmax(0, 1.15fr)", self.css)
        self.assertIn("@media (max-width: 1120px)", self.css)

    def test_catalog_demo_options_and_modal_workflow_are_available(self):
        for expected in (
            "New Experimenter...",
            "New Project...",
            "New Animal...",
            'id="catalog-dialog"',
            'title: "New Experimenter"',
            'title: "New Project"',
            'title: "New Animal"',
            "function openCatalogDialog(select)",
            'catalogDialog.close("save")',
        ):
            self.assertIn(expected, self.html + self.javascript)

    def test_catalog_dismiss_controls_do_not_submit_or_validate(self):
        self.assertEqual(self.html.count("type=\"button\" data-dialog-dismiss"), 2)
        self.assertIn('id="catalog-save"\n                type="submit" value="save"', self.html)
        self.assertIn('button.addEventListener("click", () => catalogDialog.close("cancel"))', self.javascript)
        self.assertIn('catalogDialog.returnValue = ""', self.javascript)

    def test_theme_control_and_browser_local_persistence_are_available(self):
        self.assertEqual(self.parser.theme_toggle["aria-pressed"], "false")
        self.assertLess(self.html.index('id="theme-toggle"'), self.html.index('id="alerts"'))
        for expected in (
            'data-theme="light"',
            'localStorage.getItem("miceball-theme")',
            "function setTheme(theme, persist = true)",
            'localStorage.setItem("miceball-theme"',
            'themeToggle.addEventListener("click"',
            'html[data-theme="dark"]',
            "color-scheme: dark",
        ):
            self.assertIn(expected, self.html + self.css + self.javascript)

    def test_services_list_and_warning_history_have_responsive_accessible_containers(self):
        view = (STATIC / 'services-view.js').read_text(encoding='utf-8')
        css = (STATIC / 'services-view.css').read_text(encoding='utf-8')
        for expected in ('class="service-row ', 'class="service-row-actions"',
                         'data-expand-service=', 'aria-expanded=', 'Check readiness',
                         'aria-label="Warning and error history" tabindex="0"',
                         'Acknowledged · retained in history', 'data-service-ack='):
            self.assertIn(expected, view)
        self.assertIn('.services-history { overflow: visible; }', css)
        self.assertNotIn('.services-history { max-height:', css)
        self.assertIn('data-toggle-history aria-controls="services-history"', view)
        self.assertIn("'Show less' : 'Show more'", view)
        self.assertIn('white-space: normal', css)
        self.assertIn('@media (max-width: 760px)', css)

    def test_services_administrator_entry_and_operation_review_are_separate(self):
        view = (STATIC / 'services-view.js').read_text(encoding='utf-8')
        for expected in ('Danger Zone — Administrator Mode', 'data-danger-cancel',
                         'Enter Administrator Mode', 'if (!model.administrator) return',
                         'aria-label="Administrative operations"',
                         'Selected-service administration', 'name="confirm-scope"',
                         'data-admin-review disabled', 'Record local scope review',
                         'Recovery execution is unavailable'):
            self.assertIn(expected, view)

    def test_session_stop_is_under_protocol_steps_without_fixture_selector(self):
        view = (STATIC / 'session-view.js').read_text(encoding='utf-8')
        self.assertNotIn('id="session-stop-scenario"', view)
        self.assertIn('class="stop-session-demo" data-stop-session>Stop Session', view)
        self.assertLess(view.index("}).join('')}</ol>"), view.index('class="stop-session-demo"'))

    def test_notification_history_includes_more_than_ten_fixtures_without_replacing_active_alerts(self):
        self.assertIn('Array.from({ length: 10 }', self.javascript)
        self.assertIn('acknowledged: true', self.javascript)
        self.assertIn('notifications = notifications.filter(item => item.id !== id)', self.javascript)
        self.assertIn('acknowledgedNotifications.has(item.id)', self.javascript)

if __name__ == "__main__":
    unittest.main()
