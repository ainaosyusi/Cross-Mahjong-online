const API_BASE = "https://mj-api.kyoten-hub.com";

// ========== Navigation ==========
document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    const page = link.dataset.page;
    showPage(page);
    // モバイルメニュー閉じる
    document.querySelector(".nav-mobile").classList.remove("open");
  });
});

document.querySelector(".hamburger").addEventListener("click", () => {
  document.querySelector(".nav-mobile").classList.toggle("open");
});

function showPage(page) {
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  document.getElementById(`page-${page}`).classList.add("active");
  document.querySelectorAll(".nav-link").forEach((l) => {
    l.classList.toggle("active", l.dataset.page === page);
  });
  window.scrollTo(0, 0);
  if (page === "edit") loadEdit();
}

// ========== Ranking ==========
let currentPeriod = "all";

document.querySelectorAll(".period-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".period-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    currentPeriod = tab.dataset.period;
    loadRanking();
  });
});

async function loadRanking() {
  const el = document.getElementById("ranking-content");
  el.innerHTML = '<div class="loading-state">読み込み中...</div>';

  try {
    const res = await fetch(`${API_BASE}/api/ranking`);
    const data = await res.json();

    if (!data.length) {
      el.innerHTML = '<div class="no-data">まだデータがありません</div>';
      return;
    }

    const medals = ["🥇", "🥈", "🥉"];
    let html =
      '<table class="ranking-table"><tr><th>#</th><th>プレイヤー</th><th>対戦数</th><th>平均順位</th><th>トップ率</th><th>連対率</th></tr>';

    data.forEach((r, i) => {
      const cls = i < 3 ? ` class="rank-${i + 1}"` : "";
      const rank = medals[i] || i + 1;
      html += `<tr>
        <td${cls}>${rank}</td>
        <td>${r.display_name}</td>
        <td>${r.game_count}</td>
        <td>${r.avg_rank}</td>
        <td>${r.top_rate}%</td>
        <td>${r.rentai_rate}%</td>
      </tr>`;
    });

    html += "</table>";
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="no-data">データの取得に失敗しました</div>';
  }
}

// ========== History ==========
async function loadHistory() {
  const el = document.getElementById("history-content");
  el.innerHTML = '<div class="loading-state">読み込み中...</div>';

  try {
    const res = await fetch(`${API_BASE}/api/recent`);
    const data = await res.json();

    if (!data.length) {
      el.innerHTML = '<div class="no-data">まだデータがありません</div>';
      return;
    }

    let html = "";
    data.forEach((m) => {
      const date = m.finished_at
        ? new Date(m.finished_at).toLocaleString("ja-JP", {
            month: "numeric",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })
        : "";

      html += `<div class="match-card">
        <div class="match-header">
          <span class="match-date">${date}</span>
          <span class="match-type-badge">${m.match_type}人戦</span>
        </div>
        <div class="match-players">`;

      m.players.forEach((p) => {
        const cls = p.rank <= 3 ? ` rank-${p.rank}` : "";
        html += `<span class="match-player${cls}">${p.rank}位: ${p.name}</span>`;
      });

      html += "</div></div>";
    });

    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="no-data">データの取得に失敗しました</div>';
  }
}

// ========== Edit ==========
let members = [];

function getToken() {
  return localStorage.getItem("mj_edit_token") || "";
}

function saveToken() {
  const v = document.getElementById("edit-token").value;
  localStorage.setItem("mj_edit_token", v);
  alert("トークンを保存しました。");
  loadEdit();
}

async function loadEdit() {
  const el = document.getElementById("edit-content");
  document.getElementById("edit-token").value = getToken();
  el.innerHTML = '<div class="loading-state">読み込み中...</div>';

  try {
    const [recentRes, membersRes] = await Promise.all([
      fetch(`${API_BASE}/api/recent`),
      fetch(`${API_BASE}/api/members`),
    ]);
    const data = await recentRes.json();
    members = await membersRes.json();

    if (!data.length) {
      el.innerHTML = '<div class="no-data">まだデータがありません</div>';
      return;
    }

    let html = "";
    data.forEach((m) => {
      const date = m.finished_at
        ? new Date(m.finished_at).toLocaleString("ja-JP", {
            month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
          })
        : "";
      html += `<div class="match-card edit-match-card">
        <div class="match-header">
          <span class="match-date">#${m.match_id}  ${date}</span>
          <span class="match-type-badge">${m.match_type}人戦</span>
        </div>`;

      m.players.forEach((p) => {
        const memberOptions = members.map(mem =>
          `<option value="${mem.id}"${mem.id === p.member_id ? " selected" : ""}>${mem.display_name}</option>`
        ).join("");
        html += `<div class="player-row" data-result-id="${p.result_id}">
          <select class="edit-rank">
            ${[1,2,3,4].map(r => `<option value="${r}"${r === p.rank ? " selected" : ""}>${r}位</option>`).join("")}
          </select>
          <select class="edit-member">${memberOptions}</select>
          <input class="edit-score" type="number" value="${p.score || 0}" step="100">
          <input class="edit-point" type="number" value="${p.point || 0}" step="0.1">
          <button class="btn-primary" onclick="saveRow(this)">保存</button>
        </div>`;
      });

      html += "</div>";
    });

    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="no-data">データの取得に失敗しました</div>';
  }
}

async function saveRow(btn) {
  const row = btn.closest(".player-row");
  const resultId = row.dataset.resultId;
  const payload = {
    rank: parseInt(row.querySelector(".edit-rank").value, 10),
    member_id: parseInt(row.querySelector(".edit-member").value, 10),
    score: parseInt(row.querySelector(".edit-score").value, 10),
    point: parseFloat(row.querySelector(".edit-point").value),
  };
  try {
    const res = await fetch(`${API_BASE}/api/result/${resultId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Edit-Token": getToken(),
      },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      btn.textContent = "保存済";
      setTimeout(() => (btn.textContent = "保存"), 2000);
    } else if (res.status === 401) {
      alert("編集トークンが無効です。");
    } else {
      alert("保存に失敗しました。");
    }
  } catch (e) {
    alert("保存に失敗しました: " + e.message);
  }
}

// ========== Init ==========
loadRanking();
loadHistory();
