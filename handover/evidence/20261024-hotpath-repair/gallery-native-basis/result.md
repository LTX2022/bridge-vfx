# H21 Render Gallery native basis

Version inspected: installed Houdini 21.0.631. Read-only local help/source and lstat; no host launch, Python HOM import, DB contents, or user galleries read. Source/member hashes are in sources.json and excerpts carry original line numbers.

## Established native semantics

- nodes.zip manager/lopnet.txt:77-80 identifies rendergallerysource as the LOP Network's render gallery database path. It states the value is unused until the gallery is opened within that network.
- ref.zip panes/rendergallery.txt:451-469 documents default raw `$HIP/galleries/$HIPNAME.$OS/rendergallery.db`; $HIP is scene directory, $HIPNAME scene name, $OS network name. Captured EXRs are saved in that same directory. Unsaved scenes can retain gallery data in memory; database and intermediate directories are created only on a snapshot.
- hom.zip hou/RenderGallery.txt:1-7 classifies the object as a UI PathBasedPaneTab, a render gallery pane.
- python3.11libs/husd/backgroundrenderer.py:3-16 obtains a model for a LOP network and updates its image path and metadata. Lines 22-29 expose background-render start/poll/stop extension methods; lines 34-49 create registered renderer instances. Thus a gallery is not merely an inert label: it has snapshot storage and background-render integrations.
- python3.11libs/houpythonportion/qt/_RenderGalleryModel.py:23-30 maps LopNode/LopNetwork to QT_SnapshotGalleryModel.modelForLOPNetwork. This Python wrapper does not establish whether a model already exists, whether gallery data is resident, or whether the C++ model can be used in a headless process. That implementation is not present in these inspected Python files.

## Exact historical evidence and current stat

The identified genuine node.create receipt (SHA256 90fb28d0def84bcbd34702fc82d81fe2b4d0a2b11c68c8662e0233b6154b1d1b) records public usd_network type Object/lopnet and an evaluated path ending galleries/untitled.usd_network/rendergallery.db. Channel evidence says expression=null, reference_path=null, keyframes=[], evaluated_available=true. It does NOT record rawValue/default status, so actual raw default cannot be inferred from this evaluated value or the help default.

Current lstat finds that exact DB, its -wal/-shm/-journal companions, parent network gallery directory and galleries directory absent; existing ancestors are recorded separately. This does not prove absence at the historical capture time, lack of in-memory gallery state, or absence of a future destination. No new SaveAs target was supplied for this diagnostic, so no new-path stat claim is made.

## Classification and admission recommendation

Native classification is a conditional gallery snapshot-storage locator, not a USD render setting and not universally harmless UI metadata. The docs support inactivity ONLY when the gallery has not been opened for that network. Once used, changing it can redirect gallery DB/EXR output or select different stored gallery input.

For a future private preparation policy, all of the following need evidence rather than a name allowlist:
1. Exact node type/version and exact installed parameter semantics; live raw value equals the documented factory default, with unchanged raw/channel/keyframe/reference facts and no custom or driven path.
2. Authoritative no-gallery-use state/provenance for the actual process/network: no opened pane/model, in-memory unsaved gallery, snapshot activity, or active background-render integration. headless=false is disqualifying for a headless-only policy, but headless=true by itself does not prove this state from these sources.
3. Both concrete old/new expansions are owned, contain no symlink/reparse component, and DB, sidecars, gallery directory and stored EXR assets are absent before and after preparation. Absence alone is insufficient because the help explicitly allows in-memory gallery data.
4. Complete actual per-frame USD/file/cache/reference inputs and effective render products/outputs remain equal, with no other field, expression or code consuming this locator. The historical record only proves the parameter has no outgoing channel driver; it does not prove no incoming consumers elsewhere.
5. Record this as an explicit preparation transition with both full evaluated contracts retained; the subsequent typed save still compares complete before/after contracts, with no field omissions.

Current blockers: actual raw/default status, no-gallery/model/in-memory-consumer evidence, complete reference/effective-output continuity, and new destination stat are not available in the supplied historical receipt. The local source inspection supplies semantics but cannot fill those runtime facts. Therefore this historical gallery drift is NOT independently cleared by this task. Keep it fail-closed unless the implementation can establish those conditions; do not label it allowed solely because it is rendergallerysource or its DB is currently missing.
