const simulator = document.getElementById('simulator');

const canvas = document.createElement('canvas');
canvas.width = 800;
canvas.height = 600;
simulator.appendChild(canvas);
const grayscaleOption = document.getElementById('electron-option-grayscale');
const slowOption = document.getElementById('electron-option-slow');
const slowDelaySetting = document.getElementById('electron-slow-delay-setting');
const slowDelayOption = document.getElementById('electron-slow-delay');
const slowDelayValue = document.getElementById('electron-slow-delay-value');
const orderOption = document.getElementById('electron-option-order');
const oneOption = document.getElementById('electron-option-one');
const center = { x: canvas.width / 2, y: canvas.height / 2 };

const circleRadius = 10;
const targetOrbitRadius = 150;
const circleCount = Math.round(
    Math.PI / Math.asin(circleRadius / targetOrbitRadius)
);
const orbitRadius = circleRadius / Math.sin(Math.PI / circleCount);
const angle = (2 * Math.PI) / circleCount;
const context = canvas.getContext('2d');

class Electron {
    constructor(x, y, order) {
        this.x = x;
        this.y = y;
        this.order = order;
        this.color = `hsl(${Math.random() * 360}, 70%, 80%)`;
    }

    draw(context, grayscale, showOrder) {
        context.beginPath();
        context.fillStyle = grayscale ? '#808080' : this.color;
        context.arc(this.x, this.y, circleRadius, 0, 2 * Math.PI);
        context.fill();
        if (showOrder) {
            context.fillStyle = '#334155';
            context.font = '8px sans-serif';
            context.textAlign = 'center';
            context.textBaseline = 'middle';
            context.fillText(this.order, this.x, this.y);
        }
    }

    rotate(center, angle) {
        const x = this.x - center.x;
        const y = this.y - center.y;
        this.x = center.x + x * Math.cos(angle) - y * Math.sin(angle);
        this.y = center.y + x * Math.sin(angle) + y * Math.cos(angle);
    }
}

const electrons = [];
for (let i = 0; i < circleCount - 1; i += 1) {
    const electronAngle = i * angle;
    const x = center.x + Math.cos(electronAngle) * orbitRadius;
    const y = center.y + Math.sin(electronAngle) * orbitRadius;
    electrons.push(new Electron(x, y, i + 1));
}

function drawElectrons() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (oneOption.checked) {
        electrons[0].draw(context, grayscaleOption.checked, orderOption.checked);
        return;
    }
    electrons.forEach((electron) => {
        electron.draw(context, grayscaleOption.checked, orderOption.checked);
    });
}

let cancelWait = null;
grayscaleOption.addEventListener('change', drawElectrons);
orderOption.addEventListener('change', drawElectrons);
oneOption.addEventListener('change', drawElectrons);
slowOption.addEventListener('change', () => {
    slowDelaySetting.hidden = !slowOption.checked;
    if (!slowOption.checked && cancelWait) cancelWait();
});
slowDelayOption.addEventListener('input', () => {
    slowDelayValue.textContent = `${slowDelayOption.value}ms`;
});
drawElectrons();

const wait = (milliseconds) => new Promise((resolve) => {
    const timer = window.setTimeout(() => {
        cancelWait = null;
        resolve();
    }, milliseconds);
    cancelWait = () => {
        window.clearTimeout(timer);
        cancelWait = null;
        resolve();
    };
});

async function updatePositions() {
    if (slowOption.checked) {
        const startingPositions = electrons.map((electron) => ({
            x: electron.x,
            y: electron.y
        }));
        let interrupted = false;
        for (let i = 0; i < electrons.length; i += 1) {
            const electron = electrons[i];
            electron.rotate(center, -angle);
            drawElectrons();
            await wait(Number(slowDelayOption.value));
            if (!slowOption.checked) {
                interrupted = true;
                break;
            }
        }
        if (interrupted) {
            electrons.forEach((electron, i) => {
                electron.x = startingPositions[i].x;
                electron.y = startingPositions[i].y;
            });
            drawElectrons();
            await wait(100);
        }
    } else {
        electrons.forEach((electron) => electron.rotate(center, -angle));
        drawElectrons();
        await wait(100);
    }
    updatePositions();
}

updatePositions();
