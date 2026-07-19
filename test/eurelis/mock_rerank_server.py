# Eurelis — mock d'un serveur de reranking (API Jina-compatible) pour les tests e2e.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# But : fournir un reranker déterministe et hermétique (pas de cloud, pas de modèle lourd) pour
# valider le CÂBLAGE du logging de consommation rerank (token_type="rerank") dans usage_log —
# pas la qualité du reranking. Répond à tout POST par une réponse Jina valide + un usage non nul
# (sinon total_token_count_from_response = 0 et la ligne usage_log serait skippée).

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Health check.
        self._send(200, {"status": "ok"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            req = {}
        # Jina envoie `documents`; d'autres connecteurs `texts`. On score tout de façon décroissante.
        docs = req.get("documents") or req.get("texts") or []
        results = [{"index": i, "relevance_score": max(0.0, 1.0 - i * 0.01)} for i in range(len(docs))]
        # `usage.total_tokens` > 0 pour que le connecteur comptabilise des tokens.
        tokens = sum(len(str(d).split()) for d in docs) + len(str(req.get("query", "")).split()) or 1
        self._send(200, {"model": req.get("model", "mock-rerank"), "results": results, "usage": {"total_tokens": tokens}})

    def log_message(self, *args):
        pass  # silence


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
