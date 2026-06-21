/**
 * 没丢 - 前端交互逻辑 v6
 * 多用户注册登录 + 结构化登记（单条/批量）+ 自然语言查找
 */

const API_VOICE = '/api/voice';
const API_RECORD = '/api/record';

let currentMode = 'auto';

// ══════════════════════════════════════════════════
//  Token 管理
// ══════════════════════════════════════════════════

const TOKEN_KEY = 'nodi_token';
const USERNAME_KEY = 'nodi_username';

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USERNAME_KEY); }

function api(url, options = {}) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(url, { ...options, headers }).then(r => r.json());
}

// ══════════════════════════════════════════════════
//  登录 / 注册
// ══════════════════════════════════════════════════

const authPage = document.getElementById('authPage');
const appDiv = document.getElementById('app');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const loginError = document.getElementById('loginError');
const regError = document.getElementById('regError');
const logoutBtn = document.getElementById('logoutBtn');

function showLogin() {
    loginForm.classList.remove('hidden');
    registerForm.classList.add('hidden');
    loginError.classList.add('hidden');
    regError.classList.add('hidden');
}

function showRegister() {
    registerForm.classList.remove('hidden');
    loginForm.classList.add('hidden');
    loginError.classList.add('hidden');
    regError.classList.add('hidden');
}

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    try {
        const resp = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await resp.json();
        if (data.ok) {
            setToken(data.token);
            localStorage.setItem(USERNAME_KEY, username);
            showApp();
        } else {
            loginError.textContent = data.error || '登录失败';
            loginError.classList.remove('hidden');
        }
    } catch {
        loginError.textContent = '网络错误';
        loginError.classList.remove('hidden');
    }
});

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('regUsername').value.trim();
    const password = document.getElementById('regPassword').value;
    try {
        const resp = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await resp.json();
        if (data.ok) {
            setToken(data.token);
            localStorage.setItem(USERNAME_KEY, username);
            showApp();
        } else {
            regError.textContent = data.error || '注册失败';
            regError.classList.remove('hidden');
        }
    } catch {
        regError.textContent = '网络错误';
        regError.classList.remove('hidden');
    }
});

logoutBtn.addEventListener('click', async () => {
    try {
        await api('/api/logout', { method: 'POST' });
    } catch { /* 忽略 */ }
    clearToken();
    hideApp();
});

function showApp() {
    authPage.classList.add('hidden');
    appDiv.classList.remove('hidden');
    loadLogSection();
}

function hideApp() {
    authPage.classList.remove('hidden');
    appDiv.classList.add('hidden');
    document.getElementById('loginUsername').value = '';
    document.getElementById('loginPassword').value = '';
    document.getElementById('regUsername').value = '';
    document.getElementById('regPassword').value = '';
}

// 自动检测 token
(async () => {
    const token = getToken();
    if (token) {
        try {
            const data = await api('/api/recent');
            if (data.ok !== undefined) {
                showApp();
                return;
            }
        } catch { /* token 失效 */ }
        clearToken();
    }
    hideApp();
})();

// ══════════════════════════════════════════════════
//  DOM 引用
// ══════════════════════════════════════════════════

const textInput = document.getElementById('textInput');
const submitBtn = document.getElementById('submitBtn');
const resultArea = document.getElementById('result');
const logList = document.getElementById('logList');
const logCount = document.getElementById('logCount');
const boxesGrid = document.getElementById('boxesGrid');
const boxesHeader = document.getElementById('boxesHeader');
const drawerItemsView = document.getElementById('drawerItemsView');
const drawerItemsTitle = document.getElementById('drawerItemsTitle');
const drawerItemsList = document.getElementById('drawerItemsList');
const manualInput = document.getElementById('manualInput');
const recordForm = document.getElementById('recordForm');

// ══════════════════════════════════════════════════
//  自然语言查找（find 模式走 /api/voice）
// ══════════════════════════════════════════════════

function submitText(text) {
    if (!text || !text.trim()) return;
    text = text.trim();
    textInput.value = '';
    submitBtn.disabled = true;
    processVoice(text);
}

textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        submitText(textInput.value);
    }
});

submitBtn.addEventListener('click', () => {
    submitText(textInput.value);
});

textInput.addEventListener('input', () => {
    submitBtn.disabled = !textInput.value.trim();
});

async function processVoice(text) {
    if (!text) return;
    resultArea.classList.remove('hidden');
    resultArea.innerHTML = '<div class="result-loading">处理中...</div>';
    try {
        const data = await api(API_VOICE, {
            method: 'POST',
            body: JSON.stringify({ text })
        });
        if (!data.ok) {
            resultArea.innerHTML = `<div class="result-error">${data.error || data.msg || '处理失败，请重试'}</div>`;
        } else {
            showResult(data);
        }
        loadLogSection();
    } catch {
        resultArea.innerHTML = '<div class="result-error">网络错误，请重试</div>';
    }
}

function showResult(data) {
    let html = '';
    if (data.msg) {
        html += `<div class="result-msg">${escapeHtml(data.msg)}</div>`;
    }
    if (data.results && data.results.length > 0) {
        html += '<div class="result-items">';
        data.results.forEach(r => {
            const expStr = r.expiry ? ` <span class="result-item-expiry">至${escapeHtml(r.expiry)}</span>` : '';
            const purpStr = r.purpose ? ` <span class="result-item-purpose">${escapeHtml(r.purpose)}</span>` : '';
            html += `<div class="result-item"><span class="result-item-name">${escapeHtml(r.item)}</span><span class="result-item-drawer">${escapeHtml(r.drawer)}</span>${purpStr}${expStr}</div>`;
        });
        html += '</div>';
    }
    resultArea.innerHTML = html;
}

function escapeHtml(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

// ══════════════════════════════════════════════════
//  日期解析（支持 8 位数字 YYYYMMDD 和 YYYY-MM-DD）
// ══════════════════════════════════════════════════

function parseDate(str) {
    if (!str || !str.trim()) return '';
    str = str.trim();

    // 8 位纯数字：20260630 → 2026-06-30
    if (/^\d{8}$/.test(str)) {
        const y = str.slice(0, 4);
        const m = str.slice(4, 6);
        const d = str.slice(6, 8);
        // 基本合法性校验
        const month = parseInt(m, 10);
        const day = parseInt(d, 10);
        if (month < 1 || month > 12 || day < 1 || day > 31) return '';
        return `${y}-${m}-${d}`;
    }

    // YYYY-MM-DD 或 YYYY/MM/DD
    const m = str.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
    if (m) {
        const y = m[1];
        const mo = m[2].padStart(2, '0');
        const d = m[3].padStart(2, '0');
        const month = parseInt(mo, 10);
        const day = parseInt(d, 10);
        if (month < 1 || month > 12 || day < 1 || day > 31) return '';
        return `${y}-${mo}-${d}`;
    }

    // 无法识别，原样返回（留给后端处理）
    return str;
}

// ══════════════════════════════════════════════════
//  登记表单 — 待提交记录管理
// ══════════════════════════════════════════════════

let pendingRecords = [];  // {drawer, item, purpose, date}

function addRecordItem() {
    const drawer = document.getElementById('recordDrawer').value.trim();
    const item = document.getElementById('recordItem').value.trim();
    const purpose = document.getElementById('recordPurpose').value.trim();
    const dateRaw = document.getElementById('recordDate').value.trim();

    if (!drawer) { showToast('请输入箱子名'); return; }
    if (!item) { showToast('请输入物品名'); return; }

    const date = parseDate(dateRaw);

    pendingRecords.push({ drawer, item, purpose, date });

    // 清空输入
    document.getElementById('recordItem').value = '';
    document.getElementById('recordPurpose').value = '';
    document.getElementById('recordDate').value = '';
    document.getElementById('recordItem').focus();

    // 更新箱子 datalist
    updateDrawerDatalist();

    renderPendingList();
}

function parseBatch() {
    const raw = document.getElementById('batchInput').value.trim();
    if (!raw) { showToast('请输入批量内容'); return; }

    const lines = raw.split('\n').filter(l => l.trim());
    const parsed = [];
    const errors = [];

    lines.forEach((line, idx) => {
        // 按逗号（中英文）或制表符分割，最多 4 段
        const parts = line.split(/[,，\t]+/).map(s => s.trim());
        if (parts.length < 2) {
            errors.push(`第 ${idx + 1} 行格式错误（至少需要箱子,物品）：${line}`);
            return;
        }
        const drawer = parts[0];
        const item = parts[1];
        const purpose = parts[2] || '';
        const dateRaw = parts[3] || '';
        const date = parseDate(dateRaw);
        if (dateRaw && !date) {
            errors.push(`第 ${idx + 1} 行日期无法识别：${dateRaw}`);
            return;
        }
        parsed.push({ drawer, item, purpose, date });
    });

    if (errors.length > 0) {
        resultArea.classList.remove('hidden');
        resultArea.innerHTML = `<div class="result-error">${errors.join('<br>')}</div>`;
        if (parsed.length === 0) return;
    }

    pendingRecords = pendingRecords.concat(parsed);
    document.getElementById('batchInput').value = '';
    updateDrawerDatalist();
    renderPendingList();
}

function renderPendingList() {
    const listDiv = document.getElementById('pendingList');
    const itemsDiv = document.getElementById('pendingItems');
    const countSpan = document.getElementById('pendingCount');

    if (pendingRecords.length === 0) {
        listDiv.classList.add('hidden');
        return;
    }

    listDiv.classList.remove('hidden');
    countSpan.textContent = `（${pendingRecords.length} 条）`;

    itemsDiv.innerHTML = pendingRecords.map((r, i) => {
        const purpStr = r.purpose ? ` <span class="pending-purpose">${escapeHtml(r.purpose)}</span>` : '';
        const dateStr = r.date ? ` <span class="pending-date">到期 ${escapeHtml(r.date)}</span>` : '';
        return `<div class="pending-item">
            <span class="pending-drawer">${escapeHtml(r.drawer)}</span>
            <span class="pending-arrow">→</span>
            <span class="pending-name">${escapeHtml(r.item)}</span>${purpStr}${dateStr}
            <button class="btn-icon-mini" onclick="removePendingItem(${i})" title="移除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </div>`;
    }).join('');
}

function removePendingItem(index) {
    pendingRecords.splice(index, 1);
    renderPendingList();
}

function clearPending() {
    pendingRecords = [];
    renderPendingList();
}

async function submitAllRecords() {
    if (pendingRecords.length === 0) return;

    // 按 drawer 分组
    const groups = {};
    pendingRecords.forEach(r => {
        if (!groups[r.drawer]) groups[r.drawer] = [];
        const obj = { name: r.item };
        if (r.purpose) obj.purpose = r.purpose;
        if (r.date) obj.date = r.date;
        groups[r.drawer].push(obj);
    });

    const drawerNames = Object.keys(groups);
    resultArea.classList.remove('hidden');
    resultArea.innerHTML = '<div class="result-loading">提交中...</div>';

    let allOk = true;
    const allResults = [];

    for (const drawer of drawerNames) {
        const items = groups[drawer];
        try {
            const data = await api(API_RECORD, {
                method: 'POST',
                body: JSON.stringify({ drawer, items })
            });
            if (data.ok) {
                allResults.push({ drawer, count: items.length, ok: true });
            } else {
                allOk = false;
                allResults.push({ drawer, count: items.length, ok: false, error: data.error || data.msg || '失败' });
            }
        } catch {
            allOk = false;
            allResults.push({ drawer, count: items.length, ok: false, error: '网络错误' });
        }
    }

    // 展示结果
    let html = '';
    if (allOk) {
        html += `<div class="result-msg">全部登记成功</div>`;
    } else {
        html += `<div class="result-msg">部分登记失败</div>`;
    }
    html += '<div class="result-items">';
    allResults.forEach(r => {
        const status = r.ok
            ? '<span class="result-item-ok">已登记</span>'
            : `<span class="result-item-expiry">${escapeHtml(r.error)}</span>`;
        html += `<div class="result-item"><span class="result-item-name">${escapeHtml(r.drawer)}（${r.count}件）</span>${status}</div>`;
    });
    html += '</div>';
    resultArea.innerHTML = html;

    // 清空已提交
    pendingRecords = [];
    renderPendingList();
    loadLogSection();
}

// ══════════════════════════════════════════════════
//  登记模式切换（单条 / 批量）
// ══════════════════════════════════════════════════

function switchRecordMode(mode) {
    const tabSingle = document.getElementById('tabSingle');
    const tabBatch = document.getElementById('tabBatch');
    const singleDiv = document.getElementById('recordSingle');
    const batchDiv = document.getElementById('recordBatch');

    if (mode === 'single') {
        tabSingle.classList.add('active');
        tabBatch.classList.remove('active');
        singleDiv.classList.remove('hidden');
        batchDiv.classList.add('hidden');
        document.getElementById('recordItem').focus();
    } else {
        tabBatch.classList.add('active');
        tabSingle.classList.remove('active');
        batchDiv.classList.remove('hidden');
        singleDiv.classList.add('hidden');
        document.getElementById('batchInput').focus();
    }
}

// ══════════════════════════════════════════════════
//  加载箱子选项列表（供 datalist 下拉）
// ══════════════════════════════════════════════════

async function loadDrawerOptions() {
    try {
        const data = await api('/api/drawers');
        const datalist = document.getElementById('drawerList');
        if (data.drawers && data.drawers.length > 0) {
            datalist.innerHTML = data.drawers.map(d => `<option value="${escapeHtml(d)}">`).join('');
        }
    } catch { /* 忽略 */ }
}

function updateDrawerDatalist() {
    const datalist = document.getElementById('drawerList');
    const existing = new Set();
    datalist.querySelectorAll('option').forEach(o => existing.add(o.value));
    let changed = false;
    pendingRecords.forEach(r => {
        if (!existing.has(r.drawer)) {
            existing.add(r.drawer);
            const opt = document.createElement('option');
            opt.value = r.drawer;
            datalist.appendChild(opt);
            changed = true;
        }
    });
    // Also check current input value
    const curVal = document.getElementById('recordDrawer').value.trim();
    if (curVal && !existing.has(curVal)) {
        const opt = document.createElement('option');
        opt.value = curVal;
        datalist.appendChild(opt);
    }
}

// ══════════════════════════════════════════════════
//  统一日志区域（最近登记 + 查找日志 合并）
// ══════════════════════════════════════════════════

async function loadLogSection() {
    try {
        const [recentData, logData] = await Promise.all([
            api('/api/recent'),
            api('/api/query_logs?limit=50')
        ]);

        const items = [];

        // 最近登记物品
        if (recentData.items && recentData.items.length > 0) {
            recentData.items.slice(0, 30).forEach(r => {
                const t = r.created_at ? r.created_at.slice(5, 16).replace('T', ' ') : '';
                const purp = r.purpose ? `（${r.purpose}）` : '';
                items.push({
                    summary: `登记了「${r.item}」${purp}→ ${r.drawer}`,
                    intent: '登记',
                    time: t
                });
            });
        }

        // 操作日志
        if (logData.logs && logData.logs.length > 0) {
            logData.logs.forEach(l => {
                const t = l.created_at ? l.created_at.slice(5, 16).replace('T', ' ') : '';
                const il = { query: '查询', search: '搜索', delete: '删除', move: '移动' }[l.intent] || l.intent;
                items.push({
                    summary: l.result_summary,
                    intent: il,
                    time: t
                });
            });
        }

        // 按时间倒序
        items.sort((a, b) => b.time.localeCompare(a.time));

        logCount.textContent = items.length > 0 ? `（共 ${items.length} 条）` : '';

        if (items.length === 0) {
            logList.innerHTML = '<div class="empty">还没有记录</div>';
            return;
        }

        logList.innerHTML = items.map(item => `
            <div class="log-item">
                <div class="log-summary">${escapeHtml(item.summary)}</div>
                <div class="log-meta">
                    <span class="log-intent">${escapeHtml(item.intent)}</span>
                    <span class="log-time">${escapeHtml(item.time)}</span>
                </div>
            </div>
        `).join('');
    } catch {
        logList.innerHTML = '<div class="empty">加载失败</div>';
    }
}

// ══════════════════════════════════════════════════
//  删除
// ══════════════════════════════════════════════════

async function deleteItem(id, name) {
    if (!confirm(`确定删除「${name}」？`)) return;
    try {
        const data = await api(`/api/delete/${id}`, { method: 'DELETE' });
        if (data.ok) { showToast(`已删除「${name}」`); loadLogSection(); }
    } catch { showToast('删除失败'); }
}

// ══════════════════════════════════════════════════
//  模式切换
// ══════════════════════════════════════════════════

function switchMode(mode) {
    currentMode = mode;
    boxesGrid.classList.add('hidden');
    boxesHeader.classList.add('hidden');
    drawerItemsView.classList.add('hidden');
    resultArea.classList.add('hidden');
    recordForm.classList.add('hidden');
    manualInput.classList.add('hidden');

    if (mode === 'record') {
        recordForm.classList.remove('hidden');
        loadDrawerOptions();
        // 默认显示单条模式
        switchRecordMode('single');
        if (pendingRecords.length > 0) renderPendingList();
    } else if (mode === 'find') {
        manualInput.classList.remove('hidden');
        textInput.focus();
        textInput.placeholder = '如：头孢在哪';
    } else if (mode === 'drawer') {
        boxesHeader.classList.remove('hidden');
        boxesGrid.classList.remove('hidden');
        loadBoxes();
    } else if (mode === 'expiry') {
        loadExpiring();
    } else if (mode === 'expired') {
        loadExpired();
    }
}

// ══════════════════════════════════════════════════
//  临期查询
// ══════════════════════════════════════════════════

async function loadExpiring() {
    resultArea.classList.remove('hidden');
    resultArea.innerHTML = '<div class="result-loading">查询中...</div>';
    try {
        const data = await api('/api/expiring?days=90');
        if (data.ok) {
            if (data.count > 0) {
                showResult(data);
            } else {
                resultArea.innerHTML = '<div class="result-msg">没有临期物品</div>';
            }
        }
    } catch { showToast('查询失败'); }
}

// ══════════════════════════════════════════════════
//  到期查询
// ══════════════════════════════════════════════════

async function loadExpired() {
    resultArea.classList.remove('hidden');
    resultArea.innerHTML = '<div class="result-loading">查询中...</div>';
    try {
        const data = await api('/api/expired');
        if (data.ok) {
            if (data.results && data.results.length > 0) {
                showResult(data);
            } else {
                resultArea.innerHTML = '<div class="result-msg">没有已过期物品</div>';
            }
        } else {
            resultArea.innerHTML = `<div class="result-error">${data.error || '查询失败'}</div>`;
        }
    } catch { showToast('查询失败'); }
}

// ══════════════════════════════════════════════════
//  箱子网格
// ══════════════════════════════════════════════════

async function loadBoxes() {
    try {
        const data = await api('/api/drawers');
        if (!data.drawers || data.drawers.length === 0) { boxesGrid.innerHTML = '<div class="empty">还没有箱子</div>'; return; }
        boxesGrid.innerHTML = data.drawers.map(d =>
            `<div class="box-card" onclick="viewBox('${d.replace(/'/g,"\\'")}')">
              <div class="box-card-actions" onclick="event.stopPropagation()">
                <button class="btn-icon-small" onclick="renameBox('${d.replace(/'/g,"\\'")}')" title="重命名">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="btn-icon-small danger" onclick="deleteBox('${d.replace(/'/g,"\\'")}')" title="删除">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </div>
              <div class="box-icon"><svg viewBox="0 0 64 64" width="48" height="48"><polygon points="32,8 58,22 32,36 6,22" fill="none" stroke="#6366F1" stroke-width="2" stroke-linejoin="round"/><polygon points="32,8 58,22 58,44 32,58 6,44 6,22" fill="none" stroke="#8B5CF6" stroke-width="2" stroke-linejoin="round"/><polyline points="32,36 32,58" stroke="#6366F1" stroke-width="2"/><line x1="6" y1="22" x2="32" y2="36" stroke="#6366F1" stroke-width="1.5" opacity="0.5"/></svg></div>
              <div class="box-name">${d}</div>
            </div>`
        ).join('');
    } catch { boxesGrid.innerHTML = '<div class="empty">加载失败</div>'; }
}

async function addBox() {
    const name = prompt('请输入新箱子名称：');
    if (!name || !name.trim()) return;
    try {
        const data = await api('/api/box', { method: 'POST', body: JSON.stringify({ name: name.trim() }) });
        data.ok ? (showToast(`已新增「${data.name}」`), loadBoxes()) : showToast(data.error);
    } catch { showToast('新增失败'); }
}

async function renameBox(oldName) {
    const newName = prompt(`重命名「${oldName}」为：`, oldName);
    if (!newName || !newName.trim() || newName.trim() === oldName) return;
    try {
        const data = await api(`/api/box/${encodeURIComponent(oldName)}`, { method: 'PUT', body: JSON.stringify({ name: newName.trim() }) });
        data.ok ? (showToast(`已重命名为「${data.new_name}」`), loadBoxes()) : showToast(data.error);
    } catch { showToast('重命名失败'); }
}

async function deleteBox(name) {
    if (!confirm(`确定删除箱子「${name}」及其所有物品？`)) return;
    try {
        const data = await api(`/api/box/${encodeURIComponent(name)}`, { method: 'DELETE' });
        data.ok ? (showToast(`已删除「${data.name}」（${data.deleted} 件）`), loadBoxes()) : showToast(data.error);
    } catch { showToast('删除失败'); }
}

async function viewBox(drawerName) {
    try {
        const data = await api(API_VOICE, { method: 'POST', body: JSON.stringify({ text: `${drawerName}里有什么` }) });
        if (!data.ok) { showToast(data.error); return; }
        boxesGrid.classList.add('hidden'); drawerItemsView.classList.remove('hidden');
        drawerItemsTitle.textContent = `「${drawerName}」`;
        if (!data.results || data.results.length === 0) { drawerItemsList.innerHTML = '<div class="empty">这个箱子是空的</div>'; return; }
        drawerItemsList.innerHTML = data.results.map(r => {
            let expBadge = '';
            if (r.expiry) {
                const d = new Date(r.expiry); const now = new Date();
                const dl = Math.ceil((d - now)/86400000);
                if (dl <= 0) expBadge = '<span class="exp-badge expired">已过期</span>';
                else if (dl <= 30) expBadge = `<span class="exp-badge warning">${dl}天到期</span>`;
                else expBadge = `<span class="exp-badge ok">${r.expiry}</span>`;
            }
            const purpBadge = r.purpose ? `<span class="exp-badge ok">${escapeHtml(r.purpose)}</span>` : '';
            return `<div class="item-card accent-${hashCode(drawerName)%8}">
              <div class="item-body"><span class="item-name">${escapeHtml(r.item)}</span>${purpBadge}${expBadge}</div>
              <button class="btn-icon-mini" onclick="deleteItem(${r.id},'${escapeHtml(r.item).replace(/'/g,"\\'")}')" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button></div>`;
        }).join('');
    } catch { showToast('查询失败'); }
}

function backToBoxes() {
    boxesHeader.classList.remove('hidden'); boxesGrid.classList.remove('hidden');
    drawerItemsView.classList.add('hidden'); drawerItemsList.innerHTML = '';
}

function showToast(msg) {
    const el = document.createElement('div'); el.className = 'toast'; el.textContent = msg;
    document.body.appendChild(el); setTimeout(() => el.remove(), 2000);
}

function hashCode(s) { let h = 0; for (let i = 0; i < s.length; i++) { h = ((h<<5)-h)+s.charCodeAt(i); h |= 0; } return Math.abs(h); }

if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js').catch(() => {}); }
