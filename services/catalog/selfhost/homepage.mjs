import { createHash } from 'node:crypto';

const style = `
:root{color-scheme:light;font-family:"Avenir Next","Helvetica Neue",Arial,sans-serif;color:#193f2b;background:#edf3ed;font-synthesis:none}
*{box-sizing:border-box}body{margin:0}a{color:inherit;text-underline-offset:5px}a:focus-visible{outline:3px solid #347550;outline-offset:6px}
.page{width:min(1080px,calc(100% - 80px));margin:auto}header{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:38px 0 64px}
.brand{display:flex;align-items:center;gap:13px;text-decoration:none;font-size:21px;font-weight:750;letter-spacing:-.6px}.brand span{font-size:14px;font-weight:500;letter-spacing:0;color:#42544b;border-left:1px solid #b9cabc;padding-left:13px}
.project{font-size:14px}.intro{display:grid;grid-template-columns:1.35fr 1fr;background:#fff;border:1px solid #d5e1d6;border-radius:28px;overflow:hidden}
.copy{padding:58px 50px 62px}h1{font-size:clamp(43px,5.6vw,66px);font-weight:650;line-height:1.06;letter-spacing:-3px;margin:0 0 27px;max-width:9em}
.description{font-size:18px;line-height:1.65;color:#42544b;max-width:30em;margin:0 0 32px}.action{display:inline-flex;align-items:center;min-height:48px;background:#193f2b;color:#fff;padding:12px 23px;border-radius:10px;text-decoration:none;font-size:15px;font-weight:650}
.action:hover{background:#2a5b3f}.sign-in{display:block;font-size:13px;color:#42544b;margin-top:12px}
aside{background:#193f2b;color:#edf3ed;padding:52px 38px;display:flex;flex-direction:column;justify-content:center}.preview{font-size:16px;font-weight:650;margin:0 0 14px;display:flex;align-items:center;gap:9px}.preview:before{content:"";width:8px;height:8px;background:#b3d9a4;border-radius:50%}
aside>p{font-size:15px;line-height:1.65;color:#d3e0d4;margin:0 0 32px}dl{margin:0}dl>div{display:flex;justify-content:space-between;gap:18px;padding:17px 0;border-top:1px solid #44644e;font-size:14px}dt{color:#c6d8c9}dd{margin:0;text-align:right;font-weight:600}
.boundary{display:grid;grid-template-columns:1fr 1fr;gap:40px;padding:34px 4px 38px}.boundary h2{font-size:16px;font-weight:650;margin:0 0 9px;letter-spacing:-.2px}.boundary p{font-size:14px;line-height:1.7;color:#42544b;margin:0;max-width:33em}
footer{display:flex;justify-content:space-between;gap:24px;border-top:1px solid #c8d7ca;padding:22px 4px 35px;color:#42544b;font-size:12px}footer nav{display:flex;gap:22px}
@media(max-width:760px){.page{width:calc(100% - 36px)}header{padding:25px 0 36px}.brand{font-size:19px;gap:10px}.brand span{font-size:12px;padding-left:10px}.project{font-size:12px}.intro{grid-template-columns:1fr;border-radius:22px}.copy{padding:34px 28px 38px}h1{letter-spacing:-2px;margin-bottom:22px}.description{font-size:16px;margin-bottom:26px}aside{padding:30px 28px}aside>p{margin-bottom:20px}.boundary{grid-template-columns:1fr;gap:24px;padding:29px 4px}footer{flex-direction:column;gap:15px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
`;

export const HOME_HEADERS = Object.freeze({
  'Content-Type': 'text/html; charset=utf-8',
  'Cache-Control': 'no-store',
  'Content-Security-Policy': `default-src 'none'; style-src 'sha256-${createHash('sha256').update(style).digest('base64')}'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
});

export const HOME_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#edf3ed">
<meta name="description" content="Kokiri’s shader compatibility catalog. View the protocol and follow the private testing stage.">
<title>Kokiri Shader Catalog</title>
<style>${style}</style>
</head>
<body>
<div class="page">
<header><a class="brand" href="/">Kokiri <span>Shader catalog</span></a><a class="project" href="https://github.com/christianfurr/Kokiri">Project source</a></header>
<main>
<section class="intro" aria-labelledby="title">
<div class="copy"><h1 id="title">A shared catalog for Kokiri.</h1><p class="description">Compatibility metadata for Kokiri’s shader and pipeline work. The catalog is currently in private testing.</p><a class="action" href="/v1/protocol">View protocol</a><span class="sign-in">Email sign-in required</span></div>
<aside aria-label="Catalog availability"><h2 class="preview">Private preview</h2><p>The service is being verified before the catalog opens for community use.</p><dl><div><dt>Access</dt><dd>Email sign-in</dd></div><div><dt>Contributions</dt><dd>Paused</dd></div><div><dt>Shared content</dt><dd>Metadata only</dd></div></dl></aside>
</section>
<section class="boundary" aria-label="About the catalog"><div><h2>Your files stay local.</h2><p>The catalog is designed for compatibility metadata. Game files, saves, and compiled shaders stay on your device.</p></div><div><h2>Follow the work.</h2><p>Read the <a href="https://github.com/christianfurr/Kokiri/blob/HEAD/docs/catalog/integration.md">catalog documentation</a> for the protocol, verification boundaries, and current development status.</p></div></section>
</main>
<footer><span>An independent, open-source Kokiri project.</span><nav aria-label="Project information"><a href="https://github.com/christianfurr/Kokiri/blob/HEAD/LICENSE">License</a><a href="https://github.com/christianfurr/Kokiri/blob/HEAD/THIRD_PARTY_NOTICES.md">Attribution</a></nav></footer>
</div>
</body>
</html>`;
