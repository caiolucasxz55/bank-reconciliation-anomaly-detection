"""Request size limit for uploads, enforced before the multipart body is parsed."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Room for multipart boundaries and part headers on top of the file contents.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


class UploadSizeLimit:
    """Rejects upload requests whose declared size exceeds ``max_bytes``.

    Without it, the whole body would be received and spooled to disk before the
    endpoint could check any file size. Requests without ``Content-Length`` (chunked)
    are refused on these paths, since their size cannot be known in advance.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int, path_prefix: str) -> None:
        self.app = app
        self.max_bytes = max_bytes + MULTIPART_OVERHEAD_BYTES
        self.path_prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith(self.path_prefix)
        ):
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is None or not length.isdigit():
            response = JSONResponse({"detail": "envio sem Content-Length"}, status_code=411)
        elif int(length) > self.max_bytes:
            mb = (self.max_bytes - MULTIPART_OVERHEAD_BYTES) // (1024 * 1024)
            response = JSONResponse(
                {"detail": f"envio grande demais (máximo {mb} MB por envio)"}, status_code=413
            )
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)
