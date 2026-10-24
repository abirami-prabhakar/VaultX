"""ASGI request boundary: authenticate and bound actual bytes before parsing."""
import asyncio
from collections import deque
import hmac
import re
import time

from starlette.responses import JSONResponse


class SecurityBoundaryMiddleware:
    """A bounded in-memory request buffer prevents multipart spooling bypasses.

    The upload limit plus 1 MiB covers the complete multipart envelope. The file
    itself is checked separately. A process-local IP budget bounds request
    frequency, and a deadline bounds body ingestion (not native PDF/OCR work).
    Add CORS *after* this middleware so preflights and error CORS stay outermost.
    """
    PUBLIC_PATHS = frozenset({'/health', '/docs', '/openapi.json'})

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self._requests = {}

    def _within_rate_limit(self, scope):
        now = time.monotonic()
        window = getattr(self.settings, 'rate_limit_window_seconds', 60)
        count = getattr(self.settings, 'rate_limit_requests', 600)
        client = scope.get('client')
        source = client[0] if client else 'unknown'
        # Never trust a client-controlled forwarding header for identity.
        cutoff = now - window
        if source not in self._requests and len(self._requests) >= 1024:
            self._requests = {key: values for key, values in self._requests.items()
                              if values and values[-1] > cutoff}
            if len(self._requests) >= 1024:
                source = '__overflow__'
        requests = self._requests.setdefault(source, deque())
        while requests and requests[0] <= cutoff:
            requests.popleft()
        if len(requests) >= count:
            return False
        requests.append(now)
        return True

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        if scope.get('method') == 'OPTIONS':
            return await self.app(scope, receive, send)
        headers = {}
        for name, value in scope.get('headers', []):
            headers.setdefault(name.lower(), []).append(value)

        async def reject(status, message, response_headers=None):
            return await JSONResponse({'detail': message}, status_code=status, headers=response_headers)(scope, receive, send)

        if scope.get('path') not in self.PUBLIC_PATHS:
            if not self._within_rate_limit(scope):
                return await reject(429, 'Request rate limit exceeded; retry shortly',
                                    {'Retry-After': str(max(1, int(getattr(self.settings, 'rate_limit_window_seconds', 60))))})
            keys = headers.get(b'x-api-key', [])
            # Match Starlette's header decoding; non-ASCII/wrong/duplicate keys
            # fail cleanly rather than allowing a parser exception or ambiguity.
            key = keys[0].decode('latin-1').encode('utf-8') if len(keys) == 1 else b''
            if not hmac.compare_digest(key, self.settings.api_key.encode('utf-8')):
                return await reject(401, 'A valid reviewer API key is required')

        limit = self.settings.max_upload_mb * 1024 * 1024 + 1024 * 1024
        lengths = headers.get(b'content-length', [])
        length = None
        if lengths:
            raw = lengths[0]
            if len(lengths) != 1 or len(raw) > 20 or not re.fullmatch(rb'[0-9]+', raw):
                return await reject(400, 'Invalid content length')
            if b'transfer-encoding' in headers:
                return await reject(400, 'Ambiguous request framing')
            length = int(raw)
            if length > limit:
                return await reject(413, 'Request body exceeds upload limit')

        body = bytearray()
        deadline = time.monotonic() + getattr(self.settings, 'request_timeout_seconds', 30)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                message = await asyncio.wait_for(receive(), timeout=remaining)
                if message['type'] == 'http.disconnect':
                    return
                if message['type'] != 'http.request':
                    return await reject(400, 'Invalid request body')
                chunk = message.get('body', b'')
                if len(body) + len(chunk) > limit:
                    return await reject(413, 'Request body exceeds upload limit')
                body.extend(chunk)
                if not message.get('more_body', False):
                    break
        except TimeoutError:
            return await reject(408, 'Request body did not complete within the configured deadline')
        if length is not None and len(body) != length:
            return await reject(400, 'Request body does not match content length')

        replayed = False

        async def bounded_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        return await self.app(scope, bounded_receive, send)
