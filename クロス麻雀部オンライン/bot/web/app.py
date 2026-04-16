import os
import secrets
import sqlite3

from flask import Flask, jsonify, render_template, request

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "mahjong.db")
EDIT_TOKEN = os.getenv("EDIT_TOKEN", secrets.token_urlsafe(16))

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    allowed = ["https://mj.kyoten-hub.com", "http://localhost:3000"]
    origin = request.headers.get("Origin", "")
    if origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers["Access-Control-Allow-Origin"] = "https://mj.kyoten-hub.com"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Edit-Token"
    return response


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def _require_edit_token():
    token = request.headers.get("X-Edit-Token", "")
    return secrets.compare_digest(token, EDIT_TOKEN)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ranking")
def api_ranking():
    db = get_db()
    rows = db.execute("""
        SELECT
            m.display_name,
            COUNT(*) AS game_count,
            ROUND(AVG(r.rank), 2) AS avg_rank,
            ROUND(SUM(r.point), 1) AS total_point,
            ROUND(SUM(CASE WHEN r.rank = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS top_rate,
            ROUND(SUM(CASE WHEN r.rank <= 2 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rentai_rate
        FROM match_results r
        JOIN members m ON m.id = r.member_id
        JOIN matches mt ON mt.id = r.match_id
        WHERE mt.status = 'finished'
        GROUP BY m.id
        ORDER BY total_point DESC
    """).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/recent")
def api_recent():
    db = get_db()
    rows = db.execute("""
        SELECT
            mt.id AS match_id,
            mt.match_type,
            mt.finished_at,
            r.rank,
            r.score,
            r.point,
            m.display_name,
            r.id AS result_id,
            m.id AS member_id
        FROM match_results r
        JOIN members m ON m.id = r.member_id
        JOIN matches mt ON mt.id = r.match_id
        WHERE mt.status = 'finished'
        ORDER BY mt.finished_at DESC, r.rank ASC
        LIMIT 100
    """).fetchall()
    db.close()

    matches = {}
    for r in rows:
        mid = r["match_id"]
        if mid not in matches:
            matches[mid] = {
                "match_id": mid,
                "match_type": r["match_type"],
                "finished_at": r["finished_at"],
                "players": [],
            }
        matches[mid]["players"].append({
            "result_id": r["result_id"],
            "member_id": r["member_id"],
            "rank": r["rank"],
            "score": r["score"],
            "point": r["point"],
            "name": r["display_name"],
        })

    return jsonify(list(matches.values()))


@app.route("/api/members")
def api_members():
    db = get_db()
    rows = db.execute(
        "SELECT id, discord_id, display_name FROM members ORDER BY display_name"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/result/<int:result_id>", methods=["PATCH", "OPTIONS"])
def api_update_result(result_id: int):
    if request.method == "OPTIONS":
        return ("", 204)
    if not _require_edit_token():
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json() or {}
    fields = []
    params = []
    for key in ("rank", "score", "point", "member_id"):
        if key in data:
            fields.append(f"{key} = ?")
            params.append(data[key])
    if not fields:
        return jsonify({"error": "no fields"}), 400

    params.append(result_id)
    db = get_db()
    db.execute(f"UPDATE match_results SET {', '.join(fields)} WHERE id = ?", params)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/result/<int:result_id>", methods=["DELETE"])
def api_delete_result(result_id: int):
    if not _require_edit_token():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    db.execute("DELETE FROM match_results WHERE id = ?", (result_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    print(f"Edit token (set EDIT_TOKEN env to persist): {EDIT_TOKEN}")
    app.run(host="0.0.0.0", port=8080)
