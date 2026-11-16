const hostMap = document.querySelector('#landgrab-host-map');
const playerList = document.querySelector('#landgrab-player-list');
const hostStatus = document.querySelector('#landgrab-host-status');
const intervalInput = document.querySelector('#landgrab-interval');
const costIncreaseInput = document.querySelector('#landgrab-cost-increase');
const startButton = document.querySelector('#landgrab-start');
const stopButton = document.querySelector('#landgrab-stop');

const resourceNames = { wood: '목재', stone: '석재', food: '식량' };
const terrainMarks = {
    water: '물',
    grass: '초',
    desert: '사',
    forest: '숲',
    mountain: '산'
};

function renderMap(container, tiles) {
    container.replaceChildren();
    if (!tiles.length) return;

    const size = 38;
    const hexWidth = Math.sqrt(3) * size;
    const centers = tiles.map((tile) => ({
        tile,
        x: hexWidth * (tile.q + tile.r / 2),
        y: size * 1.5 * tile.r
    }));
    const xs = centers.map((point) => point.x);
    const ys = centers.map((point) => point.y);
    const padding = 8;
    const minX = Math.min(...xs) - hexWidth / 2 - padding;
    const maxX = Math.max(...xs) + hexWidth / 2 + padding;
    const minY = Math.min(...ys) - size - padding;
    const maxY = Math.max(...ys) + size + padding;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', [minX, minY, maxX - minX, maxY - minY].join(' '));
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', '땅따먹기 육각형 지도');

    centers.forEach(({ tile, x, y }) => {
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'landgrab-hex' + (tile.owner ? ' owned' : ''));
        const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
        title.textContent = '(' + tile.q + ', ' + tile.r + ') ' +
            tile.terrain_name + (tile.owner ? ' · ' + tile.owner : '');
        group.appendChild(title);
        const points = [];
        for (let index = 0; index < 6; index += 1) {
            const angle = (Math.PI / 180) * (60 * index - 30);
            points.push(
                (x + size * Math.cos(angle)) + ',' +
                (y + size * Math.sin(angle))
            );
        }
        const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
        polygon.setAttribute('points', points.join(' '));
        polygon.setAttribute('fill', tile.color);
        group.appendChild(polygon);

        const mark = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        mark.setAttribute('x', String(x));
        mark.setAttribute('y', String(y - (tile.owner ? 3 : 0)));
        mark.setAttribute('class', 'landgrab-terrain-mark');
        mark.textContent = terrainMarks[tile.terrain];
        group.appendChild(mark);
        if (tile.owner) {
            const owner = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            owner.setAttribute('x', String(x));
            owner.setAttribute('y', String(y + 12));
            owner.setAttribute('class', 'landgrab-owner-mark');
            owner.textContent = Array.from(tile.owner).slice(0, 7).join('');
            group.appendChild(owner);
        }
        svg.appendChild(group);
    });
    container.appendChild(svg);
}

function renderHostState(state) {
    renderMap(hostMap, state.tiles || []);
    playerList.replaceChildren();
    (state.players || []).forEach((player) => {
        const card = document.createElement('article');
        card.className = 'landgrab-player-card';
        const heading = document.createElement('h3');
        heading.textContent = player.name + ' · 영토 ' + player.territory_count;
        card.appendChild(heading);
        const resources = document.createElement('p');
        resources.textContent = Object.entries(player.resources)
            .map(([key, amount]) => resourceNames[key] + ' ' + amount)
            .join(' · ');
        card.appendChild(resources);
        playerList.appendChild(card);
    });

    const running = state.phase === 'running';
    startButton.disabled = running;
    stopButton.disabled = !running;
    intervalInput.disabled = running;
    costIncreaseInput.disabled = running;
    if (running) {
        hostStatus.textContent = '게임 진행 중 · ' +
            state.resource_interval + '초마다 자원을 생산합니다. 시작 도시에서 한 칸 멀어질 때마다 구매 비용이 ' +
            state.cost_increase_rate + '%씩 증가합니다.';
    } else if (state.phase === 'ended') {
        hostStatus.textContent = '게임이 종료되었습니다. 새 지도를 생성할 수 있습니다.';
    } else {
        hostStatus.textContent = '주기와 거리당 비용 증가율을 설정하고 게임을 시작하세요.';
    }
}

socket.on('connect', () => {
    socket.emit('landgrab_sync', (response) => {
        if (response && response.ok) renderHostState(response);
        else {
            hostStatus.textContent = (response && response.message) ||
                '게임 상태를 불러오지 못했습니다.';
            startButton.disabled = true;
        }
    });
});
socket.on('landgrab_host_state', renderHostState);

startButton.addEventListener('click', () => {
    startButton.disabled = true;
    socket.emit('landgrab_start', {
        resource_interval: Number(intervalInput.value),
        cost_increase_rate: Number(costIncreaseInput.value)
    }, (response) => {
        if (!response || !response.ok) {
            hostStatus.textContent = (response && response.message) ||
                '게임을 시작하지 못했습니다.';
            startButton.disabled = false;
            return;
        }
        renderHostState(response);
    });
});

stopButton.addEventListener('click', () => {
    stopButton.disabled = true;
    socket.emit('landgrab_stop', (response) => {
        if (!response || !response.ok) {
            hostStatus.textContent = (response && response.message) ||
                '게임을 종료하지 못했습니다.';
            stopButton.disabled = false;
            return;
        }
        renderHostState(response);
    });
});
