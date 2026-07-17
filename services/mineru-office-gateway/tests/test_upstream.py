import asyncio
import unittest

import httpx

from app.upstream import send_upstream


class UpstreamTests(unittest.TestCase):
    def test_preserves_status_body_and_safe_headers(self):
        async def run():
            transport = httpx.MockTransport(
                lambda request: httpx.Response(
                    202,
                    json={"task_id": "abc"},
                    headers={
                        "content-type": "application/json",
                        "connection": "close",
                    },
                )
            )
            async with httpx.AsyncClient(transport=transport) as client:
                response = await send_upstream(
                    client,
                    "http://mineru-router:8002/tasks",
                    "POST",
                    [("return_md", "true")],
                    [],
                )
                body = b"".join(
                    [chunk async for chunk in response.body_iterator]
                )
                await response.background()
                return response, body

        response, body = asyncio.run(run())
        self.assertEqual(response.status_code, 202)
        self.assertEqual(body, b'{"task_id":"abc"}')
        self.assertNotIn("connection", response.headers)


if __name__ == "__main__":
    unittest.main()
