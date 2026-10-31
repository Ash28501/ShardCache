// Load test for ShardCache.
//   docker compose up -d --build          (rate limiting is disabled in compose for load tests)
//   k6 run loadtest/k6-shardcache.js
// Reports requests/sec, p50/p95/p99 latency and error rate. Multiply req/s by 60 for req/min.
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const KEYS = 10000;

export const options = {
  scenarios: {
    mixed: {
      executor: 'constant-vus',
      vus: Number(__ENV.VUS || 50),
      duration: __ENV.DURATION || '60s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  for (let i = 0; i < 1000; i++) {
    http.post(`${BASE}/set?key=k${i}&value=v${i}&ttl=600`);
  }
}

export default function () {
  const k = `k${Math.floor(Math.random() * KEYS)}`;
  if (Math.random() < 0.2) {
    const r = http.post(`${BASE}/set?key=${k}&value=v&ttl=600`);
    check(r, { 'set 200': (res) => res.status === 200 });
  } else {
    const r = http.get(`${BASE}/get/${k}`, { responseCallback: http.expectedStatuses(200, 404) });
    check(r, { 'get 200/404': (res) => res.status === 200 || res.status === 404 });
  }
}
