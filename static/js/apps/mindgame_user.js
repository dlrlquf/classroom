registerUserApp('mindgame', (root) => {
    const scope = createSocketScope();
    const button = root.querySelector('#mindgame-click');
    const status = root.querySelector('#mindgame-user-status');
    let phase = 'waiting';
    let alreadyClicked = false;

    function renderState(state) {
        phase = state.phase;
        alreadyClicked = state.already_clicked || false;
        button.disabled = phase !== 'playing' || alreadyClicked;
        button.textContent = alreadyClicked ? '눌렀습니다' : '누르기';

        if (phase === 'playing') {
            status.textContent = alreadyClicked
                ? '이번 게임에서 버튼을 눌렀습니다. 다른 참가자를 기다려 주세요.'
                : '너무 빠르게 연속으로 누르면 게임오버됩니다. 타이밍을 맞춰 누르세요.';
        } else if (phase === 'game_over') {
            status.textContent = state.game_over
                ? state.game_over.name + '님이 너무 빨리 눌러 게임오버되었습니다.'
                : '게임오버되었습니다. 호스트의 다음 게임을 기다려 주세요.';
            button.disabled = true;
        } else if (phase === 'ended') {
            status.textContent = '호스트가 게임을 종료했습니다. 다음 게임을 기다려 주세요.';
        } else {
            status.textContent = '호스트가 게임을 시작하기를 기다리는 중입니다.';
        }
    }

    button.addEventListener('click', () => {
        if (phase !== 'playing' || alreadyClicked) return;
        button.disabled = true;
        socket.emit('mindgame_click', (response) => {
            if (!response || !response.ok) {
                status.textContent = (response && response.message) ||
                    '버튼 입력을 처리하지 못했습니다.';
                if (phase === 'playing') button.disabled = alreadyClicked;
                return;
            }
            alreadyClicked = true;
            button.textContent = '눌렀습니다';
            if (response.game_over) {
                renderState({
                    phase: 'game_over',
                    game_over: response.game_over,
                    already_clicked: true
                });
            } else {
                status.textContent = '버튼을 눌렀습니다. 다른 참가자를 기다려 주세요.';
            }
        });
    });

    scope.on('mindgame_started', () => renderState({
        phase: 'playing',
        already_clicked: false
    }));
    scope.on('mindgame_over', (gameOver) => renderState({
        phase: 'game_over',
        game_over: gameOver,
        already_clicked: true
    }));
    scope.on('mindgame_ended', () => renderState({
        phase: 'ended',
        already_clicked: true
    }));
    scope.on('connect', () => {
        socket.emit('mindgame_sync', (response) => {
            if (response && response.ok) renderState(response);
            else status.textContent = (response && response.message) ||
                '게임 상태를 불러오지 못했습니다.';
        });
    });
    socket.emit('mindgame_sync', (response) => {
        if (response && response.ok) renderState(response);
        else status.textContent = (response && response.message) ||
            '게임 상태를 불러오지 못했습니다.';
    });

    return () => scope.dispose();
});
