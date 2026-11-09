import { app } from '../../../scripts/app.js';
import { api } from '../../../scripts/api.js';

const MAX_IMAGES = 128;
const base = '/magik/4-references/presets';
const queueRandomizers = new Set();
let queueHookInstalled = false;
function installQueueHook() {
    if (queueHookInstalled || typeof api.queuePrompt !== 'function') return;
    const original = api.queuePrompt;
    api.queuePrompt = function (number, prompt, ...args) {
        // Work on a separate submission: batch queue callers may reuse prompt objects.
        if (prompt?.output && [...queueRandomizers].some(entry => entry.enabled())) {
            prompt = JSON.parse(JSON.stringify(prompt));
            for (const entry of queueRandomizers) if (entry.enabled()) entry.apply(prompt);
        }
        return original.call(this, number, prompt, ...args);
    };
    queueHookInstalled = true;
}

async function request(url, options) {
    const response = await api.fetchApi(url, options);
    if (response.status === 404 && url === '/magik/4-references/upload') throw new Error('Restart ComfyUI to enable the updated Magik image upload handler, then refresh the browser.');
    const data = await response.json();
    if (!response.ok) {
        const error = new Error(data.error || `Request failed (${response.status})`);
        error.status = response.status;
        throw error;
    }
    return data;
}
function element(tag, parent, text) {
    const el = document.createElement(tag);
    if (tag === 'button') el.type = 'button';
    if (text) el.textContent = text;
    parent.append(el);
    return el;
}
function thumb(value) {
    return api.apiURL(`/magik/4-references/thumbnail?${new URLSearchParams({image: value})}`);
}
function fullImage(value) {
    const normalized = value.replaceAll('\\', '/');
    const slash = normalized.lastIndexOf('/');
    return api.apiURL(`/view?${new URLSearchParams({filename: normalized.slice(slash + 1), subfolder: slash < 0 ? '' : normalized.slice(0, slash), type: 'input'})}`);
}
function post(url, body) {
    return request(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
}
function randomSample(items, count = 4) {
    const shuffled = [...items];
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled.slice(0, count);
}
app.registerExtension({
    name: 'Magik.4ReferencesImages',
    async beforeRegisterNodeDef(type, data) {
        if (!['Magik4ReferencesImages', 'Magik6ReferencesImages', 'Magik8ReferencesImages', 'Magik9ReferencesImages', 'MagikReferencesImages', 'Magik References Images'].includes(data.name)) return;
        const imageCount = Array.isArray(data.output) ? data.output.filter(value => value === 'IMAGE').length : 0;
        const portCount = imageCount === 9 || data.name === 'Magik9ReferencesImages' ? 9 : imageCount === 8 || data.name === 'Magik8ReferencesImages' ? 8 : imageCount === 6 || data.name === 'Magik6ReferencesImages' ? 6 : 4;
        const portNumbers = Array.from({length: portCount}, (_, i) => i + 1);
        const defaultWidth = portCount >= 6 ? 780 : 580;
        const created = type.prototype.onNodeCreated;
        type.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            const node = this;
            const fields = portNumbers.map(i => node.widgets.find(w => w.name === `reference_${i}`));
            const extra = node.widgets.find(w => w.name === 'extra_references');
            const titleField = node.widgets.find(w => w.name === 'title');
            const pinField = node.widgets.find(w => w.name === 'pinned_outputs');
            const readPins = () => { try { const values = JSON.parse(pinField.value || '[]'); return Array.from({length: portCount}, (_, i) => typeof values?.[i] === 'string' ? values[i] : null); } catch { return Array(portCount).fill(null); } };
            const isPinned = i => readPins()[i] !== null;
            const descriptionField = node.widgets.find(w => w.name === 'description');
            const outputs = portNumbers.map(i => node.widgets.find(w => w.name === `output_${i}`));
            const readExtra = () => { try { const value = JSON.parse(extra.value || '[]'); return Array.isArray(value) ? value.slice(0, MAX_IMAGES - portCount).map(path => typeof path === 'string' ? path : '') : []; } catch { return []; } };
            const dragToken = `magik-${Date.now()}-${Math.random()}`;
            const dragType = 'application/x-magik-reference';
            let activeOutput = 0;
            // Keep exactly four direct input-to-output sockets, independent of collection size.
            for (let index = (node.inputs?.length || 0) - 1; index >= 0; index--) {
                const match = /^image_(\d+)$/.exec(node.inputs[index].name);
                if (match && Number(match[1]) > portCount) node.removeInput(index);
            }
            [...fields, extra, ...outputs, titleField, descriptionField, pinField].forEach(field => {
                field.type = 'converted-widget'; field.computeSize = () => [0, -4]; field.draw = () => {};
            });
            const root = document.createElement('div'); root.className = 'magik-four-refs';
            let scheduleFit = () => {};
            element('style', root).textContent = `.magik-four-refs{position:relative;min-width:0;max-width:100%;box-sizing:border-box;padding:10px;background:#20232a;color:#eee;font:13px sans-serif;width:100%;height:auto;overflow:visible;pointer-events:auto}.magik-four-refs *{box-sizing:border-box}.magik-four-refs input,.magik-four-refs textarea,.magik-four-refs select,.magik-four-refs button{background:#343944;color:#eee;border:1px solid #606878;border-radius:5px;padding:6px;min-width:0}.magik-four-refs button{cursor:pointer}.magik-four-refs button:hover{background:#485268}.magik-four-refs button:disabled{opacity:.5;cursor:default}.magik-four-refs .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.magik-four-refs .image-cards{grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-rows:1fr;align-items:stretch}.magik-four-refs .add-card{min-width:0;aspect-ratio:auto;align-self:stretch;font-size:42px;border:2px dashed #65718a;background:#292e38}.magik-four-refs .card{padding:8px;border:1px solid #555d6b;border-radius:7px;min-width:0;display:flex;flex-direction:column;gap:5px}.magik-four-refs .card-header{display:flex;align-items:center;justify-content:space-between;gap:6px}.magik-four-refs .card-header button{padding:3px 7px;font-size:11px}.magik-four-refs .preview{position:relative;width:100%;aspect-ratio:1/1;background:#15171b;border-radius:5px;overflow:hidden;flex:none}.magik-four-refs .card .preview img,.magik-four-refs .output-mosaic .preview img{position:absolute;inset:0;width:100%;height:100%;margin:0;object-fit:contain}.magik-four-refs .card .row{margin-top:0;align-items:center}.magik-four-refs .card .row button{padding:5px;font-size:11px;white-space:nowrap}.magik-four-refs .card .row select{padding:5px;font-size:11px}.magik-four-refs .card.over{border-color:#e5bd58}.magik-four-refs img{display:block;width:100%;height:110px;object-fit:contain;background:#15171b;margin:6px 0}.magik-four-refs .row{display:flex;gap:6px;margin-top:8px}.magik-four-refs .row input,.magik-four-refs select{flex:1;width:100%}.magik-four-refs .filename{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px;color:#b8c4d8}.magik-four-refs .gallery{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}.magik-four-refs .mini{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:3px;width:100%;margin-top:5px}.magik-four-refs .preset-cell{position:relative;aspect-ratio:1/1;min-width:0;background:#15171b;overflow:hidden}.magik-four-refs .mini img{position:absolute;inset:0;width:100%;height:100%;margin:0;object-fit:contain}.magik-four-refs .output-mosaic{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;width:100%;margin-bottom:10px}.magik-four-refs .output-mosaic .preview{border:2px solid #505969;cursor:pointer;min-width:0}.magik-four-refs .output-mosaic .preview.output-active{border-color:#69cfff;box-shadow:0 0 0 2px #69cfff66}.magik-four-refs .output-mosaic .preview:focus-visible{outline:2px solid #fff}.magik-four-refs .output-tile{display:flex;flex-direction:column;gap:5px;min-width:0}.magik-four-refs .output-badge{display:block;text-align:center;font-size:11px;line-height:1.4;overflow-wrap:anywhere}.magik-four-refs .output-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#aebbd0;font-size:12px}.magik-four-refs .gallery{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.magik-four-refs .preset{overflow:hidden;text-align:left}.magik-four-refs .preset.active{border-color:#e5bd58}`;
            const titleRow = element('div', root); titleRow.className = 'title-row';
            titleRow.style.cssText = 'width:100%;margin-bottom:10px';
            const titleInput = element('input', titleRow); titleInput.type = 'text'; titleInput.placeholder = 'Title…';
            titleInput.maxLength = 512; titleInput.value = titleField.value || '';
            titleInput.setAttribute('aria-label', 'Reference collection title');
            titleInput.style.cssText = 'display:block;width:100%;font-size:66px;font-weight:600;text-align:center;padding:10px 12px';
            titleInput.oninput = () => { titleField.value = titleInput.value; node.setDirtyCanvas(true, true); scheduleFit(); };
            let viewer = null;
            const closeViewer = () => { viewer?.remove(); viewer = null; };
            const openViewer = (path, index) => {
                if (!path) return;
                closeViewer();
                viewer = document.createElement('dialog');
                viewer.style.cssText = 'width:94vw;height:92vh;max-width:1600px;background:#181b22;color:#eee;border:1px solid #65718a;border-radius:10px;padding:14px';
                const entries = fields.map((field, i) => ({path: field.value, index: i})).filter(item => item.path);
                let current = entries.findIndex(item => item.path === path && item.index === index);
                if (current < 0) current = entries.findIndex(item => item.path === path);
                if (current < 0) { entries.unshift({path, index}); current = 0; }
                const bar = element('div', viewer); bar.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:16px';
                const caption = element('span', bar);
                const close = element('button', bar, 'Close'); close.onclick = closeViewer;
                const stage = element('div', viewer); stage.style.cssText = 'position:relative;width:100%;height:calc(100% - 40px);margin-top:10px;overflow:hidden;touch-action:none';
                const image = element('img', stage);
                image.style.cssText = 'display:block;width:100%;height:100%;object-fit:contain;transform-origin:center;user-select:none';
                image.draggable = false;
                let zoom = 1, panX = 0, panY = 0, drag = null;
                const zoomLabel = element('span', bar);
                zoomLabel.style.whiteSpace = 'nowrap';
                const applyView = () => {
                    const width = stage.clientWidth || stage.offsetWidth;
                    const height = stage.clientHeight || stage.offsetHeight;
                    const fit = image.naturalWidth && image.naturalHeight
                        ? Math.min(width / image.naturalWidth, height / image.naturalHeight) : 1;
                    const maxX = Math.max(0, ((image.naturalWidth || width) * fit * zoom - width) / 2);
                    const maxY = Math.max(0, ((image.naturalHeight || height) * fit * zoom - height) / 2);
                    panX = Math.max(-maxX, Math.min(maxX, panX));
                    panY = Math.max(-maxY, Math.min(maxY, panY));
                    image.style.transform = `translate(${panX}px,${panY}px) scale(${zoom})`;
                    image.style.cursor = zoom > 1 ? (drag ? 'grabbing' : 'grab') : 'zoom-in';
                    zoomLabel.textContent = `${Math.round(zoom * 100)}% · Wheel: zoom · Drag: pan · Double-click: reset`;
                };
                const resetView = () => { zoom = 1; panX = panY = 0; drag = null; applyView(); };
                image.onload = applyView;
                stage.addEventListener('wheel', event => {
                    event.preventDefault(); event.stopPropagation();
                    const nextZoom = Math.max(1, Math.min(16, zoom * Math.exp(-event.deltaY * (event.deltaMode === 1 ? 0.04 : 0.002))));
                    const rect = stage.getBoundingClientRect();
                    const x = event.clientX - rect.left - rect.width / 2;
                    const y = event.clientY - rect.top - rect.height / 2;
                    panX = x - (x - panX) * nextZoom / zoom;
                    panY = y - (y - panY) * nextZoom / zoom;
                    zoom = nextZoom; applyView();
                }, {passive: false});
                image.addEventListener('dblclick', event => { event.preventDefault(); event.stopPropagation(); resetView(); });
                image.addEventListener('pointerdown', event => {
                    if (event.button !== 0 || zoom <= 1) return;
                    event.preventDefault(); event.stopPropagation();
                    drag = {id: event.pointerId, x: event.clientX, y: event.clientY};
                    image.setPointerCapture(event.pointerId); applyView();
                });
                image.addEventListener('pointermove', event => {
                    if (!drag || drag.id !== event.pointerId) return;
                    panX += event.clientX - drag.x; panY += event.clientY - drag.y;
                    drag.x = event.clientX; drag.y = event.clientY; applyView();
                });
                const endDrag = event => {
                    if (!drag || drag.id !== event.pointerId) return;
                    drag = null;
                    if (image.hasPointerCapture(event.pointerId)) image.releasePointerCapture(event.pointerId);
                    applyView();
                };
                image.addEventListener('pointerup', endDrag);
                image.addEventListener('pointercancel', endDrag);
                image.addEventListener('lostpointercapture', () => { drag = null; applyView(); });
                const previous = element('button', stage, '❮'); previous.setAttribute('aria-label', 'Previous image'); previous.title = 'Previous image (Left arrow)';
                const next = element('button', stage, '❯'); next.setAttribute('aria-label', 'Next image'); next.title = 'Next image (Right arrow)';
                const arrowStyle = 'position:absolute;top:50%;transform:translateY(-50%);z-index:2;border:1px solid #8793a8;border-radius:8px;background:#1a202cdd;color:white;font-size:36px;padding:12px;cursor:pointer';
                previous.style.cssText = arrowStyle + ';left:8px'; next.style.cssText = arrowStyle + ';right:8px';
                const render = () => {
                    resetView();
                    const entry = entries[current]; image.src = fullImage(entry.path); image.alt = `Image ${entry.index + 1}`;
                    caption.textContent = `Image ${entry.index + 1} · ${current + 1} / ${entries.length} · ${entry.path}`;
                    previous.disabled = next.disabled = entries.length < 2;
                };
                const move = delta => { current = (current + delta + entries.length) % entries.length; render(); };
                previous.onclick = event => { event?.stopPropagation(); move(-1); };
                next.onclick = event => { event?.stopPropagation(); move(1); };
                viewer.addEventListener('keydown', event => {
                    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                        event.preventDefault(); event.stopPropagation(); move(event.key === 'ArrowLeft' ? -1 : 1);
                    }
                });
                render();
                viewer.addEventListener('cancel', event => { event.preventDefault(); closeViewer(); });
                viewer.addEventListener('click', event => { if (event.target === viewer) closeViewer(); });
                document.body.append(viewer); viewer.showModal(); close.focus();
            };
            const mosaic = element('div', root); mosaic.className = 'output-mosaic'; mosaic.style.gridTemplateColumns = `repeat(${portCount === 9 ? 3 : portCount === 8 ? 4 : portCount},minmax(0,1fr))`;
            const outputTiles = outputs.map((_, i) => {
                const tile = element('div', mosaic); tile.className = 'output-tile';
                const cell = element('div', tile); cell.className = 'preview';
                const img = element('img', cell); img.alt = `Output ${i + 1}`; img.style.cursor = 'zoom-in';
                const empty = element('span', cell, 'Empty'); empty.className = 'output-empty';
                const pin = element('button', cell, '📌'); pin.className = 'pin-output';
                pin.style.cssText = 'position:absolute;top:5px;right:5px;z-index:2;font-size:18px;padding:3px 5px';
                pin.onclick = event => {
                    event?.stopPropagation();
                    const values = readPins();
                    values[i] = values[i] === null ? (linked(i) ? inputCaptures[i] || '' : fields[Number(outputs[i].value) - 1]?.value || '') : null;
                    pinField.value = JSON.stringify(values); refresh();
                };
                pin.ondblclick = event => event.stopPropagation();
                pin.addEventListener('keydown', event => event.stopPropagation());
                const badge = element('span', tile, `Output ${i + 1}`); badge.className = 'output-badge';
                img.onload = () => { if (cell.dataset.path) empty.style.display = 'none'; };
                img.onerror = () => { if (cell.dataset.path) { empty.textContent = 'Preview unavailable'; empty.style.display = 'flex'; } };
                cell.tabIndex = 0; cell.setAttribute('role', 'button');
                cell.setAttribute('aria-label', `Activate output ${i + 1}`);
                cell.onclick = () => { activeOutput = i; refresh(); };
                cell.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); cell.onclick(); } };
                cell.ondblclick = () => { if (cell.dataset.path) openViewer(cell.dataset.path, linked(i) ? i : Number(outputs[i].value) - 1); };
                img.style.cursor = 'grab'; img.draggable = true; cell.draggable = true;
                cell.title = 'Drop a loaded card to assign; drag onto another output to swap selections';
                cell.ondragstart = event => {
                    if (event.target?.closest?.('button') || isPinned(i) || linked(i)) { event.preventDefault(); return; }
                    event.stopPropagation(); event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setData(dragType, JSON.stringify({token: dragToken, kind: 'output', index: i}));
                };
                cell.ondragend = () => outputTiles.forEach(item => item.cell.style.outline = '');
                cell.ondragover = event => {
                    event.preventDefault(); event.stopPropagation();
                    cell.style.outline = isPinned(i) || linked(i) ? '2px solid #dd7777' : '2px solid #69cfff';
                    event.dataTransfer.dropEffect = isPinned(i) || linked(i) ? 'none' : 'move';
                };
                cell.ondragleave = () => { cell.style.outline = ''; };
                cell.ondrop = event => {
                    event.preventDefault(); event.stopPropagation(); cell.style.outline = '';
                    let source;
                    try { source = JSON.parse(event.dataTransfer.getData(dragType)); } catch { return; }
                    if (source.token !== dragToken || !Number.isInteger(source.index)) return;
                    if (isPinned(i) || linked(i)) { message('Unpin or disconnect this output before changing its selection.', true); return; }
                    const next = outputs.map(field => Number(field.value));
                    if (source.kind === 'output') {
                        const from = source.index;
                        if (from < 0 || from >= portCount || from === i) return;
                        if (isPinned(from) || linked(from)) { message('Pinned or connected outputs cannot be swapped.', true); return; }
                        [next[i], next[from]] = [next[from], next[i]];
                    } else {
                        if (source.index < 0 || source.index >= fields.length || !fields[source.index].value) return;
                        next[i] = source.index + 1;
                    }
                    changeSelections(next, {newActive: i});
                    message(source.kind === 'output' ? 'Output selections swapped.' : `Image ${source.index + 1} assigned to Output ${i + 1}.`);
                };
                return {tile, cell, img, empty, badge, pin};
            });
            const selectionRow = element('div', root); selectionRow.className = 'row';
            const selectionHint = element('span', selectionRow); selectionHint.style.cssText = 'flex:1;line-height:1.4';
            const redoButton = element('button', selectionRow, 'Redo');
            const undoButton = element('button', selectionRow, 'Undo'); undoButton.title = 'Undo the last selection or collection edit';
            undoButton.onclick = undoSelection;
            redoButton.onclick = () => restoreHistory(redoStack, undoStack, 'Change reapplied.');
            element('button', selectionRow, 'Clear active slot').onclick = () => { const selected = outputs.map(field => Number(field.value)); selected[activeOutput] = 0; changeSelections(selected, {disconnectSlot: activeOutput}); };
            element('button', selectionRow, 'Reset outputs').onclick = () => changeSelections(portNumbers, {newActive: 0});
            const exclusions = () => new Set(Array.isArray(node.properties?.magik_excluded_images) ? node.properties.magik_excluded_images : []);
            let cycleKey = '', cycleUsed = new Set();
            const resetCycle = () => { cycleKey = ''; cycleUsed = new Set(); };
            const randomizeSelections = () => {
                const locked = readPins();
                const free = outputs.map((_, i) => i).filter(i => !isPinned(i) && !linked(i));
                if (!free.length) { message('All outputs are pinned or connected. Unpin or disconnect a slot to randomize it.'); return; }
                const seen = new Set(locked.filter(Boolean));
                const pool = fields.map((field, i) => ({path: field.value, index: i + 1})).filter(item => {
                    if (!item.path || seen.has(item.path) || exclusions().has(item.path)) return false;
                    seen.add(item.path); return true;
                });
                if (!pool.length) { message('No eligible images. Load images or include some cards in randomization.', true); return; }
                let chosen, nextUsed, nextKey;
                if (node.properties?.magik_avoid_repeats === true) {
                    nextKey = JSON.stringify(pool.map(item => item.path).sort());
                    nextUsed = new Set(nextKey === cycleKey ? cycleUsed : []);
                    chosen = [];
                    while (chosen.length < Math.min(free.length, pool.length)) {
                        let available = pool.filter(item => !nextUsed.has(item.path) && !chosen.some(value => value.path === item.path));
                        if (!available.length) {
                            nextUsed.clear();
                            available = pool.filter(item => !chosen.some(value => value.path === item.path));
                        }
                        const item = randomSample(available, 1)[0];
                        if (!item) break;
                        chosen.push(item); nextUsed.add(item.path);
                    }
                } else chosen = randomSample(pool, free.length);
                const next = outputs.map(field => Number(field.value)); free.forEach((index, i) => { next[index] = chosen[i]?.index || 0; });
                changeSelections(next, {forceRecord: !!nextUsed});
                if (nextUsed) { cycleUsed = nextUsed; cycleKey = nextKey; }
                message(`Selected ${chosen.length} random image(s) without repetition.${outputs.some((_, i) => linked(i)) ? ' Connected inputs still override their matching outputs.' : ''}`);
            };
            element('button', selectionRow, 'Randomize').onclick = randomizeSelections;
            node.properties ??= {};
            const queueRow = element('label', root); queueRow.className = 'row';
            const queueToggle = element('input', queueRow); queueToggle.type = 'checkbox';
            queueToggle.checked = node.properties.magik_randomize_on_queue === true;
            queueToggle.setAttribute('aria-label', 'Randomize on queue');
            element('span', queueRow, 'Randomize on queue');
            queueToggle.onchange = () => {
                node.properties.magik_randomize_on_queue = queueToggle.checked;
                node.setDirtyCanvas(true, true);
            };
            const repeatRow = element('label', root); repeatRow.className = 'row';
            const repeatToggle = element('input', repeatRow); repeatToggle.type = 'checkbox';
            repeatToggle.checked = node.properties.magik_avoid_repeats === true;
            repeatToggle.setAttribute('aria-label', 'Avoid repeats');
            element('span', repeatRow, 'Avoid repeats');
            repeatToggle.title = 'Use every eligible image before starting a new shuffled cycle';
            repeatToggle.onchange = () => {
                node.properties.magik_avoid_repeats = repeatToggle.checked;
                resetCycle(); node.setDirtyCanvas(true, true);
            };
            const queueEntry = {
                enabled: () => !removed && node.properties?.magik_randomize_on_queue === true,
                apply: prompt => {
                    const submitted = prompt.output[String(node.id)];
                    if (!submitted?.inputs || !['Magik4ReferencesImages', 'Magik6ReferencesImages', 'Magik8ReferencesImages', 'Magik9ReferencesImages', 'MagikReferencesImages', 'Magik References Images'].includes(submitted.class_type)) return;
                    // A queue caller can reuse a prompt serialized before later UI edits.
                    // Keep that job intact rather than applying new indices to an old pool.
                    const stale = portNumbers.some((n, i) =>
                        (`reference_${n}` in submitted.inputs && submitted.inputs[`reference_${n}`] !== fields[i].value) ||
                        ((`image_${n}` in submitted.inputs || `reference_${n}` in submitted.inputs) && Array.isArray(submitted.inputs[`image_${n}`]) !== linked(i))) ||
                        ('extra_references' in submitted.inputs && submitted.inputs.extra_references !== extra.value) ||
                        ('pinned_outputs' in submitted.inputs && submitted.inputs.pinned_outputs !== pinField.value);
                    if (stale) { message('Queued snapshot differs from the current collection. Its original selections were kept; queue again to randomize.', true); return; }
                    randomizeSelections();
                    outputs.forEach((field, i) => { submitted.inputs[`output_${i + 1}`] = Number(field.value); });
                    const saved = prompt.workflow?.nodes?.find(item => String(item.id) === String(node.id));
                    if (saved) {
                        const serializedWidgets = node.widgets.filter(widget => widget.options?.serialize !== false);
                        if (Array.isArray(saved.widgets_values)) outputs.forEach(field => {
                            const index = serializedWidgets.indexOf(field);
                            if (index >= 0 && index < saved.widgets_values.length) saved.widgets_values[index] = Number(field.value);
                        });
                    }
                },
            };
            queueRandomizers.add(queueEntry); installQueueHook();
            const collectionRow = element('div', root); collectionRow.className = 'row';
            const counter = element('span', collectionRow);
            const folderRow = element('div', root); folderRow.className = 'row';
            const folderMode = element('select', folderRow); folderMode.setAttribute('aria-label', 'Folder load mode');
            const appendOption = element('option', folderMode, 'Append to collection'); appendOption.value = 'append';
            const replaceOption = element('option', folderMode, 'Replace collection'); replaceOption.value = 'replace';
            folderMode.value = 'append';
            const folderSource = element('select', folderRow); folderSource.setAttribute('aria-label', 'Folder location');
            const computer = element('option', folderSource, 'This computer'); computer.value = 'computer';
            const server = element('option', folderSource, 'ComfyUI server'); server.value = 'server';
            folderSource.value = 'computer';
            const loadFolder = element('button', folderRow, 'Load Folder');
            loadFolder.title = 'Choose a folder on this computer. Image files, including subfolders, are uploaded in filename order.';
            const pathRow = element('div', root); pathRow.className = 'row'; pathRow.style.display = 'none';
            const folderPath = element('input', pathRow); folderPath.placeholder = '/path/to/image/folder';
            folderPath.setAttribute('aria-label', 'Folder path on the ComfyUI server');
            folderSource.onchange = () => { pathRow.style.display = folderSource.value === 'server' ? 'flex' : 'none'; scheduleFit(); };
            // Keep the native picker outside the canvas widget, whose event handling
            // and visibility can interfere with directory selection in some browsers.
            const folderPicker = element('input', document.body); folderPicker.type = 'file';
            folderPicker.multiple = true; folderPicker.webkitdirectory = true;
            folderPicker.setAttribute('webkitdirectory', ''); folderPicker.setAttribute('directory', '');
            folderPicker.style.cssText = 'position:fixed;left:-10000px;top:0;width:1px;height:1px;opacity:0;pointer-events:none';
            folderPicker.addEventListener('click', event => event.stopPropagation());
            folderPicker.addEventListener('change', event => event.stopPropagation());
            loadFolder.onclick = event => {
                event?.preventDefault(); event?.stopPropagation();
                if (folderSource.value === 'server') return loadServerFolder();
                folderPicker.value = '';
                try { if (typeof folderPicker.showPicker === 'function') folderPicker.showPicker(); else folderPicker.click(); }
                catch { folderPicker.click(); }
            };
            node.properties ??= {};
            const cardsToggle = element('button', root, 'Hide cards');
            cardsToggle.style.cssText = 'display:block;width:100%;margin-top:8px;text-align:left';
            const grid = element('div', root); grid.className = 'grid image-cards'; grid.style.cssText = 'margin-top:8px';
            function updateCardsVisibility() {
                const collapsed = node.properties?.magik_cards_collapsed === true;
                grid.style.display = collapsed ? 'none' : 'grid';
                cardsToggle.textContent = `${collapsed ? 'Show' : 'Hide'} cards (${fields.length})`;
                cardsToggle.setAttribute('aria-expanded', String(!collapsed));
                scheduleFit();
            }
            cardsToggle.onclick = () => { node.properties.magik_cards_collapsed = !node.properties.magik_cards_collapsed; updateCardsVisibility(); node.setDirtyCanvas(true, true); };
            const descriptionRow = element('div', root); descriptionRow.className = 'description-row';
            descriptionRow.style.cssText = 'width:100%;margin-top:10px';
            element('div', descriptionRow, 'description');
            const descriptionInput = element('textarea', descriptionRow);
            descriptionInput.setAttribute('aria-label', 'description'); descriptionInput.placeholder = 'description';
            descriptionInput.rows = 4; descriptionInput.value = descriptionField.value || '';
            descriptionInput.style.cssText = 'display:block;width:100%;min-height:96px;resize:vertical;font:14px/1.4 sans-serif;margin-top:5px';
            descriptionInput.oninput = () => { descriptionField.value = descriptionInput.value; node.setDirtyCanvas(true, true); scheduleFit(); };
            const saveRow = element('div', root); saveRow.className = 'row';
            const name = element('input', saveRow); name.placeholder = 'Preset name…';
            const save = element('button', saveRow, 'Save');
            const addCard = element('button', grid, '+'); addCard.className = 'add-card';
            addCard.title = 'Add an image card'; addCard.setAttribute('aria-label', 'Add an image card');
            const previews = [], captures = [], inputCaptures = Array(portCount).fill(null);
            const status = document.createElement('div'); status.style.cssText = 'margin-top:8px;min-height:30px;white-space:pre-wrap';
            const message = (text, error = false) => { status.textContent = text; status.style.color = error ? '#ff9b9b' : '#acd6af'; scheduleFit(); };
            const slotIndex = i => node.inputs?.findIndex(input => input.name === `image_${i + 1}`) ?? -1;
            const linked = i => { const index = slotIndex(i); return index >= 0 && node.inputs[index].link != null; };
            const refresh = () => {
                undoButton.disabled = undoStack.length === 0;
                redoButton.disabled = redoStack.length === 0;
                updateCardsVisibility();
                counter.textContent = `${fields.length} / ${MAX_IMAGES} images`;
                addCard.disabled = fields.length >= MAX_IMAGES;
                if (fields.length >= MAX_IMAGES) addCard.remove(); else grid.append(addCard);
                selectionHint.textContent = isPinned(activeOutput) ? `Output ${activeOutput + 1} is pinned. Unpin it to change its selection.` : linked(activeOutput) ? `Output ${activeOutput + 1} uses Input ${activeOutput + 1} directly. Disconnect it to select a loaded image.` : `Output ${activeOutput + 1} active — click a loaded image to assign it.`;
                fields.forEach((field, i) => {
                    const {img, label, hint, dice} = previews[i];
                    const excluded = exclusions().has(field.value);
                    dice.textContent = excluded ? '🎲✕' : '🎲'; dice.style.opacity = excluded ? '0.4' : '1';
                    dice.disabled = !field.value; dice.setAttribute('aria-pressed', String(excluded));
                    dice.setAttribute('aria-label', `${excluded ? 'Include' : 'Exclude'} Image ${i + 1} ${excluded ? 'in' : 'from'} randomization`);
                    dice.title = excluded ? 'Excluded from randomization — click to include' : 'Included in randomization — click to exclude';
                    const value = field.value;
                    label.textContent = value || 'Empty slot'; label.title = value || '';
                    const assigned = outputs.map((w, k) => !linked(k) && (isPinned(k) ? readPins()[k] === field.value && !!field.value : Number(w.value) === i + 1) ? k + 1 : null).filter(Boolean);
                    hint.textContent = `${assigned.length ? 'Output ' + assigned.join(', ') : 'Not selected'}`;
                    previews[i].card.style.borderColor = !linked(activeOutput) && (isPinned(activeOutput) ? readPins()[activeOutput] === field.value && !!field.value : Number(outputs[activeOutput].value) === i + 1) ? '#69cfff' : assigned.length ? '#d9ba60' : '#555d6b';
                    if (value) {
                        const url = thumb(value);
                        if (img.dataset.reference !== url) { img.dataset.reference = url; img.src = url; }
                    } else { delete img.dataset.reference; img.removeAttribute('src'); }
                });
                outputTiles.forEach(({cell, img, empty, badge, pin}, i) => {
                    cell.className = `preview${i === activeOutput ? ' output-active' : ''}`;
                    cell.setAttribute('aria-pressed', i === activeOutput ? 'true' : 'false');
                    const index = Number(outputs[i].value) - 1;
                    const locked = isPinned(i);
                    pin.setAttribute('aria-pressed', String(locked)); pin.setAttribute('aria-label', `${locked ? 'Unpin' : 'Pin'} output ${i + 1}`);
                    pin.title = locked ? 'Unpin this output' : 'Pin this output'; pin.style.opacity = locked ? '1' : '0.45'; pin.style.background = locked ? '#8b691d' : '#343944';
                    const direct = linked(i);
                    const value = direct ? inputCaptures[i] : locked ? readPins()[i] : index >= 0 && index < fields.length ? fields[index].value : '';
                    badge.textContent = `Output ${i + 1} — ${direct ? 'Input ' + (i + 1) : locked ? 'Pinned image' : index >= 0 ? 'Image ' + (index + 1) : 'Empty'}`;
                    cell.dataset.path = value || '';
                    if (value) {
                        const url = fullImage(value);
                        if (img.dataset.reference !== url) { img.dataset.reference = url; empty.textContent = 'Loading…'; empty.style.display = 'flex'; img.src = url; }
                        img.style.visibility = 'visible';
                    } else {
                        delete img.dataset.reference; img.removeAttribute('src'); img.style.visibility = 'hidden';
                        empty.textContent = direct ? 'Run workflow to preview' : 'Empty'; empty.style.display = 'flex';
                    }
                });
                node.setDirtyCanvas(true, true);
                scheduleFit();
            };
            const disconnect = i => { const index = slotIndex(i); if (index >= 0 && linked(i)) node.disconnectInput(index); };
            const undoStack = [], redoStack = [];
            const snapshot = (connectionSlot = null) => ({
                pool: fields.map(field => field.value), indices: outputs.map(field => Number(field.value)),
                active: activeOutput, excluded: [...exclusions()], connectionSlot, cycleKey, cycleUsed: [...cycleUsed],
                connection: connectionSlot === null ? null : (() => {
                    const link = node.graph?.links[node.inputs[slotIndex(connectionSlot)]?.link];
                    return link ? {origin: link.origin_id, slot: link.origin_slot, capture: inputCaptures[connectionSlot]} : null;
                })(),
            });
            function remember(connectionSlot = null) {
                undoStack.push(snapshot(connectionSlot));
                if (undoStack.length > 50) undoStack.shift();
                redoStack.length = 0;
            }
            function changeSelections(next, {newActive = activeOutput, disconnectSlot = null, forceRecord = false} = {}) {
                const current = outputs.map(field => Number(field.value));
                next = next.map((value, i) => isPinned(i) ? current[i] : value);
                if (disconnectSlot !== null && isPinned(disconnectSlot)) disconnectSlot = null;
                const disconnecting = disconnectSlot !== null && linked(disconnectSlot);
                if (forceRecord || disconnecting || current.some((value, i) => value !== next[i])) remember(disconnecting ? disconnectSlot : null);
                if (disconnecting) disconnect(disconnectSlot);
                outputs.forEach((field, i) => { field.value = next[i]; });
                activeOutput = newActive; refresh();
            }
            function restoreHistory(from, to, text) {
                const previous = from.pop(); if (!previous) return;
                to.push(snapshot(previous.connectionSlot));
                const retained = outputs.map(field => fields[Number(field.value) - 1]?.value || '');
                node.properties.magik_excluded_images = previous.excluded;
                setCount(previous.pool.length);
                previous.pool.forEach((path, i) => { fields[i].value = path; captures[i] = null; });
                outputs.forEach((field, i) => {
                    field.value = isPinned(i) ? Math.max(0, fields.findIndex(item => item.value === retained[i]) + 1) : previous.indices[i];
                });
                activeOutput = previous.active;
                cycleKey = previous.cycleKey; cycleUsed = new Set(previous.cycleUsed);
                const slot = previous.connectionSlot;
                if (slot !== null && !isPinned(slot)) {
                    const current = node.graph?.links[node.inputs[slotIndex(slot)]?.link];
                    const target = previous.connection;
                    if (current && (!target || current.origin_id !== target.origin || current.origin_slot !== target.slot)) disconnect(slot);
                    if (target && !linked(slot)) {
                        node.graph?.getNodeById(target.origin)?.connect(target.slot, node, slotIndex(slot));
                        inputCaptures[slot] = target.capture;
                    }
                }
                refresh(); message(text);
            }
            function undoSelection() { restoreHistory(undoStack, redoStack, 'Previous collection and selections restored.'); }
            function swap(a, b) {
                if (a === b || a < 0 || b < 0 || a >= fields.length || b >= fields.length) return;
                if (fields[a].value === fields[b].value) return;
                remember();
                const previous = fields[a].value;
                fields[a].value = fields[b].value; fields[b].value = previous;
                refresh(); message('Loaded images swapped. Direct input connections are unchanged.');
            }
            function createCard(field, i) {
                const card = element('div', grid); card.className = 'card';
                card.draggable = true;
                card.ondragstart = event => {
                    if (event.target?.closest?.('button,input,select')) { event.preventDefault(); return; }
                    event.stopPropagation();
                    event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setData(dragType, JSON.stringify({token: dragToken, index: i}));
                };
                card.ondragend = () => previews.forEach(item => item.card.classList.remove('over'));
                const header = element('div', card); header.className = 'card-header';
                element('strong', header, `Image ${i + 1}`);
                const preview = element('div', card); preview.className = 'preview';
                const img = element('img', preview); img.draggable = true; img.alt = `Reference ${i + 1}`;
                img.loading = 'lazy'; img.decoding = 'async';
                img.style.cursor = 'pointer'; img.tabIndex = 0; img.title = 'Click to assign to the active output; double-click for a larger preview';
                const show = () => openViewer(field.value, i);
                const assign = () => {
                    if (isPinned(activeOutput)) { message('Unpin the active output before assigning another image.', true); return; }
                    if (linked(activeOutput)) { message(`Output ${activeOutput + 1} is controlled by Input ${activeOutput + 1}. Disconnect that input first.`, true); return; }
                    if (!field.value) { message(`Image ${i + 1} is empty. Choose or connect an image first.`, true); return; }
                    const selected = outputs.map(field => Number(field.value)); selected[activeOutput] = i + 1;
                    changeSelections(selected); message(`Image ${i + 1} assigned to Output ${activeOutput + 1}.`);
                };
                img.onclick = event => { event?.stopPropagation(); assign(); };
                img.ondblclick = event => { event?.stopPropagation(); show(); };
                img.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); assign(); } };
                card.onclick = event => { if (!event?.target?.closest?.('button,input,select')) assign(); };
                const hint = element('div', card); hint.style.cssText = 'font-size:11px;color:#aebbd0;margin:0;line-height:1.3';
                const label = element('div', card); label.className = 'filename';
                const dice = element('button', header, '🎲');
                dice.setAttribute('aria-label', `Exclude Image ${i + 1} from randomization`);
                dice.onclick = event => {
                    event?.stopPropagation(); if (!field.value) return;
                    remember(); const values = exclusions();
                    if (values.has(field.value)) values.delete(field.value); else values.add(field.value);
                    node.properties.magik_excluded_images = [...values]; refresh();
                };
                previews.push({img, label, hint, card, dice});
                img.onerror = () => message(`Image ${i + 1} is missing or cannot be previewed.`, true);
                const controls = element('div', card); controls.className = 'row';
                const button = element('button', controls, 'Choose image…');
                const picker = element('input', card); picker.type = 'file'; picker.accept = 'image/*'; picker.style.display = 'none';
                button.onclick = () => picker.click();
                let uploadSequence = 0;
                const upload = async file => {
                    if (!file) return;
                    const sequence = ++uploadSequence, originalPath = field.value;
                    button.disabled = true;
                    try {
                        const body = new FormData(); body.append('image', file);
                        body.append('type', 'input'); body.append('subfolder', 'magik_4_references');
                        const uploaded = await request('/magik/4-references/upload', {method: 'POST', body});
                        if (removed || fields[i] !== field || sequence !== uploadSequence) return;
                        if (field.value !== originalPath) { message('Upload finished, but the card changed in the meantime. Its current image was kept.', true); return; }
                        remember();
                        captures[i] = null;
                        field.value = [uploaded.subfolder, uploaded.name].filter(Boolean).join('/');
                        refresh(); message(`Image ${i + 1} loaded.`);
                    } catch (error) { message(error.message, true); }
                    finally { if (sequence === uploadSequence) { button.disabled = false; picker.value = ''; } }
                };
                picker.onchange = () => upload(picker.files[0]);
                card.ondragover = event => { event.preventDefault(); event.stopPropagation(); card.classList.add('over'); };
                card.ondragleave = () => card.classList.remove('over');
                card.ondrop = event => {
                    event.preventDefault(); event.stopPropagation(); card.classList.remove('over');
                    const encoded = event.dataTransfer.getData?.(dragType);
                    if (encoded) {
                        try {
                            const source = JSON.parse(encoded);
                            if (source.token === dragToken && source.kind !== 'output' && Number.isInteger(source.index)) swap(source.index, i);
                        } catch { message('Could not read the dragged image slot.', true); }
                        return;
                    }
                    upload(event.dataTransfer.files?.[0]);
                };
                element('button', header, 'Clear').onclick = () => { if (!field.value) return; remember(); field.value = ''; captures[i] = null; refresh(); message(`Image ${i + 1} cleared.`); };
                if (i >= portCount) {
                    const trash = element('button', header, '🗑');
                    trash.title = `Delete Image ${i + 1} card`; trash.setAttribute('aria-label', `Delete image ${i + 1} card`);
                    trash.onclick = event => { event?.stopPropagation(); deleteCard(i); };
                }
                const callback = field.callback;
                field.callback = function () { const value = callback?.apply(this, arguments); captures[i] = null; refresh(); return value; };
            }
            fields.forEach(createCard);
            function setCount(count) {
                count = Math.max(portCount, Math.min(MAX_IMAGES, count));
                while (fields.length < count) {
                    const i = fields.length;
                    const field = {};
                    Object.defineProperty(field, 'value', {
                        get() { return readExtra()[i - portCount] || ''; },
                        set(value) { const values = readExtra(); while (values.length <= i - portCount) values.push(''); values[i - portCount] = value; extra.value = JSON.stringify(values); },
                    });
                    fields.push(field); field.value = field.value;
                    createCard(field, i);
                }
                while (fields.length > count) {
                    const i = fields.length - 1;
                    previews.pop().card.remove(); fields.pop(); captures.pop();
                }
                extra.value = JSON.stringify(readExtra().slice(0, count - portCount));
                outputs.forEach(field => { if (Number(field.value) > count) field.value = 0; });
                refresh();
            }
            function deleteCard(index) {
                if (index < portCount || index >= fields.length) return;
                if (fields[index].value && !confirm(`Delete Image ${index + 1} card? The source file is kept.`)) return;
                remember();
                const paths = fields.map(field => field.value); paths.splice(index, 1);
                const mapped = outputs.map(field => { const value = Number(field.value); return value === index + 1 ? 0 : value > index + 1 ? value - 1 : value; });
                setCount(paths.length);
                paths.forEach((path, i) => { fields[i].value = path; });
                outputs.forEach((field, i) => { field.value = mapped[i]; });
                refresh(); message('Card deleted. Direct input connections are unchanged.');
            }
            addCard.onclick = () => { if (fields.length >= MAX_IMAGES) return; remember(); setCount(fields.length + 1); };
            function applyFolder(paths, replacing, start) {
                remember();
                if (replacing) {
                    fields.forEach((field, i) => { field.value = ''; captures[i] = null; });
                    setCount(Math.max(portCount, paths.length));
                } else setCount(Math.max(fields.length, start + paths.length));
                paths.forEach((path, index) => { const i = start + index; fields[i].value = path; captures[i] = null; });
                if (replacing) outputs.forEach((field, i) => { field.value = i < paths.length ? i + 1 : 0; });
                refresh();
            }
            async function loadServerFolder() {
                const replacing = folderMode.value === 'replace';
                let start = 0;
                if (!replacing) fields.forEach((field, i) => { if (field.value) start = i + 1; });
                if (start >= MAX_IMAGES) { message('Collection full. Choose Replace or clear final slots.', true); return; }
                root.inert = true; loadFolder.textContent = 'Loading…';
                try {
                    const data = await post('/magik/4-references/folder', {path: folderPath.value, limit: MAX_IMAGES - start});
                    if (removed) return;
                    if (!data.images.length) { message(`No readable images found. Collection unchanged. ${(data.errors || []).join('\n')}`, true); return; }
                    applyFolder(data.images, replacing, start);
                    message(`Loaded ${data.images.length} image(s). ${data.skipped} skipped at limit. ${data.failed} failed. ${(data.errors || []).join('\n')}`, data.failed > 0);
                } catch (error) { message(error.message, true); }
                finally { root.inert = false; loadFolder.textContent = 'Load Folder'; }
            }
            folderPicker.onchange = async () => {
                const selected = Array.from(folderPicker.files || []);
                folderPicker.value = '';
                if (!selected.length) return;
                const files = selected.filter(file => file.type?.startsWith('image/') || /\.(png|jpe?g|webp|gif|bmp|tiff?|avif|ico|ppm|pgm|pbm|apng)$/i.test(file.name));
                files.sort((a, b) => (a.webkitRelativePath || a.name).localeCompare(b.webkitRelativePath || b.name, undefined, {numeric: true, sensitivity: 'base'}));
                if (!files.length) { message('No supported image files found in this folder. Collection unchanged.', true); return; }
                const replacing = folderMode.value === 'replace';
                let start = 0;
                if (!replacing) fields.forEach((field, i) => { if (field.value) start = i + 1; });
                const capacity = MAX_IMAGES - start;
                if (capacity <= 0) { message(`The collection already contains ${MAX_IMAGES} images. Choose Replace or clear the final slots first.`, true); return; }
                root.inert = true;
                loadFolder.textContent = 'Loading…';
                const uploadedPaths = [];
                let attempted = 0, failed = 0;
                const errors = [];
                try {
                    for (const file of files) {
                        if (uploadedPaths.length >= capacity || removed) break;
                        attempted++;
                        message(`Uploading folder: ${attempted} / ${files.length} · ${uploadedPaths.length} loaded · ${failed} failed`);
                        try {
                            const body = new FormData(); body.append('image', file);
                            body.append('type', 'input'); body.append('subfolder', 'magik_4_references');
                            const uploaded = await request('/magik/4-references/upload', {method: 'POST', body});
                            if (!uploaded.name) throw new Error('Upload returned no image filename.');
                            uploadedPaths.push([uploaded.subfolder, uploaded.name].filter(Boolean).join('/'));
                        } catch (error) { failed++; errors.push(`${file.name}: ${error.message}`); }
                    }
                    if (removed) return;
                    if (!uploadedPaths.length) {
                        message(`No images could be uploaded. Collection unchanged.\n${errors.slice(0, 3).join('\n')}`, true);
                        return;
                    }
                    // Stage uploads first: a cancelled picker or wholly failed load never clears existing selections.
                    applyFolder(uploadedPaths, replacing, start);
                    const skipped = files.length - attempted;
                    message(`${replacing ? 'Replaced collection with' : 'Appended'} ${uploadedPaths.length} image(s). ${skipped ? `${skipped} skipped at the ${MAX_IMAGES}-image limit. ` : ''}${failed ? `${failed} upload(s) failed. ` : ''}${selected.length - files.length} non-image file(s) ignored.${errors.length ? '\n' + errors.slice(0, 3).join('\n') : ''}`, failed > 0);
                } catch (error) { message(error.message, true); }
                finally { root.inert = false; loadFolder.textContent = 'Load Folder'; }
            };
            const searchRow = element('div', root); searchRow.className = 'row';
            const search = element('input', searchRow); search.placeholder = 'Search presets…'; search.setAttribute('aria-label', 'Search presets');
            const reload = element('button', searchRow, 'Refresh');
            const presetRow = element('div', root); presetRow.className = 'row';
            const select = element('select', presetRow); select.setAttribute('aria-label', 'Saved presets');
            const load = element('button', presetRow, 'Load');
            const rename = element('button', presetRow, 'Rename');
            const remove = element('button', presetRow, 'Delete');
            const presetToggle = element('button', root, 'Show preset previews');
            presetToggle.style.marginTop = '8px'; presetToggle.setAttribute('aria-expanded', 'false');
            let presetsVisible = false;
            const gallery = element('div', root); gallery.className = 'gallery'; gallery.style.display = 'none';
            presetToggle.onclick = () => {
                presetsVisible = !presetsVisible;
                gallery.style.display = presetsVisible ? 'grid' : 'none';
                presetToggle.textContent = presetsVisible ? 'Hide preset previews' : 'Show preset previews';
                presetToggle.setAttribute('aria-expanded', String(presetsVisible));
                if (presetsVisible) presetSamples.clear();
                drawGallery(); scheduleFit();
            };
            const transferRow = element('div', root); transferRow.className = 'row';
            const exportOne = element('button', transferRow, 'Export selected');
            const exportAll = element('button', transferRow, 'Export all');
            const importButton = element('button', transferRow, 'Import ZIP…');
            const importPicker = element('input', transferRow); importPicker.type = 'file'; importPicker.accept = '.zip,application/zip'; importPicker.style.display = 'none';
            root.append(status);
            let presets = [], sequence = 0, timer, removed = false;
            const presetSamples = new Map();
            const drawGallery = () => {
                gallery.replaceChildren();
                if (!presetsVisible) { scheduleFit(); return; }
                for (const preset of presets) {
                    const card = element('button', gallery); card.className = `preset${select.value === preset.name ? ' active' : ''}`;
                    element('div', card, `${preset.name} · ${preset.images.length} images`);
                    const strip = element('div', card); strip.className = 'mini'; strip.style.gridTemplateColumns = `repeat(${portCount === 9 ? 3 : portCount === 8 ? 4 : portCount === 6 ? 3 : 2},minmax(0,1fr))`;
                    const key = JSON.stringify([preset.name, preset.images]);
                    if (!presetSamples.has(key)) presetSamples.set(key, randomSample([...new Set(preset.images.filter(Boolean))], portCount));
                    const sampled = presetSamples.get(key);
                    Array.from({length: portCount}, (_, i) => sampled[i] || '').forEach((path, i) => { const cell = element('div', strip); cell.className = 'preset-cell'; const img = element('img', cell); img.alt = path ? `Random image ${i + 1}` : 'Empty'; img.loading = 'lazy'; if (path) img.src = thumb(path); });
                    card.onclick = () => { select.value = preset.name; name.value = preset.name; drawGallery(); };
                    card.ondblclick = () => { select.value = preset.name; load.onclick(); };
                }
                scheduleFit();
            };
            const fetchPresets = async () => {
                const seq = ++sequence, selected = select.value;
                try {
                    const data = await request(`${base}?${new URLSearchParams({q: search.value})}`);
                    if (seq !== sequence || removed) return;
                    presets = data.presets; presetSamples.clear(); select.replaceChildren();
                    if (!presets.length) { const option = element('option', select, 'No matching presets'); option.value = ''; }
                    for (const preset of presets) { const option = element('option', select, preset.name); option.value = preset.name; }
                    if (presets.some(p => p.name === selected)) select.value = selected;
                    load.disabled = rename.disabled = remove.disabled = !presets.length;
                    drawGallery();
                } catch (error) { message(error.message, true); }
            };
            const download = async all => {
                exportOne.disabled = exportAll.disabled = true;
                try {
                    if (!all && !select.value) throw new Error('Select a preset first.');
                    const query = all ? '' : `?${new URLSearchParams({name: select.value})}`;
                    const response = await api.fetchApi(`${base}/export${query}`);
                    if (!response.ok) { const data = await response.json(); throw new Error(data.error || 'Export failed.'); }
                    const url = URL.createObjectURL(await response.blob());
                    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'Magik_References_Presets.zip';
                    document.body.append(anchor); anchor.click(); anchor.remove();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                    message('Preset ZIP exported, including the referenced image files.');
                } catch (error) { message(error.message, true); }
                finally { exportOne.disabled = exportAll.disabled = false; }
            };
            exportOne.onclick = () => download(false); exportAll.onclick = () => download(true);
            importButton.onclick = () => importPicker.click();
            importPicker.onchange = async () => {
                if (!importPicker.files[0]) return;
                importButton.disabled = true;
                try {
                    const body = new FormData(); body.append('archive', importPicker.files[0]);
                    const result = await request(`${base}/import`, {method: 'POST', body});
                    search.value = ''; await fetchPresets();
                    if (result.names.length) { select.value = result.names[0]; name.value = result.names[0]; drawGallery(); }
                    message(`Imported ${result.count} preset(s). Existing names are kept; duplicates receive a numbered suffix.`);
                } catch (error) { message(error.message, true); }
                finally { importButton.disabled = false; importPicker.value = ''; }
            };
            select.onchange = () => { name.value = select.value; drawGallery(); };
            search.oninput = () => { clearTimeout(timer); sequence++; timer = setTimeout(fetchPresets, 200); };
            reload.onclick = fetchPresets;
            load.onclick = () => {
                const preset = presets.find(p => p.name === select.value); if (!preset) return;
                undoStack.length = redoStack.length = 0; resetCycle();
                node.properties.magik_excluded_images = (preset.excluded || []).map(index => preset.images[index]).filter(Boolean);
                setCount(preset.images.length);
                fields.forEach((field, i) => { captures[i] = null; field.value = preset.images[i] || ''; });
                outputs.forEach((field, i) => { field.value = preset.outputs?.[i] ?? (i < preset.images.length ? i + 1 : 0); });
                titleField.value = preset.title || ''; titleInput.value = titleField.value;
                descriptionField.value = preset.description || ''; descriptionInput.value = descriptionField.value;
                name.value = preset.name; refresh(); message(`Preset loaded: ${preset.name}`);
            };
            rename.onclick = async () => {
                try {
                    const old = select.value, next = name.value.trim();
                    if (old === next) { message('Enter the new name in the preset name field, then click Rename.'); return; }
                    await post(`${base}/manage`, {action: 'rename', name: old, new_name: next});
                    await fetchPresets(); select.value = next; drawGallery(); message(`Preset renamed to ${next}.`);
                } catch (error) { message(error.message, true); }
            };
            remove.onclick = async () => {
                if (!confirm(`Delete preset “${select.value}”? Image files will be kept.`)) return;
                try { await post(`${base}/manage`, {action: 'delete', name: select.value}); await fetchPresets(); message('Preset deleted.'); }
                catch (error) { message(error.message, true); }
            };
            save.onclick = async () => {
                save.disabled = true;
                try {
                    const images = fields.map(field => field.value || '');
                    const selected = outputs.map(field => Number(field.value));
                    for (let i = 0; i < portCount; i++) if (linked(i) || isPinned(i)) {
                        const captured = linked(i) ? inputCaptures[i] : readPins()[i];
                        if (!linked(i) && captured === '') { selected[i] = 0; continue; }
                        if (!captured) throw new Error(`Run the workflow first to capture Input ${i + 1}.`);
                        let index = images.indexOf(captured);
                        if (index < 0) {
                            if (images.length >= MAX_IMAGES) throw new Error('Free a collection slot before saving connected input snapshots.');
                            index = images.push(captured) - 1;
                        }
                        selected[i] = index + 1;
                    }
                    const payload = {name: name.value.trim(), images, excluded: images.map((path, i) => exclusions().has(path) ? i : -1).filter(i => i >= 0), outputs: selected, title: titleField.value || '', description: descriptionField.value || ''};
                    try { await post(base, payload); }
                    catch (error) {
                        if (error.status !== 409) throw error;
                        if (!confirm(`Replace preset “${payload.name}”?`)) return;
                        payload.overwrite = true; await post(base, payload);
                    }
                    search.value = ''; await fetchPresets(); select.value = payload.name; drawGallery(); message(`Preset saved: ${payload.name}`);
                } catch (error) { message(error.message, true); }
                finally { save.disabled = false; }
            };
            const executed = node.onExecuted;
            node.onExecuted = function (data) {
                const value = executed?.apply(this, arguments);
                if (Array.isArray(data?.magik_inputs)) data.magik_inputs.slice(0, portCount).forEach((path, i) => { inputCaptures[i] = path || null; });
                if (Array.isArray(data?.magik_references)) {
                    data.magik_references.forEach((path, i) => { captures[i] = path || null; });
                    refresh(); message('Previews updated. Save captures the connected images from this execution.');
                }
                return value;
            };
            const changed = node.onConnectionsChange;
            node.onConnectionsChange = function (kind, slot) {
                const value = changed?.apply(this, arguments);
                if (kind === 1) { const i = fields.findIndex((_, index) => slotIndex(index) === slot); if (i >= 0 && i < portCount) inputCaptures[i] = null; refresh(); }
                return value;
            };
            // Measure an unconstrained inner panel, not the widget host whose height
            // ComfyUI sets from computeSize. This permits shrinking as well as growing.
            const host = document.createElement('div');
            // Clip both paint and hit testing to the rectangle allocated by ComfyUI.
            // The inner root remains naturally sized so it can still be measured.
            // Empty host space must not intercept canvas gestures.
            host.style.cssText = 'position:relative;box-sizing:border-box;width:100%;height:100%;min-width:0;min-height:0;max-width:100%;overflow:hidden;clip-path:inset(0);contain:paint;pointer-events:none';
            host.append(root);
            let contentHeight = 1, fitQueued = false, fitting = false;
            const panel = node.addDOMWidget('references_panel', 'magik_refs', host, {
                serialize: false, hideOnZoom: false,
                getMinHeight: () => contentHeight,
                getMaxHeight: () => contentHeight,
            });
            panel.computeSize = width => [width || node.size?.[0] || defaultWidth, contentHeight];
            scheduleFit = () => {
                if (fitQueued || removed) return;
                fitQueued = true;
                requestAnimationFrame(() => {
                    fitQueued = false;
                    if (removed || fitting || !root.isConnected || !root.offsetWidth || node.flags?.collapsed) return;
                    // offsetHeight/scrollHeight are in CSS pixels, unaffected by canvas zoom.
                    const measured = Math.ceil(Math.max(root.offsetHeight, root.scrollHeight));
                    if (!measured) return;
                    fitting = true;
                    try {
                        contentHeight = measured;
                        const width = node.size?.[0] || defaultWidth;
                        const computed = node.computeSize();
                        const height = Math.ceil(computed[1]);
                        if (Math.abs((node.size?.[1] || 0) - height) > 1) node.setSize([width, height]);
                        node.setDirtyCanvas(true, true);
                    } finally { fitting = false; }
                });
            };
            const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(scheduleFit);
            resizeObserver?.observe(root);
            const resized = node.onResize;
            node.onResize = function () { const value = resized?.apply(this, arguments); scheduleFit(); return value; };
            const configured = node.onConfigure;
            node.onConfigure = function () { const value = configured?.apply(this, arguments);
                node.properties ??= {}; resetCycle(); repeatToggle.checked = node.properties.magik_avoid_repeats === true; queueToggle.checked = node.properties.magik_randomize_on_queue === true; updateCardsVisibility();
                if (node.outputs && !node.outputs.some(output => output.name === 'description' && output.type === 'STRING')) node.addOutput('description', 'STRING'); titleInput.value = titleField.value || ''; descriptionInput.value = descriptionField.value || ''; undoStack.length = redoStack.length = 0; captures.fill(null); inputCaptures.fill(null);
                requestAnimationFrame(() => {
                    for (let i = node.inputs.length - 1; i >= 0; i--) if (Number(/^image_(\d+)$/.exec(node.inputs[i].name)?.[1]) > portCount) node.removeInput(i);
                    setCount(readExtra().length + portCount);
                }); return value; };
            const onRemoved = node.onRemoved;
            node.onRemoved = function () { removed = true; queueRandomizers.delete(queueEntry); clearTimeout(timer); resizeObserver?.disconnect(); folderPicker.remove(); closeViewer(); return onRemoved?.apply(this, arguments); };
            node.setSize([Math.max(defaultWidth, node.size?.[0] || 0), node.computeSize()[1]]); setCount(readExtra().length + portCount); scheduleFit(); fetchPresets();
            return result;
        };
    },
});
