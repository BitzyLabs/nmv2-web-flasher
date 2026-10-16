// The site is one page, so the sitemap is one URL with one honest date:
// the commit that produced this build. Deterministic per commit, which
// keeps rebuilds of the same tree byte-identical. The build script runs
// this before `next build`, so every deploy -- the firmware bot's too --
// refreshes the date the crawlers are told about.
import { execSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const HOST = 'https://flasher.bitzylabs.com';

let lastmod;
try {
  lastmod = new Date(
    execSync('git log -1 --format=%cI').toString().trim()
  ).toISOString();
} catch {
  // No git around (never true on a machine that builds this site):
  // now beats a sitemap with no date on it.
  lastmod = new Date().toISOString();
}

writeFileSync(
  'public/sitemap.xml',
  `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${HOST}/</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
`
);
