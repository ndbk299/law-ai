"""Máy chủ Backend API & Web Server cho Law GPT (Infranixx)
Tích hợp Medical AI Engine (RAG, Medical NER, Guardrails, Generative Synthesis).
Sử dụng dữ liệu từ SQLite Database (data/drugs.db).
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sqlite3
import unicodedata
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "drugs.db"
FRONTEND_DIR = ROOT / "frontend"
PORT = 8000

# Import Medical AI Engine
try:
    from backend.ai_engine import LLMProviderError, ai_engine
except ImportError:
    from ai_engine import LLMProviderError, ai_engine


def normalize(text: str) -> str:
    """Loại bỏ dấu tiếng Việt và chuyển sang chữ thường để tìm kiếm gần đúng"""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = text.replace("đ", "d")
    return text.strip()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_all_drugs_data() -> dict:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name, hue, description FROM drug_groups ORDER BY hue ASC")
    groups = [
        {"id": row["id"], "name": row["name"], "hue": row["hue"], "description": row["description"]}
        for row in cur.fetchall()
    ]

    cur.execute("""
        SELECT id, name, active_ingredient, strength, form, group_id,
               manufacturer, country, registration_no, packaging,
               indications, contraindications, dosage, side_effects
        FROM drugs ORDER BY id ASC
    """)
    drugs = []
    for r in cur.fetchall():
        drugs.append({
            "id": r["id"],
            "name": r["name"],
            "activeIngredient": r["active_ingredient"],
            "strength": r["strength"],
            "form": r["form"],
            "group": r["group_id"],
            "manufacturer": r["manufacturer"],
            "country": r["country"],
            "registrationNo": r["registration_no"],
            "packaging": r["packaging"],
            "indications": r["indications"],
            "contraindications": r["contraindications"],
            "dosage": r["dosage"],
            "sideEffects": r["side_effects"],
        })

    conn.close()

    return {
        "meta": {
            "isSample": False,
            "total": len(drugs),
            "source": "Cục Quản lý Dược – Bộ Y tế Việt Nam (DAV)",
            "updatedAt": "2026-10-23",
        },
        "groups": groups,
        "drugs": drugs,
    }


def fetch_drug_by_id(drug_id: str) -> dict | None:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT d.*, g.name AS group_name, g.hue AS group_hue
        FROM drugs d
        JOIN drug_groups g ON d.group_id = g.id
        WHERE d.id = ?
    """, (drug_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def fetch_stats() -> dict:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM drugs")
    total_drugs = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM drug_groups")
    total_groups = cur.fetchone()[0]

    cur.execute("""
        SELECT g.name, COUNT(d.id) AS count
        FROM drug_groups g
        LEFT JOIN drugs d ON g.id = d.group_id
        GROUP BY g.id, g.name
        ORDER BY count DESC
    """)
    by_group = [{"name": r["name"], "count": r["count"]} for r in cur.fetchall()]

    cur.execute("""
        SELECT COALESCE(form, 'Chưa rõ') AS form_name, COUNT(*) AS count
        FROM drugs
        GROUP BY form
        ORDER BY count DESC
    """)
    by_form = [{"name": r["form_name"], "count": r["count"]} for r in cur.fetchall()]

    conn.close()
    return {
        "totalDrugs": total_drugs,
        "totalGroups": total_groups,
        "totalForms": len(by_form),
        "byGroup": by_group,
        "byForm": by_form,
    }


def search_drugs_db(query: str, group_id: str | None = None) -> list[dict]:
    data = fetch_all_drugs_data()
    drugs = data["drugs"]
    q_norm = normalize(query)
    tokens = q_norm.split()

    results = []
    for d in drugs:
        if group_id and d["group"] != group_id:
            continue
        if not tokens:
            results.append(d)
            continue
        haystack = normalize(" ".join([
            d["name"], d["activeIngredient"], d["form"],
            d["manufacturer"], d["registrationNo"], d.get("indications", "")
        ]))
        if all(token in haystack for token in tokens):
            results.append(d)
    return results


class LawGPTRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, status: int, data: dict | list):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API: GET /api/drugs
        if path == "/api/drugs":
            data = fetch_all_drugs_data()
            self._send_json(HTTPStatus.OK, data)
            return

        # 2. API: GET /api/drugs/<id>
        if path.startswith("/api/drugs/"):
            drug_id = path[len("/api/drugs/"):].strip()
            drug = fetch_drug_by_id(drug_id)
            if drug:
                self._send_json(HTTPStatus.OK, drug)
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Không tìm thấy thuốc với id: {drug_id}"})
            return

        # 3. API: GET /api/stats
        if path == "/api/stats":
            stats = fetch_stats()
            self._send_json(HTTPStatus.OK, stats)
            return

        # 4. API: GET /api/search?q=...&group=...
        if path == "/api/search":
            query_params = parse_qs(parsed.query)
            q = query_params.get("q", [""])[0]
            group = query_params.get("group", [None])[0]
            results = search_drugs_db(q, group)
            self._send_json(HTTPStatus.OK, {"query": q, "count": len(results), "results": results})
            return

        # 5. Phục vụ Frontend tĩnh
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_body = self.rfile.read(content_length).decode("utf-8")
                try:
                    payload = json.loads(raw_body)
                except Exception:
                    payload = {}
            else:
                payload = {}

            message = payload.get("message", "")
            current_group = payload.get("group", None)

            # Xử lý thông qua Medical AI Engine (RAG + NER + Guardrails + Generator)
            try:
                response = ai_engine.process(message, current_group)
            except LLMProviderError as exc:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, response)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint không tồn tại"})


def run_server(port: int = PORT) -> None:
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, LawGPTRequestHandler)
    print(f"==================================================")
    print(f"🚀 Law GPT Unified Medical AI Server đang chạy!")
    print(f"👉 Địa chỉ truy cập Web: http://localhost:{port}")
    print(f"👉 Trợ lý AI Medical:    http://localhost:{port}/api/chat (POST)")
    print(f"👉 API Danh mục Dược:    http://localhost:{port}/api/drugs")
    print(f"👉 Database SQLite:      {DB_PATH}")
    print(f"👉 AI Engine Provider:   {ai_engine.llm.provider.upper()}")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang dừng máy chủ...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
