const startButton = document.querySelector('#mindgame-start');
const stopButton = document.querySelector('#mindgame-stop');
const intervalInput = document.querySelector('#mindgame-interval');
const status = document.querySelector('#mindgame-status');
const clickOrder = document.querySelector('#mindgame-click-order');

function renderMindgameState(state) {
    clickOrder.replaceChildren();
    state.clicks.forEach((click) => {
        const item = document.createElement('li');
        item.textContent = click.name;
        clickOrder.appendChild(item);
    });

    const playing = state.phase === 'playing';
    startButton.disabled = playing;
    stopButton.disabled = !playing;
    intervalInput.disabled = playing;
    startButton.textContent = ['game_over', 'ended'].includes(state.phase)
        ? '다시 시작'
        : '게임 시작';
    if (playing) {
        status.textContent = '게임 진행 중 · ' +
            (state.interval_ms / 1000) + '초 이내에 연속으로 누르면 게임오버입니다.';
    } else if (state.phase === 'game_over' && state.game_over) {
        status.textContent = state.game_over.name + '님이 ' +
            (state.game_over.gap_ms / 1000) + '초 간격으로 눌러 게임오버되었습니다.';
    } else if (state.phase === 'ended') {
        status.textContent = '호스트가 게임을 종료했습니다.';
    } else {
        status.textContent = '판정 간격을 설정하고 게임을 시작하세요.';
    }
}

socket.on('connect', () => {
    socket.emit('mindgame_sync', (response) => {
        if (response && response.ok) renderMindgameState(response);
        else {
            status.textContent = (response && response.message) ||
                '게임 상태를 불러오지 못했습니다.';
            startButton.disabled = true;
        }
    });
});

socket.on('mindgame_state', renderMindgameState);

startButton.addEventListener('click', () => {
    const intervalMs = Math.round(Number(intervalInput.value) * 1000);
    startButton.disabled = true;
    socket.emit('mindgame_start', { interval_ms: intervalMs }, (response) => {
        if (!response || !response.ok) {
            status.textContent = (response && response.message) ||
                '게임을 시작하지 못했습니다.';
            startButton.disabled = false;
            return;
        }
        renderMindgameState(response);
    });
});

stopButton.addEventListener('click', () => {
    stopButton.disabled = true;
    socket.emit('mindgame_stop', (response) => {
        if (!response || !response.ok) {
            status.textContent = (response && response.message) ||
                '게임을 종료하지 못했습니다.';
            stopButton.disabled = false;
            return;
        }
        renderMindgameState(response);
    });
});
