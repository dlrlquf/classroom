const CLIENT_ID_KEY = 'clientId';
const SESSION_KEY = 'lobbySession';

const lobbyPanel = document.querySelector('#lobby-panel');
const lobbyForm = document.querySelector('#join-form');
const nameInput = document.querySelector('#name-input');
const codeInputs = Array.from(document.querySelectorAll('.code-input'));
const lobbyStatus = document.querySelector('#join-status');

function fillCodeInputs(value, startIndex = 0) {
    const digits = String(value).replace(/\D/g, '').slice(0, codeInputs.length - startIndex);
    digits.split('').forEach((digit, offset) => {
        codeInputs[startIndex + offset].value = digit;
    });
    const nextInput = codeInputs[Math.min(startIndex + digits.length, codeInputs.length - 1)];
    nextInput.focus();
    nextInput.select();
}

codeInputs.forEach((input, index) => {
    input.addEventListener('input', () => {
        const digits = input.value.replace(/\D/g, '');
        if (digits.length > 1) {
            fillCodeInputs(digits, index);
            return;
        }
        input.value = digits;
        if (digits && index < codeInputs.length - 1) {
            codeInputs[index + 1].focus();
            codeInputs[index + 1].select();
        }
    });

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Backspace' && !input.value && index > 0) {
            codeInputs[index - 1].focus();
            codeInputs[index - 1].select();
        } else if (event.key === 'ArrowLeft' && index > 0) {
            codeInputs[index - 1].focus();
        } else if (event.key === 'ArrowRight' && index < codeInputs.length - 1) {
            codeInputs[index + 1].focus();
        }
    });

    input.addEventListener('paste', (event) => {
        event.preventDefault();
        fillCodeInputs(event.clipboardData.getData('text'), index);
    });
});

// 기기마다 한 번 만들어 두고, 연결이 끊겨도 같은 사용자로 인식하는 데 쓴다.
function getClientId() {
    let id = localStorage.getItem(CLIENT_ID_KEY);
    if (!id) {
        id = crypto.randomUUID ? crypto.randomUUID()
            : Array.from(crypto.getRandomValues(new Uint8Array(16)),
                (b) => b.toString(16).padStart(2, '0')).join('');
        localStorage.setItem(CLIENT_ID_KEY, id);
    }
    return id;
}

function loadSession() {
    try {
        return JSON.parse(localStorage.getItem(SESSION_KEY)) || null;
    } catch (error) {
        return null;
    }
}

function showLobbyError(message) {
    lobbyStatus.textContent = message;
    lobbyStatus.classList.add('error');
}

const appRoot = document.querySelector('#app-root');
const idleTemplate = document.querySelector('#app-idle-template');

const userApps = {};
const fragmentCache = {};
const scriptCache = {};
let unmountCurrent = null;
let renderToken = 0;
let currentApp = null;
let statusPollTimer = null;

// 앱 스크립트가 자신의 mount 함수를 등록한다. mount는 정리(unmount) 함수를 반환한다.
function registerUserApp(appId, mount) {
    userApps[appId] = mount;
}

// 앱이 바뀔 때 소켓 리스너가 쌓이지 않도록 한꺼번에 해제하기 위한 도우미.
function createSocketScope() {
    const handlers = [];
    return {
        on(event, handler) {
            socket.on(event, handler);
            handlers.push([event, handler]);
        },
        dispose() {
            handlers.forEach(([event, handler]) => socket.off(event, handler));
            handlers.length = 0;
        }
    };
}

function loadFragment(appId) {
    if (!fragmentCache[appId]) {
        fragmentCache[appId] = fetch('/user/app/' + encodeURIComponent(appId))
            .then((response) => {
                if (!response.ok) throw new Error('fragment ' + response.status);
                return response.text();
            })
            .catch((error) => {
                delete fragmentCache[appId];
                throw error;
            });
    }
    return fragmentCache[appId];
}

function loadScript(appId) {
    if (!scriptCache[appId]) {
        scriptCache[appId] = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = userAppScriptUrls[appId] ||
                '/static/js/apps/' + encodeURIComponent(appId) + '_user.js';
            script.onload = resolve;
            script.onerror = () => {
                delete scriptCache[appId];
                reject(new Error('script ' + appId));
            };
            document.head.appendChild(script);
        });
    }
    return scriptCache[appId];
}

function clearApp() {
    if (unmountCurrent) unmountCurrent();
    unmountCurrent = null;
    appRoot.replaceChildren();
}

async function showApp(appId) {
    const token = ++renderToken;
    currentApp = appId;
    clearApp();
    if (!appId) {
        appRoot.appendChild(idleTemplate.content.cloneNode(true));
        return;
    }
    try {
        const [html] = await Promise.all([loadFragment(appId), loadScript(appId)]);
        if (token !== renderToken) return;
        appRoot.innerHTML = html;
        unmountCurrent = userApps[appId](appRoot) || null;
    } catch (error) {
        if (token !== renderToken) return;
        appRoot.textContent = '앱 화면을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
    }
}

function enterApp(appId) {
    lobbyPanel.hidden = true;
    showApp(appId);
}

function stopWaitingForClass() {
    if (statusPollTimer === null) return;
    window.clearInterval(statusPollTimer);
    statusPollTimer = null;
}

async function pollClassStatus() {
    try {
        const response = await fetch('/class-status', { cache: 'no-store' });
        if (!response.ok) throw new Error('class status ' + response.status);
        const status = await response.json();
        if (!status.started) return;
        stopWaitingForClass();
        socket.connect();
    } catch (error) {
        lobbyStatus.textContent = '수업 시작 여부를 확인하지 못했습니다.';
        lobbyStatus.classList.add('error');
    }
}

function startWaitingForClass() {
    stopWaitingForClass();
    lobbyStatus.textContent = '호스트가 수업을 시작하면 자동으로 연결됩니다.';
    lobbyStatus.classList.remove('error');
    statusPollTimer = window.setInterval(pollClassStatus, 1000);
    pollClassStatus();
}

function joinLobby(name, code) {
    socket.emit('user_join', { name, code, client_id: getClientId() }, (response) => {
        if (!response || !response.ok) {
            const message = (response && response.message) || '입장에 실패했습니다.';
            // 만료된 세션 정보는 지워서 재접속 시도를 반복하지 않는다.
            localStorage.removeItem(SESSION_KEY);
            renderToken += 1;
            clearApp();
            lobbyPanel.hidden = false;
            showLobbyError(message);
            return;
        }
        localStorage.setItem(SESSION_KEY, JSON.stringify({ name: response.name, code }));
        lobbyStatus.classList.remove('error');
        enterApp(response.app);
    });
}

const savedSession = loadSession();
if (savedSession) {
    nameInput.value = savedSession.name;
    if (codeInputs.every((input) => !input.value)) {
        fillCodeInputs(savedSession.code);
    }
}

lobbyForm.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!socket.connected) {
        lobbyStatus.textContent = '호스트가 수업을 아직 시작하지 않았습니다.';
        lobbyStatus.classList.add('error');
        return;
    }
    joinLobby(
        nameInput.value.trim(),
        codeInputs.map((input) => input.value).join('')
    );
});

socket.on('app_changed', (data) => {
    if (!lobbyPanel.hidden) return;
    enterApp(data.app);
});

socket.on('connect', () => {
    stopWaitingForClass();
    const session = loadSession();
    if (session) joinLobby(session.name, session.code);
});

socket.on('class_stopped', () => {
    socket.disconnect();
    renderToken += 1;
    clearApp();
    lobbyPanel.hidden = false;
    startWaitingForClass();
});

if (initialClassStarted) {
    socket.connect();
} else {
    startWaitingForClass();
}
