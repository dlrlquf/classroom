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

    function hideTilePanel() {
        hideBuildWarning();
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

    function refreshTileActions() {
        if (!selectedTile) return;
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
        resourceNames = state.resource_names;
        resourceIcons = state.resource_icons;
        running = state.phase === 'running' && !state.eliminated;
        const ownedPositions = new Set((state.owned || []).map((tile) => tile.q + ',' + tile.r));
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
            status.textContent = '';
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
