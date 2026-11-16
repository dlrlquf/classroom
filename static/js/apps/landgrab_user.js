registerUserApp('landgrab', (root) => {
    const scope = createSocketScope();
    const status = root.querySelector('#landgrab-user-status');
    const resourcesContainer = root.querySelector('#landgrab-resources');
    const mapContainer = root.querySelector('#landgrab-user-map');
    const buyableList = root.querySelector('#landgrab-buyable-list');
    const resourceTimer = root.querySelector('#landgrab-resource-timer');
    let resourceDeadline = null;
    const timerId = window.setInterval(updateResourceTimer, 1000);

    const resourceNames = { wood: '목재', stone: '석재', food: '식량' };
    const terrainMarks = {
        water: '물',
        grass: '초',
        desert: '사',
        forest: '숲',
        mountain: '산'
    };

    function updateResourceTimer() {
        if (resourceDeadline === null) {
            resourceTimer.textContent = '--:--';
            return;
        }

        const remaining = Math.max(
            0,
            Math.ceil((resourceDeadline - Date.now()) / 1000)
        );
        const minutes = Math.floor(remaining / 60);
        const seconds = remaining % 60;
        resourceTimer.textContent = String(minutes).padStart(2, '0') + ':' +
            String(seconds).padStart(2, '0');
    }

    function renderMap(tiles) {
        mapContainer.replaceChildren();
        if (!tiles.length) return;

        const size = 34;
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
                owner.setAttribute('y', String(y + 11));
                owner.setAttribute('class', 'landgrab-owner-mark');
                owner.textContent = Array.from(tile.owner).slice(0, 6).join('');
                group.appendChild(owner);
            }
            svg.appendChild(group);
        });
        mapContainer.appendChild(svg);
    }

    function renderUserState(state) {
        resourceDeadline = state.phase === 'running' &&
            Number.isFinite(state.resource_seconds_remaining)
            ? Date.now() + state.resource_seconds_remaining * 1000
            : null;
        updateResourceTimer();
        renderMap(state.tiles || []);
        resourcesContainer.replaceChildren();
        Object.entries(state.resources || {}).forEach(([key, amount]) => {
            const item = document.createElement('span');
            item.className = 'landgrab-resource';
            item.textContent = resourceNames[key] + ': ' + amount +
                ' (+' + ((state.production || {})[key] || 0) + ')';
            resourcesContainer.appendChild(item);
        });

        buyableList.replaceChildren();
        (state.buyable || []).forEach((tile) => {
            const item = document.createElement('li');
            const details = document.createElement('div');
            details.className = 'landgrab-buyable-details';
            const lines = [
                '좌표 : (' + tile.q + ', ' + tile.r + ')',
                '지형 : ' + tile.terrain_name,
                '자원 : ' + Object.entries(tile.production || {})
                    .map(([key, amount]) => resourceNames[key] + ' +' + amount)
                    .join(', '),
                '비용 : ' + Object.entries(tile.cost || {})
                    .map(([key, amount]) => resourceNames[key] + ' ' + amount)
                    .join(', ')
            ];
            lines.forEach((text) => {
                const line = document.createElement('div');
                line.textContent = text;
                details.appendChild(line);
            });
            item.appendChild(details);

            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'item-btn';
            button.textContent = '구매';
            button.disabled = Object.entries(tile.cost).some(
                ([key, amount]) => (state.resources[key] || 0) < amount
            );
            button.addEventListener('click', () => {
                button.disabled = true;
                socket.emit('landgrab_buy', { q: tile.q, r: tile.r }, (response) => {
                    if (!response || !response.ok) {
                        status.textContent = (response && response.message) ||
                            '땅을 구매하지 못했습니다.';
                        button.disabled = false;
                        return;
                    }
                    renderUserState(response);
                    status.textContent = '땅을 구매했습니다.';
                });
            });
            item.appendChild(button);
            buyableList.appendChild(item);
        });

        if (state.phase === 'running') {
            status.textContent = '자원은 ' + state.resource_interval +
                '초마다 생산됩니다. 내 영토에 인접한 땅만 구매할 수 있습니다.';
        } else if (state.phase === 'ended') {
            status.textContent = '게임이 종료되었습니다.';
        } else {
            status.textContent = '호스트가 지도를 생성하기를 기다리는 중입니다.';
        }
    }

    scope.on('landgrab_user_state', renderUserState);
    scope.on('connect', () => {
        socket.emit('landgrab_sync', (response) => {
            if (response && response.ok) renderUserState(response);
            else status.textContent = (response && response.message) ||
                '게임 상태를 불러오지 못했습니다.';
        });
    });
    socket.emit('landgrab_sync', (response) => {
        if (response && response.ok) renderUserState(response);
        else status.textContent = (response && response.message) ||
            '게임 상태를 불러오지 못했습니다.';
    });

    return () => {
        window.clearInterval(timerId);
        scope.dispose();
    };
});
