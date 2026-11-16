registerUserApp('drawing', (root) => {
    const scope = createSocketScope();
    const $ = (selector) => root.querySelector(selector);

    const playerList = $('#player-list');
    const playerCount = $('#player-count');
    const gameStatus = $('#game-status');
    const playArea = $('#play-area');
    const roundTitle = $('#round-title');
    const countdown = $('#round-countdown');
    const drawerWord = $('#drawer-word');
    const canvas = $('#drawing-canvas');
    const ctx = canvas.getContext('2d');
    const drawingControls = $('#drawing-controls');
    const normalChat = $('#normal-chat');
    const solvedChat = $('#solved-chat');
    const chatForm = $('#chat-form');
    const chatInput = $('#chat-input');
    const finalStatistics = $('#final-statistics');
    const playerStatistics = $('#player-statistics');
    const roundStatistics = $('#round-statistics');

    let canDraw = false;
    let drawing = false;
    let lastPoint = null;
    let countdownTimer = null;

    function showError(message) {
        gameStatus.textContent = message;
    }

    function drawStroke(target, stroke, previousPoint) {
        target.save();
        target.strokeStyle = stroke.color;
        target.lineWidth = stroke.width;
        target.lineCap = 'round';
        target.lineJoin = 'round';
        stroke.points.forEach((point, index) => {
            const from = index === 0 ? (stroke.begin ? point : previousPoint) : stroke.points[index - 1];
            if (!from) return;
            target.beginPath();
            target.moveTo(from[0], from[1]);
            target.lineTo(point[0], point[1]);
            target.stroke();
        });
        target.restore();
    }

    function replaceDrawing(strokes) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        lastPoint = null;
        strokes.forEach((stroke) => {
            drawStroke(ctx, stroke, null);
            lastPoint = stroke.points[stroke.points.length - 1];
        });
    }

    function canvasPoint(event) {
        const rect = canvas.getBoundingClientRect();
        return [
            Math.max(0, Math.min(canvas.width, (event.clientX - rect.left) * canvas.width / rect.width)),
            Math.max(0, Math.min(canvas.height, (event.clientY - rect.top) * canvas.height / rect.height))
        ];
    }

    function emitStroke(point, begin) {
        const stroke = {
            color: $('#drawing-color').value,
            width: Number($('#drawing-width').value),
            begin,
            points: [point]
        };
        drawStroke(ctx, stroke, lastPoint);
        lastPoint = point;
        socket.emit('drawing_strokes', { strokes: [stroke] });
    }

    function appendChat(container, data) {
        const item = document.createElement('li');
        const speaker = document.createElement('strong');
        speaker.textContent = data.nickname + ': ';
        item.append(speaker, document.createTextNode(data.message));
        if (data.correct) item.classList.add('correct-answer');
        container.appendChild(item);
        container.scrollTop = container.scrollHeight;
    }

    canvas.addEventListener('pointerdown', (event) => {
        if (!canDraw || (event.button !== 0 && event.pointerType === 'mouse')) return;
        event.preventDefault();
        drawing = true;
        canvas.setPointerCapture(event.pointerId);
        lastPoint = null;
        emitStroke(canvasPoint(event), true);
    });
    canvas.addEventListener('pointermove', (event) => {
        if (!drawing) return;
        emitStroke(canvasPoint(event), false);
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((eventName) => {
        canvas.addEventListener(eventName, () => {
            drawing = false;
            lastPoint = null;
        });
    });
    canvas.addEventListener('contextmenu', (event) => event.preventDefault());

    chatForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const message = chatInput.value.trim();
        if (!message) return;
        socket.emit('game_chat_message', { message }, (response) => {
            if (response && response.ok) chatInput.value = '';
            else showError((response && response.message) || '메시지를 보내지 못했습니다.');
        });
    });

    $('#undo-button').addEventListener('click', () => {
        if (canDraw && !drawing) socket.emit('drawing_undo');
    });

    scope.on('game_error', (data) => showError(data.message));

    scope.on('game_state', (state) => {
        const players = state.players || [];
        playerCount.textContent = String(players.length);
        playerList.replaceChildren();
        players.forEach((player) => {
            const item = document.createElement('li');
            item.textContent = player.nickname + ' · 정답 ' + player.score + '개';
            if (player.solved) item.textContent += ' · 정답 완료';
            playerList.appendChild(item);
        });
        if (state.phase === 'lobby') {
            gameStatus.textContent = '호스트가 게임을 준비하고 있습니다.';
        } else if (state.phase === 'playing') {
            gameStatus.textContent = state.theme + ' 테마로 게임 중입니다.';
            playArea.hidden = false;
        } else if (state.phase === 'finished') {
            gameStatus.textContent = '게임이 끝났습니다.';
        }
    });

    scope.on('drawing_strokes', (data) => {
        if (data.id === socket.id) return;
        data.strokes.forEach((stroke) => {
            drawStroke(ctx, stroke, stroke.begin ? null : lastPoint);
            lastPoint = stroke.points[stroke.points.length - 1];
        });
    });

    scope.on('drawing_cleared', () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        lastPoint = null;
    });

    scope.on('drawing_state', (data) => replaceDrawing(data.strokes));

    scope.on('round_started', (round) => {
        canDraw = round.drawer_sid === socket.id;
        drawingControls.hidden = !canDraw;
        drawerWord.hidden = !canDraw;
        drawerWord.textContent = '';
        playArea.hidden = false;
        finalStatistics.hidden = true;
        roundTitle.textContent = '라운드 ' + round.number + ' / ' + round.total
            + ' · ' + round.drawer_name + '님이 그림을 그립니다 (' + round.theme + ')';
        normalChat.replaceChildren();
        solvedChat.replaceChildren();
        if (countdownTimer) window.clearInterval(countdownTimer);
        const deadline = performance.now() + round.duration * 1000;
        const updateCountdown = () => {
            countdown.textContent = String(Math.max(0, Math.ceil((deadline - performance.now()) / 1000)));
        };
        updateCountdown();
        countdownTimer = window.setInterval(updateCountdown, 250);
        socket.emit('drawing_sync', (response) => replaceDrawing(response.strokes || []));
    });

    scope.on('drawer_word', (data) => {
        drawerWord.textContent = '제시어: ' + data.word;
    });

    scope.on('round_finished', (data) => {
        roundTitle.textContent = '정답: ' + data.word + ' · 그림: ' + data.drawer_name
            + ' · 정답자 ' + data.solved.length + '명 · ' + data.seconds + '초';
    });

    scope.on('game_chat', (data) => {
        appendChat(data.channel === 'solved' ? solvedChat : normalChat, data);
    });

    scope.on('game_finished', (data) => {
        playArea.hidden = true;
        finalStatistics.hidden = false;
        gameStatus.textContent = '모든 참가자가 한 번씩 그림을 그렸습니다.';
        playerStatistics.replaceChildren();
        data.statistics.players.forEach((player) => {
            const item = document.createElement('p');
            const avg = player.average_seconds === null
                ? '정답 없음'
                : '평균 정답 시간 ' + player.average_seconds + '초';
            item.textContent = player.nickname + ' · 정답 ' + player.correct_count + '개 · ' + avg;
            playerStatistics.appendChild(item);
        });
        roundStatistics.replaceChildren();
        data.statistics.rounds.forEach((round) => {
            const item = document.createElement('li');
            item.textContent = round.number + '라운드 · ' + round.drawer + ' · '
                + round.word + ' · 정답 ' + round.correct_count + '명 · ' + round.seconds + '초';
            roundStatistics.appendChild(item);
        });
    });

    // 앱 화면이 늦게 붙으므로, 그 사이에 놓친 현재 상태를 서버에서 다시 받는다.
    socket.emit('game_sync');

    return () => {
        scope.dispose();
        if (countdownTimer) window.clearInterval(countdownTimer);
    };
});
