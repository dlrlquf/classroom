registerUserApp('truefalse', (root) => {
    const scope = createSocketScope();
    const buttons = root.querySelectorAll('[data-choice]');
    const status = root.querySelector('#tf-status');

    function markChoice(choice) {
        buttons.forEach((button) => {
            const selected = button.dataset.choice === choice;
            button.classList.toggle('selected', selected);
            button.setAttribute('aria-pressed', String(selected));
        });
        status.textContent = choice ? '"' + choice + '"을(를) 선택했습니다.' : '하나를 선택하세요.';
    }

    buttons.forEach((button) => {
        button.addEventListener('click', () => {
            socket.emit('tf_vote', { choice: button.dataset.choice }, (response) => {
                if (response && response.ok) markChoice(response.choice);
                else status.textContent = (response && response.message) || '선택하지 못했습니다.';
            });
        });
    });

    scope.on('tf_cleared', () => markChoice(null));
    socket.emit('tf_my_choice', (response) => markChoice(response && response.choice));

    return () => scope.dispose();
});
