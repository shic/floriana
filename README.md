# Floriana Celani static site

This repository contains a static export of the WordPress site at
`https://florianacelani.com/`, ready to deploy with GitHub Pages.

## Structure

- `public/` is the generated static website published by GitHub Pages.
- `scripts/export_static.py` refreshes `public/` from the live WordPress site.
- `scripts/validate_static.py` checks generated pages and local resource links.
- `.github/workflows/deploy.yml` deploys `public/` through GitHub Actions.

## Refresh the export

```bash
python3 scripts/export_static.py
python3 scripts/validate_static.py
```

Preview locally:

```bash
python3 -m http.server 4173 --directory public
python3 scripts/validate_static.py --base-url http://127.0.0.1:4173
```

## GitHub Pages setup

1. Push this repository to GitHub.
2. In GitHub, open Settings -> Pages.
3. Set Build and deployment -> Source to "GitHub Actions".
4. Add the custom domain `florianacelani.com` in the Pages settings.
5. Point DNS for `florianacelani.com` at GitHub Pages:

   ```text
   @     A      185.199.108.153
   @     A      185.199.109.153
   @     A      185.199.110.153
   @     A      185.199.111.153
   @     AAAA   2606:50c0:8000::153
   @     AAAA   2606:50c0:8001::153
   @     AAAA   2606:50c0:8002::153
   @     AAAA   2606:50c0:8003::153
   www   CNAME  shic.github.io
   ```

   If the domain's nameservers are Cloudflare, make these changes in
   Cloudflare DNS and set the records to "DNS only" until GitHub Pages finishes
   its certificate check. A proxied Cloudflare record returns Cloudflare IPs
   instead of GitHub Pages IPs, which prevents GitHub Pages from validating the
   custom domain.

   Remove the old apex and `www` `A` records that point to the WordPress host
   before adding the GitHub Pages records. DNS changes can take up to 24 hours.

The export includes `public/CNAME` for branch-based Pages compatibility, but the
workflow deployment still needs the custom domain configured in GitHub Pages.

## Static form behavior

The original Contact page used WordPress/Avada AJAX forms. Static hosting cannot
run `admin-ajax.php`, so `public/assets/floriana-static.js` changes form
submission into a `mailto:` flow to `celanifloriana@gmail.com`. Replace that
with Formspree, Netlify Forms, or another hosted form endpoint if a real inbox
submission service is needed.
