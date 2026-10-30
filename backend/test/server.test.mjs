import { test } from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from '../src/server.mjs';

test('health works and unimplemented API routes never approve', async (t) => {
  const server = createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise(resolve => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;
  const health = await fetch(`${base}/health`);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).implementation, 'scaffold');
  for (const [method, path] of [
    ['POST', '/v1/proposals'], ['GET', '/v1/proposals/example'],
    ['GET', '/v1/proposals/example/questions'], ['POST', '/v1/proposals/example/grade'],
    ['GET', '/v1/proposals/example/log'],
  ]) {
    const response = await fetch(base + path, { method });
    assert.equal(response.status, 501);
    assert.equal((await response.json()).error.code, 'NOT_IMPLEMENTED');
  }
  assert.equal((await fetch(`${base}/unknown`)).status, 404);
});
