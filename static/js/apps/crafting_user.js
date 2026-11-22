registerUserApp('crafting', (root) => {
    const scope = createSocketScope();
    const status = root.querySelector('#crafting-user-status');
    const choice = root.querySelector('#crafting-team-choice');
    const teamSection = root.querySelector('#crafting-my-team');
    const teamName = root.querySelector('#crafting-my-team-name');
    const members = root.querySelector('#crafting-my-team-members');

    function renderTeamState(state) {
        choice.replaceChildren();
        members.replaceChildren();

        if (state.mode === 'participant') {
            choice.hidden = false;
            state.teams.forEach((team) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'item-btn';
                button.textContent = `${team.name} (${team.member_count}명)`;
                button.disabled = state.team && state.team.id === team.id;
                button.addEventListener('click', () => {
                    button.disabled = true;
                    socket.emit('crafting_team_choose', { team_id: team.id }, (response) => {
                        if (!response || !response.ok) {
                            status.textContent = (response && response.message) ||
                                '팀을 선택하지 못했습니다.';
                        }
                    });
                });
                choice.appendChild(button);
            });
            status.textContent = state.team
                ? '팀을 선택했습니다.'
                : '참가할 팀을 선택해 주세요.';
        } else if (state.mode === 'random') {
            choice.hidden = true;
            status.textContent = '호스트가 무작위로 팀을 배정했습니다.';
        } else {
            choice.hidden = true;
            status.textContent = '호스트가 팀을 배정할 때까지 기다려 주세요.';
        }

        if (state.team) {
            teamSection.hidden = false;
            teamName.textContent = state.team.name;
            state.team.members.forEach((member) => {
                const item = document.createElement('li');
                item.textContent = member.name;
                members.appendChild(item);
            });
        } else {
            teamSection.hidden = true;
        }
    }

    scope.on('crafting_team_state', renderTeamState);
    scope.on('connect', () => {
        socket.emit('crafting_team_sync', (response) => {
            if (response && response.ok) renderTeamState(response);
        });
    });
    socket.emit('crafting_team_sync', (response) => {
        if (response && response.ok) renderTeamState(response);
        else status.textContent = (response && response.message) ||
            '팀 상태를 불러오지 못했습니다.';
    });

    return () => scope.dispose();
});
