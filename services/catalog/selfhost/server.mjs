import { createServer } from 'node:http';
import { readFileSync, realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import worker from '../src/worker.ts';
import { CatalogDatabase } from './database.mjs';
import { readTrustedKeys, verifyPublished } from './published.mjs';

const LOOPBACK = '127.0.0.1';
export const HOST_LIMITS = Object.freeze({ bodyBytes: 65536, inflight: 8, connections: 32, requestsPerMinute: 300, postsPerMinute: 60, bodyTimeoutMs: 5000 });
const reply = (res, status, error, extra = {}) => {
  if (!res.destroyed && !res.headersSent) {
    res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Connection': 'close', ...extra });
    res.end(JSON.stringify({ error }));
  }
};

function minuteBucket(limit) {
  let started = Date.now(), count = 0;
  return () => {
    const now = Date.now();
    if (now - started >= 60000) { started = now; count = 0; }
    return ++count <= limit;
  };
}

export function createCatalogServer({ database, ingest = false, limits = HOST_LIMITS } = {}) {
  const allowRequest = minuteBucket(limits.requestsPerMinute), allowPost = minuteBucket(limits.postsPerMinute);
  let active = 0;
  const metrics = { requests: 0, rejected: 0, failures: 0 };
  const server = createServer({ maxHeaderSize: 8192, headersTimeout: 5000, requestTimeout: 10000, connectionsCheckingInterval: 1000 }, async (req, res) => {
    metrics.requests++;
    res.on('error', () => {});
    if (!allowRequest()) { metrics.rejected++; reply(res, 429, 'rate_limited', { 'Retry-After': '60' }); return; }
    if (active >= limits.inflight) { metrics.rejected++; reply(res, 503, 'busy', { 'Retry-After': '5' }); return; }
    // Do not trust Host/forwarded headers or expose arbitrary local paths.
    if (!req.url?.startsWith('/') || req.url.startsWith('//') || req.url.length > 256 || !['GET', 'POST'].includes(req.method)) {
      metrics.rejected++; reply(res, 400, 'invalid_request'); return;
    }
    if (req.method === 'POST' && (!ingest || !allowPost())) {
      metrics.rejected++; reply(res, ingest ? 429 : 503, ingest ? 'rate_limited' : 'ingestion_disabled', { 'Retry-After': '60' }); return;
    }
    const length = req.headers['content-length'];
    if ((length !== undefined && (!/^\d+$/.test(length) || Number(length) > limits.bodyBytes)) ||
        req.headers['content-encoding'] || (req.method === 'GET' && (req.headers['transfer-encoding'] || Number(length) > 0))) {
      metrics.rejected++; reply(res, 413, 'body_bounds'); return;
    }
    active++;
    const timer = setTimeout(() => {
      metrics.rejected++; req.pause();
      res.once('finish', () => req.destroy());
      reply(res, 408, 'request_timeout');
    }, limits.bodyTimeoutMs);
    timer.unref();
    try {
      const chunks = []; let bytes = 0;
      for await (const chunk of req) {
        bytes += chunk.length;
        if (bytes > limits.bodyBytes) { metrics.rejected++; reply(res, 413, 'body_bounds'); return; }
        chunks.push(chunk);
      }
      if (res.destroyed || res.writableEnded) return;
      clearTimeout(timer);
      const request = new Request('http://catalog.local' + req.url, {
        method: req.method,
        headers: { 'Content-Type': req.headers['content-type'] ?? '' },
        ...(req.method === 'POST' ? { body: Buffer.concat(chunks) } : {}),
      });
      const response = await worker.fetch(request, { DB: database });
      res.writeHead(response.status, Object.fromEntries(response.headers));
      res.end(Buffer.from(await response.arrayBuffer()));
    } catch {
      metrics.failures++;
      reply(res, 503, 'service_unavailable');
    } finally { clearTimeout(timer); active--; }
  });
  server.maxConnections = limits.connections;
  server.maxRequestsPerSocket = 20;
  server.keepAliveTimeout = 2000;
  server.setTimeout(10000, socket => socket.destroy());
  // Parser errors never echo raw request bytes (which can contain metadata).
  server.on('clientError', (_error, socket) => { metrics.rejected++; socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'); });
  return { server, metrics, listen: port => new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, LOOPBACK, () => { server.removeListener('error', reject); resolve(server.address()); });
  }) };
}

export async function main() {
  const major = Number(process.versions.node.split('.')[0]);
  if (major < 24 || major % 2) throw new Error('supported_node_lts_required');
  process.umask(0o077);
  const directory = process.env.KOKIRI_CATALOG_DATA;
  const port = Number(process.env.KOKIRI_CATALOG_PORT ?? 8787);
  if (!directory || !Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('invalid_service_configuration');
  const database = new CatalogDatabase(directory, readFileSync(new URL('./0001_catalog.sql', import.meta.url), 'utf8'));
  const service = createCatalogServer({ database, ingest: process.env.KOKIRI_CATALOG_INGEST === '1' });
  try {
    await verifyPublished(database.db, readTrustedKeys(process.env.KOKIRI_CATALOG_TRUSTED_KEYS));
    await service.listen(port);
  } catch (error) { database.close(); throw error; }
  console.log(JSON.stringify({ event: 'catalog_started', bind: LOOPBACK, port, ingestion: process.env.KOKIRI_CATALOG_INGEST === '1' }));
  const health = setInterval(() => console.log(JSON.stringify({ event: 'aggregate_health', ...service.metrics })), 60000);
  health.unref();
  let closing = false;
  const stop = () => {
    if (closing) return;
    closing = true; clearInterval(health);
    service.server.close(() => { database.close(); });
    service.server.closeIdleConnections();
    const deadline = setTimeout(() => service.server.closeAllConnections(), 12000);
    deadline.unref();
  };
  process.on('SIGTERM', stop); process.on('SIGINT', stop);
}

function launchedAsEntryPoint() {
  try { return process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href; }
  catch { return false; }
}
if (launchedAsEntryPoint()) {
  main().catch(error => {
    const code = /^[a-z0-9_]+$/.test(error.message) ? error.message : /^[A-Z0-9_]+$/.test(error.code) ? error.code : 'initialization_failed';
    console.error(JSON.stringify({ event: 'catalog_start_failed', code })); process.exitCode = 1;
  });
}
