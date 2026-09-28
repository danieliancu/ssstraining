# SST Django clone — working notes

Django rebuild of the WordPress site in `..` (C:\xampp\htdocs\sst). Goal: pixel-identical output.

- venv: `.venv/Scripts/python`; settings `sst.settings.dev`; DB MySQL `sst_django` (XAMPP MariaDB 10.4 via `sst.db_mysql_legacy`).
- Source WP DB is `DATABASES['wordpress']` (read-only). Reimport: `python manage.py wp_import [steps]`.
- Reference HTML from WordPress: `tools/visual/golden/*.html` (captured by `tools/visual/golden.sh`); live WP at http://localhost/sst/.
- Dev server: `sh tools/restart_dev.sh [port]` (no autoreload — restart after Python/template changes).
- Parity checks (Git Bash needs `MSYS_NO_PATHCONV=1` for path args):
  - `python tools/visual/dom_diff.py /path/ [--golden name]` — normalised DOM diff vs WordPress
  - `python tools/visual/capture.py /path/ ...` — screenshots at 1440 and 375px + pixel diff (out/)
  - `SST_DJ_URL=http://127.0.0.1:8001` to point the tools at another dev server port.
- HTML responses are minified like Autoptimize (`apps/core/minify.py`), except /basket/ and /checkout*.
- Assets: `static/wp/` mirrors WP paths; per-page asset lists come from `apps/core/wp_assets.json` and
  `templates/wp_assets/<handle>.html` (regenerate with `python tools/extract_assets.py`). Pick the list with
  the `asset_profile` context var: default, home, shop, product_category, page_with_datepicker, product, basket, checkout.
- Shared helpers (don't duplicate): `apps/core/templatetags/wp.py` (wp_assets, nav_menu, breadcrumbs, seo_head,
  contact_form, wc_price, price_html, wpautop, texturize, wp_date, media_url), `apps/core/bodyclass.py`,
  `apps/core/views.wp_render`, `apps/seo/engine.Seo`.
- Contact forms (CF7): fields/labels/layout/validation are Django forms in `apps/contact/forms.py` (`FORMS` by CF7 id),
  rendered as CF7 markup by `templates/contact/cf7_form.html` + `widgets/`; `ContactForm` rows only hold mail settings
  and messages. CF7's JS talks to `apps/contact/views.py` (feedback/schema); reCAPTCHA v3 via django-recaptcha.
- Known intentional differences: privacy page omits WP's PHP warnings and fixes the empty mailto link.
