const hostMap = document.querySelector('#landgrab-host-map');
const playerList = document.querySelector('#landgrab-player-list');
const hostStatus = document.querySelector('#landgrab-host-status');
const intervalInput = document.querySelector('#landgrab-interval');
const costIncreaseInput = document.querySelector('#landgrab-cost-increase');
const aiCountInput = document.querySelector('#landgrab-ai-count');
const mapWidthInput = document.querySelector('#landgrab-map-width');
const mapHeightInput = document.querySelector('#landgrab-map-height');
const mapGenerationInput = document.querySelector('#landgrab-map-generation');
const mapWrapInput = document.querySelector('#landgrab-map-wrap');
const startButton = document.querySelector('#landgrab-start');
const stopButton = document.querySelector('#landgrab-stop');
const optionSection = document.querySelector('#landgrab-option');
const mapRenderer = createLandgrabMapRenderer(hostMap, 38, 7, 12);

function renderHostState(state) {
    const resourceNames = state.resource_names;
    const resourceIcons = state.resource_icons;
    document.querySelectorAll('[data-landgrab-resource]').forEach((element) => {
        const key = element.dataset.landgrabResource;
        element.replaceChildren(createLandgrabResourceIcon(key, resourceNames, resourceIcons));
    });
    mapRenderer.render(state.tiles || [], state.map_width, state.map_wrap);
    optionSection.style.display = state.phase === 'running' ? 'none' : '';
    playerList.replaceChildren();
    (state.players || []).forEach((player) => {
        const card = document.createElement('article');
        card.className = 'landgrab-player-card';
        const heading = document.createElement('h3');
        if (player.color) {
            const color = document.createElement('span');
            color.className = 'landgrab-player-color';
            color.style.backgroundColor = player.color;
            color.setAttribute('aria-hidden', 'true');
            heading.appendChild(color);
        }
        heading.appendChild(document.createTextNode(
            player.name + (player.eliminated ? ' · 탈락' : '') +
            ' · 영토 ' + player.territory_count
        ));
        card.appendChild(heading);
        const resources = document.createElement('p');
        appendLandgrabResources(resources, player.resources, resourceNames, resourceIcons,
            (amount) => amount, ' · ');
        card.appendChild(resources);
        playerList.appendChild(card);
    });

    const running = state.phase === 'running';
    startButton.style.visibility = running ? 'hidden' : 'visible';
    stopButton.style.visibility = running ? 'visible' : 'hidden';
    intervalInput.disabled = running;
    costIncreaseInput.disabled = running;
    aiCountInput.disabled = running;
    mapWidthInput.disabled = running;
    mapHeightInput.disabled = running;
    mapGenerationInput.disabled = running;
    mapWrapInput.disabled = running;
    if (running) {
        mapWidthInput.value = state.map_width;
        aiCountInput.value = state.ai_count;
        mapHeightInput.value = state.map_height;
        mapGenerationInput.value = state.map_generation;
        mapWrapInput.checked = state.map_wrap;
        hostStatus.textContent = '게임 진행 중 · ' +
            state.resource_interval + '초마다 자원을 생산합니다. 가장 가까운 도시에서 한 칸 멀어질 때마다 구매 비용이 ' +
            state.cost_increase_rate + '%씩 증가합니다. 지도 크기는 ' +
            state.map_width + ' × ' + state.map_height + '칸이며, 좌우 연결은 ' +
            (state.map_wrap ? '켜져 있습니다.' : '꺼져 있습니다.');
    } else if (state.phase === 'ended') {
        hostStatus.textContent = '게임이 종료되었습니다. 새 지도를 생성할 수 있습니다.';
    } else {
        hostStatus.textContent = '주기, 거리당 비용 증가율과 지도 크기를 설정하고 게임을 시작하세요.';
    }
}

socket.on('connect', () => {
    socket.emit('landgrab_sync', (response) => {
        if (response && response.ok) renderHostState(response);
        else {
            hostStatus.textContent = (response && response.message) ||
                '게임 상태를 불러오지 못했습니다.';
            startButton.style.visibility = 'hidden';
        }
    });
});
socket.on('landgrab_host_state', renderHostState);

mapGenerationInput.addEventListener('change', () => {
    if (mapGenerationInput.value === 'world') {
        mapWidthInput.value = 100;
        mapHeightInput.value = 70;
    } else if (mapGenerationInput.value === 'korea') {
        mapWidthInput.value = 30;
        mapHeightInput.value = 50;
    }
});

startButton.addEventListener('click', () => {
    startButton.style.visibility = 'hidden';
    socket.emit('landgrab_start', {
        resource_interval: Number(intervalInput.value),
        cost_increase_rate: Number(costIncreaseInput.value),
        ai_count: Number(aiCountInput.value),
        map_width: Number(mapWidthInput.value),
        map_height: Number(mapHeightInput.value),
        map_generation: mapGenerationInput.value,
        map_wrap: mapWrapInput.checked
    }, (response) => {
        if (!response || !response.ok) {
            hostStatus.textContent = (response && response.message) ||
                '게임을 시작하지 못했습니다.';
            startButton.style.visibility = 'visible';
            return;
        }
        renderHostState(response);
    });
});

stopButton.addEventListener('click', () => {
    stopButton.style.visibility = 'hidden';
    socket.emit('landgrab_stop', (response) => {
        if (!response || !response.ok) {
            hostStatus.textContent = (response && response.message) ||
                '게임을 종료하지 못했습니다.';
            stopButton.style.visibility = 'visible';
            return;
        }
        renderHostState(response);
    });
});
