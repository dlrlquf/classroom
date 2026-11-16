const participantList = document.querySelector('#participant-list');
const participantCount = document.querySelector('#participant-count');

function renderParticipants(participants) {
    participantCount.textContent = String(participants.length);
    participantList.replaceChildren();
    participants.forEach((participant) => {
        const item = document.createElement('li');
        item.textContent = participant.name;
        participantList.appendChild(item);
    });
}

socket.on('participants', (data) => renderParticipants(data.participants));
socket.on('connect', () => {
    socket.emit('participants_sync', (response) => {
        if (response && response.ok) renderParticipants(response.participants);
    });
});
