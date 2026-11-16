const tfLists = {
    '참': ['true', '#tf-list-true', '#tf-count-true'],
    '거짓': ['false', '#tf-list-false', '#tf-count-false'],
    none: ['none', '#tf-list-none', '#tf-count-none']
};

function renderTrueFalse(state) {
    Object.entries(tfLists).forEach(([key, [, listSelector, countSelector]]) => {
        const names = state[key] || [];
        document.querySelector(countSelector).textContent = String(names.length);
        const list = document.querySelector(listSelector);
        list.replaceChildren();
        names.forEach((name) => {
            const item = document.createElement('li');
            item.textContent = name;
            list.appendChild(item);
        });
    });
}

socket.on('tf_state', renderTrueFalse);
socket.on('connect', () => {
    socket.emit('tf_sync', (response) => {
        if (response && response.ok) renderTrueFalse(response.state);
    });
});
document.querySelector('#tf-reset').addEventListener('click', () => socket.emit('tf_reset'));
