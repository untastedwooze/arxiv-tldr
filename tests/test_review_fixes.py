import json
from datetime import date, datetime, timedelta, timezone

import httpx

from arxiv_tldr.pipeline import run

from conftest import combined_transport, ollama_handler, rss_handler
from test_run import FEEDS, SCORES, setup

D = date(2026, 10, 26)


def test_paper_whose_summary_stays_malformed_is_listed_with_its_abstract_and_a_note(
    tmp_path, clock
):
    config, _, mailer, _ = setup(tmp_path)
    inner = ollama_handler(SCORES)

    def garbled(request):
        body = json.loads(request.content) if request.url.host == "piglet.example" else {}
        if "tldr" in body.get("format", {}).get("properties", {}) and "Heavy Tails" in body["prompt"]:
            return httpx.Response(200, json={"response": "not json", "done": True})
        return inner(request)

    client = httpx.Client(transport=combined_transport(garbled, rss_handler(FEEDS)))
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    msg = mailer.sent[0]
    assert "3 featured" in msg.subject
    assert "A study of tail behaviour &amp; estimation." in msg.html
    assert "Summary unavailable" in msg.html and "Summary unavailable" in msg.text
