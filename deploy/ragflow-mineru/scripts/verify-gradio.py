"""Run inside the deployed Gradio container, using its installed MinerU client."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen


def read_url(url):
    with urlopen(url, timeout=30) as response:
        return response.geturl(), response.headers, response.read()


def verify_browser_routes():
    from gradio_pdf import PDF

    root = "http://gateway/mineru-ui/"
    _, headers, body = read_url(root + "config")
    assert headers.get("Cache-Control") == "no-store", "Gradio config must not be cached"
    config = json.loads(body)
    for stylesheet in config.get("stylesheets", []):
        # Match Gradio's root + '/' + stylesheet construction.
        url = root + stylesheet
        assert urlsplit(stylesheet).scheme == "", f"External stylesheet: {stylesheet}"
        assert "/mineru-ui/mineru-ui/" not in url, url
        read_url(url)

    pdf_class_id = PDF.get_component_class_id()
    class_ids = {component["component_class_id"] for component in config["components"]
                 if component.get("component_class_id") == pdf_class_id}
    assert class_ids, "No PDF custom component in Gradio config; verify the installed version"
    for class_id in class_ids:
        url = f"http://gateway/gradio_api/custom_component/{class_id}/client/component/index.js"
        final_url, headers, script = read_url(url)
        assert "/mineru-ui/gradio_api/" in final_url, final_url
        assert "javascript" in headers.get_content_type(), (url, headers.get_content_type())
        # Relative imports use the redirected component URL as their base.
        for dependency in re.findall(r'["\'](\.[^"\']+\.js)["\']', script.decode()):
            dependency_url = urljoin(final_url, dependency)
            _, dependency_headers, _ = read_url(dependency_url)
            assert "javascript" in dependency_headers.get_content_type(), dependency_url
    print("Gradio config, custom component redirects, and JavaScript imports passed.")


async def verify_conversion(fixture: Path):
    from mineru.cli.api_client import validate_server_health_payload
    from mineru.cli.gradio_app import _run_to_markdown_job

    api_url = "http://mineru-office-gateway:8081"
    _, _, body = read_url(api_url + "/health")
    validate_server_health_payload(json.loads(body), api_url)
    try:
        result = await _run_to_markdown_job(
            str(fixture), backend="hybrid-engine", url="http://localhost:30000", api_url=api_url,
        )
        assert result[1].strip(), "Gradio returned empty Markdown"
        assert Path(result[3]).is_file(), "Gradio result archive is missing"
        print("Gradio Office conversion passed: health, task, download, Markdown, and archive.")
    finally:
        fixture.unlink(missing_ok=True)


if __name__ == "__main__":
    verify_browser_routes()
    asyncio.run(verify_conversion(Path(sys.argv[1])))
