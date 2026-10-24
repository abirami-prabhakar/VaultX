import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, daysUntil, download, forgetReviewerKey, formatDate, money, requireReason, reviewerKey, setReviewerKey } from './api';

beforeEach(() => setReviewerKey('test-reviewer-key'));
afterEach(() => { forgetReviewerKey(); vi.unstubAllGlobals(); });
describe('review safety and API integration', () => {
  it('blocks reviews without a meaningful reason before contacting the API', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    expect(() => api.review('record-1', { action: 'approve', reason: ' ' })).toThrow('reason');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('sends reason, actor and key with a real review request', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'approved' }) }); vi.stubGlobal('fetch', fetch);
    await api.review('record-1', { action: 'approve', reason: ' Evidence checked ' });
    const [url, options] = fetch.mock.calls[0];
    expect(url).toContain('/instruments/record-1/review');
    expect(options.headers.get('X-API-Key')).toBe('test-reviewer-key');
    expect(options.headers.get('X-Actor')).toBe('Local reviewer');
    expect(JSON.parse(options.body).reason).toBe('Evidence checked');
  });
  it('surfaces backend transition errors instead of reporting success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: 'Already approved' }) }));
    await expect(api.review('record-1', { action: 'reject', reason: 'Check required' })).rejects.toThrow('Already approved');
  });
  it('rejects a persisted extraction failure even when the endpoint returns HTTP 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 'record-1', extraction_error: 'Model timed out' }) }));
    await expect(api.extract('record-1', 'gemma')).rejects.toThrow('Model timed out');
  });
  it('builds encoded list filters', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) }); vi.stubGlobal('fetch', fetch);
    await api.instruments('Bank & Trust', 'pending_review', 2);
    expect(fetch.mock.calls[0][0]).toContain('q=Bank+%26+Trust');
    expect(fetch.mock.calls[0][0]).toContain('page=2');
  });
});
describe('reviewer connection', () => {
  it('blocks private data and document downloads before contacting the backend when disconnected', async () => {
    setReviewerKey('');
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    await expect(api.dashboard()).rejects.toThrow('reviewer key');
    await expect(download('/instruments/record-1/document')).rejects.toThrow('reviewer key');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('allows the public health check without a reviewer key', async () => {
    setReviewerKey('');
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok' }) }); vi.stubGlobal('fetch', fetch);
    expect(await api.health()).toEqual({ status: 'ok' });
    expect(fetch.mock.calls[0][1].headers.has('X-API-Key')).toBe(false);
  });
  it('verifies the submitted key without silently replacing it with a previous connection', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ total: 0 }) }); vi.stubGlobal('fetch', fetch);
    await api.verifyKey(' replacement-key ');
    expect(fetch.mock.calls[0][1].headers.get('X-API-Key')).toBe('replacement-key');
    expect(reviewerKey()).toBe('test-reviewer-key');
    await expect(api.verifyKey(' ')).rejects.toThrow('reviewer key');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('keeps session keys out of URLs and supports browsers with unavailable session storage', async () => {
    vi.stubGlobal('sessionStorage', { setItem() { throw new Error('Storage denied'); }, getItem() { throw new Error('Storage denied'); }, removeItem() { throw new Error('Storage denied'); } });
    setReviewerKey(' session-secret ');
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ total: 0 }) }); vi.stubGlobal('fetch', fetch);
    await api.dashboard();
    expect(fetch.mock.calls[0][0]).not.toContain('session-secret');
    expect(fetch.mock.calls[0][1].headers.get('X-API-Key')).toBe('session-secret');
    forgetReviewerKey();
    expect(reviewerKey()).toBe('');
  });
});
describe('financial and date display', () => {
  it('handles unknown values without manufacturing data', () => { expect(money(null)).toBe('Not extracted'); expect(daysUntil(null)).toBeNull(); expect(formatDate(null)).toBe('—'); });
  it('does not assume a currency when only the amount was extracted', () => { expect(money('10000', '')).toBe('10000 · currency unknown'); });
  it('formats valid financial values and rejects short reasons', () => { expect(money('100000.50', 'INR')).toContain('1,00,000.5'); expect(() => requireReason('no')).toThrow(); });
  it('preserves cents and integer precision for amounts larger than JavaScript safe integers', () => { expect(money('999999999999999999.99', 'INR')).toContain('9,99,99,99,99,99,99,99,999.99'); });
});
describe('Security Lab reports', () => {
  it('loads the backend report without manufacturing a passing outcome', async () => {
    const result = { controls: [], guard: { status: 'disabled' }, last_run: null };
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result }); vi.stubGlobal('fetch', fetch);
    const inventory = await api.securityLab();
    expect(inventory.last_run).toBeNull();
    expect(inventory.guard.status).toBe('disabled');
    expect(fetch.mock.calls[0][0]).toContain('/security-lab');
    expect(fetch.mock.calls[0][1].headers.get('X-API-Key')).toBe('test-reviewer-key');
  });
  it('runs authenticated checks and preserves failed and skipped results from the backend', async () => {
    const result = { summary: { passed: 0, failed: 1, skipped: 1, total: 2 }, cases: [{ id: 'false-positive', status: 'failed' }, { id: 'model-unavailable', status: 'skipped' }] };
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result }); vi.stubGlobal('fetch', fetch);
    const report = await api.runSecurityLab();
    expect(report).toEqual(result);
    expect(fetch.mock.calls[0][0]).toContain('/security-lab/run');
    expect(fetch.mock.calls[0][1].method).toBe('POST');
    expect(fetch.mock.calls[0][1].headers.get('X-API-Key')).toBe('test-reviewer-key');
  });
  it('surfaces runner errors instead of returning a successful report', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: 'A security run is already in progress' }) }));
    await expect(api.runSecurityLab()).rejects.toThrow('A security run is already in progress');
  });
});
