#!/usr/bin/env python3
"""Minimal CPU Chronos-2 /forecast server.

Faithful standalone mirror of the /forecast contract in inference/server.py
(_forecast_sync), used for e2e testing the app.nz forecast flow without a GPU.
Univariate: {values, prediction_length, quantile_levels}. Multivariate: add
past_covariates / future_covariates (dicts of named series). Run:

    .venv/bin/python inference/forecast_cpu_server.py --port 8100
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from cutechronos.pipeline import CuteChronos2Pipeline

MODEL = None


def load(model_path: str):
    global MODEL
    t = time.time()
    MODEL = CuteChronos2Pipeline.from_pretrained(
        model_path, device="cpu", dtype=torch.float32, use_cute=True
    )
    # warmup
    MODEL.predict_quantiles(torch.arange(1, 17, dtype=torch.float32), prediction_length=4, quantile_levels=[0.5])
    print(f"[forecast-cpu] loaded {model_path} in {time.time()-t:.1f}s", flush=True)


def forecast(req: dict) -> dict:
    values = req["values"]
    horizon = int(req.get("prediction_length", 64))
    qlevels = req.get("quantile_levels") or [0.1, 0.5, 0.9]
    past = req.get("past_covariates")
    future = req.get("future_covariates")
    t0 = time.time()

    if past:
        for name, col in past.items():
            if len(col) != len(values):
                raise ValueError(f"past_covariate {name!r} length {len(col)} != values length {len(values)}")
        for name, col in (future or {}).items():
            if name not in past:
                raise ValueError(f"future_covariate {name!r} has no matching past_covariate")
            if len(col) != horizon:
                raise ValueError(f"future_covariate {name!r} length {len(col)} != prediction_length {horizon}")
        task = {"target": values, "past_covariates": past}
        if future:
            task["future_covariates"] = future
        quantiles, mean = MODEL.predict_quantiles([task], prediction_length=horizon, quantile_levels=qlevels)
    else:
        ctx = torch.tensor(values, dtype=torch.float32)
        quantiles, mean = MODEL.predict_quantiles(ctx, prediction_length=horizon, quantile_levels=qlevels)

    elapsed = time.time() - t0
    q_tensor = quantiles[0].squeeze(0)
    m_tensor = mean[0].squeeze(0)
    return {
        "mean": m_tensor.tolist(),
        "quantiles": {str(ql): q_tensor[:, i].tolist() for i, ql in enumerate(qlevels)},
        "prediction_length": horizon,
        "context_length": len(values),
        "inference_time_ms": int(elapsed * 1000),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": MODEL is not None})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/forecast":
            self._send(404, {"error": "not found"})
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, forecast(req))
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def log_message(self, *a):  # quiet
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--model", default="amazon/chronos-2")
    args = ap.parse_args()
    load(args.model)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[forecast-cpu] serving /forecast on :{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
