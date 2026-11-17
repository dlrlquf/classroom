registerUserApp('landgrab', (root) => {
    const scope = createSocketScope();
    const status = root.querySelector('#landgrab-user-status');
    const resourcesContainer = root.querySelector('#landgrab-resources');
    const mapContainer = root.querySelector('#landgrab-user-map');
    const tilePanel = root.querySelector('#landgrab-tile-panel');
    const tilePanelTitle = root.querySelector('#landgrab-tile-panel-title');
    const tilePanelClose = root.querySelector('#landgrab-tile-panel-close');
    const tileActions = root.querySelector('#landgrab-tile-actions');
    const buildWarning = root.querySelector('#landgrab-build-warning');
    const resourceTimer = root.querySelector('#landgrab-resource-timer');
    const myCityButton = root.querySelector('#landgrab-my-city');
    const mapRenderer = createLandgrabMapRenderer(mapContainer, 34, 6, 11, selectTile);
    let selectedTile = null;
    let includeBuilding = true;
    let tileRequest = 0;
    let disposed = false;
    let running = false;
    let warningTimer = null;
    let resourceDeadline = null;
    let cities = [];
    let gameState = null;
    let tilesByPosition = new Map();
    let ownedPositions = new Set();
    let portMode = null;
    const timerId = window.setInterval(updateResourceTimer, 1000);

    let resourceNames = {};
    let resourceIcons = {};

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

    function hideBuildWarning() {
        if (warningTimer !== null) window.clearTimeout(warningTimer);
        warningTimer = null;
        buildWarning.hidden = true;
    }

    function showBuildWarning(message) {
        hideBuildWarning();
        buildWarning.textContent = message;
        buildWarning.hidden = false;
        warningTimer = window.setTimeout(hideBuildWarning, 3500);
    }

    function selectTile(q, r) {
        if (!running) return;
        hideBuildWarning();
        if (!selectedTile || selectedTile.q !== q || selectedTile.r !== r) {
            includeBuilding = true;
        }
        selectedTile = { q, r };
        tilePanelTitle.textContent = '(' + q + ', ' + r + ')';
        mapRenderer.setSelection(q, r);
        tilePanel.hidden = false;
        refreshTileActions();
    }

    function clearPortMode() {
        portMode = null;
        mapRenderer.setPortDestinations(new Set());
    }

    function hideTilePanel() {
        hideBuildWarning();
        clearPortMode();
        selectedTile = null;
        tileRequest += 1;
        tilePanel.hidden = true;
        mapRenderer.setSelection(null, null);
    }

    tilePanelClose.addEventListener('click', () => {
        hideTilePanel();
        mapContainer.focus({ preventScroll: true });
    });

    myCityButton.addEventListener('click', () => {
        const city = cities[Math.floor(Math.random() * cities.length)];
        if (city && !mapRenderer.centerOn(city.q, city.r)) {
            status.textContent = '도시 위치를 지도에서 찾지 못했습니다.';
        }
    });

    function findPortDestinations(source) {
        const sourceKey = source.q + ',' + source.r;
        const distances = new Map([[sourceKey, 0]]);
        const destinations = new Map();
        const queue = [source];
        for (let index = 0; index < queue.length; index += 1) {
            const position = queue[index];
            const distance = distances.get(position.q + ',' + position.r);
            mapRenderer.neighborPositions(position.q, position.r).forEach((neighbor) => {
                const key = neighbor.q + ',' + neighbor.r;
                if (distances.has(key)) return;
                const tile = tilesByPosition.get(key);
                if (!tile || (tile.terrain !== 'water' && tile.terrain !== 'coast') ||
                    (tile.owner !== null && !ownedPositions.has(key))) return;
                const nextDistance = distance + 1;
                distances.set(key, nextDistance);
                queue.push(neighbor);
                if (tile.terrain === 'coast' && tile.owner === null && !tile.building) {
                    destinations.set(key, nextDistance);
                }
            });
        }
        return destinations;
    }

    function cityDistance(tile) {
        return Math.min(...cities.map((city) => {
            const dq = tile.q - city.q;
            const dr = tile.r - city.r;
            const offsets = gameState.map_wrap ? [-gameState.map_width, 0, gameState.map_width] : [0];
            return Math.min(...offsets.map((offset) =>
                Math.max(Math.abs(dq + offset), Math.abs(dr), Math.abs(dq + offset + dr))
            ));
        }));
    }

    function renderPortSource(tile) {
        tileRequest += 1;
        tileActions.replaceChildren();
        tilePanelTitle.textContent = '(' + tile.q + ', ' + tile.r + ') · ' + tile.terrain_name;
        const description = document.createElement('p');
        description.textContent = tile.active
            ? '내 항구 · 이동 가능'
            : '도시와 연결되지 않아 항구를 사용할 수 없습니다.';
        tileActions.appendChild(description);
        const production = document.createElement('p');
        production.textContent = '생산량: ';
        if (Object.keys(tile.production).length) {
            appendLandgrabResources(production, tile.production, resourceNames, resourceIcons,
                (amount) => (amount >= 0 ? '+' : '') + amount, ' ');
        } else {
            production.appendChild(document.createTextNode('없음'));
        }
        tileActions.appendChild(production);
        (gameState.port_links || []).forEach((link) => {
            const first = link.source.q === tile.q && link.source.r === tile.r;
            const second = link.target.q === tile.q && link.target.r === tile.r;
            if (!first && !second) return;
            const other = first ? link.target : link.source;
            const connection = document.createElement('p');
            connection.textContent = '연결 항구: (' + other.q + ', ' + other.r + ') · ' +
                (link.active ? '연결됨' : '연결 끊김');
            tileActions.appendChild(connection);
        });
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'item-btn';
        button.textContent = '연결 항구 건설';
        button.disabled = !tile.active;
        button.addEventListener('click', () => {
            const source = { q: tile.q, r: tile.r };
            const destinations = findPortDestinations(source);
            portMode = { source, destinations, gameId: gameState.game_id };
            mapRenderer.setPortDestinations(new Set(destinations.keys()));
            renderPortDestination();
        });
        tileActions.appendChild(button);
    }

    function renderPortDestination() {
        tileRequest += 1;
        tileActions.replaceChildren();
        const source = portMode.source;
        const key = selectedTile.q + ',' + selectedTile.r;
        const distance = portMode.destinations.get(key);
        const tile = tilesByPosition.get(key);
        const instruction = document.createElement('p');
        instruction.textContent = '노란 테두리의 빈 연안을 선택하세요. 출발 항구: (' +
            source.q + ', ' + source.r + ')';
        tileActions.appendChild(instruction);
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'item-btn';
        cancel.textContent = '연결 취소';
        cancel.addEventListener('click', () => {
            clearPortMode();
            selectTile(source.q, source.r);
        });
        tileActions.appendChild(cancel);
        if (distance === undefined) {
            const message = document.createElement('p');
            message.textContent = portMode.destinations.size
                ? '건설 가능한 연안 ' + portMode.destinations.size + '곳'
                : '연결 가능한 빈 연안이 없습니다.';
            tileActions.appendChild(message);
            return;
        }
        if (!tile || tile.owner !== null || tile.building || tile.terrain !== 'coast') {
            const message = document.createElement('p');
            message.textContent = '이 연안은 더 이상 건설할 수 없습니다. 항구를 다시 선택해 주세요.';
            tileActions.appendChild(message);
            return;
        }
        if (!tile.cost || !gameState.port_cost || !cities.length) {
            const message = document.createElement('p');
            message.textContent = '항구 건설 비용 정보를 불러오지 못했습니다.';
            tileActions.appendChild(message);
            return;
        }
        tilePanelTitle.textContent = '(' + tile.q + ', ' + tile.r + ') · ' + tile.terrain_name;
        const landDistance = cityDistance(tile);
        const rate = gameState.cost_increase_rate;
        const landCost = Object.fromEntries(Object.entries(tile.cost).map(([resource, amount]) =>
            [resource, Math.floor(amount * (100 + landDistance * rate) / 100)]
        ));
        const portCost = Object.fromEntries(Object.entries(gameState.port_cost).map(([resource, amount]) =>
            [resource, Math.floor(amount * (100 + distance * rate) / 100)]
        ));
        const total = { ...landCost };
        Object.entries(portCost).forEach(([resource, amount]) => {
            total[resource] = (total[resource] || 0) + amount;
        });
        [[landCost, '연안 구매 (도시까지 ' + landDistance + '칸): '],
            [portCost, '항구 건설 (바닷길 ' + distance + '칸): '],
            [total, '총 비용: ']].forEach(([cost, label]) => {
            const details = document.createElement('p');
            details.textContent = label;
            appendLandgrabResources(details, cost, resourceNames, resourceIcons, (amount) => amount, ', ');
            tileActions.appendChild(details);
        });
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'item-btn';
        button.textContent = '항구 건설';
        button.disabled = Object.entries(total).some(([resource, amount]) =>
            (gameState.resources[resource] || 0) < amount
        );
        if (button.disabled) {
            const reason = document.createElement('p');
            reason.textContent = '자원이 부족합니다.';
            tileActions.appendChild(reason);
        }
        const target = { q: tile.q, r: tile.r };
        const gameId = portMode.gameId;
        button.addEventListener('click', () => {
            button.disabled = true;
            socket.emit('landgrab_build_linked_port', {
                source, target, game_id: gameId, expected_distance: distance, expected_cost: total
            }, (result) => {
                if (disposed) return;
                clearPortMode();
                if (!result || !result.ok) {
                    hideTilePanel();
                    status.textContent = (result && result.message) ||
                        '연결 항구를 건설하지 못했습니다.';
                    return;
                }
                renderUserState(result);
                selectTile(target.q, target.r);
                status.textContent = '연결 항구를 건설했습니다.';
            });
        });
        tileActions.appendChild(button);
    }

    function refreshTileActions() {
        if (!selectedTile) return;
        if (portMode) {
            renderPortDestination();
            return;
        }
        const key = selectedTile.q + ',' + selectedTile.r;
        const selected = tilesByPosition.get(key);
        if (selected && ownedPositions.has(key) &&
            selected.building && selected.building.type === 'port') {
            renderPortSource(selected);
            return;
        }
        const requestId = ++tileRequest;
        const position = { ...selectedTile };
        tileActions.textContent = '타일 정보를 불러오는 중입니다.';
        socket.emit('landgrab_tile_info', position, (response) => {
            if (disposed || requestId !== tileRequest) return;
            if (!response || !response.ok) {
                tileActions.textContent = (response && response.message) ||
                    '타일 정보를 불러오지 못했습니다.';
                return;
            }
            tileActions.replaceChildren();
            const tile = response.tile;
            tilePanelTitle.textContent = '(' + tile.q + ', ' + tile.r + ') · ' + tile.terrain_name;
            const movement = document.createElement('p');
            movement.textContent = tile.movable ? '이동 가능' : '이동 불가';
            tileActions.appendChild(movement);
            const owner = document.createElement('p');
            owner.className = 'landgrab-tile-owner';
            owner.textContent = tile.owner || '빈 땅';
            tileActions.appendChild(owner);
            if (tile.owner && tile.active === false) {
                const inactive = document.createElement('p');
                inactive.textContent = '도시와 연결되지 않아 생산·건설 및 인접 땅 구매가 중단되었습니다.';
                tileActions.appendChild(inactive);
            }
            const production = document.createElement('p');
            production.textContent = '생산량: ';
            if (Object.keys(tile.production).length) {
                appendLandgrabResources(production, tile.production, resourceNames, resourceIcons,
                    (amount) => (amount >= 0 ? '+' : '') + amount, ' ');
            } else {
                production.appendChild(document.createTextNode('없음'));
            }
            tileActions.appendChild(production);

            if (!response.owned) {
                const hasBuilding = Boolean(tile.owner && tile.building);
                let selectedCost = null;
                if (hasBuilding) {
                    const label = document.createElement('label');
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.checked = includeBuilding;
                    label.appendChild(checkbox);
                    label.appendChild(document.createTextNode(
                        ' ' + tile.building.name + ' 인수 (해제 시 철거)'
                    ));
                    tileActions.appendChild(label);
                    checkbox.addEventListener('change', () => {
                        includeBuilding = checkbox.checked;
                        updatePurchase();
                    });
                }
                const cost = document.createElement('p');
                tileActions.appendChild(cost);
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'item-btn';
                button.textContent = '구매';
                button.addEventListener('click', () => {
                    button.disabled = true;
                    socket.emit('landgrab_buy', {
                        ...position,
                        include_building: hasBuilding && includeBuilding,
                        expected_building: tile.building ? tile.building.type : null,
                        expected_cost: selectedCost
                    }, (result) => {
                        if (disposed) return;
                        if (!result || !result.ok) {
                            status.textContent = (result && result.message) ||
                                '땅을 구매하지 못했습니다.';
                            refreshTileActions();
                            return;
                        }
                        renderUserState(result);
                        status.textContent = '땅을 구매했습니다.';
                    });
                });
                tileActions.appendChild(button);
                const reason = document.createElement('p');
                tileActions.appendChild(reason);
                function updatePurchase() {
                    const option = response.purchase_options[
                        hasBuilding && includeBuilding ? 'with_building' : 'land_only'
                    ];
                    selectedCost = option.cost;
                    cost.replaceChildren();
                    if (option.cost) {
                        cost.appendChild(document.createTextNode('구매 비용: '));
                        appendLandgrabResources(cost, option.cost, resourceNames, resourceIcons,
                            (amount) => amount, ', ');
                        cost.appendChild(document.createTextNode(
                            ' (가장 가까운 도시까지 ' + tile.distance + '칸)'
                        ));
                    }
                    button.disabled = Boolean(option.error);
                    reason.textContent = option.error || '';
                    reason.hidden = !option.error;
                }
                updatePurchase();
                return;
            }

            const heading = document.createElement('h3');
            heading.textContent = '건설';
            tileActions.appendChild(heading);
            if (!response.buildings.length) {
                const message = document.createElement('p');
                message.textContent = '이 지형에 건설 가능한 건물이 없습니다.';
                tileActions.appendChild(message);
                return;
            }
            const list = document.createElement('ul');
            list.className = 'landgrab-building-list';
            tileActions.appendChild(list);
            response.buildings.forEach((building) => {
                const built = tile.building && tile.building.type === building.type;
                const item = document.createElement('li');
                const details = document.createElement('div');
                const name = document.createElement('strong');
                name.textContent = building.name;
                details.appendChild(name);
                if (!built) {
                    const cost = document.createElement('div');
                    cost.textContent = '비용: ';
                    appendLandgrabResources(cost, building.cost, resourceNames, resourceIcons,
                        (amount) => amount, ', ');
                    details.appendChild(cost);
                }
                item.appendChild(details);
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'item-btn';
                button.textContent = built ? '건설 완료' : '건설';
                button.setAttribute('aria-label', building.name + ' ' + button.textContent);
                button.disabled = Boolean(built || building.error);
                if (!built) {
                    button.addEventListener('click', () => {
                        button.disabled = true;
                        socket.emit('landgrab_build', { ...position, building: building.type }, (result) => {
                            if (disposed) return;
                            if (!result || !result.ok) {
                                const message = (result && result.message) ||
                                    '건물을 건설하지 못했습니다.';
                                status.textContent = message;
                                showBuildWarning(message);
                                refreshTileActions();
                                return;
                            }
                            renderUserState(result);
                            status.textContent = building.name + '을 건설했습니다.';
                        });
                    });
                }
                if (building.error && !built) {
                    const tooltip = document.createElement('span');
                    tooltip.className = 'landgrab-building-tooltip';
                    tooltip.tabIndex = 0;
                    tooltip.title = building.error;
                    tooltip.setAttribute('role', 'group');
                    tooltip.setAttribute('aria-label', building.name + ' 건설: ' + building.error);
                    let touchStart = null;
                    tooltip.addEventListener('pointerdown', (event) => {
                        if (event.pointerType === 'touch') {
                            touchStart = { id: event.pointerId, x: event.clientX, y: event.clientY };
                        }
                    });
                    tooltip.addEventListener('pointerup', (event) => {
                        if (touchStart && event.pointerId === touchStart.id &&
                            Math.hypot(event.clientX - touchStart.x, event.clientY - touchStart.y) < 10) {
                            showBuildWarning(building.error);
                        }
                        touchStart = null;
                    });
                    tooltip.addEventListener('pointercancel', () => {
                        touchStart = null;
                    });
                    tooltip.addEventListener('keydown', (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            showBuildWarning(building.error);
                        }
                    });
                    tooltip.appendChild(button);
                    item.appendChild(tooltip);
                } else {
                    item.appendChild(button);
                }
                list.appendChild(item);
            });
        });
    }

    function renderUserState(state) {
        gameState = state;
        resourceNames = state.resource_names;
        resourceIcons = state.resource_icons;
        running = state.phase === 'running' && !state.eliminated;
        ownedPositions = new Set((state.owned || []).map((tile) => tile.q + ',' + tile.r));
        tilesByPosition = new Map((state.tiles || []).map((tile) => [tile.q + ',' + tile.r, tile]));
        cities = (state.tiles || []).filter((tile) =>
            tile.building && tile.building.type === 'city' &&
            ownedPositions.has(tile.q + ',' + tile.r)
        );
        myCityButton.disabled = !running || !cities.length;
        resourceDeadline = state.phase === 'running' &&
            Number.isFinite(state.resource_seconds_remaining)
            ? Date.now() + state.resource_seconds_remaining * 1000
            : null;
        updateResourceTimer();
        mapRenderer.render(state.tiles || [], state.map_width, state.map_wrap);
        let portInvalidated = false;
        if (portMode) {
            const sourceKey = portMode.source.q + ',' + portMode.source.r;
            const source = tilesByPosition.get(sourceKey);
            if (portMode.gameId !== state.game_id || !ownedPositions.has(sourceKey) ||
                !source || !source.active || !source.building || source.building.type !== 'port') {
                clearPortMode();
                hideTilePanel();
                portInvalidated = true;
            }
        }
        resourcesContainer.replaceChildren();
        Object.entries(state.resources || {}).forEach(([key, amount]) => {
            const item = document.createElement('span');
            item.className = 'landgrab-resource';
            item.appendChild(createLandgrabResourceIcon(key, resourceNames, resourceIcons));
            item.appendChild(document.createTextNode(' ' + amount +
                ' (+' + ((state.production || {})[key] || 0) + ')'));
            resourcesContainer.appendChild(item);
        });

        if (state.phase === 'running' && state.eliminated) {
            hideTilePanel();
            status.textContent = '도시를 모두 잃어 탈락했습니다.';
        } else if (state.phase === 'running') {
            refreshTileActions();
            status.textContent = portInvalidated ? '출발 항구를 더 이상 사용할 수 없습니다.' : '';
        } else if (state.phase === 'ended') {
            hideTilePanel();
            status.textContent = '게임이 종료되었습니다.';
        } else {
            hideTilePanel();
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
        disposed = true;
        tileRequest += 1;
        hideBuildWarning();
        window.clearInterval(timerId);
        mapRenderer.dispose();
        scope.dispose();
    };
});
