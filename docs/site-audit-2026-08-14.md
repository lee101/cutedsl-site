# CuteDSL site audit — 2026-08-14

## Production baseline

Audited `https://cutedsl.cc/gallery` with the local `seoaudit` and `webvitals`
utilities plus Lighthouse. The browser-based Python tools were run with the
compatible Python 3.13 environment because their default launcher mixed a
Python 3.9 process with Python 3.13 Playwright packages.

| Metric | Desktop | Mobile |
|---|---:|---:|
| Median LCP (3 runs) | 2.15 s | 2.50 s |
| Median FCP (3 runs) | 472 ms | 468 ms |
| Median TTFB (3 runs) | 222 ms | 225 ms |
| Median CLS (3 runs) | 0.0000 | 0.0003 |

Lighthouse scores: Performance 92, Accessibility 94, Best Practices 100,
SEO 100. Its main findings were borderline mobile LCP, unnecessary initial
image work, insufficient contrast on inline code, duplicated accessible image
text, and missing social images on some secondary pages.

## Image index validation

- `/sitemap.xml`, page/tag maps, and all sampled image maps return HTTP 200,
  `application/xml`, and gzip encoding.
- The sitemap index currently exposes 19 image sitemap shards.
- The final shard parses as valid XML and contains 39,477 URL/image pairs.
- Every sampled image entry has an image location.
- Image entries now include database-backed `lastmod` timestamps to help
  crawlers schedule recrawls efficiently.

## Improvements implemented

- Reduced the initial gallery batch from 96 to 60 items.
- Reduced eager image loading from 12 to 4 and high-priority requests from 6
  to 2, so fewer thumbnails compete with the LCP resource.
- Deferred autocomplete frequency loading and sorting until the search field
  receives focus.
- Added short browser/edge caching with stale-while-revalidate for public
  gallery and image-count JSON.
- Removed duplicated accessible overlay text and corrected inline-code color
  contrast.
- Shortened overlong gallery/evals descriptions.
- Added Open Graph and Twitter images to search, evals, and the server-rendered
  tags index.
- Added `lastmod` to image sitemap entries.

## Validation

- Frontend ESLint: pass
- Next.js production build and type checking: pass
- Go test suite: pass
- Local static SEO audit for gallery, search, and evals: 0 issues
- `git diff --check`: pass

## Follow-up measurement

Repeat the three-run mobile and desktop Web Vitals tests after deployment.
Production-only before/after LCP cannot be measured accurately from the local
frontend because gallery data and images depend on the production database and
image service. The next infrastructure-level image optimization would be a
smaller responsive thumbnail derivative (roughly 128–192 px) and a dedicated
40–80 px logo asset; Lighthouse estimated image-delivery savings beyond what
markup-only changes can achieve.
