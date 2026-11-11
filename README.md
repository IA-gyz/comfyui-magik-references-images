# Magik References Images

Category: **Magik/IO**. One package, four nodes that share one implementation, one image pool and one preset database.

| Node | IMAGE inputs → outputs | `description` socket | `Name` socket | Output preview layout | Preset preview grid | Protected cards |
|---|---|---|---|---|---|---|
| **Magik 4 References Images** | 4 → 4 | 5 | 6 | 1 row of 4 | 2 × 2 | 1–4 |
| **Magik 6 References Images** | 6 → 6 | 7 | 8 | 1 row of 6 | 3 × 2 | 1–6 |
| **Magik 8 References Images** | 8 → 8 | 9 | 10 | 2 rows of 4 | 4 × 2 | 1–8 |
| **Magik 9 References Images** | 9 → 9 | 10 | 11 | 3 × 3 | 3 × 3 | 1–9 |

Each node holds up to **128** loaded images. Input *N* feeds Output *N*. Every node also returns two STRING outputs after the images: **description** and **Name** (the collection title).

## Layout

The panel is grouped into sections, top to bottom: the **collection title**, a **status bar** (messages appear here, next to the outputs), **Outputs** (previews, the Undo / Redo / Clear / Reset / **Randomize** toolbar, and the two queue options), **Collection** (count, *Hide cards*, folder loading, the image cards), **Description**, and **Presets**.

- **Presets collapses** to a single line when you are not using it, and the node remembers whether it was open.
- Image cards and preset previews **flow to the node width**: about four cards per row at the default width, fewer when the node is narrow, more when it is wide. Toolbars wrap instead of overflowing.
- Buttons have three emphasis levels: **primary** (Randomize, Save), neutral, and **danger** (Delete). Keyboard focus is always visible, and the status bar is announced to screen readers.

## Install / update

```
ComfyUI/custom_nodes/Magik_4_References_Images/
├── __init__.py                    registration only
├── magik_references_images_.py    nodes, validation, HTTP routes, preset database
├── web/references.js              frontend extension
└── README.md
```

Replace the folder, **restart ComfyUI**, then hard-refresh the browser (Ctrl+Shift+R). Python changes need the restart; frontend-only changes need only the refresh. If the panel reports *"This Magik endpoint was not found"*, the Python module was not reloaded: restart ComfyUI.

Uses ComfyUI's existing Pillow, NumPy, Torch and aiohttp. No extra packages.

## Outputs and direct inputs

- The output preview shows what each output will deliver. A new node defaults to images 1, 2, 3 … in order.
- Click an output to make it active (blue outline), then click a loaded picture to assign it. The assigned source gets a blue border; other assigned cards get gold.
- **A connected IMAGE input always wins** over that output's file selection, including an Empty selection. Its first batch image is used without resizing and with its channels untouched.
- Connected sources are independent of the collection: uploading, deleting, swapping, folder loading and preset loading never move or disconnect them.
- Connected previews appear after the workflow runs; file previews follow selections immediately. The node executes even with nothing downstream.
- Below each output preview: its caption (which image or input it carries) and its **resolution** (`width × height px`).
- **Clear active slot** disconnects that output's input and sets its selection to Empty. **Reset outputs** restores 1, 2, 3 … and keeps connected inputs.
- **Empty outputs return `None`**, ComfyUI's normal "no value" for optional inputs. Don't wire an Empty output into a required IMAGE input.
- Two outputs that show the same image receive independent tensors, so editing one downstream cannot change the other.

## Image collection

- Cards show uncropped previews and flow to the node width (see [Layout](#layout)). The **+ Add image card** bar after the last card adds a card (it never adds a socket) and disappears at 128.
- **Choose image…** or drop an image file onto a card to upload it. **Clear** empties a card; cards past the protected ones also have **🗑**. Source files stay on disk.
- Deleting shifts later cards left and keeps assignments attached to the same *files*. Drag a card onto another card to swap them.
- Selected files become RGB tensors: EXIF orientation applied, original size kept, first frame only for animations. 16-bit grayscale is scaled linearly. Transparency is **not** composited (same as ComfyUI's Load Image node).

## Load Folder

Choose **Append** or **Replace**, then a location:

- **This computer** – native folder picker; image files (including subfolders) are uploaded.
- **ComfyUI server** – a folder path on the machine running ComfyUI; valid images are verified and copied into the input directory. Symlinked files and folders are skipped. See [Security](#security).

Files are ordered naturally (2 before 10) and capped at 128 in total. Append adds after the last occupied card; Replace clears the collection and sets outputs to the first new images. Direct inputs are kept in both modes. A cancelled picker or a folder with no readable images changes nothing; failures and skipped files are reported.

## Presets

- Type a name and click **Save** (existing names ask before overwriting). A preset stores the collection, output assignments, title, description and exclusions.
- Connected outputs are saved from their last execution's snapshot, so run the workflow first. Snapshots are appended to the saved pool and selected for their outputs; if the pool is full, free a card first.
- **◀ ▶** around the preset selector **select and load** the previous / next preset (wrapping at the ends). Load replaces the collection, so Save first if you have unsaved changes.
- **★ Favorites** is a curated, ordered strip above the preset controls for one-click switching. Press **☆** beside the preset selector to add the selected preset (it turns **★**; press again to remove it). **Click a favourite to load it** immediately, exactly like Load. **Drag** favourites to reorder them; a chip's own **★** removes it. The strip is not affected by the search box, is shared by all four nodes, and a favourite keeps its place when the preset is renamed, overwritten or re-saved. The preview gallery marks favourites with ★.
- **Load** (or double-click a preset preview) restores files and assignments; connected inputs keep overriding.
- **Rename** / **Delete** act on the selected preset (Delete asks first and keeps all image files). **Refresh** picks up presets saved elsewhere.
- **Show / Hide preset previews** toggles a panel of thumbnails sampled from each preset's whole pool. This affects previews only.
- Presets are shared by all four nodes: a preset with 4, 6, 8 or 9 selections loads into any of them (extra outputs take later images or Empty; surplus selections are dropped but the pool is kept).

## Export / import

**Export selected / Export all** downloads a ZIP of presets and their images; **Import ZIP…** restores it. Imported names that already exist get a numbered suffix. Favourite positions are included (the archive stays format version 2, so older installs can still read it): imported favourites are appended after your existing ones in their original order. Version-1 archives and archives without favourites still import.

Limits (the same for export and import): 64 MiB compressed, 256 MiB expanded, 500 presets, 2001 ZIP entries. An export that would exceed them fails up front with an explanation; export individual presets instead. ZIP member paths are never extracted directly.

## Randomization

- **Randomize** assigns distinct, non-empty pool images to the free outputs; with too few images the rest become Empty.
- **Randomize on queue** randomizes for every browser queue submission (saved with the workflow, default off). Selections are written into both the submitted prompt and the workflow metadata. If the queued prompt no longer matches the live node (pool, pins or wiring changed), it is left untouched. A wired input whose upstream node is muted or bypassed is not treated as a mismatch.
- **Avoid repeats** uses every eligible image before reusing any; manual and queue randomization share the cycle. Cycle progress is session-only.
- **🎲 / 🎲✕** on a card excludes that file from randomization (still assignable by hand). Exclusions follow file paths and are saved in workflows, presets and exports.
- Pinned outputs, connected outputs and excluded images are never touched or drawn.

## Pins

The **📌** on an output pins its *file*, not its card number: swaps, deletions, folder replacement and preset loading cannot replace it. Empty outputs can be pinned. Pinned outputs are skipped by assignment, Randomize, Reset, Clear and Undo. Pins live in the workflow (hidden `pinned_outputs` input). A pin on a connected output pins its last snapshot.

## Viewer

Double-click any source or output picture. **❮ / ❯** or Left / Right browse the non-empty collection (wrapping); the image outside the collection that you opened (a connected input or a pinned image) is included and captioned **Input N** or **Pinned image**. The caption also shows the image's resolution once it has loaded. Mouse wheel zooms from fit to 1600 % anchored at the cursor, drag pans, double-click resets, Escape closes.

## Undo / Redo and drag-and-drop

Undo and Redo cover the last 50 selection and collection edits (assignments, Randomize, Reset, Clear, additions, deletions, uploads, swaps, folder loads, and the disconnection done by *Clear active slot*). History is session-only and clears when a preset loads or a workflow is restored. Titles, descriptions, pins and preset management are not part of it.

Drag a card onto an output to assign it, or an output onto another output to swap them (not for pinned or connected outputs). Dropping activates the target output and is undoable.

## Title, description and the STRING outputs

The centred title row (up to 512 characters) is returned verbatim as **Name**; the multiline **description** box is returned verbatim as **description** (newlines and literal `{braces}` preserved). Both are saved in workflows, presets and exports. Older presets and archives default to empty.

## State kept across reloads

Besides widget values (pool, selections, pins, title, description) and the toggles, the node now remembers in the workflow: the active output, the selected preset and the preset-name field, whether the Presets section is open, whether preset previews are shown, the folder mode / location / path, and the last previews of connected inputs (while the input is still connected). Undo history and avoid-repeat progress are deliberately session-only.

## Storage, limits and configuration

| What | Where |
|---|---|
| Presets | `<ComfyUI user dir>/magik_4_references_images/presets.sqlite3` |
| Uploaded images | `input/magik_4_references/uploads/` |
| Folder-loaded images | `input/magik_4_references/folders/` |
| Imported images | `input/magik_4_references/imported/` |
| Connected-input snapshots | `input/magik_4_references/snapshots/` |

Back up the database and the first four folders. Uploaded, folder and imported files are named after their content hash and are never deleted by the node.

**Snapshots** are 8-bit PNG copies of connected images, written best-effort (a failure logs a warning and the run continues). Snapshots **not saved in any preset** are removed after 7 days; snapshots a workflow still uses (pins, pool) are refreshed every time it runs. Save a preset to keep one permanently. Snapshots written by older versions live in `uploads/` and are not pruned.

| Limit | Value |
|---|---|
| Images per node / preset | 128 |
| Upload size | 64 MiB per image |
| Title | 512 characters; preset name 1–120 |
| Archive | 64 MiB compressed · 256 MiB expanded · 500 presets · 2001 entries |

### Environment variables

| Variable | Effect |
|---|---|
| `MAGIK_SNAPSHOT_RETENTION_DAYS` | Days to keep unreferenced snapshots. Default `7`; `0` never deletes. |
| `MAGIK_FOLDER_ROOTS` | Extra server folders that *remote* browsers may load (separate several with `:` on Linux/macOS, `;` on Windows). |
| `MAGIK_ALLOW_ANY_SERVER_FOLDER` | `1` / `true` / `yes` lets every client load any server folder (the pre-hardening behaviour). |

### Security

The **ComfyUI server** folder option can read any image file the server can. Requests from the same machine (loopback) may use any folder. Requests from other machines are limited to ComfyUI's input and output directories plus `MAGIK_FOLDER_ROOTS`, and a request carrying a proxy header (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`) is always treated as remote. The allow-list is checked before the folder is touched, so a remote client cannot probe which paths exist. Over a LAN, use **This computer** to upload from your own machine.

## Compatibility and upgrading

- Class IDs `Magik4ReferencesImages`, `Magik6ReferencesImages`, `Magik8ReferencesImages` and `Magik9ReferencesImages` are unchanged; display names are *Magik N References Images*. The nodes use ComfyUI's classic (V1) node API.
- The saved widget order never changes, so older workflows load as before. `title`, `description` and `pinned_outputs` are optional inputs, so API-format workflows saved before they existed still validate.
- The preset database gains a `favorite` column automatically on first start; existing presets are untouched and start as non-favourites. Overwriting a preset now updates it in place, which is what lets it keep its favourite position.
- Restoring an old workflow adds any missing `description` / `Name` output and removes input sockets beyond the node's port count.
- A connected input overrides a missing selected file during validation, and a wired socket of the wrong type is reported clearly.
- The internal data widgets (references, selections, pins, title, description) are hidden with both the classic canvas method and the `hidden` flags newer frontends and Nodes 2.0 read.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "This Magik endpoint was not found" | ComfyUI was not restarted after updating the Python files. |
| "Reference image is missing or outside the input folder" | A selected file was deleted from `input/`; reselect it or connect an input to that output. |
| "From a remote browser only folders inside…" | See [Security](#security). |
| Preview says "Run workflow to preview" | Connected inputs are previewed only after a run. |
| "Export would exceed the 2001-entry archive limit" | Export presets individually. |

## HTTP endpoints (reference)

All under `/magik/4-references/`: `presets` (GET list, POST save), `presets/manage` (POST rename / delete / favorite / reorder_favorites), `presets/export` (GET), `presets/import` (POST), `thumbnail` (GET), `folder` (POST), `upload` (POST). Thumbnails are cached: files under `magik_4_references/` for a year (their names are content hashes), your own input files via ETag revalidation.

## Testing status

Automated checks cover the Python side (against real Pillow, NumPy and aiohttp, with stubs for Torch, `folder_paths` and the server) and the frontend (a simulated DOM with a stubbed ComfyUI). They include before/after comparisons for each fix. **A live ComfyUI session has not been tested.** Worth checking by eye after installing:

1. Nodes 2.0: none of the internal data fields should appear as editable widgets, and no stray socket dots should appear.
2. The panel sizes itself correctly (the node height follows the content).
3. Wire an input, click **Clear active slot**, then **Undo**: the input should reconnect.
4. Reload a workflow with a wired input: the active output, selected preset and connected previews return.
5. Queue with a muted upstream node and *Randomize on queue* on: it still randomizes.
6. Resize the node narrower and wider: cards, toolbar and the preset row should reflow without clipped buttons.
7. Favorites: star two presets, click a chip to load it, drag one chip onto another to reorder, reload the page and check the order stays.

## Recent changes

- **Redesigned UI:** sectioned layout with a readable title and a status bar, a toolbar with the hint on its own line and Undo before Redo, checkboxes beside their labels, a card grid that adapts to the node width, compact two-row card headers, a collapsible Presets section, primary / danger button styles, visible focus rings, and a viewer that shows the resolution.
- **Added:** **Favorites** (a curated, draggable one-click preset strip, shared by all nodes and included in ZIP exports), preset ◀ ▶ (load previous / next), per-output resolution, UI state kept across reloads, `MAGIK_*` configuration, clearer errors when the backend is stale.
- **Fixed:** 16-bit grayscale decoding; a connected image with one channel no longer aborts the run; wired inputs override missing files during validation; imported JPEGs stored as `.jpg`; missing `Name` output on old workflows; Undo after *Clear active slot* with newer frontends; randomize-on-queue with a muted upstream; viewer captions for connected/pinned images; shared tensors between outputs; export ZIPs that import would reject.
- **Performance:** thumbnails (shrink first, cached, ETag/304), SQLite work off the event loop, memoised panel parsing, snapshot retention.
- **Security:** remote server-folder loading restricted; symlinks not followed.
- **Cleanup:** removed unused payload keys, an unused array, class names with no node behind them and a duplicate CSS rule.
