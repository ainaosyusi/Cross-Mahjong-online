import sqlite3
import os
from flask import Flask, render_template, jsonify

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "mahjong.db")

app = Flask(__name__)


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


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
            m.display_name
        FROM match_results r
        JOIN members m ON m.id = r.member_id
        JOIN matches mt ON mt.id = r.match_id
        WHERE mt.status = 'finished'
        ORDER BY mt.finished_at DESC, r.rank ASC
        LIMIT 100
    """).fetchall()
    db.close()

    # マッチごとにグループ化
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
            "rank": r["rank"],
            "name": r["display_name"],
        })

    return jsonify(list(matches.values()))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
