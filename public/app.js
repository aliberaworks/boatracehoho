/**
 * BoatRace AI Predictor - フロントエンドアプリケーション
 * 物理シミュレーション計算はすべてクライアントサイドで実行
 */

// ===== Constants =====
const BOAT_COLORS = ['#ffffff', '#1a1a1a', '#ef4444', '#3b82f6', '#eab308', '#22c55e'];
const BOAT_STROKE = ['#aaa', '#666', '#fff', '#fff', '#000', '#fff'];
const PHYSICS = {
    dt: 0.01,
    turn_radius_base: 15.0,
    exhibition_distance: 150,
    boat_mass: 160,
    wind_effect_coeff: 0.15,
    wave_effect_coeff: 0.08,
    water_density: 1000,
};

// Course layout
const MARK1_X = 15, MARK1_Y = 30, TURN_ANGLE = Math.PI;
const COURSE_X = { 1: 5, 2: 12, 3: 19, 4: 26, 5: 33, 6: 40 };
const COURSE_Y_OFFSET = { 1: 0, 2: 2.5, 3: 5, 4: 7.5, 5: 10, 6: 12.5 };
const COURSE_RADIUS_FACTOR = { 1: 0.65, 2: 0.78, 3: 0.90, 4: 1.00, 5: 1.12, 6: 1.25 };

// ===== State =====
let simResult = null;
let trajectories = [];
let playbackFrame = 0;
let isPlaying = false;
let playbackInterval = null;

// ===== Physics Engine (Client-side) =====
function exhibitionTimeToVelocity(t) {
    return t > 0 ? PHYSICS.exhibition_distance / t : 20;
}

function windEffect(windSpeed, windDir, heading) {
    const dirs = { '北': 0, '北東': Math.PI / 4, '東': Math.PI / 2, '南東': 3 * Math.PI / 4, '南': Math.PI, '南西': 5 * Math.PI / 4, '西': 3 * Math.PI / 2, '北西': 7 * Math.PI / 4 };
    const angle = dirs[windDir] || 0;
    return PHYSICS.wind_effect_coeff * windSpeed * Math.cos(angle - heading);
}

function calcTurnRadius(course, velocity, windSpeed, waveHeight) {
    const base = PHYSICS.turn_radius_base;
    const cf = COURSE_RADIUS_FACTOR[course] || 1;
    const sf = 1 + 0.05 * Math.max(0, velocity - 20);
    const wvf = 1 + 0.3 * (waveHeight / 100);
    const wf = 1 + 0.1 * windSpeed * 0.5;
    return base * cf * sf * wvf * wf;
}

function simulate(exhibTimes, windSpd, windDir, waveH, waterT) {
    const dt = PHYSICS.dt;
    const boats = exhibTimes.map((et, i) => {
        const course = i + 1;
        const v = exhibitionTimeToVelocity(et);
        return {
            num: course,
            x: COURSE_X[course],
            y: 80 + COURSE_Y_OFFSET[course],
            velocity: v,
            cruiseVelocity: v,
            heading: Math.PI,
            phase: 'approach',
            turnProgress: 0,
            turnRadius: calcTurnRadius(course, v, windSpd, waveH),
            exitVelocity: 0,
            trajectory: [],
            exitSteps: 0,
        };
    });

    const wavePenalty = 1 - Math.min(0.03, (waveH / 100) * 0.6);
    const maxTime = 15;
    let t = 0;

    while (t < maxTime) {
        let allDone = true;
        for (const b of boats) {
            b.trajectory.push({ x: b.x, y: b.y });
            if (b.phase === 'finished') continue;
            allDone = false;

            if (b.phase === 'approach') {
                if (b.y <= MARK1_Y + 5) {
                    b.phase = 'turning';
                    b.turnProgress = 0;
                    continue;
                }
                b.velocity = b.cruiseVelocity * wavePenalty;
                b.heading = Math.PI;
                b.x += b.velocity * Math.sin(b.heading) * dt;
                b.y += b.velocity * Math.cos(b.heading) * dt;
            } else if (b.phase === 'turning') {
                let r = b.turnRadius || PHYSICS.turn_radius_base;
                const targetV = b.cruiseVelocity * 0.70 * (1 - Math.min(0.05, (waveH / 100) * 0.8));
                if (b.velocity > targetV) b.velocity = Math.max(targetV, b.velocity - 8 * dt);
                else b.velocity = Math.min(targetV, b.velocity + 3 * dt);
                const omega = b.velocity / r;
                const dh = omega * dt;
                b.heading -= dh;
                b.turnProgress += dh / TURN_ANGLE;
                b.x += b.velocity * Math.sin(b.heading) * dt;
                b.y += b.velocity * Math.cos(b.heading) * dt;
                if (b.turnProgress >= 1) {
                    b.phase = 'exit';
                    b.exitVelocity = b.velocity;
                }
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

    // Fallback for boats that never finished
    for (const b of boats) {
        if (b.exitVelocity === 0) b.exitVelocity = b.velocity;
    }

    return boats;
}

function calcSpreadFactor(radius, course) {
    const optimal = PHYSICS.turn_radius_base * (COURSE_RADIUS_FACTOR[course] || 1);
    return optimal > 0 ? radius / optimal : 1;
}

function predictKimarite(boats) {
    const inner = boats[0];
    const outerExitV = boats.slice(1).map(b => b.exitVelocity);
    const maxOuter = Math.max(...outerExitV);
    const avgOuter = outerExitV.reduce((a, b) => a + b, 0) / outerExitV.length;
    const spread = calcSpreadFactor(inner.turnRadius, 1);

    const probs = { '逃げ': 1, '差し': 0, 'まくり': 0, 'まくり差し': 0, '抜き': 0, '恵まれ': 0 };
    if (spread > 1.15) probs['逃げ'] *= Math.max(0.1, 1 - (spread - 1));
    if (inner.exitVelocity < avgOuter && avgOuter > 0) probs['逃げ'] *= Math.max(0.1, inner.exitVelocity / avgOuter);
    if (spread > 1.15) { probs['差し'] = Math.min(1, (spread - 1) * 2); }
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
    } else { c -= 20; }
    if (windSpd <= 2) c += 10; else if (windSpd > 5) c -= 10;
    if (waveH <= 3) c += 10; else if (waveH > 10) c -= 15;
    return Math.max(5, Math.min(95, c));
}

function predictFinishOrder(boats) {
    const scored = boats.map(b => {
        const spread = calcSpreadFactor(b.turnRadius, b.num);
        const score = b.exitVelocity * 3 - Math.max(0, spread - 1) * 10 - b.y * 0.1;
        return { num: b.num, score, exitV: b.exitVelocity, spread };
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

    // Generate top trifecta combos
    const combos = [];
    const nums = order.map(o => o.num);
    for (let i = 0; i < Math.min(6, nums.length); i++) {
        for (let j = 0; j < Math.min(6, nums.length); j++) {
            if (j === i) continue;
            for (let k = 0; k < Math.min(6, nums.length); k++) {
                if (k === i || k === j) continue;
                const a = nums[i], b = nums[j], c = nums[k];
                const p = probs[a] * (probs[b] / (1 - probs[a])) * (probs[c] / (1 - probs[a] - probs[b]));
                combos.push({ combo: `${a}-${b}-${c}`, prob: p });
            }
        }
    }
    combos.sort((a, b) => b.prob - a.prob);

    // Allocate budget
    const top = combos.slice(0, 15);
    const pTotal = top.reduce((s, t) => s + t.prob, 0);
    let tickets = top.map(t => ({
        combo: t.combo,
        prob: +(t.prob * 100).toFixed(2),
        amount: Math.max(100, Math.round(totalBudget * (t.prob / pTotal) / 100) * 100),
    }));

    // Adjust to budget
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
    if (confidence >= 70) return {
        level: 'high', icon: '🎯',
        badge: 'シミュレーション予想に従う',
        reasoning: `物理的確度 ${confidence.toFixed(1)}% は高水準。展示タイムの差が明確で、風・波の条件も安定しているため、シミュレーション予想の信頼性が高い。`,
        action: 'シミュレーション予想に従って舟券購入を推奨',
    };
    if (confidence >= 40) return {
        level: 'medium', icon: '⚠️',
        badge: '高オッズ狙い',
        reasoning: `物理的確度 ${confidence.toFixed(1)}% は中程度。荒れる可能性があるため、5,6号艇絡みの高オッズ3連単に絞った少額投資が有効。`,
        action: '5,6号艇絡みの高オッズ3連単に少額投資',
    };
    return {
        level: 'low', icon: '🚫',
        badge: 'このレースは見送り',
        reasoning: `物理的確度 ${confidence.toFixed(1)}% は非常に低い。予測困難であり、見送りを推奨する。資金を温存し、確度の高いレースに集中すべき。`,
        action: 'このレースは見送り — 資金温存推奨',
    };
}

// ===== Run Simulation =====
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

    // Show sections
    document.getElementById('simulation').style.display = '';
    document.getElementById('prediction').style.display = '';
    document.getElementById('strategy').style.display = '';

    renderCanvas();
    renderConfidence(confidence);
    renderConditions(windSpd, windDir, waveH, waterT);
    renderKimarite(kimarite);
    renderOrder(order, boats);
    renderTickets(tickets);
    renderStrategy(strategy);

    // Start playback
    resetPlayback();
    startPlayback();

    // Scroll to simulation
    document.getElementById('simulation').scrollIntoView({ behavior: 'smooth' });
}

// ===== Canvas Rendering =====
function renderCanvas() {
    const canvas = document.getElementById('sim-canvas');
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;

    // Scale: sim coords → canvas
    const scaleX = W / 60, scaleY = H / 120, offsetY = 15;
    const toCanvas = (x, y) => [x * scaleX, H - (y - offsetY) * scaleY];

    ctx.clearRect(0, 0, W, H);

    // Water
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

    // 1 Mark buoy
    const [mx, my] = toCanvas(MARK1_X, MARK1_Y);
    ctx.beginPath();
    ctx.arc(mx, my, 8, 0, Math.PI * 2);
    ctx.fillStyle = '#ff6b35';
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = '#fff';
    ctx.font = '10px Inter';
    ctx.textAlign = 'center';
    ctx.fillText('1M', mx, my + 22);

    // Trajectories — full (dimmed)
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
        ctx.strokeStyle = BOAT_COLORS[i] + '30';
        ctx.lineWidth = 2;
        ctx.stroke();
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

        // Active trail
        ctx.beginPath();
        const [sx, sy] = toCanvas(traj[0].x, traj[0].y);
        ctx.moveTo(sx, sy);
        const step = Math.max(1, Math.floor(endIdx / 200));
        for (let j = step; j <= endIdx; j += step) {
            const [px, py] = toCanvas(traj[j].x, traj[j].y);
            ctx.lineTo(px, py);
        }
        ctx.strokeStyle = BOAT_COLORS[i] + 'cc';
        ctx.lineWidth = 3;
        ctx.stroke();

        // Boat dot
        const [bx, by] = toCanvas(traj[endIdx].x, traj[endIdx].y);
        ctx.beginPath();
        ctx.arc(bx, by, 7, 0, Math.PI * 2);
        ctx.fillStyle = BOAT_COLORS[i];
        ctx.fill();
        ctx.strokeStyle = BOAT_STROKE[i];
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = i === 1 ? '#fff' : '#000';
        ctx.font = 'bold 9px Inter';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(i + 1), bx, by);
    }
}

// ===== Playback =====
function startPlayback() {
    if (isPlaying) return;
    isPlaying = true;
    document.getElementById('play-btn').textContent = '⏸';
    const speed = parseInt(document.getElementById('speed-slider').value);
    const step = speed * 5;
    const maxFrame = Math.max(...trajectories.map(t => t.length));

    playbackInterval = setInterval(() => {
        playbackFrame += step;
        if (playbackFrame >= maxFrame) {
            playbackFrame = maxFrame - 1;
            stopPlayback();
        }
        renderPlaybackFrame(playbackFrame);
    }, 16);
}

function stopPlayback() {
    isPlaying = false;
    document.getElementById('play-btn').textContent = '▶';
    clearInterval(playbackInterval);
}

function togglePlayback() {
    isPlaying ? stopPlayback() : startPlayback();
}

function resetPlayback() {
    stopPlayback();
    playbackFrame = 0;
    renderPlaybackFrame(0);
}

document.getElementById('speed-slider').addEventListener('input', (e) => {
    document.getElementById('speed-val').textContent = e.target.value;
    if (isPlaying) {
        stopPlayback();
        startPlayback();
    }
});

// ===== UI Renderers =====
function renderConfidence(conf) {
    const pct = conf / 100;
    const circle = document.getElementById('conf-circle');
    const circumference = 2 * Math.PI * 52;
    circle.style.strokeDashoffset = circumference * (1 - pct);

    const color = conf >= 70 ? '#22c55e' : conf >= 40 ? '#f59e0b' : '#ef4444';
    circle.style.stroke = color;
    const val = document.getElementById('confidence-val');
    val.textContent = conf.toFixed(1) + '%';
    val.style.color = color;
}

function renderConditions(wind, dir, wave, temp) {
    const list = document.getElementById('condition-list');
    list.innerHTML = [
        { label: '風速', value: `${wind} m/s` },
        { label: '風向', value: dir },
        { label: '波高', value: `${wave} cm` },
        { label: '水温', value: `${temp} ℃` },
    ].map(c => `
        <div class="condition-row">
            <span class="condition-label">${c.label}</span>
            <span class="condition-value">${c.value}</span>
        </div>
    `).join('');
}

function renderKimarite(probs) {
    const container = document.getElementById('kimarite-bars');
    const names = ['逃げ', '差し', 'まくり', 'まくり差し', '抜き', '恵まれ'];
    container.innerHTML = names.map(name => {
        const pct = ((probs[name] || 0) * 100).toFixed(1);
        return `
            <div class="kimarite-row">
                <span class="kimarite-name">${name}</span>
                <div class="kimarite-bar-bg">
                    <div class="kimarite-bar-fg" style="width:${pct}%"></div>
                </div>
                <span class="kimarite-pct">${pct}%</span>
            </div>
        `;
    }).join('');
}

function renderOrder(order, boats) {
    const container = document.getElementById('order-display');
    const boatBg = ['#fff', '#1a1a1a', '#ef4444', '#3b82f6', '#eab308', '#22c55e'];
    const boatFg = ['#000', '#fff', '#fff', '#fff', '#000', '#fff'];

    container.innerHTML = order.slice(0, 6).map((o, idx) => {
        const rankClass = idx < 3 ? `rank-${idx + 1}` : '';
        const rClass = idx < 3 ? `r${idx + 1}` : '';
        const bi = o.num - 1;
        return `
            <div class="order-item ${rankClass}">
                <span class="order-rank ${rClass}">${idx + 1}</span>
                <span class="order-boat" style="background:${boatBg[bi]};color:${boatFg[bi]};${bi === 1 ? 'border:1px solid #555' : ''}">${o.num}</span>
                <span style="font-weight:600;font-size:0.9rem">${o.num}号艇</span>
                <span class="order-speed">${o.exitV.toFixed(1)} m/s</span>
            </div>
        `;
    }).join('');
}

function renderTickets(tickets) {
    const container = document.getElementById('ticket-table');
    const total = tickets.reduce((s, t) => s + t.amount, 0);
    document.getElementById('total-budget').textContent = `(合計 ¥${total.toLocaleString()})`;

    container.innerHTML = `
        <div class="ticket-row ticket-header">
            <span>舟券</span>
            <span>確率</span>
            <span>金額</span>
            <span>比率</span>
        </div>
    ` + tickets.map(t => `
        <div class="ticket-row">
            <span class="ticket-combo">${t.combo}</span>
            <span class="ticket-prob">${t.prob}%</span>
            <span class="ticket-amount">¥${t.amount.toLocaleString()}</span>
            <span style="color:var(--text-muted)">${(t.amount / total * 100).toFixed(0)}%</span>
        </div>
    `).join('');
}

function renderStrategy(strategy) {
    const container = document.getElementById('strategy-content');
    container.innerHTML = `
        <div class="strategy-badge ${strategy.level}">
            ${strategy.icon} ${strategy.badge}
        </div>
        <div class="strategy-reasoning">${strategy.reasoning}</div>
        <div class="strategy-action">📌 ${strategy.action}</div>
    `;
}
