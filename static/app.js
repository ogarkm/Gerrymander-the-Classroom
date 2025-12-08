/* --- THEME LOGIC --- */
const toggle = document.getElementById("theme-toggle");
if (localStorage.getItem("theme") === "dark-mode") {
  document.body.classList.add("dark-mode");
  toggle.checked = true;
}
toggle.addEventListener("change", (e) => {
  document.body.classList.toggle("dark-mode");
  localStorage.setItem("theme", e.target.checked ? "dark-mode" : "light-mode");
});

/* --- CLIENT ID LOGIC --- */
function getOrCreateClientId() {
    let id = localStorage.getItem("gerry_client_id");
    if (!id) {
        id = 'user_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("gerry_client_id", id);
    }
    return id;
}
const CLIENT_ID = getOrCreateClientId();

/* --- WEBSOCKET & STATE --- */
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${protocol}//${window.location.host}/ws/player`);

const STATE = {
  seatId: null,
  partyIndex: null, 
  roundConfig: null,
  grid: [],
  districts: [],
  dragging: false,
  selection: [],
  timer: 60,
  interval: null,
  origWins: 0,
  myWins: 0,
  scorePct: 0,
  takenSeats: []
};

const root = document.documentElement;

ws.onopen = () => {
    console.log("Connected to Game Server");
    ws.send(JSON.stringify({ type: "identify", clientId: CLIENT_ID }));
};

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "restore_session") {
        STATE.seatId = msg.seatId;
        document.getElementById("user-badge").innerText = msg.name;
        alerUser(`Welcome back, ${msg.name}`);
        
        if(msg.round_info) applyRoundConfig(msg.round_info);
        
        if (msg.phase === "GAME" && msg.map_data) {
             startGame(msg.map_data);
        } else if (msg.phase === "VOTE") {
             showScreen("screen-vote");
        } else if (msg.phase === "LOGIN") {
             initLogin();
        }
    }
    else if (msg.type === "login_success") {
        STATE.seatId = msg.seatId;
        document.getElementById("user-badge").innerText = msg.name;
        alerUser(`Logged in as ${msg.name}`);
        const mySeat = document.querySelector(`.seat[data-login-id="${msg.seatId}"]`);
        if(mySeat) {
            mySeat.classList.add("my-seat");
            mySeat.innerText = "ME";
        }
        showWaiting("Seat Secured. Waiting for teacher...");
    }
    else if (msg.type === "game_reset") {
        alert("The game has been reset by the admin.");
        window.location.reload();
    }
    else if (msg.type === "round_setup") {
        applyRoundConfig(msg.config);
    }
    else if (msg.type === "seat_map_update") {
        STATE.takenSeats = msg.taken_seats;
        updateLoginGrid();
    }
    else if (msg.type === "error") {
        alerUser(msg.message);
    }
    else if (msg.type === "phase_change") {
        handlePhaseChange(msg);
    }
};

function applyRoundConfig(config) {
    STATE.roundConfig = config;
    STATE.partyIndex = null;
    
    root.style.setProperty('--party-a-color', config.colors[0]);
    root.style.setProperty('--party-b-color', config.colors[1]);

    document.getElementById("vote-question").innerText = config.question;
    document.getElementById("name-party-a").innerText = config.options[0];
    document.getElementById("icon-party-a").className = `vote-icon ${config.icons[0]}`;
    document.getElementById("name-party-b").innerText = config.options[1];
    document.getElementById("icon-party-b").className = `vote-icon ${config.icons[1]}`;
    
    document.querySelectorAll(".vote-card").forEach(el => {
        el.style.pointerEvents = "auto";
        el.style.opacity = "1";
    });
    document.getElementById("vote-status").innerText = "";
}

function handlePhaseChange(msg) {
    if (msg.phase === "LOGIN") {
        if(STATE.seatId === null) {
            initLogin();
        } else {
            showScreen("screen-login");
            showWaiting("New round starting... Waiting for instructions.");
        }
    } else if (msg.phase === "VOTE") {
        if(STATE.seatId !== null) showScreen("screen-vote");
    } else if (msg.phase === "GAME") {
        if(STATE.seatId !== null) {
            startGame(msg.map_data);
        }
    } else if (msg.phase === "RESULTS") {
        if(STATE.seatId !== null) showResults(msg.leaderboard);
    }
}

function alerUser(text) {
  const container = document.getElementById("notification-container");
  const notification = document.createElement("div");
  notification.className = "notification";
  notification.innerText = text;
  container.appendChild(notification);
  setTimeout(() => {
    notification.remove();
  }, 3000);
}

const screens = ["screen-login", "screen-vote", "screen-game", "screen-results"];

function showScreen(screenId) {
    const waitMsg = document.getElementById("global-wait");
    if(waitMsg) waitMsg.style.display = "none";
    
    screens.forEach((id) => {
        const screen = document.getElementById(id);
        if (id === screenId) {
            screen.classList.add("active");
        } else {
            screen.classList.remove("active");
        }
    });
}

function showWaiting(text) {
    let waitMsg = document.getElementById("global-wait");
    if(!waitMsg) {
        waitMsg = document.createElement("div");
        waitMsg.id = "global-wait";
        waitMsg.className = "waiting-msg";
        waitMsg.style.textAlign = "center";
        waitMsg.style.fontSize = "1.2rem";
        waitMsg.style.marginTop = "20px";
        waitMsg.style.fontWeight = "bold";
        waitMsg.style.color = "var(--accent-color)";
        document.querySelector(".game-header").insertAdjacentElement('afterend', waitMsg);
    }
    waitMsg.innerText = text;
    waitMsg.style.display = "block";
}

const TOTAL_SEATS = 30; 
const ROWS = 5; 
const COLS = 6;
const DISTRICT_SIZE = 5; 

function initLogin() {
    showScreen("screen-login");
    renderLoginGrid();
}

function renderLoginGrid() {
    const grid = document.getElementById("login-grid");
    grid.innerHTML = "";
    for (let i = 0; i < TOTAL_SEATS; i++) {
        const s = document.createElement("div");
        s.className = "seat open";
        s.dataset.loginId = i;
        s.innerText = i + 1;
        
        if(STATE.seatId === i) {
            s.classList.add("my-seat");
            s.innerText = "ME";
        } 
        else if (STATE.takenSeats.includes(i)) {
            s.classList.add("taken");
            s.classList.remove("open");
        }

        s.onclick = () => {
            if (STATE.seatId !== null) return; 
            if (s.classList.contains("taken")) {
                alerUser("Seat is already occupied.");
                return;
            }
            ws.send(JSON.stringify({ type: "claim_seat", seatId: i, clientId: CLIENT_ID }));
        };
        grid.appendChild(s);
    }
}

function updateLoginGrid() {
    for(let i=0; i<TOTAL_SEATS; i++) {
        const s = document.querySelector(`.seat[data-login-id="${i}"]`);
        if(!s) continue;
        if(STATE.seatId === i) continue;

        if(STATE.takenSeats.includes(i)) {
            s.classList.add("taken");
            s.classList.remove("open");
        } else {
            s.classList.remove("taken");
            s.classList.add("open");
        }
    }
}

function castVote(optionIndex) {
  STATE.partyIndex = optionIndex;
  const partyName = STATE.roundConfig.options[optionIndex];
  
  document.getElementById("vote-status").innerText = `Voted ${partyName}. Waiting for game...`;
  
  if(optionIndex === 0) {
      document.getElementById("btn-party-b").style.opacity = "0.5";
  } else {
      document.getElementById("btn-party-a").style.opacity = "0.5";
  }
  document.querySelectorAll(".vote-card").forEach(el => el.style.pointerEvents = "none");

  ws.send(JSON.stringify({ type: "vote", party: partyName }));
}

function startGame(serverMapData) {
  if(STATE.partyIndex === null) STATE.partyIndex = Math.random() > 0.5 ? 0 : 1; 

  showScreen("screen-game");
  document.getElementById("my-party-display").innerText = STATE.roundConfig.options[STATE.partyIndex];
  document.getElementById("my-party-display").style.color = STATE.roundConfig.colors[STATE.partyIndex];
  document.getElementById("finish-btn").style.display = "none";
  STATE.districts = [];
  STATE.grid = [];
  
  for (let i = 0; i < TOTAL_SEATS; i++) {
    const pIdx = serverMapData[i];
    STATE.grid.push({
      id: i,
      partyIndex: pIdx,
      districtId: null,
    });
  }

  let origWins = 0;
  for (let c = 0; c < 6; c++) {
    let myVotes = 0;
    for (let r = 0; r < 5; r++) {
      const idx = r * 6 + c;
      if (STATE.grid[idx].partyIndex === STATE.partyIndex) myVotes++;
    }
    if (myVotes >= 3) origWins++;
  }

  STATE.origWins = origWins;
  document.getElementById("orig-wins").innerText = origWins;

  renderGameGrid();
  startTimer();

  document.body.addEventListener("mouseup", endDrag);
}

function renderGameGrid() {
  const container = document.getElementById("game-grid");
  container.innerHTML = "";

  STATE.grid.forEach((data, i) => {
    const s = document.createElement("div");
    s.className = "seat";
    s.dataset.id = i;
    s.classList.add(data.partyIndex === 0 ? "party-a" : "party-b");

    const icon = document.createElement("i");
    icon.className = STATE.roundConfig.icons[data.partyIndex];
    s.appendChild(icon);

    s.onmousedown = (e) => startDrag(i);
    s.onmouseenter = (e) => onEnter(i);
    s.onclick = () => handleClick(i);

    if (data.districtId !== null) {
      const d = STATE.districts.find((dst) => dst.id === data.districtId);
      if (d) {
        s.classList.add("district-locked");
        s.classList.add(d.winnerIndex === 0 ? "winner-a" : "winner-b");
      }
    }
    container.appendChild(s);
  });
}

function getXY(index) { return { x: index % COLS, y: Math.floor(index / COLS) }; }
function isAdjacent(idx1, idx2) {
  const p1 = getXY(idx1);
  const p2 = getXY(idx2);
  return Math.abs(p1.x - p2.x) + Math.abs(p1.y - p2.y) === 1;
}
function startDrag(index) {
  if (STATE.grid[index].districtId !== null) return;
  STATE.dragging = true;
  STATE.selection = [index];
  updateHighlights();
}
function onEnter(index) {
  if (!STATE.dragging) return;
  if (STATE.grid[index].districtId !== null) return;
  if (STATE.selection.includes(index)) return;
  if (STATE.selection.length >= DISTRICT_SIZE) return;
  const hasNeighbor = STATE.selection.some((sId) => isAdjacent(sId, index));
  if (hasNeighbor) {
    STATE.selection.push(index);
    updateHighlights();
  }
}
function endDrag() {
  if (!STATE.dragging) return;
  STATE.dragging = false;
  if (STATE.selection.length === DISTRICT_SIZE) createDistrict(STATE.selection);
  STATE.selection = [];
  updateHighlights();
}
function updateHighlights() {
  document.querySelectorAll(".seat.highlight").forEach((el) => el.classList.remove("highlight"));
  STATE.selection.forEach((idx) => {
    const el = document.querySelector(`.seat[data-id="${idx}"]`);
    if (el) el.classList.add("highlight");
  });
}
function createDistrict(indices) {
  const dId = Date.now() + Math.random();
  let myVotes = 0;
  indices.forEach((i) => {
    if (STATE.grid[i].partyIndex === STATE.partyIndex) myVotes++;
  });
  
  const winnerIndex = myVotes >= 3 ? STATE.partyIndex : (STATE.partyIndex === 0 ? 1 : 0);
  
  STATE.districts.push({ id: dId, winnerIndex: winnerIndex, seats: indices });
  indices.forEach((i) => (STATE.grid[i].districtId = dId));
  renderGameGrid();
  updateScore();
}
function handleClick(index) {
  const dId = STATE.grid[index].districtId;
  if (dId !== null) {
    STATE.districts = STATE.districts.filter((d) => d.id !== dId);
    STATE.grid.forEach((s) => { if (s.districtId === dId) s.districtId = null; });
    renderGameGrid();
    updateScore();
  }
}
function updateScore() {
  const count = STATE.districts.length;
  document.getElementById("districts-count").innerText = count;
  let myWins = 0;
  STATE.districts.forEach((d) => { if (d.winnerIndex === STATE.partyIndex) myWins++; });
  STATE.myWins = myWins;
  document.getElementById("my-wins").innerText = myWins;
  const btn = document.getElementById("finish-btn");
  if (count === 6) btn.style.display = "block";
  else btn.style.display = "none";
}

function startTimer() {
  STATE.timer = 60; 
  const el = document.getElementById("game-timer");
  if(STATE.interval) clearInterval(STATE.interval);
  
  STATE.interval = setInterval(() => {
    STATE.timer--;
    let m = Math.floor(STATE.timer / 60);
    let s = STATE.timer % 60;
    el.innerText = `0${m}:${s < 10 ? "0" : ""}${s}`;
    if (STATE.timer <= 0) {
        clearInterval(STATE.interval);
        endGame();
    }
  }, 1000);
}

function endGame() {
  clearInterval(STATE.interval);
  
  let diff = STATE.myWins - STATE.origWins;
  if (diff < 0) diff = 0;
  const pct = Math.round((diff / 6) * 100);
  STATE.scorePct = pct;
  
  ws.send(JSON.stringify({ 
      type: "finish_round", 
      seatId: STATE.seatId, 
      score: pct 
  }));

  showWaiting("Round Finished. Waiting for teacher to show results...");
}

function showResults(leaderboard) {
    showScreen("screen-results");
    document.getElementById("score-percent").innerText = `+${STATE.scorePct}%`;
    
    const list = document.getElementById("lb-list");
    list.innerHTML = "";
    
    leaderboard.slice(0, 5).forEach((b, i) => {
        setTimeout(() => {
            const r = document.createElement("div");
            r.className = "lb-row";
            if (b.name === document.getElementById("user-badge").innerText) r.classList.add("me");
            
            r.innerHTML = `
                <span>${i + 1}. ${b.name}</span>
                <span>
                    <span style="font-size:0.8rem; opacity:0.7;">(+${b.round}%)</span> 
                    +${b.score}%
                </span>`;
            list.appendChild(r);
        }, i * 200);
    });
}

initLogin();