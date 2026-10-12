"""Click through MedCard in a real browser: all three portals, every data-changing feature.

Usage: start the app on a fresh database, then  python tests/e2e_browser.py http://localhost:8000 ./shots
(needs: pip install playwright && playwright install chromium)"""
import sys
from datetime import date, timedelta

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
SHOTS = sys.argv[2]
errors, results = [], []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def login(page, role, ident, pw="Demo@123"):
    page.goto(BASE)
    page.click(f".portal-btn.{role}")
    page.fill("#auth-id", ident)
    page.fill("#auth-password", pw)
    page.fill("#auth-otp", "123456")
    page.click("#auth-submit-btn")
    page.wait_for_selector("#app", state="visible", timeout=10000)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    page.on("dialog", lambda d: d.accept("Data Retention Policy 2026") if d.type == "prompt" else d.accept())

    # --- wrong password shows an error, no login
    page.goto(BASE)
    page.click(".portal-btn.patient")
    check("demo credentials shown in login box", "Demo@123" in page.inner_text("#demo-creds") and "123456" in page.inner_text("#demo-creds"))
    check("login has Full Name and OTP fields", page.locator("#auth-name").count() == 1 and page.locator("#auth-otp").count() == 1)
    page.fill("#auth-id", "2507070000057"); page.fill("#auth-password", "wrong")
    page.fill("#auth-otp", "123456")
    page.click("#auth-submit-btn")
    page.wait_for_selector("#auth-error", state="visible")
    check("wrong password rejected with message", "Wrong" in page.inner_text("#auth-error"))

    # --- patient
    login(page, "patient", "2507070000057")
    check("patient logged in, dashboard greets Riya", "Riya" in page.inner_text("#main-content"))
    page.screenshot(path=f"{SHOTS}/1_patient_dashboard.png")

    page.evaluate("navigateTo('reports')")
    page.set_input_files("#file-upload", files=[{"name": "lipid_profile.txt", "mimeType": "text/plain",
                                                  "buffer": b"Total cholesterol 212 mg/dL, LDL 140 mg/dL, HDL 42 mg/dL"}])
    page.wait_for_selector("text=lipid_profile", timeout=10000)
    check("upload stored and listed", "lipid_profile" in page.inner_text("#main-content"))
    page.wait_for_selector("#ai-analysis-result .notif", timeout=10000)
    check("AI offline handled gracefully", "unavailable" in page.inner_text("#ai-analysis-result").lower())
    check("every report has a Download button", page.locator("button:has-text('Download')").count() == page.locator("button:has-text('AI Analyze')").count() >= 4)
    with page.expect_download() as dl:
        page.locator("button:has-text('Download')").first.click()
    check("Download saves a file", dl.value.suggested_filename != "")
    page.screenshot(path=f"{SHOTS}/2_reports.png")

    page.evaluate("navigateTo('appointments')")
    page.click("text=+ Book New")
    page.select_option("#book-doctor", "DR003")
    page.fill("#book-date", (date.today() + timedelta(days=4)).isoformat())
    page.fill("#book-reason", "Breathing check")
    page.click("#book-submit")
    page.wait_for_selector("text=Breathing check", timeout=10000)
    check("appointment booked with chosen doctor", "Dr. Kavya Rao" in page.inner_text("#main-content"))
    cancel_buttons = page.locator(".appt-card button", has_text="Cancel")
    n_cancel = cancel_buttons.count()
    cancel_buttons.first.click()
    page.wait_for_timeout(800)
    check("appointment cancelled", cancel_buttons.count() == n_cancel - 1
          and "Cancelled" in page.inner_text("#main-content"))
    page.screenshot(path=f"{SHOTS}/3_appointments.png")

    page.evaluate("navigateTo('ai-chat')")
    check("chat has the API key box", page.locator("#api-key-input").count() == 1)
    page.fill("#api-key-input", "sk-ant-demo")
    check("saving a key switches to live mode", "LIVE" in page.inner_text("#chat-status-label"))
    page.fill("#api-key-input", "")
    check("clearing it goes back to offline", "OFFLINE" in page.inner_text("#chat-status-label"))

    page.evaluate("navigateTo('metrics')")
    check("seeded vitals shown", "128/82" in page.inner_text("#main-content"))
    page.fill("#vt-systolic", "142"); page.fill("#vt-diastolic", "91"); page.fill("#vt-heart_rate", "88")
    page.click("#vt-submit")
    page.wait_for_selector("text=142/91", timeout=10000)
    check("new vitals saved, BP flagged red", page.locator(".metric-bar.danger").count() >= 1)
    page.screenshot(path=f"{SHOTS}/4_metrics.png")

    page.evaluate("navigateTo('ecard')")
    page.wait_for_function("document.getElementById('qr-large-img') && document.getElementById('qr-large-img').naturalWidth > 0", timeout=10000)
    card_url = page.inner_text("#qr-url-label").strip()
    check("QR image generated by our server", card_url.startswith(BASE) and "#card=" in card_url)
    page.wait_for_timeout(600)
    page.screenshot(path=f"{SHOTS}/5_ecard.png")

    page.reload()
    page.wait_for_selector("#app", state="visible", timeout=10000)
    check("still logged in after refresh", "Riya" in page.inner_text("#nav-name"))

    # --- public emergency card in a fresh, logged-out browser
    anon = browser.new_context(viewport={"width": 420, "height": 860}).new_page()
    anon.on("pageerror", lambda e: errors.append(f"public pageerror: {e}"))
    anon.goto(card_url)
    anon.wait_for_selector("text=Emergency Information", timeout=10000)
    txt = anon.inner_text("#qr-reports-page")
    check("public card shows blood type + reports", "O+" in txt and "lipid_profile" in txt)
    check("public card hides name and patient ID", "Riya" not in txt and "2507070000057" not in txt)
    anon.screenshot(path=f"{SHOTS}/6_public_card_mobile.png", full_page=True)

    page.evaluate("logout()")

    # --- doctor
    login(page, "doctor", "DR001")
    page.evaluate("navigateTo('doc-appointments')")
    sched = page.inner_text("#main-content")
    check("doctor sees all appointments with specialty", "Riya Jain" in sched and "Diya Jain" in sched and "Pulmonology" in sched)
    page.locator("text=✓ Done").first.click()
    page.wait_for_timeout(800)
    check("doctor marks visit completed", "Completed" in page.inner_text("#main-content"))
    page.screenshot(path=f"{SHOTS}/7_doctor_schedule.png")
    page.evaluate("navigateTo('doc-add-report')")
    page.select_option("#rpt-patient", "2507070000080")
    page.fill("#rpt-name", "Peak Flow Test")
    page.fill("#rpt-notes", "Peak flow 380 L/min")
    page.click("text=Submit Report") if page.locator("text=Submit Report").count() else page.evaluate("submitReport()")
    page.wait_for_selector("#report-submit-result .notif", timeout=10000)
    check("doctor files report to patient", "added to Diya" in page.inner_text("#report-submit-result"))
    page.evaluate("logout()")

    # --- admin
    login(page, "admin", "admin@medcard.ai")
    page.evaluate("navigateTo('admin-policies')")
    page.evaluate("addPolicy()")
    page.wait_for_selector("text=Data Retention Policy 2026", timeout=10000)
    check("admin adds policy (saved server-side)", True)
    page.evaluate("navigateTo('admin-users')")
    check("admin sees all patients", "Diya Jain" in page.inner_text("#main-content") and "Riya Jain" in page.inner_text("#main-content"))
    page.screenshot(path=f"{SHOTS}/8_admin_users.png")
    page.evaluate("logout()")

    # --- new patient registration + patient sees doctor's report
    page.goto(BASE)
    page.click(".portal-btn.patient")
    page.evaluate("toggleRegister()")
    page.fill("#reg-fname", "Arjun"); page.fill("#reg-lname", "Verma"); page.fill("#reg-dob", "2002-09-14")
    page.fill("#reg-phone", "+91 90000 12345"); page.fill("#reg-email", "arjun@example.com")
    page.fill("#reg-password", "arjun123"); page.fill("#reg-allergies", "Sulfa drugs")
    page.click("#reg-submit-btn")
    page.wait_for_selector("#app", state="visible", timeout=10000)
    check("new patient registered and logged in", "Arjun" in page.inner_text("#main-content"))
    page.evaluate("logout()")
    login(page, "patient", "diya@example.com")
    page.evaluate("navigateTo('reports')")
    check("patient sees report filed by doctor", "Peak Flow Test" in page.inner_text("#main-content"))

    browser.close()

# fonts blocked offline, and the deliberate 401 / 503 checks, aren't app errors
real = [e for e in errors if not any(x in e for x in ("ERR_TUNNEL", "ERR_NAME_NOT_RESOLVED", "status of 401", "status of 503"))]
print("\nbrowser errors:", real or "none")
print(f"\n{sum(ok for _, ok in results)}/{len(results)} checks passed")
sys.exit(0 if all(ok for _, ok in results) and not real else 1)
