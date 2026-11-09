# Magik Reference Images: 4- and 6-port nodes

Category: **Magik/IO**. Both nodes are included in this one package:

- **Magik 4 References Images** — four IMAGE inputs and four separate IMAGE outputs plus a description STRING.
- **Magik 6 References Images** — six IMAGE inputs and six separate IMAGE outputs plus a description STRING.

They share the same implementation, image collection features and preset database. Each supports up to 128 loaded images. The instructions below describe the four-port variant; the six-port variant applies them to six slots as detailed at the end.

## Install/update
Extract `Magik_4_References_Images` into `ComfyUI/custom_nodes/`, replacing the old folder. **Restart ComfyUI**, then hard-refresh the browser with Ctrl+Shift+R. Old file presets remain compatible. Legacy input sockets beyond image_4 are removed when the node is restored.

## Outputs and direct inputs
- The top preview is a full-width horizontal row of four outputs. A new node defaults to collection images 1 / 2 / 3 / 4.
- Click an output preview to activate it (blue outline), then click a loaded picture to assign it. The selected source gets a blue border; other assigned cards get gold borders.
- There are exactly four optional IMAGE inputs. **image_1 → Output 1**, **image_2 → Output 2**, **image_3 → Output 3**, **image_4 → Output 4**. A connected input takes priority over that output's file selection, including an Empty selection. Its first batch image is used without resizing.
- Connected sources are independent of the file collection. Uploading, deleting, swapping, loading folders or loading presets never moves/disconnects them. Clicking a loaded image while the active output is connected explains that the input must be disconnected first.
- Connected previews appear after execution; file previews follow selections immediately. The node can execute without outgoing links.
- **Clear active slot** disconnects that output's input and sets its file selection to Empty. **Reset outputs** restores file selections 1 / 2 / 3 / 4, keeping direct inputs connected.
- Empty outputs return None. Leave them unconnected when downstream nodes require IMAGE.
- Double-click a source or output picture for the large viewer. Escape closes it. Enter/Space can activate an output or assign a focused source image.

## Image collection
- Cards are arranged **four per row** with square previews that preserve the full image without cropping.
- The **+ tile after the final card** adds one loaded-image card, up to 128. It never adds an IMAGE connection socket. The tile is removed at 128 cards and returns when a card is deleted.
- **Choose image…**, or drop an external image file onto a card, to upload it.
- **Clear** empties a card. Cards 5 onward also have a **🗑** delete icon; cards 1–4 cannot be deleted. Source files stay on disk.
- Deletion shifts later files left. File assignments referring to a deleted card become Empty; later assignments shift to preserve their source. Direct input connections remain unchanged.
- Drag a card/image onto another card in the same node to swap their file selections. Connections remain untouched. Output file assignments remain attached to slot numbers.
- Uploaded files become RGB outputs with EXIF orientation applied and their original dimensions. Animated files use their first frame. Only selected file images are decoded into output tensors. Connected tensors preserve their values/channels.

## Load Folder
Choose **Append** or **Replace**, and a folder location, then click **Load Folder**.

- **This computer** uses a native browser directory picker and uploads image files, including subfolders.
- **ComfyUI server** shows a folder path field. Enter a path on the machine running ComfyUI; valid images are verified and copied into the input directory. Symlink files are skipped.
- Files use natural relative filename ordering (2 before 10). The total collection is capped at 128.
- **Append** keeps files and adds after the last occupied file slot. **Replace** clears file selections after staging successful uploads and defaults file outputs to the first four new images. Direct IMAGE inputs are preserved in both modes.
- Cancelling the picker, having no readable images, or having every upload fail leaves the collection unchanged. Progress/errors report failed and skipped files.
- The dedicated upload handler creates its destination recursively, validates image bytes, writes atomically and reuses identical uploads. Per-image upload limit: 64 MiB. Uploaded copies remain after collection replacement.

## Presets
- Enter a name and click **Save** to save the file collection and output assignments. Existing names ask before overwrite.
- Connected outputs are saved using snapshots from their latest execution. Run first if no capture exists. Snapshots are appended to the saved collection and selected for their matching outputs; if the collection is full and a new snapshot is needed, free a card before saving. PNG snapshots use 8-bit pixels; live outputs retain their original tensors.
- Preset thumbnails are hidden by default. **Show preset previews / Hide preset previews** toggles a panel with width-scaled 2×2 previews sampled randomly from each preset’s nonempty image pool. Search, Load, Save, Rename and Delete remain available while hidden.
- Select a preset and click **Load**, or double-click its preview. This restores files/assignments and preserves direct IMAGE inputs, which continue to override matching outputs. Disconnect them to use the restored file choices.
- To rename, select a preset, enter its new name, and click Rename. Conflicting names are reported. Delete removes the preset after confirmation and retains all image files.
- Refresh retrieves presets saved by another browser/node.

## Export/import
**Export selected** or **Export all** downloads a portable ZIP containing saved presets and their images. Save pending changes before exporting. **Import ZIP…** restores them; existing names are preserved and duplicates receive numbered suffixes. Empty slots and output assignments are retained. Old version-1 archives remain supported.

Archive limits: 64 MiB compressed, 256 MiB expanded, 500 presets / 2001 ZIP entries. Export individual presets for larger collections. Missing image files cause explicit export errors. Import validates images and never extracts ZIP member paths directly.

## Storage, sizing and validation
Presets live in the configured user directory under `magik_4_references_images/presets.sqlite3`. Input images/snapshots live under `input/magik_4_references/`. Back up both. Workflows retain file choices, assignments and the four graph connections.

The panel measures its natural content and grows/shrinks the node height accordingly, including when preset previews are toggled. Manual node width changes are preserved; previews scale with width. No fixed-height collection/gallery scrolling area is imposed.

Uses ComfyUI's existing Pillow, NumPy, Torch and aiohttp dependencies. No additional packages required.

Checks cover direct input routing independent of file selections, four sockets with 128 cards, trailing add-tile order, swaps/deletion/folder loading preserving connections, connected preset snapshots, output selection and dynamic sizing. Real aiohttp HTTP WebP upload tests cover missing destination directories, duplicate reuse and invalid/empty uploads. Filesystem folder loading, presets, archives and legacy database migration are checked too. Torch/browser/ComfyUI components are mocked where unavailable; full live ComfyUI integration remains unverified.

## Random previews and output selection
Preset thumbnail panels sample up to four distinct, nonempty image files from each preset's entire pool, regardless of its saved output assignments. The sample stays stable while selecting presets, and is resampled when opening the panel again or refreshing the preset list. A preset with fewer than four unique files has empty preview cells for the remainder. This changes thumbnails only; loading a preset still restores its saved output assignments.

**Randomize** selects up to four distinct nonempty files from the current loaded-image collection and assigns them to outputs 1–4. Remaining outputs are set to Empty when fewer than four unique files are available. Empty collections show a load-first message. Connected inputs remain connected and continue to override their matching outputs. The live output previews update immediately for file selections.

The + add-card tile is absent at 128 cards, not merely disabled. Deleting an extra card makes it reappear at the end of the collection.

Checks include random sampling from beyond the first four preset images, stable preview samples during selection, distinct output assignments, preserving connected inputs, and add-tile removal/restoration at the capacity boundary. Browser/ComfyUI components are mocked; live integration remains unverified.

## Collection title
A full-width editable title row appears above the output previews, centered with 66 px text. Type directly into it (up to 512 characters). Titles are retained in workflow files and saved/loaded with presets, independently of the preset name. Exported/imported archives include titles. Existing presets and older archives default to an empty title without losing images or assignments.

This update adds a Python input and a preset database column, so restart ComfyUI after installing it and hard-refresh the browser. Checks cover title editing, preset save/load, workflow restoration, archive roundtrips, migration from old databases and invalid-title rejection. Full live ComfyUI integration remains unverified.

## Save-row placement and six-port variant
The **description** text box sits directly below the image cards, followed by the **preset name / Save** row, before preset search and preview controls.

**Magik 6 References Images** is a separate registered node under Magik/IO with fixed six-port topology, backed by the same Python and JavaScript implementation as the four-port node. No second installation folder is needed. Fixed port counts avoid renumbering/removing graph outputs in existing workflows.

For the six-port node:
- Six optional IMAGE inputs feed their matching six outputs directly.
- The top preview is one horizontal row of six cells; output selection and live previews work the same way.
- The first six collection cards are protected from deletion. Extra cards start at Image 7, and the collection still supports 128 total images with four cards per row.
- Reset uses images 1–6; Randomize chooses up to six unique loaded images. Preset preview panels sample up to six images in a 3×2 grid.
- Titles, image pools, output assignments and captured connected images save into the shared preset database and portable archives.
- A four-output preset can load into the six-port node: the first four assignments are restored and extra outputs use subsequent images if available, otherwise Empty. A six-output preset loaded into the four-port node uses its first four assignments and retains the whole pool.
- Direct connections remain connected when loading any preset and keep priority over matching file assignments.

Keep the single `Magik_4_References_Images` custom-node folder and replace its contents when updating. Restart ComfyUI and hard-refresh the browser to register the six-port node. Checks passed for both schemas, direct Input 6 routing, six output previews/selections, six-choice preset/archive roundtrips, cross-loading four-port presets and save-row position. Full live ComfyUI testing remains unverified.

## Title, alignment, output labels and Undo
Both node variants use a centered 66 px title (three times the original font size). Image-card grid rows are equal-height, and the trailing + tile stretches to the full card height, including when it is alone on a new row.

Each output caption is below its square preview instead of covering the picture. It identifies the loaded-image assignment or direct input for that output.

**Undo**, immediately before Clear active slot, restores previous output selections for image assignments, Randomize, Reset outputs and Clear active slot. Up to 50 selection changes are kept in this node's current session; no-op selections do not add entries. The previous active slot is restored too. If Clear active slot disconnected an input, Undo reconnects its original source when that source still exists and the input has not been reconnected elsewhere.

Undo tracks source file identities when collection indices change. A file removed from the collection cannot be brought back by this selection-only undo. Replacing the collection, loading a preset or restoring a workflow clears selection history. Undo does not change titles, presets or the collection itself.

Frontend checks passed for selection undo, clear/connection restoration, six-output randomization undo, button ordering, centered title sizing and captions positioned after their preview elements. Full live ComfyUI visual testing remains unverified.

## Description widget and STRING output
Both variants have a multiline text widget named **description**, directly below the loaded-image cards and above the preset Save row.  Its content is returned verbatim through the **description** STRING output, appended after all IMAGE outputs (socket 5 on the four-image node, socket 7 on the six-image node). Existing image output indices remain unchanged. Newlines and literal prompt braces are preserved.

Description text is retained in workflows, preset save/load and ZIP export/import. Existing presets and older archives default to an empty description. The textarea can be resized vertically; the panel/node height follows it.

The editable collection **title** is also returned verbatim through a second STRING output named **Name**, immediately after the description output. It is socket 6 on the four-image node, socket 8 on the six-image node, socket 10 on the eight-image node and socket 11 on the nine-image node. Existing IMAGE and description output positions are unchanged.

Restart ComfyUI after replacing the package, then hard-refresh the browser to pick up the Python input/output schema and new database column. Checks passed for both STRING outputs, multiline text passthrough, preset/archive persistence, UI save/load, old workflow output migration without duplicate sockets, and the description/Save row order. Full live ComfyUI testing remains unverified.

## Pin output selections
Each output preview on both variants has a **📌** toggle in its upper-right corner. Its highlighted state marks a pinned output. Pins retain the selected file by identity, rather than only its card number; file swaps, deletions, folder replacement and preset loading cannot silently replace that pinned file. Empty outputs can be pinned too.

Pinned slots are skipped by click-to-assign, Randomize, Reset outputs, Clear active slot and Undo. Randomize also excludes pinned files from the remaining random sample. Unpin a slot to edit its selection again. Direct IMAGE inputs keep their priority and remain live; a selection pin does not freeze upstream tensor generation.

Pins are saved in the workflow through the hidden `pinned_outputs` input. Saving a preset includes the effective pinned images and selections, even if a pinned file is no longer in the visible pool; adding such a file to a full saved collection requires freeing a slot. Pin on/off states remain workflow-local. All files still need to exist in the input directory.

Restart ComfyUI after installing this update, then hard-refresh the browser. Checks passed for pin/unpin, unchanged selections during randomize/reset/clear/assignment/undo, workflow restoration after pool changes, pinned empty outputs, sixth-output pins, execution routing and direct-input priority. Browser/ComfyUI components remain mocked where unavailable.

## Renamed node, viewer navigation and restored card toggle
The four-port node displays as **Magik 4 References Images**, with the six-port variant named **Magik 6 References Images**. Existing internal class IDs are retained for workflow compatibility. The shared frontend also recognizes the renamed `MagikReferencesImages` definition and determines the image-port count from its IMAGE output metadata when available.

The full-size viewer has **❮ / ❯** buttons at the left/right sides. Click them or press Left/Right to browse nonempty collection images. Navigation wraps at either end, updates the image/caption/counter, and does not change output selections. A connected or pinned image outside the current collection is included as the opening image. Single-image collections disable navigation arrows. Close and Escape still dismiss the viewer.

**Hide cards / Show cards** is restored immediately above the picture grid, including the current card count. It collapses only the collection/add tile, preserving the output strip and other controls. Its workflow-persisted state and automatic node-height fitting are retained.

Frontend regression checks passed for renamed six-port metadata, card-toggle restoration, previous/next wrapping, keyboard navigation, skipped empty cards and viewer close. Full live ComfyUI visual testing remains unverified.

## Viewer zoom and pan
Use the mouse wheel over the full-size image to zoom from fit-to-view (100%) up to 1600%, anchored at the cursor. Drag with the left mouse button to pan; movement is limited to the image edges. Double-click the image to reset. Previous/next navigation resets the view for each image. These controls are shared by both node variants.

## Collection Undo and Redo
Undo and Redo now track the last 50 selection and collection edits: card additions, deletion, clearing, file uploads, swaps, and folder append/replacement. A new edit clears Redo. Pinned outputs remain protected; direct input connections are unaffected by collection restoration. Clear active slot can undo/redo its connection removal. History is local to the current session and clears on preset loading or workflow restoration. Source files are retained, including uploads removed by Undo. Title, description, pin toggles, and preset management are outside this history.

## Drag onto output previews
Drag a loaded image card onto an output preview to assign it directly. Drag an output preview onto another to swap their selections, including empty selections. Pinned and directly connected outputs cannot be changed or swapped; disconnect or unpin them first. Drops activate the target output and support Undo/Redo. Card-to-card dragging continues to swap collection images; output-to-card drops do not change the collection.

## Randomize on queue
Enable the Randomize on queue checkbox to sample unique nonempty pool images for each browser queue submission. It defaults off and is saved with the workflow, not presets. Pinned and connected slots are skipped by both automatic and manual randomization. Pinned files are excluded from the sample; insufficient images leave remaining free slots empty. Repetition between separate runs is possible. Selections update in the panel and queued workflow metadata and can be undone/redone; Undo does not modify jobs already queued. Ordinary workflow saves and exports do not randomize. Direct API submissions outside the browser are unchanged.

## Avoid repeats
Enable Avoid repeats to use all eligible pool images before reusing them. Manual Randomize and Randomize on queue share the same cycle. A run spanning a cycle boundary stays unique within its outputs. Duplicate pool paths count as one image, pinned paths are excluded, and connected slots are skipped. Changes to the eligible image set restart the cycle. Undo/Redo restore cycle progress with selections. The toggle is saved with the workflow and defaults off; cycle progress is session-local and resets on workflow/preset loading or toggling the option. Click-to-assign does not consume a random draw.

## Exclude images from randomization
Each card has a dice toggle: 🎲 includes the image, dimmed 🎲✕ excludes it from manual and queued randomization. Excluded images remain available for click/drag assignment and presets. Empty cards disable the toggle. Exclusions follow file paths through card swaps (duplicate paths share the setting), support Undo/Redo, and persist in workflows, presets and exported preset ZIPs. Older presets default to no exclusions. Restart ComfyUI for the preset database migration and hard-refresh the browser after installing.

## 128-image capacity and reliability review
Both variants now support 128 collection cards, folder imports, presets and selection indices. Existing presets remain compatible. The frontend uses one capacity constant and clamps malformed/restored extra-card values; card thumbnails load lazily. Queued snapshots whose pool, pins or connections differ from the live node retain their original selections instead of receiving mismatched random indices. Late or superseded uploads cannot overwrite a card changed while uploading.

Backend and frontend regression checks cover the 128-card boundary, add-tile removal/reappearance, Undo/Redo, folder capacity, selecting Image 128, preset limits and stale queued snapshots. Live ComfyUI performance and browser behavior still require testing.

## Magik 8 References Images
The `Magik8ReferencesImages` node adds eight IMAGE inputs, eight independent IMAGE outputs, and two STRING outputs: description followed by Name (the collection title). Its output previews occupy two rows of four, and preset thumbnails also use a 2×4 grid. Input N overrides output N. The first eight cards are protected from deletion; up to 128 cards are supported. All collection controls, title/description, presets, pins, exclusions, randomization, queue randomization, avoid-repeat cycles, drag/drop, viewer and Undo/Redo share the existing implementation.

All three variants share presets. Four/six-output presets load into the eight-port node with remaining selections taken from available pool positions or left empty; eight-output presets load into smaller variants using their first four/six selections. Existing workflows retain their original node definitions. Install by replacing the same package folder, restart ComfyUI and hard-refresh the browser.

## Magik 9 References Images
The nine-port variant has nine IMAGE inputs, nine IMAGE outputs and two STRING outputs: description followed by Name (the collection title). Its output and preset previews use a 3×3 grid. It shares the 128-image pool, preset database and all collection, selection, pin, randomization, exclusion, viewer and history features. Its first nine cards cannot be deleted. All four variants accept shared presets with four, six, eight or nine selections.

The four- and six-port display names are now Magik 4 References Images and Magik 6 References Images. Their internal IDs remain unchanged for existing workflows. Restart ComfyUI and hard-refresh after installing.

## Panel mouse bounds
The DOM widget host clips painting and hit testing to its allocated rectangle. Empty host space passes pointer events through, while the visible inner panel keeps its interactive controls. The inner panel remains naturally sized for automatic height measurement. The hidden directory picker also ignores pointer events. This applies to every variant. JavaScript syntax and containment checks passed; live ComfyUI mouse testing remains necessary.
