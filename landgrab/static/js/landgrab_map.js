function createLandgrabResourceIcon(key, names, icons) {
    const icon = document.createElement('span');
    icon.textContent = icons[key];
    icon.title = names[key];
    icon.setAttribute('role', 'img');
    icon.setAttribute('aria-label', names[key]);
    return icon;
}

function appendLandgrabResources(container, resources, names, icons, formatAmount, separator) {
    Object.entries(resources).forEach(([key, amount], index) => {
        if (index) container.appendChild(document.createTextNode(separator));
        container.appendChild(createLandgrabResourceIcon(key, names, icons));
        container.appendChild(document.createTextNode(' ' + formatAmount(amount)));
    });
}

let landgrabRendererCount = 0;

function createLandgrabMapRenderer(container, size, ownerLength, ownerOffset, onSelect) {
    const namespace = 'http://www.w3.org/2000/svg';
    const patternPrefix = 'landgrab-stripe-' + landgrabRendererCount++ + '-';
    const terrainMarks = {
        water: '수역', grass: '초원', desert: '사막', forest: '산림', mountain: '산지'
    };
    const edgeNeighbors = [[1, 0], [0, 1], [-1, 1], [-1, 0], [0, -1], [1, -1]];
    const hexWidth = Math.sqrt(3) * size;
    let tiles = [];
    let tilesByPosition = new Map();
    let centers = [];
    let mapWidth = 0;
    let wrap = false;
    let sideCopies = 0;
    let renderedWidth = 0;
    let renderedHeight = 0;
    let minX = 0;
    let minY = 0;
    let mapGroup = null;
    let visibleBounds = null;
    let scrollFrame = null;
    let selected = null;
    let ownerPatterns = new Map();
    let drag = null;
    let suppressClick = false;

    function normalizeScroll() {
        if (!wrap || !mapWidth) return;
        const period = mapWidth * hexWidth;
        const anchor = sideCopies * period;
        const relative = container.scrollLeft - anchor;
        if (relative < 0 || relative >= period) {
            container.scrollLeft = anchor + ((relative % period) + period) % period;
        }
    }

    function createTile(tile, x, y) {
        const group = document.createElementNS(namespace, 'g');
        group.setAttribute('class', 'landgrab-hex');
        const inactive = Boolean(tile.owner && tile.active === false);
        group.classList.toggle('inactive', inactive);
        const description = '(' + tile.q + ', ' + tile.r + ') ' +
            tile.terrain_name + (tile.building ? ' · ' + tile.building.name : '') +
            (tile.owner ? ' · ' + tile.owner : '') + (inactive ? ' · 도시와 연결 끊김' : '');
        if (onSelect) {
            const isSelected = selected && selected.q === tile.q && selected.r === tile.r;
            group.classList.toggle('selected', Boolean(isSelected));
            group.setAttribute('data-q', String(tile.q));
            group.setAttribute('data-r', String(tile.r));
            group.setAttribute('role', 'button');
            group.setAttribute('tabindex', '0');
            group.setAttribute('aria-pressed', String(Boolean(isSelected)));
            group.setAttribute('aria-label', description);
        }
        const title = document.createElementNS(namespace, 'title');
        title.textContent = description;
        group.appendChild(title);
        const points = [];
        for (let index = 0; index < 6; index += 1) {
            const angle = (Math.PI / 180) * (60 * index - 30);
            points.push(
                (x + size * Math.cos(angle)) + ',' +
                (y + size * Math.sin(angle))
            );
        }
        const polygon = document.createElementNS(namespace, 'polygon');
        polygon.setAttribute('class', 'landgrab-hex-base');
        polygon.setAttribute('points', points.join(' '));
        polygon.setAttribute('fill', tile.color);
        group.appendChild(polygon);

        if (tile.owner_color) {
            const overlay = document.createElementNS(namespace, 'polygon');
            overlay.setAttribute('class', 'landgrab-owner-overlay');
            overlay.setAttribute('points', points.join(' '));
            overlay.setAttribute('fill', 'url(#' + ownerPatterns.get(tile.owner_color) + ')');
            group.appendChild(overlay);
        }

        const mark = document.createElementNS(namespace, 'text');
        mark.setAttribute('x', String(x));
        mark.setAttribute('y', String(y - (tile.building ? 9 : tile.owner ? 3 : 0)));
        mark.setAttribute('class', 'landgrab-terrain-mark');
        mark.textContent = terrainMarks[tile.terrain];
        group.appendChild(mark);
        if (tile.building) {
            const building = document.createElementNS(namespace, 'text');
            building.setAttribute('x', String(x));
            building.setAttribute('y', String(y + 3));
            building.setAttribute('class', 'landgrab-building-mark');
            building.textContent = tile.building.name;
            group.appendChild(building);
        }
        if (tile.owner) {
            const owner = document.createElementNS(namespace, 'text');
            owner.setAttribute('x', String(x));
            owner.setAttribute('y', String(y + ownerOffset + (tile.building ? 5 : 0)));
            owner.setAttribute('class', 'landgrab-owner-mark');
            owner.textContent = Array.from(tile.owner).slice(0, ownerLength).join('');
            group.appendChild(owner);
        }
        if (inactive) {
            const status = document.createElementNS(namespace, 'text');
            status.setAttribute('x', String(x));
            status.setAttribute('y', String(y + size - 7));
            status.setAttribute('class', 'landgrab-inactive-mark');
            status.textContent = '단절';
            group.appendChild(status);
        }
        return group;
    }

    function appendBorders(fragment, tile, x, y) {
        if (!tile.owner_color) return;
        edgeNeighbors.forEach(([dq, dr], index) => {
            const neighborR = tile.r + dr;
            let neighborQ = tile.q + dq;
            if (wrap && mapWidth) {
                const halfWidth = Math.floor(mapWidth / 2);
                const rowOffset = Math.floor(neighborR / 2);
                const column = neighborQ + rowOffset + halfWidth;
                neighborQ = ((column % mapWidth) + mapWidth) % mapWidth - halfWidth - rowOffset;
            }
            const neighbor = tilesByPosition.get(neighborQ + ',' + neighborR);
            const neighborColor = neighbor && neighbor.owner_color;
            // Player colors are unique; draw a shared border from only one side.
            if (neighborColor === tile.owner_color ||
                (neighborColor && tile.owner_color > neighborColor)) return;

            const start = (Math.PI / 180) * (60 * index - 30);
            const end = (Math.PI / 180) * (60 * (index + 1) - 30);
            function line(color) {
                const edge = document.createElementNS(namespace, 'line');
                edge.setAttribute('class', 'landgrab-owner-border');
                edge.setAttribute('x1', String(x + size * Math.cos(start)));
                edge.setAttribute('y1', String(y + size * Math.sin(start)));
                edge.setAttribute('x2', String(x + size * Math.cos(end)));
                edge.setAttribute('y2', String(y + size * Math.sin(end)));
                edge.setAttribute('stroke', color);
                return edge;
            }
            if (neighborColor) {
                fragment.appendChild(line(neighborColor));
                const dashed = line(tile.owner_color);
                dashed.setAttribute('stroke-dasharray', '5 5');
                fragment.appendChild(dashed);
            } else {
                fragment.appendChild(line(tile.owner_color));
            }
        });
    }

    function drawVisible() {
        if (!wrap || !mapGroup || !tiles.length) return;
        const left = minX + container.scrollLeft;
        const top = minY + container.scrollTop;
        const right = left + container.clientWidth;
        const bottom = top + container.clientHeight;
        if (visibleBounds && left >= visibleBounds.left && right <= visibleBounds.right &&
            top >= visibleBounds.top && bottom <= visibleBounds.bottom) return;

        const marginX = Math.max(container.clientWidth / 2, hexWidth * 2);
        const marginY = Math.max(container.clientHeight / 2, size * 2);
        visibleBounds = {
            left: left - marginX,
            right: right + marginX,
            top: top - marginY,
            bottom: bottom + marginY
        };
        const period = mapWidth * hexWidth;
        const fragment = document.createDocumentFragment();
        const borders = document.createDocumentFragment();
        centers.forEach(({ tile, x, y }) => {
            if (y + size < visibleBounds.top || y - size > visibleBounds.bottom) return;
            const first = Math.max(
                -sideCopies, Math.ceil((visibleBounds.left - hexWidth / 2 - x) / period)
            );
            const last = Math.min(
                sideCopies, Math.floor((visibleBounds.right + hexWidth / 2 - x) / period)
            );
            for (let copy = first; copy <= last; copy += 1) {
                const copyX = x + copy * period;
                fragment.appendChild(createTile(tile, copyX, y));
                appendBorders(borders, tile, copyX, y);
            }
        });
        fragment.appendChild(borders);
        mapGroup.replaceChildren(fragment);
    }

    function onScroll() {
        if (!wrap) return;
        normalizeScroll();
        if (scrollFrame !== null) return;
        scrollFrame = window.requestAnimationFrame(() => {
            scrollFrame = null;
            drawVisible();
        });
    }

    function onPointerDown(event) {
        if (!event.isPrimary || event.button !== 0 || drag) return;
        suppressClick = false;
        drag = {
            id: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            lastX: event.clientX,
            lastY: event.clientY,
            moved: false
        };
    }

    function onPointerMove(event) {
        if (!drag || event.pointerId !== drag.id) return;
        if (!drag.moved) {
            if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5) return;
            drag.moved = true;
            container.classList.add('is-dragging');
            container.setPointerCapture(event.pointerId);
        }
        const nextLeft = container.scrollLeft - (event.clientX - drag.lastX);
        if (wrap && mapWidth) {
            const period = mapWidth * hexWidth;
            const anchor = sideCopies * period;
            const relative = nextLeft - anchor;
            container.scrollLeft = anchor + ((relative % period) + period) % period;
        } else {
            container.scrollLeft = nextLeft;
        }
        container.scrollTop -= event.clientY - drag.lastY;
        drag.lastX = event.clientX;
        drag.lastY = event.clientY;
    }

    function onPointerEnd(event) {
        if (!drag || event.pointerId !== drag.id) return;
        suppressClick = event.type === 'pointerup' && drag.moved;
        drag = null;
        container.classList.remove('is-dragging');
        if (container.hasPointerCapture(event.pointerId)) {
            container.releasePointerCapture(event.pointerId);
        }
    }

    function preventNativeDrag(event) {
        event.preventDefault();
    }

    function selectTile(event) {
        if (event.type === 'click' && event.detail !== 0 && suppressClick) {
            suppressClick = false;
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        if (!onSelect || (event.type === 'keydown' && event.key !== 'Enter' && event.key !== ' ')) {
            return;
        }
        const group = event.target.closest('.landgrab-hex');
        if (!group || !container.contains(group)) return;
        if (event.type === 'keydown') event.preventDefault();
        onSelect(Number(group.getAttribute('data-q')), Number(group.getAttribute('data-r')));
    }

    function render(nextTiles, nextWidth, nextWrap) {
        const hadTiles = tiles.length > 0;
        const previousWidth = mapWidth;
        const previousWrap = wrap;
        const previousMinX = minX;
        const previousMinY = minY;
        const scrollLeft = container.scrollLeft;
        const scrollTop = container.scrollTop;
        tiles = nextTiles;
        tilesByPosition = new Map(tiles.map((tile) => [tile.q + ',' + tile.r, tile]));
        mapWidth = nextWidth;
        wrap = nextWrap;
        renderedWidth = container.clientWidth;
        renderedHeight = container.clientHeight;
        visibleBounds = null;

        if (!tiles.length) {
            centers = [];
            mapGroup = null;
            container.replaceChildren();
            return;
        }

        centers = tiles.map((tile) => ({
            tile,
            x: hexWidth * (tile.q + tile.r / 2),
            y: size * 1.5 * tile.r
        }));
        const xs = centers.map((point) => point.x);
        const ys = centers.map((point) => point.y);
        const padding = 8;
        const paddingX = Math.max(padding, renderedWidth / 2 - hexWidth / 2);
        const paddingY = Math.max(padding, renderedHeight / 2 - size);
        const period = mapWidth * hexWidth;
        sideCopies = wrap ? Math.ceil(renderedWidth / period) + 1 : 0;
        minX = Math.min(...xs) - hexWidth / 2 - paddingX - sideCopies * period;
        const maxX = Math.max(...xs) + hexWidth / 2 + paddingX + sideCopies * period;
        minY = Math.min(...ys) - size - paddingY;
        const maxY = Math.max(...ys) + size + paddingY;
        const svg = document.createElementNS(namespace, 'svg');
        svg.setAttribute('viewBox', [minX, minY, maxX - minX, maxY - minY].join(' '));
        svg.setAttribute('width', String(maxX - minX));
        svg.setAttribute('height', String(maxY - minY));
        svg.setAttribute('role', onSelect ? 'group' : 'img');
        svg.setAttribute('aria-label', '땅따먹기 육각형 지도');

        ownerPatterns = new Map();
        const definitions = document.createElementNS(namespace, 'defs');
        tiles.forEach((tile) => {
            if (!tile.owner_color || ownerPatterns.has(tile.owner_color)) return;
            const id = patternPrefix + ownerPatterns.size;
            ownerPatterns.set(tile.owner_color, id);
            const pattern = document.createElementNS(namespace, 'pattern');
            pattern.setAttribute('id', id);
            pattern.setAttribute('patternUnits', 'userSpaceOnUse');
            pattern.setAttribute('width', '12');
            pattern.setAttribute('height', '12');
            pattern.setAttribute('patternTransform', 'rotate(45)');
            const stripe = document.createElementNS(namespace, 'rect');
            stripe.setAttribute('width', '4');
            stripe.setAttribute('height', '12');
            stripe.setAttribute('fill', tile.owner_color);
            pattern.appendChild(stripe);
            definitions.appendChild(pattern);
        });
        svg.appendChild(definitions);

        mapGroup = document.createElementNS(namespace, 'g');
        if (!wrap) {
            const borders = document.createDocumentFragment();
            centers.forEach(({ tile, x, y }) => {
                mapGroup.appendChild(createTile(tile, x, y));
                appendBorders(borders, tile, x, y);
            });
            mapGroup.appendChild(borders);
        }
        svg.appendChild(mapGroup);
        container.replaceChildren(svg);
        if (wrap) {
            const relative = hadTiles && previousWrap && previousWidth === mapWidth
                ? scrollLeft + previousMinX - minX - sideCopies * period
                : paddingX - padding;
            container.scrollLeft = sideCopies * period + ((relative % period) + period) % period;
        } else {
            container.scrollLeft = hadTiles && !previousWrap
                ? scrollLeft + previousMinX - minX : paddingX - padding;
        }
        container.scrollTop = hadTiles ? scrollTop + previousMinY - minY : paddingY - padding;
        drawVisible();
    }

    container.addEventListener('scroll', onScroll);
    container.addEventListener('pointerdown', onPointerDown);
    container.addEventListener('dragstart', preventNativeDrag);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerEnd);
    window.addEventListener('pointercancel', onPointerEnd);
    if (onSelect) {
        container.addEventListener('click', selectTile);
        container.addEventListener('keydown', selectTile);
    }
    const observer = new ResizeObserver(() => {
        if (tiles.length && (
            container.clientWidth !== renderedWidth || container.clientHeight !== renderedHeight
        )) {
            render(tiles, mapWidth, wrap);
        }
    });
    observer.observe(container);

    return {
        render,
        centerOn(q, r) {
            if (tiles.length && (
                container.clientWidth !== renderedWidth || container.clientHeight !== renderedHeight
            )) {
                render(tiles, mapWidth, wrap);
            }
            const center = centers.find((point) => point.tile.q === q && point.tile.r === r);
            if (!center || !mapGroup) return false;
            const svg = mapGroup.ownerSVGElement;
            const svgRect = svg.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();
            let x = svgRect.left - containerRect.left + center.x - minX;
            if (wrap && mapWidth) {
                const period = mapWidth * hexWidth;
                x += Math.round((container.clientWidth / 2 - x) / period) * period;
            }
            container.scrollLeft += x - container.clientWidth / 2;
            container.scrollTop += svgRect.top - containerRect.top + center.y - minY -
                container.clientHeight / 2;
            normalizeScroll();
            drawVisible();
            return true;
        },
        setSelection(q, r) {
            selected = q === null ? null : { q, r };
            container.querySelectorAll('.landgrab-hex[data-q]').forEach((group) => {
                const isSelected = selected &&
                    Number(group.getAttribute('data-q')) === selected.q &&
                    Number(group.getAttribute('data-r')) === selected.r;
                group.classList.toggle('selected', Boolean(isSelected));
                group.setAttribute('aria-pressed', String(Boolean(isSelected)));
            });
        },
        dispose() {
            observer.disconnect();
            container.removeEventListener('scroll', onScroll);
            container.removeEventListener('pointerdown', onPointerDown);
            container.removeEventListener('dragstart', preventNativeDrag);
            container.removeEventListener('click', selectTile);
            container.removeEventListener('keydown', selectTile);
            window.removeEventListener('pointermove', onPointerMove);
            window.removeEventListener('pointerup', onPointerEnd);
            window.removeEventListener('pointercancel', onPointerEnd);
            if (drag && container.hasPointerCapture(drag.id)) {
                container.releasePointerCapture(drag.id);
            }
            drag = null;
            container.classList.remove('is-dragging');
            if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame);
        }
    };
}
