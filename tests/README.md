# UI checks

Free-service access, signup, upload and billing-retirement checks:

```powershell
& myenv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_free_service.py'
& myenv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_retire_billing.py'
```

See `docs/free-service.md` for the free-service behavior and legacy billing migration.

Trade integration and migration checks:

```powershell
& myenv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_trade*.py'
```

See `docs/trade-marketplace.md` for the local browser fixture and DB migration steps.

These checks render the real Jinja templates using synthetic data. They do not
import `app.py`, read `.env`, connect to the database, or invoke Firebase/Stripe.

Template checks (Jinja2 is already an application dependency):

```powershell
python -m unittest discover -s tests -p test_design_templates.py
```

Optional browser checks require Flask and Playwright:

```powershell
python -m pip install playwright
python -m playwright install chromium
python tests/check_design_browser.py
```

Screenshots and the JSON results go to `%TEMP%/spcolle-design-review`. Use
`--output DIRECTORY` to choose another location, or `--browser PATH` to use an
existing Chromium executable. The suite checks narrow/wide layouts, dark mode,
JavaScript errors, page overflow, navigation, keyboard access, detail modals,
search suggestions, and the public DB filter. Auth and analytics requests are
blocked; all fixture API calls are local. Real login, uploads, billing, and data
updates need a separate integration check in a test environment.
