import http from 'node:http';
import { pathToFileURL } from 'node:url';

export function createServer() {
  return http.createServer((req, res) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    res.setHeader('Content-Type', 'application/json');
    if (req.method === 'GET' && path === '/health') {
      res.end(JSON.stringify({ status: 'ok', api_version: 'v1', implementation: 'scaffold' }));
      return;
    }
    const planned = (req.method === 'POST' && path === '/v1/proposals') ||
      (req.method === 'GET' && /^\/v1\/proposals\/[^/]+(?:\/(?:questions|log))?$/.test(path)) ||
      (req.method === 'POST' && /^\/v1\/proposals\/[^/]+\/grade$/.test(path));
    res.statusCode = planned ? 501 : 404;
    res.end(JSON.stringify({ error: {
      code: planned ? 'NOT_IMPLEMENTED' : 'NOT_FOUND',
      message: planned ? 'This endpoint is scaffolded only.' : 'Route not found.',
    } }));
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const host = process.env.BACKEND_HOST || '127.0.0.1';
  const port = Number(process.env.BACKEND_PORT || 8000);
  createServer().listen(port, host, () => console.error(`Scaffold backend listening on ${host}:${port}`));
}
