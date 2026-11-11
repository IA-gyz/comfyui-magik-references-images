import asyncio
import collections
import io
import os
import tempfile
import zipfile
import re
import shutil
import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps
from aiohttp import web
import folder_paths
from server import PromptServer


def image_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Choose a valid reference image.')
    root = Path(folder_paths.get_input_directory()).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Reference image is missing or outside the input folder: {value}')
    return path


IMAGE_SUFFIXES = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif',
                  'BMP': '.bmp', 'TIFF': '.tiff', 'AVIF': '.avif', 'ICO': '.ico'}


def image_suffix(image_format):
    # One mapping for uploads and ZIP imports, so identical bytes get identical names
    # (Pillow's own first registered JPEG extension is '.jfif').
    suffix = IMAGE_SUFFIXES.get(image_format)
    if suffix is None:
        suffix = next((ext for ext, fmt in Image.registered_extensions().items() if fmt == image_format), None)
    return suffix


def to_float_rgb(image):
    if image.mode == 'I' or image.mode.startswith('I;16'):
        # High-bit-depth grayscale: convert('RGB') clips to 8 bits (mid-gray -> white), so scale explicitly.
        data = np.array(image, dtype=np.float32)
        peak = 65535.0 if image.mode.startswith('I;16') or data.max() > 255 else 255.0
        gray = np.clip(data / peak, 0.0, 1.0)
        return np.stack([gray] * 3, axis=-1)
    return np.array(image.convert('RGB'), dtype=np.float32) / 255.0


def snapshot_connected_image(tensor):
    # Best-effort snapshot used for previews and preset capture. It must never abort a run.
    try:
        array = np.nan_to_num(tensor[0].detach().cpu().numpy().astype(np.float32))
        pixels = np.clip(array * 255, 0, 255).astype(np.uint8)
        if pixels.ndim == 2:
            pixels = pixels[..., None]
        if pixels.shape[-1] == 1:
            picture = Image.fromarray(pixels[..., 0], 'L')
        else:
            picture = Image.fromarray(pixels[..., :4] if pixels.shape[-1] > 4 else pixels)
        encoded = io.BytesIO()
        picture.save(encoded, format='PNG', compress_level=1)
        stored = store_uploaded_image(encoded.getvalue(), SNAPSHOT_SUBFOLDER)
        maybe_prune_snapshots()
        return stored['subfolder'] + '/' + stored['name']
    except Exception as exc:
        logging.warning('Magik References: connected image snapshot skipped (%s). Preview and preset capture are unavailable for this run.', exc)
        return ''


SNAPSHOT_SUBFOLDER = 'magik_4_references/snapshots'
_last_prune = 0.0


def snapshot_retention_days():
    # MAGIK_SNAPSHOT_RETENTION_DAYS: days to keep unreferenced connected-image snapshots (0 = never delete).
    try:
        return float(os.environ.get('MAGIK_SNAPSHOT_RETENTION_DAYS', '7'))
    except ValueError:
        return 7.0


def prune_snapshots(retention_days=None):
    """Delete snapshots older than the retention period that no saved preset references. Returns how many."""
    days = snapshot_retention_days() if retention_days is None else retention_days
    root = Path(folder_paths.get_input_directory()) / SNAPSHOT_SUBFOLDER
    if days <= 0 or not root.is_dir():
        return 0
    db = database()  # if the database cannot be read this raises, so nothing is deleted
    try:
        protected = {path for (images,) in db.execute('SELECT images FROM presets') for path in json.loads(images) if path}
    finally:
        db.close()
    cutoff = time.time() - days * 86400
    removed = 0
    for path in root.iterdir():
        if not path.is_file() or f'{SNAPSHOT_SUBFOLDER}/{path.name}' in protected:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def maybe_prune_snapshots():
    global _last_prune
    if time.time() - _last_prune < 3600:  # at most once an hour
        return
    _last_prune = time.time()
    try:
        removed = prune_snapshots()
        if removed:
            logging.info('Magik References: removed %d expired connected-image snapshot(s).', removed)
    except Exception as exc:
        logging.warning('Magik References: snapshot cleanup skipped (%s).', exc)


def touch_snapshots(paths):
    # Snapshots a workflow still uses (pins, pool) stay fresh, so retention only removes forgotten ones.
    for value in paths:
        if isinstance(value, str) and value.startswith(SNAPSHOT_SUBFOLDER + '/'):
            try:
                os.utime(image_path(value), None)
            except (ValueError, OSError):
                pass


def database():
    root = Path(folder_paths.get_user_directory()) / 'magik_4_references_images'
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'presets.sqlite3', timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS presets (name TEXT PRIMARY KEY, images TEXT NOT NULL)')
    # Columns added over the versions; each is added once to a database created by an older version.
    for column, definition in (('outputs', "TEXT NOT NULL DEFAULT '[1,2,3,4]'"),
                               ('title', "TEXT NOT NULL DEFAULT ''"),
                               ('description', "TEXT NOT NULL DEFAULT ''"),
                               ('excluded', "TEXT NOT NULL DEFAULT '[]'"),
                               ('favorite', 'INTEGER NOT NULL DEFAULT 0')):  # 0 = not a favourite, N = its position in Favorites
        if column not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
            try:
                db.execute(f'ALTER TABLE presets ADD COLUMN {column} {definition}')
            except sqlite3.OperationalError:  # another process added it first
                if column not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
                    raise
    return db


MAX_SLOTS = 128


def preset_excluded(value, count):
    if not isinstance(value, list) or len(value) > MAX_SLOTS or any(type(i) is not int or not 0 <= i < count for i in value):
        raise ValueError('Excluded images must be a list of valid zero-based slot indices.')
    return sorted(set(value))



def references(kwargs, slots=4):
    extra = json.loads(kwargs.get('extra_references', '[]'))
    if not isinstance(extra, list) or len(extra) > MAX_SLOTS - slots or any(not isinstance(v, str) for v in extra):
        raise ValueError('Additional references must be an array of image paths (maximum 128 total).')
    values = [kwargs.get(f'reference_{i}', '') for i in range(1, slots + 1)] + extra
    return values


def output_choices(value, count, expected=None):
    valid_lengths = (expected,) if expected is not None else (4, 6, 8, 9)
    if not isinstance(value, list) or len(value) not in valid_lengths or any(type(i) is not int or not 0 <= i <= max(len(value), count) for i in value):
        raise ValueError('Choose one output index per port (0 means empty).')
    return value


def pinned_references(kwargs, slots):
    pins = json.loads(kwargs.get('pinned_outputs', '[]'))
    if not isinstance(pins, list) or len(pins) > slots or any(value is not None and not isinstance(value, str) for value in pins):
        raise ValueError('Pinned outputs must contain image paths or null values.')
    return pins + [None] * (slots - len(pins))


def preset_title(value):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('Title must be text with at most 512 characters.')
    return value


class Magik4ReferencesImages:
    PORT_COUNT = 4
    CATEGORY = 'Magik/IO'
    RETURN_TYPES = ('IMAGE',) * 4 + ('STRING', 'STRING')
    RETURN_NAMES = ('Image 1', 'Image 2', 'Image 3', 'Image 4', 'description', 'Name')
    FUNCTION = 'load'
    OUTPUT_NODE = True
    DESCRIPTION = 'Load up to 128 reference images and choose which image feeds each of four independent outputs.'

    @classmethod
    def INPUT_TYPES(cls):
        return {
            'required': {**{f'reference_{i}': ('STRING', {'default': ''}) for i in range(1, cls.PORT_COUNT + 1)},
                         'extra_references': ('STRING', {'default': '[]'}),
                         **{f'output_{i}': ('INT', {'default': i, 'min': 0, 'max': MAX_SLOTS}) for i in range(1, cls.PORT_COUNT + 1)}},
            # title / description / pinned_outputs were added after the first release, so they are optional: API-format
            # workflows saved earlier (which lack them) still validate. They are widgets, not sockets, so the widget
            # order and therefore every saved widgets_values array stay exactly as they were.
            'optional': {**{f'image_{i}': ('IMAGE',) for i in range(1, cls.PORT_COUNT + 1)},
                         'title': ('STRING', {'default': ''}),
                         'description': ('STRING', {'default': '', 'dynamicPrompts': False}),
                         'pinned_outputs': ('STRING', {'default': '[]', 'dynamicPrompts': False})},
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types=None, **kwargs):
        # ComfyUI leaves linked inputs out of kwargs here and reports them through input_types.
        linked = input_types or {}
        for socket, received in linked.items():
            if socket.startswith('image_') and received != 'IMAGE':
                return f'{socket} expects IMAGE but received {received}.'
        try:
            values = references(kwargs, cls.PORT_COUNT)
            choices = output_choices([kwargs.get(f'output_{i}', i) for i in range(1, cls.PORT_COUNT + 1)], len(values), cls.PORT_COUNT)
            pins = pinned_references(kwargs, cls.PORT_COUNT)
            for output, selected in enumerate(choices, 1):
                reference = pins[output - 1] if pins[output - 1] is not None else values[selected - 1] if 0 < selected <= len(values) else ''
                if f'image_{output}' not in linked and kwargs.get(f'image_{output}') is None and reference:
                    image_path(reference)
        except (ValueError, TypeError) as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        digest = hashlib.sha256()
        values = references(kwargs, cls.PORT_COUNT)
        pins = pinned_references(kwargs, cls.PORT_COUNT)
        for output in range(1, cls.PORT_COUNT + 1):
            selected = kwargs.get(f'output_{output}', output)
            if kwargs.get(f'image_{output}') is not None:
                continue
            value = pins[output - 1] if pins[output - 1] is not None else values[selected - 1] if 0 < selected <= len(values) else ''
            if not value:
                continue
            try:
                path = image_path(value)
            except ValueError:
                digest.update(b'missing:' + value.encode())  # VALIDATE_INPUTS reports it for outputs that use it
                continue
            digest.update(str(path).encode())
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
        return digest.hexdigest()

    def load(self, **kwargs):
        values = references(kwargs, self.PORT_COUNT)
        choices = output_choices([kwargs.get(f'output_{i}', i) for i in range(1, self.PORT_COUNT + 1)], len(values), self.PORT_COUNT)
        pins = pinned_references(kwargs, self.PORT_COUNT)
        touch_snapshots(values + pins)
        result, input_captures = [], []
        decoded, used = {}, set()
        for output, selected in enumerate(choices, 1):
            connected = kwargs.get(f'image_{output}')
            if connected is not None:
                if connected.ndim != 4 or connected.shape[0] < 1:
                    raise ValueError(f'Input {output}: expected an IMAGE tensor with at least one image.')
                tensor = connected[:1]
                path = snapshot_connected_image(tensor)
                input_captures.append(path)
                result.append(tensor)
                continue
            input_captures.append('')
            reference = pins[output - 1] if pins[output - 1] is not None else values[selected - 1] if 0 < selected <= len(values) else ''
            if not reference:
                result.append(None)
                continue
            if reference not in decoded:
                with Image.open(image_path(reference)) as source:
                    source.seek(0)
                    image = ImageOps.exif_transpose(source)
                    array = to_float_rgb(image)
                    decoded[reference] = torch.from_numpy(array).unsqueeze(0)
            # Outputs showing the same image get independent tensors, so a downstream node that edits one in place
            # cannot change the others.
            result.append(decoded[reference].clone() if reference in used else decoded[reference])
            used.add(reference)
        return {'ui': {'magik_inputs': input_captures},
                'result': tuple(result) + (kwargs.get('description', ''), kwargs.get('title', ''))}


routes = PromptServer.instance.routes


def _list_presets(query):
    db = database()
    try:
        rows = db.execute('SELECT name, images, outputs, title, description, excluded, favorite FROM presets ORDER BY name COLLATE NOCASE').fetchall()
    finally:
        db.close()
    shaped = [{'name': name, 'images': json.loads(images), 'outputs': json.loads(outputs), 'title': title, 'description': description,
               'excluded': json.loads(excluded), 'favorite': favorite}
              for name, images, outputs, title, description, excluded, favorite in rows]
    favorites = sorted((p for p in shaped if p['favorite'] > 0), key=lambda p: (p['favorite'], p['name'].casefold()))
    return {'presets': [p for p in shaped if query in p['name'].casefold()], 'favorites': favorites}


def _save_preset(data):
    name = data.get('name')
    images = data.get('images')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError('Preset name must contain 1–120 characters.')
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_SLOTS:
        raise ValueError('A preset requires between 1 and 128 image slots.')
    outputs = output_choices(data.get('outputs', [1, 2, 3, 4]), len(images))
    excluded = preset_excluded(data.get('excluded', []), len(images))
    title = preset_title(data.get('title', ''))
    description = data.get('description', '')
    if not isinstance(description, str):
        raise ValueError('Description must be text.')
    for value in images:
        if value != '':
            image_path(value)
    values = (name.strip(), json.dumps(images), json.dumps(outputs), title, description, json.dumps(excluded))
    insert = 'INSERT INTO presets (name, images, outputs, title, description, excluded) VALUES (?, ?, ?, ?, ?, ?)'
    db = database()
    try:
        with db:
            if data.get('overwrite') is True:
                # An upsert, not INSERT OR REPLACE: replacing deletes the row, which would reset its favourite position.
                db.execute(insert + ' ON CONFLICT(name) DO UPDATE SET images = excluded.images, outputs = excluded.outputs, '
                           'title = excluded.title, description = excluded.description, excluded = excluded.excluded', values)
            else:
                db.execute(insert, values)
    finally:
        db.close()
    return name.strip()


def _reorder_favorites(names):
    if not isinstance(names, list) or len(names) > 4096 or not all(isinstance(item, str) for item in names):
        raise ValueError('Favorites order must be a list of preset names.')
    db = database()
    try:
        with db:
            current = [row[0] for row in db.execute('SELECT name FROM presets WHERE favorite > 0 ORDER BY favorite, name COLLATE NOCASE')]
            listed = [item for item in dict.fromkeys(names) if item in current]  # unknown names and repeats are ignored
            for position, preset in enumerate(listed + [item for item in current if item not in listed], 1):
                db.execute('UPDATE presets SET favorite = ? WHERE name = ?', (position, preset))
    finally:
        db.close()
    return True


def _manage_preset(data):
    """Rename, delete, favourite / unfavourite, or reorder Favorites. Returns False when the preset no longer exists."""
    action = data.get('action')
    if action == 'reorder_favorites':
        return _reorder_favorites(data.get('names'))
    name = data.get('name')
    if not isinstance(name, str):
        raise ValueError('Select a preset first.')
    if action == 'rename':
        new_name = data.get('new_name')
        if not isinstance(new_name, str) or not 1 <= len(new_name.strip()) <= 120:
            raise ValueError('Preset name must contain 1\u2013120 characters.')
    elif action == 'favorite':
        if not isinstance(data.get('value'), bool):
            raise ValueError('Favorite must be true or false.')
    elif action != 'delete':
        raise ValueError('Unknown preset operation.')
    db = database()
    try:
        with db:
            if action == 'delete':
                cursor = db.execute('DELETE FROM presets WHERE name = ?', (name,))
            elif action == 'favorite':
                if data['value']:  # new favourites go to the end; an existing one keeps its position
                    db.execute('UPDATE presets SET favorite = (SELECT COALESCE(MAX(favorite), 0) + 1 FROM presets) WHERE name = ? AND favorite = 0', (name,))
                    return db.execute('SELECT 1 FROM presets WHERE name = ?', (name,)).fetchone() is not None
                cursor = db.execute('UPDATE presets SET favorite = 0 WHERE name = ?', (name,))
            else:
                cursor = db.execute('UPDATE presets SET name = ? WHERE name = ?', (new_name.strip(), name))
            return cursor.rowcount > 0
    finally:
        db.close()


# SQLite calls block, so every handler hands its database work to a worker thread
# (a locked database used to freeze the whole ComfyUI server for up to 15 seconds).
@routes.get('/magik/4-references/presets')
async def list_presets(request):
    query = request.query.get('q', '').casefold()
    try:
        return web.json_response(await asyncio.to_thread(_list_presets, query))
    except sqlite3.Error as exc:
        return web.json_response({'error': f'Preset database error: {exc}'}, status=500)


@routes.post('/magik/4-references/presets')
async def save_preset(request):
    try:
        data = await request.json()
        return web.json_response({'name': await asyncio.to_thread(_save_preset, data)})
    except sqlite3.IntegrityError:
        return web.json_response({'error': 'A preset with this name already exists.'}, status=409)
    except (ValueError, TypeError, AttributeError) as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except sqlite3.Error as exc:
        return web.json_response({'error': f'Preset database error: {exc}'}, status=500)


@routes.post('/magik/4-references/presets/manage')
async def manage_preset(request):
    try:
        data = await request.json()
        if not await asyncio.to_thread(_manage_preset, data):
            return web.json_response({'error': 'Preset no longer exists.'}, status=404)
        return web.json_response({'ok': True})
    except sqlite3.IntegrityError:
        return web.json_response({'error': 'A preset with this name already exists.'}, status=409)
    except (ValueError, TypeError, AttributeError) as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except sqlite3.Error as exc:
        return web.json_response({'error': f'Preset database error: {exc}'}, status=500)


THUMBNAIL_BOX = (320, 240)
THUMBNAIL_CACHE_MAX = 512
THUMBNAIL_VERSION = 't2'  # part of the ETag: bump when the renderer changes
_thumbnail_cache = collections.OrderedDict()
_thumbnail_lock = threading.Lock()
_EXIF_TRANSPOSE = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
                   5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}


def render_thumbnail(path):
    # Shrink first, convert second: decoding is unavoidable, but nothing full-size is copied or colour-converted.
    with Image.open(path) as source:
        orientation = source.getexif().get(0x0112, 1)
        box = THUMBNAIL_BOX[::-1] if orientation in (5, 6, 7, 8) else THUMBNAIL_BOX  # box applies after the EXIF turn
        source.draft('RGB', (box[0] * 2, box[1] * 2))  # JPEG decodes at reduced scale; no-op for other formats
        image = source
        if source.mode.startswith('I;16'):  # Pillow cannot resample these modes: sample down, then scale to 8 bits
            data = np.asarray(source)
            step = max(1, min(data.shape[0] // box[1], data.shape[1] // box[0]))
            image = Image.fromarray((np.clip(data[::step, ::step].astype(np.float32) / 65535.0, 0.0, 1.0) * 255).astype(np.uint8))
        image.thumbnail(box)
        if image.mode == 'I':
            image = Image.fromarray((to_float_rgb(image) * 255).astype(np.uint8))
        else:
            image = image.convert('RGB')
        if orientation in _EXIF_TRANSPOSE:
            image = image.transpose(_EXIF_TRANSPOSE[orientation])
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=82)
        return output.getvalue()


def cached_thumbnail(path, stat):
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _thumbnail_lock:
        if key in _thumbnail_cache:
            _thumbnail_cache.move_to_end(key)
            return _thumbnail_cache[key]
    body = render_thumbnail(path)
    with _thumbnail_lock:
        _thumbnail_cache[key] = body
        while len(_thumbnail_cache) > THUMBNAIL_CACHE_MAX:
            _thumbnail_cache.popitem(last=False)
    return body


@routes.get('/magik/4-references/thumbnail')
async def thumbnail(request):
    value = request.query.get('image', '')
    try:
        path = image_path(value)
        stat = path.stat()
    except (ValueError, OSError):
        return web.json_response({'error': 'Image unavailable.'}, status=404)
    # Files under magik_4_references/ are named after their content hash, so they can never change;
    # anything else (a user's own input file) is revalidated cheaply through the ETag.
    content_addressed = value.replace('\\', '/').startswith('magik_4_references/')
    headers = {'ETag': f'"{stat.st_mtime_ns:x}-{stat.st_size:x}-{THUMBNAIL_VERSION}"',
               'Cache-Control': 'public, max-age=31536000, immutable' if content_addressed else 'private, no-cache'}
    if request.headers.get('If-None-Match') == headers['ETag']:
        return web.Response(status=304, headers=headers)
    try:
        body = await asyncio.to_thread(cached_thumbnail, path, stat)
    except Image.DecompressionBombError:
        return web.json_response({'error': 'Image is too large to preview.'}, status=413)
    except (ValueError, OSError):
        return web.json_response({'error': 'Image unavailable.'}, status=404)
    return web.Response(body=body, content_type='image/jpeg', headers=headers)


MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2001  # images + manifest.json; enforced by both export and import


def export_presets(name=None):
    db = database()
    try:
        rows = db.execute('SELECT name, images, outputs, title, description, excluded, favorite FROM presets ORDER BY name').fetchall()
    finally:
        db.close()
    if name is not None:
        rows = [row for row in rows if row[0] == name]
        if not rows:
            raise ValueError('Preset no longer exists.')
    manifest = {'format': 'magik-four-references', 'version': 2, 'presets': []}
    output = io.BytesIO()
    included = {}
    total = 0
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for preset_name, encoded, outputs, title, description, excluded, favorite in rows:
            images = []
            for value in json.loads(encoded):
                if not value:
                    images.append('')
                    continue
                path = image_path(value)
                if value not in included:
                    total += path.stat().st_size
                    if total > MAX_EXPANDED:
                        raise ValueError('Export exceeds 256 MiB. Export individual presets instead.')
                    data = path.read_bytes()
                    key = 'images/' + hashlib.sha256(data).hexdigest() + path.suffix.lower()
                    if key not in included.values():
                        if len(archive.namelist()) >= MAX_ARCHIVE_ENTRIES - 1:  # keep room for manifest.json
                            raise ValueError(f'Export would exceed the {MAX_ARCHIVE_ENTRIES}-entry archive limit that import enforces. Export individual presets instead.')
                        archive.writestr(key, data)
                    included[value] = key
                images.append(included[value])
            manifest['presets'].append({'name': preset_name, 'images': images, 'outputs': json.loads(outputs), 'title': title, 'description': description, 'excluded': json.loads(excluded), 'favorite': favorite})
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
    if output.tell() > MAX_ARCHIVE:
        raise ValueError('Export exceeds 64 MiB. Export individual presets instead.')
    return output.getvalue()


def import_presets(payload):
    if len(payload) > MAX_ARCHIVE:
        raise ValueError('Archive exceeds 64 MiB.')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_ENTRIES or len({item.filename for item in members}) != len(members):
            raise ValueError('Archive contains too many entries or duplicate filenames.')
        if sum(item.file_size for item in members) > MAX_EXPANDED:
            raise ValueError('Expanded archive exceeds 256 MiB.')
        manifest_info = archive.getinfo('manifest.json')
        if manifest_info.file_size > 1024 * 1024:
            raise ValueError('Preset manifest is too large.')
        manifest = json.loads(archive.read(manifest_info))
        if manifest.get('format') != 'magik-four-references' or manifest.get('version') not in (1, 2):
            raise ValueError('Not a supported Magik reference archive.')
        presets = manifest.get('presets')
        if not isinstance(presets, list) or len(presets) > 500:
            raise ValueError('Archive requires a preset list with at most 500 entries.')
        staged = {}
        validated = []
        for preset in presets:
            name, images = preset.get('name'), preset.get('images')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
                raise ValueError('Archive contains an invalid preset name.')
            if not isinstance(images, list) or not 1 <= len(images) <= MAX_SLOTS:
                raise ValueError('Each preset requires between 1 and 128 slots.')
            outputs = output_choices(preset.get('outputs', [1, 2, 3, 4]), len(images))
            excluded = preset_excluded(preset.get('excluded', []), len(images))
            title = preset_title(preset.get('title', ''))
            description = preset.get('description', '')
            if not isinstance(description, str):
                raise ValueError('Description must be text.')
            favorite = preset.get('favorite', 0)  # absent in archives from older versions
            if not isinstance(favorite, int) or favorite < 0:
                raise ValueError('Preset favorite position must be a non-negative number.')
            paths = []
            for key in images:
                if key == '':
                    paths.append('')
                    continue
                if not isinstance(key, str) or not key.startswith('images/'):
                    raise ValueError('Archive contains an invalid image reference.')
                if key not in staged:
                    data = archive.read(key)
                    with Image.open(io.BytesIO(data)) as source:
                        source.verify()
                    # Use only a content-addressed local filename; never extract ZIP paths.
                    with Image.open(io.BytesIO(data)) as source:
                        suffix = image_suffix(source.format) or '.img'
                    relative = 'magik_4_references/imported/' + hashlib.sha256(data).hexdigest() + suffix
                    staged[key] = (relative, data)
                paths.append(staged[key][0])
            validated.append((name.strip(), paths, outputs, title, description, excluded, favorite))
    # Complete validation before writing files or touching the preset database.
    for relative, data in staged.values():
        destination = Path(folder_paths.get_input_directory()) / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            fd, temporary = tempfile.mkstemp(dir=destination.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    db = database()
    names, imported_favorites = [], []
    try:
        with db:
            for name, paths, outputs, title, description, excluded, favorite in validated:
                candidate, index = name, 2
                while db.execute('SELECT 1 FROM presets WHERE name = ?', (candidate,)).fetchone():
                    suffix = f' ({index})'
                    candidate = name[:120-len(suffix)] + suffix
                    index += 1
                db.execute('INSERT INTO presets (name, images, outputs, title, description, excluded) VALUES (?, ?, ?, ?, ?, ?)', (candidate, json.dumps(paths), json.dumps(outputs), title, description, json.dumps(excluded)))
                names.append(candidate)
                if favorite:
                    imported_favorites.append((favorite, candidate))
            if imported_favorites:
                base = db.execute('SELECT COALESCE(MAX(favorite), 0) FROM presets').fetchone()[0]
                for position, (_, imported) in enumerate(sorted(imported_favorites, key=lambda item: item[0]), base + 1):
                    db.execute('UPDATE presets SET favorite = ? WHERE name = ?', (position, imported))
    finally:
        db.close()
    return names


@routes.get('/magik/4-references/presets/export')
async def export_archive(request):
    try:
        data = await asyncio.to_thread(export_presets, request.query.get('name'))
        return web.Response(body=data, content_type='application/zip', headers={
            'Content-Disposition': 'attachment; filename="Magik_References_Presets.zip"'})
    except (ValueError, OSError) as exc:
        return web.json_response({'error': str(exc)}, status=400)


@routes.post('/magik/4-references/presets/import')
async def import_archive(request):
    try:
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != 'archive':
            raise ValueError('Choose a Magik reference ZIP archive.')
        payload = bytearray()
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_ARCHIVE:
                raise ValueError('Archive exceeds 64 MiB.')
        names = await asyncio.to_thread(import_presets, bytes(payload))
        return web.json_response({'names': names, 'count': len(names)})
    except (ValueError, TypeError, AttributeError, KeyError, OSError, zipfile.BadZipFile, RuntimeError, Image.DecompressionBombError) as exc:
        return web.json_response({'error': str(exc)}, status=400)


def allowed_server_roots():
    roots = [folder_paths.get_input_directory()]
    output = getattr(folder_paths, 'get_output_directory', None)
    if output:
        roots.append(output())
    roots += [p for p in os.environ.get('MAGIK_FOLDER_ROOTS', '').split(os.pathsep) if p.strip()]
    return [Path(r).expanduser().resolve() for r in roots]


def is_local_request(request):
    # A reverse proxy on this machine makes every client look local, so forwarded requests are never trusted as local.
    if any(h in request.headers for h in ('X-Forwarded-For', 'Forwarded', 'X-Real-IP')):
        return False
    remote = request.remote or ''
    return remote == '::1' or remote.startswith('127.') or remote.startswith('::ffff:127.')


def openable_extensions():
    # Only formats Pillow can read: PDF/PS are save-only and EPS needs Ghostscript.
    return {ext for ext, fmt in Image.registered_extensions().items() if fmt in Image.OPEN and fmt != 'EPS'}


def load_server_folder(value, limit=MAX_SLOTS, unrestricted=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Enter the folder path on the ComfyUI server.')
    if type(limit) is not int or not 1 <= limit <= MAX_SLOTS:
        raise ValueError('Folder capacity must be between 1 and 128.')
    root = Path(value.strip()).expanduser().resolve()
    # Checked before any existence test, so a remote client cannot probe which paths exist.
    if not unrestricted and not any(root == allowed or root.is_relative_to(allowed) for allowed in allowed_server_roots()):
        raise ValueError('From a remote browser only folders inside ComfyUI\u2019s input or output directory (or MAGIK_FOLDER_ROOTS) can be loaded. Use \u201cThis computer\u201d to upload a folder from your own machine.')
    if not root.is_dir():
        raise ValueError('Folder does not exist or is not accessible to ComfyUI.')
    extensions = openable_extensions()
    candidates = []
    for directory, _subdirs, names in os.walk(root, followlinks=False):  # never descends into symlinked folders
        for file_name in names:
            candidate = Path(directory) / file_name
            if not candidate.is_symlink() and candidate.suffix.lower() in extensions:
                candidates.append(candidate)
    def natural(path):
        return [(1, int(part)) if part.isdigit() else (0, part.casefold())
                for part in re.split(r'(\d+)', str(path.relative_to(root)))]
    candidates.sort(key=natural)
    images, errors = [], []
    attempted = 0
    for path in candidates:
        if len(images) >= limit:
            break
        attempted += 1
        try:
            with Image.open(path) as source:
                source.verify()
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            relative = 'magik_4_references/folders/' + digest.hexdigest() + path.suffix.lower()
            destination = Path(folder_paths.get_input_directory()) / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                fd, temporary = tempfile.mkstemp(dir=destination.parent)
                os.close(fd)
                try:
                    shutil.copyfile(path, temporary)
                    os.replace(temporary, destination)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            images.append(relative)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            errors.append(f'{path.name}: {exc}')
    return {'images': images, 'failed': len(errors), 'errors': errors[:3], 'skipped': len(candidates) - attempted}


@routes.post('/magik/4-references/folder')
async def folder_import(request):
    try:
        data = await request.json()
        unrestricted = is_local_request(request) or os.environ.get('MAGIK_ALLOW_ANY_SERVER_FOLDER', '').lower() in ('1', 'true', 'yes')
        result = await asyncio.to_thread(load_server_folder, data.get('path'), data.get('limit', MAX_SLOTS), unrestricted)
        return web.json_response(result)
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        return web.json_response({'error': str(exc)}, status=400)


MAX_IMAGE_UPLOAD = 64 * 1024 * 1024


def store_uploaded_image(payload, subfolder='magik_4_references/uploads'):
    if not payload:
        raise ValueError('The uploaded image is empty.')
    if len(payload) > MAX_IMAGE_UPLOAD:
        raise ValueError('Image exceeds the 64 MiB upload limit.')
    # Verify bytes before creating persistent files. The client filename is never
    # used as a filesystem path; actual image format determines the extension.
    with Image.open(io.BytesIO(payload)) as image:
        image_format = image.format
        image.verify()
    suffix = image_suffix(image_format)
    if suffix is None:
        raise ValueError('Unsupported image format.')
    destination_dir = Path(folder_paths.get_input_directory()) / subfolder
    # A fresh installation must work even when neither directory exists yet.
    destination_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(payload).hexdigest() + suffix
    destination = destination_dir / name
    if not destination.is_file():
        fd, temporary = tempfile.mkstemp(dir=destination_dir, suffix='.upload')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    else:
        try:
            os.utime(destination, None)  # reused: refresh its age so retention does not remove it
        except OSError:
            pass
    return {'name': name, 'subfolder': subfolder, 'type': 'input'}


@routes.post('/magik/4-references/upload')
async def upload_reference(request):
    try:
        reader = await request.multipart()
        field = await reader.next()
        while field is not None and field.name != 'image':
            await field.release()
            field = await reader.next()
        if field is None:
            raise ValueError('No image file was included in the upload.')
        payload = bytearray()
        while True:
            chunk = await field.read_chunk(size=1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_IMAGE_UPLOAD:
                return web.json_response({'error': 'Image exceeds the 64 MiB upload limit.'}, status=413)
        result = await asyncio.to_thread(store_uploaded_image, bytes(payload))
        return web.json_response(result)
    except (ValueError, TypeError, Image.DecompressionBombError, Image.UnidentifiedImageError) as exc:
        return web.json_response({'error': f'Could not read the image: {exc}'}, status=400)
    except OSError as exc:
        return web.json_response({'error': f'Could not save the reference image in the ComfyUI input directory: {exc}'}, status=500)


class Magik6ReferencesImages(Magik4ReferencesImages):
    PORT_COUNT = 6
    RETURN_TYPES = ('IMAGE',) * 6 + ('STRING', 'STRING')
    RETURN_NAMES = tuple(f'Image {i}' for i in range(1, 7)) + ('description', 'Name')
    DESCRIPTION = 'Load up to 128 reference images and choose six outputs. Each of the six IMAGE inputs overrides its matching output.'


class Magik8ReferencesImages(Magik4ReferencesImages):
    PORT_COUNT = 8
    RETURN_TYPES = ('IMAGE',) * 8 + ('STRING', 'STRING')
    RETURN_NAMES = tuple(f'Image {i}' for i in range(1, 9)) + ('description', 'Name')
    DESCRIPTION = 'Load up to 128 reference images and choose eight outputs. Each IMAGE input overrides its matching output.'


class Magik9ReferencesImages(Magik4ReferencesImages):
    PORT_COUNT = 9
    RETURN_TYPES = ('IMAGE',) * 9 + ('STRING', 'STRING')
    RETURN_NAMES = tuple(f'Image {i}' for i in range(1, 10)) + ('description', 'Name')
    DESCRIPTION = 'Load up to 128 reference images and choose nine outputs. Each IMAGE input overrides its matching output.'
