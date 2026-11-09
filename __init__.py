import asyncio
import io
import os
import tempfile
import zipfile
import re
import shutil
import hashlib
import json
import sqlite3
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


def database():
    root = Path(folder_paths.get_user_directory()) / 'magik_4_references_images'
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'presets.sqlite3', timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS presets (name TEXT PRIMARY KEY, images TEXT NOT NULL)')
    if 'outputs' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
        try:
            db.execute("ALTER TABLE presets ADD COLUMN outputs TEXT NOT NULL DEFAULT '[1,2,3,4]'")
        except sqlite3.OperationalError:
            if 'outputs' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
                raise
    if 'title' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
        try:
            db.execute("ALTER TABLE presets ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            if 'title' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
                raise
    if 'description' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
        try:
            db.execute("ALTER TABLE presets ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            if 'description' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
                raise
    if 'excluded' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
        try:
            db.execute("ALTER TABLE presets ADD COLUMN excluded TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            if 'excluded' not in {row[1] for row in db.execute('PRAGMA table_info(presets)')}:
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
                         **{f'output_{i}': ('INT', {'default': i, 'min': 0, 'max': MAX_SLOTS}) for i in range(1, cls.PORT_COUNT + 1)}, 'title': ('STRING', {'default': ''}),
                         'description': ('STRING', {'default': '', 'dynamicPrompts': False}),
                         'pinned_outputs': ('STRING', {'default': '[]', 'dynamicPrompts': False})},
            'optional': {f'image_{i}': ('IMAGE',) for i in range(1, cls.PORT_COUNT + 1)},
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        try:
            values = references(kwargs, cls.PORT_COUNT)
            choices = output_choices([kwargs.get(f'output_{i}', i) for i in range(1, cls.PORT_COUNT + 1)], len(values), cls.PORT_COUNT)
            pins = pinned_references(kwargs, cls.PORT_COUNT)
            for output, selected in enumerate(choices, 1):
                reference = pins[output - 1] if pins[output - 1] is not None else values[selected - 1] if 0 < selected <= len(values) else ''
                if kwargs.get(f'image_{output}') is None and reference:
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
            path = image_path(value)
            digest.update(str(path).encode())
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
        return digest.hexdigest()

    def load(self, **kwargs):
        values = references(kwargs, self.PORT_COUNT)
        choices = output_choices([kwargs.get(f'output_{i}', i) for i in range(1, self.PORT_COUNT + 1)], len(values), self.PORT_COUNT)
        pins = pinned_references(kwargs, self.PORT_COUNT)
        result, input_captures, output_paths = [], [], []
        decoded = {}
        for output, selected in enumerate(choices, 1):
            connected = kwargs.get(f'image_{output}')
            if connected is not None:
                if connected.ndim != 4 or connected.shape[0] < 1:
                    raise ValueError(f'Input {output}: expected an IMAGE tensor with at least one image.')
                tensor = connected[:1]
                pixels = np.clip(tensor[0].detach().cpu().numpy() * 255, 0, 255).astype(np.uint8)
                encoded = io.BytesIO()
                Image.fromarray(pixels).save(encoded, format='PNG')
                stored = store_uploaded_image(encoded.getvalue())
                path = stored['subfolder'] + '/' + stored['name']
                input_captures.append(path)
                output_paths.append(path)
                result.append(tensor)
                continue
            input_captures.append('')
            reference = pins[output - 1] if pins[output - 1] is not None else values[selected - 1] if 0 < selected <= len(values) else ''
            output_paths.append(reference)
            if not reference:
                result.append(None)
                continue
            if reference not in decoded:
                with Image.open(image_path(reference)) as source:
                    source.seek(0)
                    image = ImageOps.exif_transpose(source)
                    if image.mode == 'I':
                        image = image.point(lambda p: p / 255)
                    array = np.array(image.convert('RGB'), dtype=np.float32) / 255.0
                    decoded[reference] = torch.from_numpy(array).unsqueeze(0)
            result.append(decoded[reference])
        return {'ui': {'magik_references': values, 'magik_inputs': input_captures,
                       'magik_outputs': output_paths},
                'result': tuple(result) + (kwargs.get('description', ''), kwargs.get('title', ''))}


routes = PromptServer.instance.routes


@routes.get('/magik/4-references/presets')
async def list_presets(request):
    query = request.query.get('q', '').casefold()
    db = database()
    try:
        rows = db.execute('SELECT name, images, outputs, title, description, excluded FROM presets ORDER BY name COLLATE NOCASE').fetchall()
        return web.json_response({'presets': [{'name': name, 'images': json.loads(images), 'outputs': json.loads(outputs), 'title': title, 'description': description, 'excluded': json.loads(excluded)}
                                             for name, images, outputs, title, description, excluded in rows if query in name.casefold()]})
    finally:
        db.close()


@routes.post('/magik/4-references/presets')
async def save_preset(request):
    try:
        data = await request.json()
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
        db = database()
        try:
            with db:
                if data.get('overwrite') is True:
                    db.execute('INSERT OR REPLACE INTO presets (name, images, outputs, title, description, excluded) VALUES (?, ?, ?, ?, ?, ?)', (name.strip(), json.dumps(images), json.dumps(outputs), title, description, json.dumps(excluded)))
                else:
                    db.execute('INSERT INTO presets (name, images, outputs, title, description, excluded) VALUES (?, ?, ?, ?, ?, ?)', (name.strip(), json.dumps(images), json.dumps(outputs), title, description, json.dumps(excluded)))
        finally:
            db.close()
        return web.json_response({'name': name.strip()})
    except sqlite3.IntegrityError:
        return web.json_response({'error': 'A preset with this name already exists.'}, status=409)
    except (ValueError, TypeError, AttributeError) as exc:
        return web.json_response({'error': str(exc)}, status=400)


@routes.post('/magik/4-references/presets/manage')
async def manage_preset(request):
    db = database()
    try:
        data = await request.json()
        name = data.get('name')
        if not isinstance(name, str):
            raise ValueError('Select a preset first.')
        with db:
            if data.get('action') == 'delete':
                cursor = db.execute('DELETE FROM presets WHERE name = ?', (name,))
            elif data.get('action') == 'rename':
                new_name = data.get('new_name')
                if not isinstance(new_name, str) or not 1 <= len(new_name.strip()) <= 120:
                    raise ValueError('Preset name must contain 1–120 characters.')
                cursor = db.execute('UPDATE presets SET name = ? WHERE name = ?', (new_name.strip(), name))
            else:
                raise ValueError('Unknown preset operation.')
            if cursor.rowcount == 0:
                return web.json_response({'error': 'Preset no longer exists.'}, status=404)
        return web.json_response({'ok': True})
    except sqlite3.IntegrityError:
        return web.json_response({'error': 'A preset with this name already exists.'}, status=409)
    except (ValueError, TypeError, AttributeError) as exc:
        return web.json_response({'error': str(exc)}, status=400)
    finally:
        db.close()


@routes.get('/magik/4-references/thumbnail')
async def thumbnail(request):
    def render():
        path = image_path(request.query.get('image', ''))
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((320, 240))
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=82)
            return output.getvalue()
    try:
        return web.Response(body=await asyncio.to_thread(render), content_type='image/jpeg')
    except (ValueError, OSError):
        return web.json_response({'error': 'Image unavailable.'}, status=404)


MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024


def export_presets(name=None):
    db = database()
    try:
        rows = db.execute('SELECT name, images, outputs, title, description, excluded FROM presets ORDER BY name').fetchall()
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
        for preset_name, encoded, outputs, title, description, excluded in rows:
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
                        archive.writestr(key, data)
                    included[value] = key
                images.append(included[value])
            manifest['presets'].append({'name': preset_name, 'images': images, 'outputs': json.loads(outputs), 'title': title, 'description': description, 'excluded': json.loads(excluded)})
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
    if output.tell() > MAX_ARCHIVE:
        raise ValueError('Export exceeds 64 MiB. Export individual presets instead.')
    return output.getvalue()


def import_presets(payload):
    if len(payload) > MAX_ARCHIVE:
        raise ValueError('Archive exceeds 64 MiB.')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > 2001 or len({item.filename for item in members}) != len(members):
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
                        extension = Image.registered_extensions()
                        suffix = next((ext for ext, fmt in extension.items() if fmt == source.format), '.img')
                    relative = 'magik_4_references/imported/' + hashlib.sha256(data).hexdigest() + suffix
                    staged[key] = (relative, data)
                paths.append(staged[key][0])
            validated.append((name.strip(), paths, outputs, title, description, excluded))
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
    names = []
    try:
        with db:
            for name, paths, outputs, title, description, excluded in validated:
                candidate, index = name, 2
                while db.execute('SELECT 1 FROM presets WHERE name = ?', (candidate,)).fetchone():
                    suffix = f' ({index})'
                    candidate = name[:120-len(suffix)] + suffix
                    index += 1
                db.execute('INSERT INTO presets (name, images, outputs, title, description, excluded) VALUES (?, ?, ?, ?, ?, ?)', (candidate, json.dumps(paths), json.dumps(outputs), title, description, json.dumps(excluded)))
                names.append(candidate)
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


def load_server_folder(value, limit=MAX_SLOTS):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Enter the folder path on the ComfyUI server.')
    if type(limit) is not int or not 1 <= limit <= MAX_SLOTS:
        raise ValueError('Folder capacity must be between 1 and 128.')
    root = Path(value.strip()).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Folder does not exist or is not accessible to ComfyUI.')
    extensions = set(Image.registered_extensions())
    candidates = [p for p in root.rglob('*') if not p.is_symlink() and p.is_file() and p.suffix.lower() in extensions]
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
        result = await asyncio.to_thread(load_server_folder, data.get('path'), data.get('limit', MAX_SLOTS))
        return web.json_response(result)
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        return web.json_response({'error': str(exc)}, status=400)


MAX_IMAGE_UPLOAD = 64 * 1024 * 1024


def store_uploaded_image(payload):
    if not payload:
        raise ValueError('The uploaded image is empty.')
    if len(payload) > MAX_IMAGE_UPLOAD:
        raise ValueError('Image exceeds the 64 MiB upload limit.')
    # Verify bytes before creating persistent files. The client filename is never
    # used as a filesystem path; actual image format determines the extension.
    with Image.open(io.BytesIO(payload)) as image:
        image_format = image.format
        image.verify()
    suffix = { 'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif',
               'BMP': '.bmp', 'TIFF': '.tiff', 'AVIF': '.avif', 'ICO': '.ico' }.get(image_format)
    if suffix is None:
        suffix = next((ext for ext, fmt in Image.registered_extensions().items() if fmt == image_format), None)
    if suffix is None:
        raise ValueError('Unsupported image format.')
    subfolder = 'magik_4_references/uploads'
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


NODE_CLASS_MAPPINGS = {'Magik4ReferencesImages': Magik4ReferencesImages,
                       'Magik6ReferencesImages': Magik6ReferencesImages,
                       'Magik8ReferencesImages': Magik8ReferencesImages,
                       'Magik9ReferencesImages': Magik9ReferencesImages}
NODE_DISPLAY_NAME_MAPPINGS = {'Magik4ReferencesImages': 'Magik 4 References Images',
                              'Magik6ReferencesImages': 'Magik 6 References Images',
                              'Magik8ReferencesImages': 'Magik 8 References Images',
                              'Magik9ReferencesImages': 'Magik 9 References Images'}
WEB_DIRECTORY = './web'
