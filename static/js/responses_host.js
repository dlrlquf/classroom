const responseTypeNames = {
    truefalse: '참 / 거짓',
    scale: '1~5 선택',
    short_text: '짧은 답변'
};

function renderResponseRun(run) {
    const section = document.querySelector('#response-current');
    section.hidden = !run;
    if (!run) return;

    document.querySelector('#response-type-name').textContent = run.type_name;
    document.querySelector('#response-current-prompt').textContent = run.prompt;
    document.querySelector('#response-total').textContent = String(run.responses.length);

    const breakdown = document.querySelector('#response-breakdown');
    breakdown.replaceChildren();
    Object.entries(run.counts).forEach(([answer, count]) => {
        const item = document.createElement('span');
        item.className = 'response-count';
        item.textContent = answer + ': ' + count;
        breakdown.appendChild(item);
    });

    const answers = document.querySelector('#response-answers');
    answers.replaceChildren();
    run.responses.forEach((response) => {
        const item = document.createElement('li');
        item.textContent = response.name + ': ' + response.answer;
        answers.appendChild(item);
    });
}

function renderResponseHistory(history) {
    const container = document.querySelector('#response-history-list');
    container.replaceChildren();
    history.forEach((run) => {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = '#' + run.id + ' ' + run.type_name + ' — ' +
            run.prompt + ' (' + run.responses.length + '개 응답)';
        details.appendChild(summary);

        const answers = document.createElement('ol');
        run.responses.forEach((response) => {
            const item = document.createElement('li');
            item.textContent = response.name + ': ' + response.answer;
            answers.appendChild(item);
        });
        details.appendChild(answers);
        container.appendChild(details);
    });
}

function renderResponseState(state) {
    renderResponseRun(state.run);
    renderResponseHistory(state.history || []);
}

const resultsVisible = document.querySelector('#response-results-visible');
const responseResults = document.querySelector('#response-results');

resultsVisible.addEventListener('change', () => {
    responseResults.hidden = !resultsVisible.checked;
});

socket.on('responses_state', renderResponseState);
socket.on('connect', () => {
    socket.emit('responses_sync', (response) => {
        if (response && response.ok) renderResponseState(response);
        else document.querySelector('#response-host-status').textContent =
            (response && response.message) || '응답 상태를 불러오지 못했습니다.';
    });
});

document.querySelectorAll('[data-response-type]').forEach((button) => {
    button.addEventListener('click', () => {
        const prompt = document.querySelector('#response-prompt').value.trim();
        document.querySelector('#response-host-status').textContent = '';
        socket.emit('response_start', {
            type: button.dataset.responseType,
            prompt
        }, (response) => {
            if (!response || !response.ok) {
                document.querySelector('#response-host-status').textContent =
                    (response && response.message) || '활동을 시작하지 못했습니다.';
                return;
            }
            document.querySelector('#response-host-status').textContent =
                responseTypeNames[response.run.type] + ' 활동을 시작했습니다.';
            renderResponseRun(response.run);
        });
    });
});

document.querySelector('#response-stop').addEventListener('click', () => {
    socket.emit('response_stop', (response) => {
        if (!response || !response.ok) {
            document.querySelector('#response-host-status').textContent =
                (response && response.message) || '응답을 마감하지 못했습니다.';
        } else {
            document.querySelector('#response-host-status').textContent =
                '응답을 마감했습니다.';
        }
    });
});
