"""Offline HTTP test for the monitor server — no LLM/kernel.

Spins up the real stdlib server on an ephemeral port against an fn-only graph,
then drives it over HTTP: structure, static app, trigger a run, poll state.
"""

import json
import threading
import time
import urllib.request

from wolfram_llmgraph import LLMGraph, RunMonitor
from wolfram_llmgraph.server import serve


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _post(url, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_server_endpoints_and_run():
    mon = RunMonitor()
    g = LLMGraph(
        {"A": {"fn": (lambda: 21)}, "B": (lambda A: A * 2)},
        monitor=mon, llm_factory=lambda m: None,
    )
    httpd, _app = serve(g, mon, host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        # static structure (semantic LLMGraph layer)
        status, body = _get(base + "/api/graph")
        assert status == 200
        info = json.loads(body)
        assert set(info["Nodes"]) == {"A", "B"}
        assert "InputEdges" in info

        # compiled LangGraph runtime layer
        status, lbody = _get(base + "/api/langgraph")
        assert status == 200
        lg = json.loads(lbody)
        assert "__start__" in lg["nodes"] and "__end__" in lg["nodes"]
        assert any(e["source"] == "__start__" for e in lg["edges"])
        assert lg.get("mermaid")  # LangGraph's own mermaid export

        # the web app itself
        status, html = _get(base + "/")
        assert status == 200 and "<title>" in html and "runtime monitor" in html.lower()

        # trigger a run, then poll state until done
        status, res = _post(base + "/api/run", {"input": {}})
        assert status == 200 and res["started"] is True

        snap = None
        for _ in range(50):
            _, sbody = _get(base + "/api/state")
            snap = json.loads(sbody)
            if snap.get("status") == "done":
                break
            time.sleep(0.05)
        assert snap and snap["status"] == "done"
        assert snap["nodes"]["B"]["status"] == "done"
        assert snap["nodes"]["B"]["preview"] == "42"
        assert snap["progress"] == {"done": 2, "total": 2}
    finally:
        httpd.shutdown()
