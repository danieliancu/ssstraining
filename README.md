# Site Safety Training — Django

Django rebuild of the WordPress/WooCommerce site sstcourses.co.uk. The front end reproduces the
WordPress theme (`twentyseventeen-child`) markup and assets, so pages render the same; courses
come from ManageMyCourses (MMC), payments go through Stripe, email through Brevo's HTTP API.

## Local setup (Windows / XAMPP)

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env                  # then fill in keys (see below)
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py wp_import          # copy content from the WordPress DB + uploads
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver
```

XAMPP ships MariaDB 10.4, older than Django 5.2 supports; `.env` selects `sst.db_mysql_legacy`,
which only relaxes the version check. Production uses MySQL 8 — remove `DATABASE_ENGINE` there.

## Importing from WordPress

`manage.py wp_import [media options terms content render products menus forms orders redirects]`
reads the WordPress database configured as `WP_DATABASE_URL` (read-only) and is safe to re-run.
`render` runs `tools/wp_render.php` with PHP so page bodies get WordPress's own formatting.
Lorem-ipsum placeholder news items are skipped; MMC/Stripe secrets are never imported.

## Courses (MMC)

| Command | When |
|---|---|
| `mmc_sync --sessions` | cron every 15 min (sessions → products, same titles/SKUs/prices/attributes as the WP plugin) |
| `mmc_sync --nvq` | cron every 6 h |
| `mmc_sync --dry-run` | report only |
| `mmc_test_connection` | check credentials |
| `mmc_retry_bookings` | cron every 10 min: resend failed bookings |
| `mmc_prune_logs` | daily |

Webhook URL for MMC: `https://sstcourses.co.uk/wp-json/mmc-wc/v1/webhook` (same path as WordPress).
Settings, sync buttons, logs and webhook replay: Admin → MMC settings.

## Checkout

Basket and checkout keep WooCommerce's markup and JavaScript. Card payments use the Stripe Payment
Element; a Stripe webhook must point to `/stripe/webhook/` (events: `payment_intent.succeeded`,
`payment_intent.payment_failed`, `charge.refunded`). After payment each delegate is booked in MMC
(`POST /bookings`), then the customer and admin emails are sent. Without Stripe keys the checkout
shows "no available payment methods", like the WordPress clone does.

## Environment (.env)

See `.env.example`. Secrets: `DJANGO_SECRET_KEY`, `MMC_CLIENT_ID`, `MMC_CLIENT_SECRET`,
`MMC_WEBHOOK_SECRET` (**rotate it** — the old default was hard-coded in the WP plugin),
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `BREVO_API_KEY`, `RECAPTCHA_SECRET_KEY`.

## Checking parity with WordPress

```sh
sh tools/restart_dev.sh                                   # dev server on :8000
MSYS_NO_PATHCONV=1 python tools/visual/dom_diff.py /contact-us/ --golden contact
MSYS_NO_PATHCONV=1 python tools/visual/capture.py --all  # screenshots + pixel diff at 1440/375px
python manage.py test
```

`tools/visual/golden/` holds HTML captured from the WordPress site (`tools/visual/golden.sh`).
`tools/extract_assets.py` rebuilds `static/wp/` and the per-page asset lists from those files.

## Deploy (Forge / DigitalOcean)

`deploy/` has the nginx snippet, the gunicorn systemd unit, the cron list and the Forge deploy
script. DigitalOcean blocks outbound SMTP, so set `EMAIL_BACKEND=apps.emails.backends.BrevoEmailBackend`.
