registerUserApp('responses', (root) => {
    const scope = createSocketScope();
    const prompt = root.querySelector('#response-user-prompt');
    const typeLabel = root.querySelector('#response-user-type');
    const options = root.querySelector('#response-user-options');
    const shortForm = root.querySelector('#response-short-form');
    const shortAnswer = root.querySelector('#response-short-answer');
    const status = root.querySelector('#response-user-status');
    let activeRun = null;
    let submittedAnswer = null;

    function setClosed() {
        options.querySelectorAll('button').forEach((button) => {
            button.disabled = true;
        });
        shortForm.querySelectorAll('input, button').forEach((control) => {
            control.disabled = true;
        });
        status.textContent = '응답이 마감되었습니다.';
    }

    function submitAnswer(answer) {
        if (!activeRun) return;
        socket.emit('response_submit', {
            run_id: activeRun.id,
            answer
        }, (response) => {
            if (!response || !response.ok) {
                status.textContent = (response && response.message) || '답변을 제출하지 못했습니다.';
                return;
            }
            submittedAnswer = response.answer;
            options.querySelectorAll('button').forEach((button) => {
                button.setAttribute('aria-pressed', String(button.textContent === submittedAnswer));
            });
            status.textContent = '답변이 저장되었습니다. 다시 제출하면 최신 답변으로 바뀝니다.';
        });
    }

    function renderRun(run, answer) {
        activeRun = run;
        submittedAnswer = answer;
        options.replaceChildren();
        shortForm.hidden = true;
        shortForm.querySelectorAll('input, button').forEach((control) => {
            control.disabled = false;
        });
        if (!run) {
            prompt.textContent = '대기 중';
            typeLabel.textContent = '';
            status.textContent = '호스트가 활동을 시작하기를 기다리는 중입니다.';
            return;
        }

        prompt.textContent = run.prompt;
        typeLabel.textContent = run.type_name;
        status.textContent = answer
            ? '현재 답변: ' + answer + ' (다시 제출할 수 있습니다.)'
            : '답변을 선택하거나 입력하세요.';

        if (run.type === 'truefalse' || run.type === 'scale') {
            const values = run.type === 'truefalse'
                ? ['참', '거짓']
                : ['1', '2', '3', '4', '5'];
            values.forEach((value) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'item-btn';
                button.textContent = value;
                button.setAttribute('aria-pressed', String(answer === value));
                button.addEventListener('click', () => submitAnswer(value));
                options.appendChild(button);
            });
        } else if (run.type === 'short_text') {
            shortForm.hidden = false;
            shortAnswer.value = answer || '';
        }
    }

    scope.on('response_started', (run) => renderRun(run, null));
    scope.on('response_ended', (event) => {
        if (activeRun && event.run_id === activeRun.id) setClosed();
    });
    socket.emit('response_sync', (response) => {
        if (response && response.ok) renderRun(response.run, response.answer);
        else status.textContent = (response && response.message) || '활동 정보를 불러오지 못했습니다.';
    });
    scope.on('connect', () => {
        socket.emit('response_sync', (response) => {
            if (response && response.ok) renderRun(response.run, response.answer);
        });
    });

    shortForm.addEventListener('submit', (event) => {
        event.preventDefault();
        submitAnswer(shortAnswer.value);
    });

    return () => scope.dispose();
});
