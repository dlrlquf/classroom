const modeSelect = document.querySelector('#crafting-team-mode');
const countSelect = document.querySelector('#crafting-team-count');
const configureButton = document.querySelector('#crafting-team-configure');
const randomizeButton = document.querySelector('#crafting-team-randomize');
const teamsContainer = document.querySelector('#crafting-host-teams');
const status = document.querySelector('#crafting-team-status');
const teamNamesById = new Map();

function startTeamNameEdit(team, heading, title, editButton) {
    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 12;
    input.value = team.name;
    input.className = 'crafting-team-name-input';
    input.setAttribute('aria-label', '팀 이름');

    const finish = () => {
        const name = input.value.trim() || `${team.id}팀`;
        title.textContent = name;
        team.name = name;
        teamNamesById.set(team.id, name);
        heading.replaceChildren(title, editButton);
    };

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            input.blur();
        } else if (event.key === 'Escape') {
            input.value = team.name;
            input.blur();
        }
    });
    input.addEventListener('blur', finish);
    title.replaceChildren(input);
    input.focus();
    input.select();
}

function renderTeamState(state) {
    modeSelect.value = state.mode;
    countSelect.value = String(state.team_count);
    randomizeButton.hidden = state.mode !== 'random';

    teamsContainer.replaceChildren();
    state.teams.forEach((team) => {
        if (!teamNamesById.has(team.id)) {
            teamNamesById.set(team.id, team.name);
        } else {
            team.name = teamNamesById.get(team.id);
        }
        const card = document.createElement('article');
        card.className = 'crafting-host-team';

        const heading = document.createElement('h3');
        heading.className = 'crafting-team-heading';

        const title = document.createElement('span');
        title.textContent = team.name;

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'crafting-team-edit';
        editButton.textContent = '✏️';
        editButton.setAttribute('aria-label', `${team.name} 이름 바꾸기`);
        editButton.addEventListener('click', () => {
            startTeamNameEdit(team, heading, title, editButton);
        });

        heading.append(title, editButton);
        card.appendChild(heading);

        const members = document.createElement('ul');
        team.members.forEach((member) => {
            const row = document.createElement('li');
            const name = document.createElement('span');
            name.textContent = member.name;
            row.appendChild(name);

            if (state.mode === 'host') {
                const select = document.createElement('select');
                state.teams.forEach((option) => {
                    const choice = document.createElement('option');
                    choice.value = String(option.id);
                    choice.textContent = option.name;
                    choice.selected = team.id === option.id;
                    select.appendChild(choice);
                });
                select.addEventListener('change', () => {
                    socket.emit('crafting_team_assign', {
                        client_id: member.id,
                        team_id: Number(select.value),
                    });
                });
                row.appendChild(select);
            }
            members.appendChild(row);
        });
        card.appendChild(members);
        teamsContainer.appendChild(card);
    });

    if (state.mode === 'host' && state.unassigned.length) {
        const card = document.createElement('article');
        card.className = 'crafting-host-team crafting-unassigned';
        const title = document.createElement('h3');
        title.textContent = '미배정';
        card.appendChild(title);
        const members = document.createElement('ul');
        state.unassigned.forEach((participant) => {
            const row = document.createElement('li');
            const name = document.createElement('span');
            name.textContent = participant.name;
            row.appendChild(name);
            const select = document.createElement('select');
            state.teams.forEach((team) => {
                const choice = document.createElement('option');
                choice.value = String(team.id);
                choice.text = team.name;
                select.appendChild(choice);
            });
            select.addEventListener('change', () => {
                socket.emit('crafting_team_assign', {
                    client_id: participant.id,
                    team_id: Number(select.value),
                });
            });
            row.appendChild(select);
            members.appendChild(row);
        });
        card.appendChild(members);
        teamsContainer.appendChild(card);
    }
}

function configureTeams() {
    configureButton.disabled = true;
    const teamCount = Number(countSelect.value);
    const names = Array.from(
        { length: teamCount },
        (_, index) => teamNamesById.get(index + 1) || `${index + 1}팀`
    );
    socket.emit('crafting_team_configure', {
        mode: modeSelect.value,
        team_count: Number(countSelect.value),
        team_names: names,
    }, (response) => {
        configureButton.disabled = false;
        if (!response || !response.ok) {
            status.textContent = (response && response.message) ||
                '팀 설정을 적용하지 못했습니다.';
            return;
        }
        renderTeamState(response);
        status.textContent = '팀 설정을 적용했습니다.';
    });
}

countSelect.addEventListener('change', () => {
    status.textContent = '팀 수를 적용하려면 팀 설정을 적용하세요.';
});

configureButton.addEventListener('click', configureTeams);

randomizeButton.addEventListener('click', () => {
    randomizeButton.disabled = true;
    socket.emit('crafting_team_randomize', (response) => {
        randomizeButton.disabled = false;
        if (response && response.ok) {
            status.textContent = '참가자를 다시 무작위로 배정했습니다.';
        }
    });
});

socket.on('connect', () => {
    socket.emit('crafting_team_sync', (response) => {
        if (response && response.ok) renderTeamState(response);
    });
});
socket.on('crafting_team_state', renderTeamState);

socket.emit('crafting_team_sync', (response) => {
    if (response && response.ok) renderTeamState(response);
});
