const classList = document.querySelector('#home-class-list');
const createForm = document.querySelector('#home-class-create-form');
const createName = document.querySelector('#home-class-create-name');
const startButton = document.querySelector('#home-start-class');
const classStatus = document.querySelector('#home-class-status');
const joinInfo = document.querySelector('#join-info');
let selectedClassId = classList.dataset.selectedClassId
    ? Number(classList.dataset.selectedClassId)
    : null;

function setStatus(message, isError = false) {
    classStatus.textContent = message;
    classStatus.classList.toggle('error', isError);
}

function selectCard(card) {
    classList.querySelectorAll('.home-class-card').forEach((item) => {
        item.classList.toggle('selected', item === card);
    });
    selectedClassId = Number(card.dataset.classId);
    startButton.disabled = false;
    setStatus(`${card.querySelector('.home-class-name').textContent} 반을 선택했습니다.`);
}

function createClassCard(classInfo) {
    const card = document.createElement('article');
    card.className = 'home-class-card';
    card.dataset.classId = String(classInfo.id);

    const select = document.createElement('button');
    select.type = 'button';
    select.className = 'home-class-select';
    const name = document.createElement('span');
    name.className = 'home-class-name';
    name.textContent = classInfo.name;
    const label = document.createElement('span');
    label.className = 'home-class-select-label';
    label.textContent = '이 반으로 시작';
    select.append(name, label);

    const actions = document.createElement('div');
    actions.className = 'home-class-actions';
    const rename = document.createElement('button');
    rename.type = 'button';
    rename.className = 'home-class-rename';
    rename.textContent = '이름 수정';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'home-class-delete';
    remove.textContent = '삭제';
    actions.append(rename, remove);
    card.append(select, actions);
    return card;
}

async function createClass() {
    try {
        const response = await fetch('/classes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: createName.value })
        });
        const result = await response.json();
        if (!response.ok || !result.ok) {
            setStatus((result && result.message) || '반을 추가하지 못했습니다.', true);
            return;
        }
        classList.appendChild(createClassCard(result.class));
        createName.value = '';
        setStatus(`${result.class.name} 반을 추가했습니다.`);
    } catch (error) {
        setStatus('반을 추가하는 동안 연결 오류가 발생했습니다.', true);
    }
}

async function updateClassName(card) {
    const name = card.querySelector('.home-class-name');
    const nextName = window.prompt('반 이름을 수정해 주세요.', name.textContent);
    if (nextName === null) return;
    try {
        const response = await fetch(`/classes/${card.dataset.classId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: nextName })
        });
        const result = await response.json();
        if (!response.ok || !result.ok) {
            setStatus(
                (result && result.message) || '반 이름을 수정하지 못했습니다.',
                true
            );
            return;
        }
        name.textContent = result.class.name;
        setStatus(`${result.class.name} 반 이름을 수정했습니다.`);
    } catch (error) {
        setStatus('반 이름을 수정하는 동안 연결 오류가 발생했습니다.', true);
    }
}

async function deleteClass(card) {
    const name = card.querySelector('.home-class-name').textContent;
    if (!window.confirm(`${name} 반과 연결된 명단, 질문을 모두 삭제할까요?`)) return;
    try {
        const response = await fetch(`/classes/${card.dataset.classId}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        if (!response.ok || !result.ok) {
            setStatus((result && result.message) || '반을 삭제하지 못했습니다.', true);
            return;
        }
        const deletedId = Number(card.dataset.classId);
        card.remove();
        if (deletedId === selectedClassId) {
            selectedClassId = null;
            startButton.disabled = true;
        }
        setStatus(`${name} 반을 삭제했습니다.`);
    } catch (error) {
        setStatus('반을 삭제하는 동안 연결 오류가 발생했습니다.', true);
    }
}

function selectCurrentClass() {
    if (!selectedClassId) return;
    socket.emit('lobby_select_class', { class_id: selectedClassId }, (response) => {
        if (!response || !response.ok) {
            setStatus(
                (response && response.message) || '반을 선택하지 못했습니다.',
                true
            );
            startButton.disabled = false;
            return;
        }
        classStarted = true;
        setStatus(`${response.class.name} 반으로 수업을 시작했습니다.`);
        joinInfo.hidden = false;
    });
}

classList.addEventListener('click', (event) => {
    const card = event.target.closest('.home-class-card');
    if (!card) return;
    if (event.target.closest('.home-class-rename')) {
        updateClassName(card);
        return;
    }
    if (event.target.closest('.home-class-delete')) {
        deleteClass(card);
        return;
    }
    if (event.target.closest('.home-class-select')) selectCard(card);
});

createForm.addEventListener('submit', (event) => {
    event.preventDefault();
    createClass();
});

startButton.addEventListener('click', () => {
    if (!selectedClassId) {
        setStatus('반 카드를 선택해 주세요.', true);
        return;
    }
    startButton.disabled = true;
    setStatus('수업 연결을 시작하는 중입니다...');
    if (socket.connected) {
        selectCurrentClass();
    } else {
        socket.connect();
    }
});

socket.on('connect', selectCurrentClass);
socket.on('connect_error', () => {
    startButton.disabled = !selectedClassId;
    setStatus('수업 연결을 시작하지 못했습니다.', true);
});
