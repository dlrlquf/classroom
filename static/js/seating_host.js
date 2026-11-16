const classSelect = document.querySelector('#seating-class-select');
const columnsSelect = document.querySelector('#seating-columns');
const classForm = document.querySelector('#seating-class-form');
const classNameInput = document.querySelector('#seating-class-name');
const rosterForm = document.querySelector('#seating-roster-form');
const rosterInput = document.querySelector('#seating-roster-input');
const seatingGrid = document.querySelector('#seating-grid');
const seatingStatus = document.querySelector('#seating-status');
const addRowButton = document.querySelector('#seating-add-row');
const shuffleButton = document.querySelector('#seating-shuffle');

let selectedClass = null;
let draggedSeatId = null;
let rosterDirty = false;

function renderSeating(state, preserveRoster = false) {
    classSelect.replaceChildren();
    state.classes.forEach((classInfo) => {
        const option = document.createElement('option');
        option.value = String(classInfo.id);
        option.textContent = classInfo.name;
        classSelect.appendChild(option);
    });

    selectedClass = state.class;
    if (!selectedClass) {
        rosterDirty = false;
        rosterInput.value = '';
        columnsSelect.disabled = true;
        addRowButton.disabled = true;
        shuffleButton.disabled = true;
        seatingGrid.replaceChildren();
        seatingGrid.style.removeProperty('--seating-columns');
        return;
    }

    classSelect.value = String(selectedClass.id);
    columnsSelect.value = String(selectedClass.columns);
    columnsSelect.disabled = false;
    addRowButton.disabled = false;
    shuffleButton.disabled = selectedClass.seats.every((seat) => !seat.name);
    seatingGrid.style.setProperty('--seating-columns', selectedClass.columns);
    if (!preserveRoster) {
        rosterDirty = false;
        rosterInput.value = selectedClass.seats
            .filter((seat) => seat.name)
            .map((seat) => seat.name).join('\n');
    }
    const onlineNames = new Set(
        selectedClass.online_names.map((name) => name.toLocaleLowerCase())
    );
    const nameCounts = new Map();
    selectedClass.seats.forEach((seat) => {
        if (!seat.name) return;
        const key = seat.name.toLocaleLowerCase();
        nameCounts.set(key, (nameCounts.get(key) || 0) + 1);
    });
    const nameIndexes = new Map();
    seatingGrid.replaceChildren();
    selectedClass.seats.forEach((seat) => {
        const item = document.createElement('li');
        item.className = 'seating-seat' +
            (seat.locked ? ' locked' : '') +
            (seat.name ? '' : ' empty');
        item.draggable = Boolean(seat.name && !seat.locked);
        item.dataset.seatOrder = String(seat.order);

        const name = document.createElement('strong');
        if (seat.name) {
            const key = seat.name.toLocaleLowerCase();
            const index = (nameIndexes.get(key) || 0) + 1;
            nameIndexes.set(key, index);
            name.textContent = nameCounts.get(key) > 1
                ? seat.name + ' (' + index + ')'
                : seat.name;
        } else {
            name.textContent = '빈 자리';
        }
        const nameLength = Array.from(name.textContent).length;
        name.style.fontSize = Math.max(
            0.75,
            1.25 - Math.max(0, nameLength - 6) * 0.05
        ) + 'rem';
        item.appendChild(name);

        if (seat.name) {
            const attendance = document.createElement('span');
            const present = onlineNames.has(seat.name.toLocaleLowerCase());
            attendance.className = present ? 'seating-present' : 'seating-absent';
            attendance.textContent = present ? '참가 중' : '미참가';
            item.appendChild(attendance);
        }
        const lockLabel = document.createElement('span');
        lockLabel.className = 'seating-lock-label';
        lockLabel.textContent = seat.locked ? '잠김' : '';
        item.appendChild(lockLabel);

        item.addEventListener('dragstart', () => {
            draggedSeatId = seat.order;
            item.classList.add('dragging');
        });
        item.addEventListener('dragend', () => {
            draggedSeatId = null;
            item.classList.remove('dragging');
        });
        item.addEventListener('dragover', (event) => event.preventDefault());
        item.addEventListener('drop', (event) => {
            event.preventDefault();
            const targetOrder = Number(item.dataset.seatOrder);
            if (draggedSeatId === null || draggedSeatId === targetOrder) return;
            socket.emit('seating_swap', {
                class_id: selectedClass.id,
                source_order: draggedSeatId,
                target_order: targetOrder
            }, handleSeatingResponse);
        });
        item.addEventListener('contextmenu', (event) => {
            event.preventDefault();
            socket.emit('seating_seat_lock', {
                class_id: selectedClass.id,
                seat_order: seat.order,
                locked: !seat.locked
            }, handleSeatingResponse);
        });
        seatingGrid.appendChild(item);
    });
}

function handleSeatingResponse(response) {
    if (!response || !response.ok) {
        seatingStatus.textContent = (response && response.message) ||
            '자리 배치를 저장하지 못했습니다.';
        columnsSelect.disabled = !selectedClass;
        return;
    }
    if (response.class) {
        selectedClass = response.class;
        seatingStatus.textContent = '';
        renderSeating({
            classes: Array.from(classSelect.options, (option) => ({
                id: Number(option.value),
                name: option.textContent
            })),
            class: response.class
        }, rosterDirty);
    }
}

function syncSeating(classId = null) {
    const data = classId === null ? {} : { class_id: classId };
    socket.emit('seating_sync', data, (response) => {
        if (!response || !response.ok) {
            seatingStatus.textContent = (response && response.message) ||
                '자리 배치 정보를 불러오지 못했습니다.';
            return;
        }
        renderSeating(response);
    });
}

classSelect.addEventListener('change', () => {
    syncSeating(Number(classSelect.value));
});

columnsSelect.addEventListener('change', () => {
    if (!selectedClass) return;
    columnsSelect.disabled = true;
    socket.emit('seating_columns_update', {
        class_id: selectedClass.id,
        columns: Number(columnsSelect.value)
    }, handleSeatingResponse);
});

addRowButton.addEventListener('click', () => {
    if (!selectedClass) return;
    addRowButton.disabled = true;
    socket.emit('seating_row_add', { class_id: selectedClass.id }, (response) => {
        handleSeatingResponse(response);
        if (!response || !response.ok) addRowButton.disabled = false;
    });
});

shuffleButton.addEventListener('click', () => {
    if (!selectedClass) return;
    socket.emit('seating_shuffle', { class_id: selectedClass.id }, handleSeatingResponse);
});

classForm.addEventListener('submit', (event) => {
    event.preventDefault();
    socket.emit('seating_class_create', { name: classNameInput.value }, (response) => {
        if (!response || !response.ok) {
            seatingStatus.textContent = (response && response.message) ||
                '반을 추가하지 못했습니다.';
            return;
        }
        classNameInput.value = '';
        seatingStatus.textContent = '';
        renderSeating(response);
    });
});

rosterForm.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!selectedClass) {
        seatingStatus.textContent = '먼저 반을 추가해 주세요.';
        return;
    }
    socket.emit('seating_roster_save', {
        class_id: selectedClass.id,
        roster: rosterInput.value
    }, (response) => {
        if (response && response.ok) rosterDirty = false;
        handleSeatingResponse(response);
    });
});

rosterInput.addEventListener('input', () => {
    rosterDirty = true;
});

socket.on('participants', (data) => {
    if (!selectedClass) return;
    selectedClass.online_names = (data.participants || []).map((participant) => participant.name);
    renderSeating({
        classes: Array.from(classSelect.options, (option) => ({
            id: Number(option.value),
            name: option.textContent
        })),
        class: selectedClass
    }, true);
});

socket.on('connect', () => {
    syncSeating(selectedClass ? selectedClass.id : null);
});
