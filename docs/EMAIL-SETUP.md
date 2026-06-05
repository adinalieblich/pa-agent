# Email setup — `hello@adinalieblich.com`

The portfolio site, cinematic v2 page, all 6 concepts, and the README concept all link `mailto:hello@adinalieblich.com`. That address is **not currently receiving mail**. This doc walks through wiring it up via Cloudflare Email Routing — free, ~5 minutes, no card needed.

## Why Cloudflare

- Free (no card, no trial)
- Forwards to your real inbox (Gmail) — you read + reply from there
- No DNS expertise needed — Cloudflare does the SPF/DKIM/MX records for you
- Recipient address can be anything: `hello@`, `adina@`, `me@` — all forward to the same Gmail
- LinkedIn / recruiters see a professional domain address, not your personal Gmail

## Setup (5 min)

### 1. Move DNS to Cloudflare (if not already)
You can check at https://dash.cloudflare.com/ — log in, look for `adinalieblich.com` in your sites. If it's there, skip to step 2.

If it's not:
1. https://dash.cloudflare.com/ → Add site → enter `adinalieblich.com`
2. Pick the Free plan
3. Cloudflare will show you 2 nameservers (looks like `ns1.cloudflare.com` / `ns2.cloudflare.com`)
4. At your domain registrar (probably GoDaddy / Namecheap), change the nameservers to the Cloudflare ones
5. Wait 5-30 min for propagation
6. Cloudflare emails you "site is active" when done

**Note**: changing nameservers may briefly affect your existing DNS records (the ones pointing app.adinalieblich.com, vote.*, demo.* at AWS). Cloudflare imports them automatically but verify after the switch that those subdomains still resolve.

### 2. Enable Email Routing
1. In Cloudflare dashboard → click `adinalieblich.com`
2. Left sidebar → **Email** → **Email Routing**
3. Click **Get Started** / **Enable**
4. Cloudflare will auto-add the necessary MX + TXT (SPF) records — accept them
5. Wait ~1 min for the records to propagate

### 3. Add the forwarding rule
1. In Email Routing → **Routes** tab
2. Click **Create address**
3. Custom address: `hello`
4. Action: **Send to an email**
5. Destination: your Gmail (e.g. `adinalieblich@gmail.com`)
6. Save

### 4. Verify destination
- Gmail will get a "verify this destination" email from Cloudflare
- Click the link
- Done

### 5. Test it
Send a test email from your phone to `hello@adinalieblich.com`. Should land in your Gmail inbox within ~30 seconds.

## Optional — catch-all

In Email Routing → **Routes** → **Catch-all address** → set to forward to your Gmail. Then `anything@adinalieblich.com` works (`adina@`, `me@`, `engineer@`, etc). Useful for giving different addresses for different contexts (e.g. `careers@` on LinkedIn).

## What lives where (after setup)

| Address | Where it appears | Goes to |
|---|---|---|
| `hello@adinalieblich.com` | Portfolio contact section, all 6 concept pages, cinematic v2 | Your Gmail |
| `mailto:` links | Every concept's contact CTA | Triggers your default mail app to compose |

## If you want to change the address

Just edit the 9 files where it appears:

```bash
grep -rn "hello@adinalieblich.com" pwa-v2/public/
```

Files (as of this writing):
- `pwa-v2/public/concepts/brutalist.html`
- `pwa-v2/public/concepts/editorial.html`
- `pwa-v2/public/concepts/gallery.html`
- `pwa-v2/public/concepts/terminal.html`
- `pwa-v2/public/concepts/readme.html`
- `pwa-v2/public/portfolio-preview.html`

Sed one-liner if you want to rename to `adina@adinalieblich.com`:
```bash
find pwa-v2/public -name "*.html" -exec sed -i 's/hello@adinalieblich.com/adina@adinalieblich.com/g' {} \;
```

Then add the new prefix to Cloudflare Email Routing → Routes.

---

## TL;DR

5 steps to working email at `hello@adinalieblich.com`:
1. Site on Cloudflare ✓
2. Enable Email Routing ✓
3. Add `hello` → your Gmail rule ✓
4. Verify Gmail destination ✓
5. Test ✓

No code change needed on the portfolio. The address already works in HTML.
