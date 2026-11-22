registerUserApp('question', () => {
    const form = document.querySelector('#question-form');
    const questionInput = document.querySelector('#question');
    const askButton = document.querySelector('#ask_question');
    const status = document.querySelector('#question-status');

    const onSubmit = (event) => {
        event.preventDefault();
        const question = questionInput.value.trim();
        if (!question) return;
        askButton.disabled = true;
        socket.emit('ask_question', { question }, (response) => {
            askButton.disabled = false;
            if (!response || !response.ok) {
                status.textContent =
                    (response && response.message) || '질문을 전송하지 못했습니다.';
                status.classList.add('error');
                return;
            }
            questionInput.value = '';
            status.textContent = '질문을 전송했습니다.';
            status.classList.remove('error');
            questionInput.focus();
        });
    };

    form.addEventListener('submit', onSubmit);
    return () => form.removeEventListener('submit', onSubmit);
});