const startButton = document.querySelector('#start-game-button');
const adminStatus = document.querySelector('#admin-status');
const statisticsSection = document.querySelector('#admin-statistics');
const statisticsContent = document.querySelector('#statistics-content');
const roundStatistics = document.querySelector('#round-statistics');

function renderStatistics(statistics) {
    statisticsSection.hidden = false;
    statisticsContent.replaceChildren();
    roundStatistics.replaceChildren();
    statistics.players.forEach((player) => {
        const row = document.createElement('p');
        row.textContent = player.nickname + ' · 정답 ' + player.correct_count + '개 · '
            + (player.average_seconds === null
                ? '정답 없음'
                : '평균 정답 시간 ' + player.average_seconds + '초');
        statisticsContent.appendChild(row);
    });
    statistics.rounds.forEach((round) => {
        const row = document.createElement('li');
        row.textContent = round.number + '라운드 · ' + round.drawer + ' · '
            + round.word + ' · 정답 ' + round.correct_count + '명 · ' + round.seconds + '초';
        roundStatistics.appendChild(row);
    });
}

function renderState(state) {
    const players = state.players || [];
    startButton.disabled = players.length < 2 || state.phase === 'playing';
    startButton.textContent = state.phase === 'finished' ? '다시 시작' : '게임 시작';
    if (state.phase === 'playing') {
        adminStatus.textContent = state.theme + ' 테마로 게임 중입니다.';
    } else if (state.phase === 'finished') {
        adminStatus.textContent = '게임이 끝났습니다.';
    } else {
        adminStatus.textContent = players.length < 2
            ? '게임 시작에는 참가자가 2명 이상 필요합니다.'
            : '참가자 준비 완료. 게임을 시작할 수 있습니다.';
    }
}

socket.on('connect', () => {
    socket.emit('host_join', (response) => {
        if (!response || !response.ok) {
            adminStatus.textContent = (response && response.message)
                || '관리자 연결에 실패했습니다.';
            startButton.disabled = true;
        }
    });
});

socket.on('game_state', renderState);
socket.on('game_error', (data) => {
    adminStatus.textContent = data.message;
    startButton.disabled = false;
});
socket.on('game_finished', (data) => {
    renderState(data.state);
    renderStatistics(data.statistics);
});
socket.on('round_started', (round) => {
    adminStatus.textContent = '라운드 ' + round.number + ' / ' + round.total
        + ' · ' + round.drawer_name + '님이 그림을 그리고 있습니다.';
});

startButton.addEventListener('click', () => {
    startButton.disabled = true;
    socket.emit('game_start', (response) => {
        if (!response || !response.ok) {
            adminStatus.textContent = (response && response.message)
                || '게임을 시작하지 못했습니다.';
            startButton.disabled = false;
        }
    });
});
