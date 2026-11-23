registerUserApp('question', () => {
    const form = document.querySelector('#question-form');
    const questionInput = document.querySelector('#question');
    const askButton = document.querySelector('#ask_question');
    const status = document.querySelector('#question-status');
    const sessionStatus = document.querySelector('#question-session-status');
    let activeSession = null;

    const updateSession = (response) => {
        if (!response || response.ok === false) {
            activeSession = null;
            sessionStatus.textContent =
                (response && response.message) || '질문 세션 정보를 불러오지 못했습니다.';
            questionInput.disabled = true;
            askButton.disabled = true;
            return;
        }
        activeSession = response.active_session || null;
        questionInput.disabled = !activeSession;
        askButton.disabled = !activeSession;
        sessionStatus.textContent = activeSession
            ? `질문 세션: ${activeSession.name}`
            : '호스트가 질문 세션을 열기를 기다리는 중입니다.';
    };

    const syncSession = () => {
        socket.emit('question_session_sync', updateSession);
    };

    const onSubmit = (event) => {
        event.preventDefault();
        const question = questionInput.value.trim();
        if (!question || !activeSession) return;
        askButton.disabled = true;
        socket.emit('ask_question', { question }, (response) => {
            if (!response || !response.ok) {
                status.textContent =
                    (response && response.message) || '질문을 전송하지 못했습니다.';
                status.classList.add('error');
                askButton.disabled = !activeSession;
                return;
            }
            questionInput.value = '';
            status.textContent =
                `${response.session.name} 세션에 질문을 전송하고 저장했습니다.`;
            status.classList.remove('error');
            askButton.disabled = !activeSession;
            questionInput.focus();
        });
    };

    form.addEventListener('submit', onSubmit);
    socket.on('question_active_session', updateSession);
    socket.on('connect', syncSession);
    if (socket.connected) syncSession();
    return () => {
        form.removeEventListener('submit', onSubmit);
        socket.off('question_active_session', updateSession);
        socket.off('connect', syncSession);
    };
});