# Observability bundle - qa-001

## Environment
- URL: http://localhost:3000/dashboard
- Auth: session cookie present, request returned 200
- Browser: Chromium via Playwright

## DOM snapshot (after page load)

```
@e1 <main class="page-layout">
  @e2 <h1 class="text-3xl font-semibold mb-6">Welcome back</h1>
  @e3 <div class="grid grid-cols-3 gap-4">
    @e4 <div class="kpi-card">
      @e5 <span class="label">Active Users</span>
      @e6 <span class="value">1,248</span>
      @e7 <span class="trend positive">+4.2%</span>
    </div>
    @e8 <div class="kpi-card">
      @e9 <span class="label">Revenue</span>
      @e10 <span class="value">$18,320</span>
      @e11 <span class="trend positive">+1.1%</span>
    </div>
    @e12 <div class="kpi-card">
      @e13 <span class="label">Sessions</span>
      @e14 <span class="value">3,104</span>
      @e15 <span class="trend negative">-0.3%</span>
    </div>
  </div>
</main>
```

## Console log

```
[log] page hydrated in 184ms
```

0 errors, 0 warnings.

## Network log

```
200 GET /dashboard  (178ms, 12.4kb)
200 GET /_next/static/chunks/pages/dashboard-abc123.js  (64ms)
```

## Test runner output

```
$ pnpm test src/pages/__tests__/dashboard.test.tsx
PASS  src/pages/__tests__/dashboard.test.tsx
  Dashboard
    ok renders the welcome heading (14ms)
    ok renders three KPI cards (22ms)
    ok applies the correct grid layout (8ms)
Tests: 3 passed, 3 total
```

## Screenshots

- /tmp/qa_20260420_131500_dashboard_initial.png - initial page load, all three cards visible
