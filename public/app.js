/**
 * BoatRace AI Predictor v2 - Dashboard + Manual Simulation
 *
 * On page load: fetches /data/daily_YYYYMMDD.json and renders
 * upset race cards with tier badges and physics data.
 * Also supports manual exhibition-time input + client-side sim.
 */

// ===== Constants =====
const BOAT_COLORS = ['#ffffff', '#1a1a1a', '#ef4444', '#3b82f6', '#eab308', '#22c55e'];
const BOAT_STROKE = ['#aaa', '#666', '#fff', '#fff', '#000', '#fff'];
const BOAT_BG = ['#fff', '#1a1a1a', '#ef4444', '#3b82f6', '#eab308', '#22c55e'];
const BOAT_FG = ['#000', '#fff', '#fff', '#fff', '#000', '#fff'];
const VENUE_NAMES = {
    '01': '桐生', '02': '戸田', '03': '江戸川', '04': '平和島', '05': '多摩川',
    '06': '浜名湖', '07': '蒲郡', '08': '常滑', '09': '津', '10': '三国',
    '11': 'びわこ', '12': '住之江', '13': '尼崎', '14': '鳴門', '15': '丸亀',
    '16': '児島', '17': '宮島', '18': '徳山', '19': '下関', '20': '若松',
    '21': '芦屋', '22': '福岡', '23': '唐津', '24': '大村',
};
const TIER_CONFIG = {
    tier1: { label: 'Tier 1 荒れ本命', color: '#ef4444', bg: 'rgba(239,68,68,0.15)', border: 'rgba(239,68,68,0.4)' },
    tier2: { label: 'Tier 2 準・勝負', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)', border: 'rgba(245,158,11,0.4)' },
    physics: { label: '物理異常', color: '#a855f7', bg: 'rgba(168,85,247,0.15)', border: 'rgba(168,85,247,0.4)' },
    fallback: { label: '次点ピック', color: '#6366f1', bg: 'rgba(99,102,241,0.15)', border: 'rgba(99,102,241,0.4)' },
};

const PHYSICS_CONST = {
    dt: 0.01, turn_radius_base: 15.0, exhibition_distance: 150,
    wind_effect_coeff: 0.15, wave_effect_coeff: 0.08,
};
const MARK1_X = 15, MARK1_Y = 30, TURN_ANGLE = Math.PI;
const COURSE_X = { 1: 5, 2: 12, 3: 19, 4: 26, 5: 33, 6: 40 };
const COURSE_Y_OFFSET = { 1: 0, 2: 2.5, 3: 5, 4: 7.5, 5: 10, 6: 12.5 };
const COURSE_RADIUS_FACTOR = { 1: 0.65, 2: 0.78, 3: 0.90, 4: 1.00, 5: 1.12, 6: 1.25 };

// ===== State =====
let simResult = null, trajectories = [], playbackFrame = 0, isPlaying = false, playbackInterval = null;

// ====================================================================
// Daily Dashboard - Auto-load JSON
// ====================================================================

async function loadDailyData() {
    const loadingEl = document.getElementById('loading-msg');
    const cardsEl = document.getElementById('race-cards');
    const statsEl = document.getElementById('stats-bar');
    const metaEl = document.getElementById('meta-date');

    // Try today and yesterday
    const today = new Date();
    const dates = [];
    for (let i = 0; i < 3; i++) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
        dates.push(`${y}${m}${day}`);
    }

    let data = null;
    for (const hd of dates) {
        try {
            const res = await fetch(`/data/daily_${hd}.json`);
            if (res.ok) {
                data = await res.json();
                break;
            }
        } catch (e) { /* try next */ }
    }

    if (!data || !data.venues || Object.keys(data.venues).length === 0) {
        loadingEl.innerHTML = '<p class="no-data">本日の予測データはまだありません。<br>GitHub Actions パイプラインの完了をお待ちください。</p>';
        return;
    }

    // Render stats
    if (data.stats) {
        statsEl.style.display = '';
        document.getElementById('stat-scanned').textContent = data.stats.scanned || 0;
        document.getElementById('stat-tier1').textContent = data.stats.tier1 || 0;
        document.getElementById('stat-tier2').textContent = data.stats.tier2 || 0;
        document.getElementById('stat-physics').textContent = data.stats.physics || 0;
        document.getElementById('stat-simulated').textContent = data.stats.simulated || 0;
    }

    metaEl.textContent = `${data.date.replace(/(\d{4})(\d{2})(\d{2})/, '$1/$2/$3')} | 更新: ${new Date(data.ts).toLocaleTimeString('ja-JP')}`;

    // Build race cards
    let html = '';
    for (const [jcd, venueData] of Object.entries(data.venues)) {
        const venueName = venueData.name || VENUE_NAMES[jcd] || jcd;
        for (const [rno, race] of Object.entries(venueData.races)) {
            html += renderRaceCard(venueName, jcd, rno, race);
        }
    }

    cardsEl.innerHTML = html || '<p class="no-data">シミュレーション対象のレースがありませんでした。</p>';
}

function renderRaceCard(venueName, jcd, rno, race) {
    const tier = race.tier || 'tier1';
    const tc = TIER_CONFIG[tier] || TIER_CONFIG.tier1;
    const pred = race.pred || {};
    const sim = race.sim || {};
    const km = race.km || {};
    const tickets = pred.tickets || [];
    const order = pred.predicted_order || sim.order || [];

    // Win rate for boat 1
    const wr1 = race.win1 != null ? race.win1 : '-';

    // Physics data summary
    const physSummary = [];
    if (sim.boats && sim.boats.length > 0) {
        const b1 = sim.boats.find(b => b.n === 1);
        if (b1) {
            physSummary.push(`出口速度: ${b1.ev.toFixed(1)}m/s`);
            physSummary.push(`膨らみ: ${b1.sf.toFixed(2)}x`);
            physSummary.push(`旋回R: ${b1.tr.toFixed(1)}m`);
        }
    }

    // Spread warning
    const spreadWarn = race.spread_warning ? `<span class="spread-alert">${race.spread_warning}</span>` : '';
    const anomalyTag = race.anomaly ? `<span class="anomaly-tag">${race.anomaly}</span>` : '';

    // Ticket rows (top 5)
    const ticketRows = tickets.slice(0, 5).map(t =>
        `<div class="mini-ticket">
            <span class="tk-combo">${t.combo}</span>
            <span class="tk-prob">${t.prob}%</span>
            <span class="tk-amt">&yen;${t.amt.toLocaleString()}</span>
        </div>`
    ).join('');

    // Order badges
    const orderBadges = order.slice(0, 3).map((n, i) => {
        const bi = n - 1;
        return `<span class="order-badge" style="background:${BOAT_BG[bi]};color:${BOAT_FG[bi]};${bi === 1 ? 'border:1px solid #555' : ''}">${n}</span>`;
    }).join('<span class="order-arrow">→</span>');

    return `
    <div class="race-card glass" data-tier="${tier}" style="border-left:4px solid ${tc.color}">
        <div class="race-card-header">
            <div class="race-card-title">
                <span class="venue-name">${venueName}</span>
                <span class="race-num">${rno}R</span>
                <span class="tier-badge" style="background:${tc.bg};color:${tc.color};border:1px solid ${tc.border}">${tc.label}</span>
                ${spreadWarn}${anomalyTag}
            </div>
            <div class="race-card-meta">
                <span class="wr1-tag ${wr1 <= 4.0 ? 'wr-danger' : wr1 <= 5.5 ? 'wr-warning' : 'wr-normal'}">
                    1号艇勝率: ${typeof wr1 === 'number' ? wr1.toFixed(2) : wr1}
                </span>
                <span class="wind-tag">${race.wind || '-'}</span>
                <span class="wave-tag">波${race.wave || 0}cm</span>
            </div>
        </div>
        <div class="race-card-body">
            <div class="race-order-section">
                <div class="race-order-label">予測着順</div>
                <div class="race-order-badges">${orderBadges}</div>
                <div class="race-confidence">確度 ${pred.confidence || sim.confidence || 0}%</div>
            </div>
            <div class="race-kimarite">
                <span class="km-type">${km.type || '-'}</span>
                <span class="km-prob">${km.prob || 0}%</span>
            </div>
            <div class="race-physics">
                ${physSummary.map(s => `<span class="phys-item">${s}</span>`).join('')}
            </div>
        </div>
        ${tickets.length > 0 ? `
        <div class="race-card-tickets">
            <div class="mini-ticket-header">
                <span>舟券</span><span>確率</span><span>金額</span>
            </div>
            ${ticketRows}
        </div>` : ''}
    </div>`;
}


// ====================================================================
// Client-side Physics Engine (for manual simulation)
// ====================================================================

function exhibitionTimeToVelocity(t) {
    return t > 0 ? PHYSICS_CONST.exhibition_distance / t : 20;
}

function windEffect(windSpeed, windDir, heading) {
    const dirs = { '北': 0, '北東': Math.PI / 4, '東': Math.PI / 2, '南東': 3 * Math.PI / 4, '南': Math.PI, '南西': 5 * Math.PI / 4, '西': 3 * Math.PI / 2, '北西': 7 * Math.PI / 4 };
    return PHYSICS_CONST.wind_effect_coeff * windSpeed * Math.cos((dirs[windDir] || 0) - heading);
}

function calcTurnRadius(course, velocity, windSpeed, waveHeight) {
    const cf = COURSE_RADIUS_FACTOR[course] || 1;
    const sf = 1 + 0.05 * Math.max(0, velocity - 20);
    const wvf = 1 + 0.3 * (waveHeight / 100);
    const wf = 1 + 0.1 * windSpeed * 0.5;
    return PHYSICS_CONST.turn_radius_base * cf * sf * wvf * wf;
}

function simulate(exhibTimes, windSpd, windDir, waveH, waterT) {
    const dt = PHYSICS_CONST.dt;
    const boats = exhibTimes.map((et, i) => {
        const course = i + 1;
        const v = exhibitionTimeToVelocity(et);
        return {
            num: course, x: COURSE_X[course], y: 80 + COURSE_Y_OFFSET[course],
            velocity: v, cruiseVelocity: v, heading: Math.PI,
            phase: 'approach', turnProgress: 0,
            turnRadius: calcTurnRadius(course, v, windSpd, waveH),
            exitVelocity: 0, trajectory: [], exitSteps: 0,
        };
    });
    const wavePenalty = 1 - Math.min(0.03, (waveH / 100) * 0.6);
    let t = 0;
    while (t < 15) {
        let allDone = true;
        for (const b of boats) {
            b.trajectory.push({ x: b.x, y: b.y });
            if (b.phase === 'finished') continue;
            allDone = false;
            if (b.phase === 'approach') {
                if (b.y <= MARK1_Y + 5) { b.phase = 'turning'; b.turnProgress = 0; continue; }
                b.velocity = b.cruiseVelocity * wavePenalty;
                b.heading = Math.PI;
                b.x += b.velocity * Math.sin(b.heading) * dt;
                b.y += b.velocity * Math.cos(b.heading) * dt;
            } else if (b.phase === 'turning') {
                const r = b.turnRadius || PHYSICS_CONST.turn_radius_base;
                const targetV = b.cruiseVelocity * 0.70 * (1 - Math.min(0.05, (waveH / 100) * 0.8));
                if (b.velocity > targetV) b.velocity = Math.max(targetV, b.velocity - 8 * dt);
                else b.velocity = Math.min(targetV, b.velocity + 3 * dt);
                const omega = b.velocity / r, dh = omega * dt;
                b.heading -= dh;
                b.turnProgress += dh / TURN_ANGLE;
                b.x += b.velocity * Math.sin(b.heading) * dt;
                b.y += b.velocity * Math.cos(b.heading) * dt;
                if (b.turnProgress >= 1) { b.phase = 'exit'; b.exitVelocity = b.velocity; }
            } else if (b.phase === 'exit') {
                if (b.velocity < b.cruiseVelocity) b.velocity = Math.min(b.cruiseVelocity, b.velocity + 5 * dt);
                b.heading = 0;
                b.x += b.velocity * Math.sin(b.heading) * dt;
                b.y += b.velocity * Math.cos(b.heading) * dt;
                b.exitVelocity = Math.max(b.exitVelocity, b.velocity);
                b.exitSteps++;
                if (b.exitSteps >= 50) b.phase = 'finished';
            }
        }
        t += dt;
        if (allDone) break;
    }
    for (const b of boats) { if (b.exitVelocity === 0) b.exitVelocity = b.velocity; }
    return boats;
}

function calcSpreadFactor(radius, course) {
    const optimal = PHYSICS_CONST.turn_radius_base * (COURSE_RADIUS_FACTOR[course] || 1);
    return optimal > 0 ? radius / optimal : 1;
}

function predictKimarite(boats) {
    const inner = boats[0], outerExitV = boats.slice(1).map(b => b.exitVelocity);
    const maxOuter = Math.max(...outerExitV), avgOuter = outerExitV.reduce((a, b) => a + b, 0) / outerExitV.length;
    const spread = calcSpreadFactor(inner.turnRadius, 1);
    const probs = { '逃げ': 1, '差し': 0, 'まくり': 0, 'まくり差し': 0, '抜き': 0, '恵まれ': 0 };
    if (spread > 1.15) probs['逃げ'] *= Math.max(0.1, 1 - (spread - 1));
    if (inner.exitVelocity < avgOuter && avgOuter > 0) probs['逃げ'] *= Math.max(0.1, inner.exitVelocity / avgOuter);
    if (spread > 1.15) probs['差し'] = Math.min(1, (spread - 1) * 2);
    if (maxOuter > inner.exitVelocity * 1.05 && inner.exitVelocity > 0) probs['まくり'] = Math.min(1, (maxOuter / inner.exitVelocity - 1) * 5);
    if (spread > 1.1 && maxOuter > inner.exitVelocity && inner.exitVelocity > 0) probs['まくり差し'] = Math.min(1, (spread - 1) * 1.5 * (maxOuter / inner.exitVelocity));
    const total = Object.values(probs).reduce((a, b) => a + b, 0);
    for (const k in probs) probs[k] = total > 0 ? probs[k] / total : 0;
    return probs;
}

function calcConfidence(times, windSpd, waveH) {
    let c = 50;
    const valid = times.filter(t => t > 0);
    if (valid.length >= 2) {
        const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
        const variance = valid.reduce((a, t) => a + (t - mean) ** 2, 0) / valid.length;
        c += Math.min(25, variance * 500);
    } else c -= 20;
    if (windSpd <= 2) c += 10; else if (windSpd > 5) c -= 10;
    if (waveH <= 3) c += 10; else if (waveH > 10) c -= 15;
    return Math.max(5, Math.min(95, c));
}

function predictFinishOrder(boats) {
    const scored = boats.map(b => {
        const spread = calcSpreadFactor(b.turnRadius, b.num);
        return { num: b.num, score: b.exitVelocity * 3 - Math.max(0, spread - 1) * 10 - b.y * 0.1, exitV: b.exitVelocity, spread };
    });
    scored.sort((a, b) => b.score - a.score);
    return scored;
}

function generateTickets(order, totalBudget = 10000) {
    const scores = {};
    let totalScore = 0;
    for (const { num, score } of order) {
        const s = Math.max(0.1, score);
        scores[num] = s;
        totalScore += s;
    }
    const probs = {};
    for (const n in scores) probs[n] = scores[n] / totalScore;

    const combos = [];
    const nums = order.map(o => o.num);
    // Amplify differences for trifecta probability
    const ampProbs = {};
    const maxP = Math.max(...Object.values(probs));
    for (const n in probs) {
        ampProbs[n] = Math.pow(probs[n] / maxP, 1.5) * maxP; // power amplification
    }
    const ampTotal = Object.values(ampProbs).reduce((a, b) => a + b, 0);
    for (const n in ampProbs) ampProbs[n] /= ampTotal;

    for (let i = 0; i < Math.min(6, nums.length); i++) {
        for (let j = 0; j < Math.min(6, nums.length); j++) {
            if (j === i) continue;
            for (let k = 0; k < Math.min(6, nums.length); k++) {
                if (k === i || k === j) continue;
                const a = nums[i], b = nums[j], c = nums[k];
                const pa = ampProbs[a], pb = ampProbs[b], pc = ampProbs[c];
                const p = pa * (pb / (1 - pa)) * (pc / (1 - pa - pb));
                combos.push({ combo: `${a}-${b}-${c}`, prob: p });
            }
        }
    }
    combos.sort((a, b) => b.prob - a.prob);
    const top = combos.slice(0, 15);
    const pTotal = top.reduce((s, t) => s + t.prob, 0);
    let tickets = top.map(t => ({
        combo: t.combo,
        prob: +(t.prob * 100).toFixed(2),
        amount: Math.max(100, Math.round(totalBudget * (t.prob / pTotal) / 100) * 100),
    }));
    let sum = tickets.reduce((s, t) => s + t.amount, 0);
    while (sum > totalBudget && tickets.length > 1) {
        tickets[tickets.length - 1].amount -= 100;
        if (tickets[tickets.length - 1].amount < 100) tickets.pop();
        sum = tickets.reduce((s, t) => s + t.amount, 0);
    }
    const remainder = totalBudget - sum;
    if (remainder >= 100 && tickets.length > 0) tickets[0].amount += Math.floor(remainder / 100) * 100;
    return tickets;
}

function decideStrategy(confidence) {
    if (confidence >= 70) return { level: 'high', icon: '🎯', badge: 'シミュレーション予想に従う', reasoning: `物理的確度 ${confidence.toFixed(1)}% — 高水準。展示タイムの差が明確で安定。`, action: 'シミュレーション予想通りの舟券購入を推奨' };
    if (confidence >= 40) return { level: 'medium', icon: '⚠️', badge: '高オッズ狙い', reasoning: `物理的確度 ${confidence.toFixed(1)}% — 中程度。荒れる可能性あり。`, action: '5,6号艇絡みの高オッズ3連単に少額投資' };
    return { level: 'low', icon: '🚫', badge: 'このレースは見送り', reasoning: `物理的確度 ${confidence.toFixed(1)}% — 低い。見送り推奨。`, action: 'このレースは見送り — 資金温存' };
}


// ====================================================================
// Run Manual Simulation
// ====================================================================

function runSimulation() {
    const times = [];
    for (let i = 1; i <= 6; i++) times.push(parseFloat(document.getElementById(`ex-${i}`).value) || 6.8);
    const windSpd = parseFloat(document.getElementById('wind-speed').value) || 0;
    const windDir = document.getElementById('wind-direction').value;
    const waveH = parseFloat(document.getElementById('wave-height').value) || 0;
    const waterT = parseFloat(document.getElementById('water-temp').value) || 20;

    const boats = simulate(times, windSpd, windDir, waveH, waterT);
    trajectories = boats.map(b => b.trajectory);
    const order = predictFinishOrder(boats);
    const kimarite = predictKimarite(boats);
    const confidence = calcConfidence(times, windSpd, waveH);
    const tickets = generateTickets(order);
    const strategy = decideStrategy(confidence);

    simResult = { boats, order, kimarite, confidence, tickets, strategy };

    document.getElementById('simulation').style.display = '';
    document.getElementById('prediction').style.display = '';
    document.getElementById('strategy').style.display = '';

    resizeCanvas();
    renderCanvas();
    renderConfidence(confidence);
    renderConditions(windSpd, windDir, waveH, waterT);
    renderKimarite(kimarite);
    renderOrder(order, boats);
    renderTickets(tickets);
    renderStrategy(strategy);

    resetPlayback();
    startPlayback();
    document.getElementById('simulation').scrollIntoView({ behavior: 'smooth' });
}


// ====================================================================
// Responsive Canvas
// ====================================================================

function resizeCanvas() {
    const canvas = document.getElementById('sim-canvas');
    const container = canvas.parentElement;
    const w = container.clientWidth;
    const h = Math.min(500, Math.round(w * 0.625)); // 5:8 aspect ratio
    canvas.width = w * (window.devicePixelRatio || 1);
    canvas.height = h * (window.devicePixelRatio || 1);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
}

function renderCanvas() {
    const canvas = document.getElementById('sim-canvas');
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr, H = canvas.height / dpr;

    const scaleX = W / 60, scaleY = H / 120, offsetY = 15;
    const toCanvas = (x, y) => [x * scaleX, H - (y - offsetY) * scaleY];

    ctx.clearRect(0, 0, W, H);
    const gradient = ctx.createLinearGradient(0, 0, 0, H);
    gradient.addColorStop(0, '#0d2137');
    gradient.addColorStop(1, '#061018');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, W, H);

    // Grid
    ctx.strokeStyle = 'rgba(100,140,200,0.08)';
    ctx.lineWidth = 1;
    for (let i = 0; i < W; i += 50) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, H); ctx.stroke(); }
    for (let i = 0; i < H; i += 50) { ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(W, i); ctx.stroke(); }

    // 1 Mark
    const [mx, my] = toCanvas(MARK1_X, MARK1_Y);
    ctx.beginPath(); ctx.arc(mx, my, 8, 0, Math.PI * 2);
    ctx.fillStyle = '#ff6b35'; ctx.fill();
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = '#fff'; ctx.font = '10px Inter'; ctx.textAlign = 'center';
    ctx.fillText('1M', mx, my + 22);

    // Trajectories
    for (let i = 0; i < trajectories.length; i++) {
        const traj = trajectories[i];
        if (traj.length < 2) continue;
        ctx.beginPath();
        const [sx, sy] = toCanvas(traj[0].x, traj[0].y);
        ctx.moveTo(sx, sy);
        const step = Math.max(1, Math.floor(traj.length / 300));
        for (let j = step; j < traj.length; j += step) {
            const [px, py] = toCanvas(traj[j].x, traj[j].y);
            ctx.lineTo(px, py);
        }
        ctx.strokeStyle = BOAT_COLORS[i] + '30'; ctx.lineWidth = 2; ctx.stroke();
    }
    return { ctx, W, H, scaleX, scaleY, offsetY, toCanvas };
}

function renderPlaybackFrame(frame) {
    const r = renderCanvas();
    const { ctx, toCanvas } = r;
    for (let i = 0; i < trajectories.length; i++) {
        const traj = trajectories[i];
        const endIdx = Math.min(frame, traj.length - 1);
        if (endIdx < 1) continue;
        ctx.beginPath();
        const [sx, sy] = toCanvas(traj[0].x, traj[0].y);
        ctx.moveTo(sx, sy);
        const step = Math.max(1, Math.floor(endIdx / 200));
        for (let j = step; j <= endIdx; j += step) {
            const [px, py] = toCanvas(traj[j].x, traj[j].y);
            ctx.lineTo(px, py);
        }
        ctx.strokeStyle = BOAT_COLORS[i] + 'cc'; ctx.lineWidth = 3; ctx.stroke();
        const [bx, by] = toCanvas(traj[endIdx].x, traj[endIdx].y);
        ctx.beginPath(); ctx.arc(bx, by, 7, 0, Math.PI * 2);
        ctx.fillStyle = BOAT_COLORS[i]; ctx.fill();
        ctx.strokeStyle = BOAT_STROKE[i]; ctx.lineWidth = 2; ctx.stroke();
        ctx.fillStyle = i === 1 ? '#fff' : '#000';
        ctx.font = 'bold 9px Inter'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(String(i + 1), bx, by);
    }
}

// ====================================================================
// Playback
// ====================================================================
function startPlayback() {
    if (isPlaying) return;
    isPlaying = true;
    document.getElementById('play-btn').textContent = '⏸';
    const speed = parseInt(document.getElementById('speed-slider').value), step = speed * 5;
    const maxFrame = Math.max(...trajectories.map(t => t.length));
    playbackInterval = setInterval(() => {
        playbackFrame += step;
        if (playbackFrame >= maxFrame) { playbackFrame = maxFrame - 1; stopPlayback(); }
        renderPlaybackFrame(playbackFrame);
    }, 16);
}
function stopPlayback() { isPlaying = false; document.getElementById('play-btn').textContent = '▶'; clearInterval(playbackInterval); }
function togglePlayback() { isPlaying ? stopPlayback() : startPlayback(); }
function resetPlayback() { stopPlayback(); playbackFrame = 0; renderPlaybackFrame(0); }

document.getElementById('speed-slider').addEventListener('input', (e) => {
    document.getElementById('speed-val').textContent = e.target.value;
    if (isPlaying) { stopPlayback(); startPlayback(); }
});

// ====================================================================
// UI Renderers
// ====================================================================

function renderConfidence(conf) {
    const circle = document.getElementById('conf-circle');
    const circumference = 2 * Math.PI * 52;
    circle.style.strokeDashoffset = circumference * (1 - conf / 100);
    const color = conf >= 70 ? '#22c55e' : conf >= 40 ? '#f59e0b' : '#ef4444';
    circle.style.stroke = color;
    const val = document.getElementById('confidence-val');
    val.textContent = conf.toFixed(1) + '%'; val.style.color = color;
}

function renderConditions(wind, dir, wave, temp) {
    document.getElementById('condition-list').innerHTML = [
        { label: '風速', value: `${wind} m/s` }, { label: '風向', value: dir },
        { label: '波高', value: `${wave} cm` }, { label: '水温', value: `${temp} ℃` },
    ].map(c => `<div class="condition-row"><span class="condition-label">${c.label}</span><span class="condition-value">${c.value}</span></div>`).join('');
}

function renderKimarite(probs) {
    document.getElementById('kimarite-bars').innerHTML = ['逃げ', '差し', 'まくり', 'まくり差し', '抜き', '恵まれ'].map(name => {
        const pct = ((probs[name] || 0) * 100).toFixed(1);
        return `<div class="kimarite-row"><span class="kimarite-name">${name}</span><div class="kimarite-bar-bg"><div class="kimarite-bar-fg" style="width:${pct}%"></div></div><span class="kimarite-pct">${pct}%</span></div>`;
    }).join('');
}

function renderOrder(order, boats) {
    document.getElementById('order-display').innerHTML = order.slice(0, 6).map((o, idx) => {
        const bi = o.num - 1;
        return `<div class="order-item ${idx < 3 ? `rank-${idx + 1}` : ''}"><span class="order-rank ${idx < 3 ? `r${idx + 1}` : ''}">${idx + 1}</span><span class="order-boat" style="background:${BOAT_BG[bi]};color:${BOAT_FG[bi]};${bi === 1 ? 'border:1px solid #555' : ''}">${o.num}</span><span style="font-weight:600;font-size:0.9rem">${o.num}号艇</span><span class="order-speed">${o.exitV.toFixed(1)} m/s</span></div>`;
    }).join('');
}

function renderTickets(tickets) {
    const total = tickets.reduce((s, t) => s + t.amount, 0);
    document.getElementById('total-budget').textContent = `(合計 ¥${total.toLocaleString()})`;
    document.getElementById('ticket-table').innerHTML = `<div class="ticket-row ticket-header"><span>舟券</span><span>確率</span><span>金額</span><span>比率</span></div>` +
        tickets.map(t => `<div class="ticket-row"><span class="ticket-combo">${t.combo}</span><span class="ticket-prob">${t.prob}%</span><span class="ticket-amount">¥${t.amount.toLocaleString()}</span><span style="color:var(--text-muted)">${(t.amount / total * 100).toFixed(0)}%</span></div>`).join('');
}

function renderStrategy(strategy) {
    document.getElementById('strategy-content').innerHTML = `<div class="strategy-badge ${strategy.level}">${strategy.icon} ${strategy.badge}</div><div class="strategy-reasoning">${strategy.reasoning}</div><div class="strategy-action">📌 ${strategy.action}</div>`;
}


// ====================================================================
// Init
// ====================================================================
window.addEventListener('resize', () => {
    if (simResult) resizeCanvas();
});

// Load daily data on page load
document.addEventListener('DOMContentLoaded', loadDailyData);
