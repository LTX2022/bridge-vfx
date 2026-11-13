# Offline installation lifecycle

Use Python 3.11 or later from the extracted release. The installer requires an explicit target, uses bundled source without network access, and preserves unrelated native plug-in settings.

```sh
python scripts/install_runtime.py --self-test
python scripts/install_runtime.py --target /path/to/bridge-install --action install
python -I /path/to/bridge-install/run_runtime.py --probe
python -I /path/to/bridge-install/run_runtime.py --deployment-root
python scripts/install_runtime.py --target /path/to/bridge-install --action status
```

Each immutable generation contains `site` and a complete `deploy` source layout: four runtime packages, Houdini/Nuke plugins, bundled tools, controller-entry, and static native schema resources. `--probe` reports the imported module and SHA-256; `--deployment-root` reports the active generation's complete source root. The packaged static schemas describe vendor definitions, not native execution.

Run a bundled tool through the installed launcher so imports and repository-relative worker paths resolve within that generation:

```sh
python -I /path/to/bridge-install/run_runtime.py --tool prepare_workbuddy_graph.py --help
python -I /path/to/bridge-install/run_runtime.py --tool verify_skill_lifecycle.py --installed-closure /path/to/bridge-install --output /path/to/software-closure.json
```

The closure check requires a fresh target with no `closure-evidence` directory. It uses the formal generator, starts its generated stdio server, then runs the default supervised GraphJob worker with a controlled Python software HOM boundary. It saves and reloads a three-node OBJ/SOP graph, verifies parameters and connections, and records actual Result and import paths. It never starts Houdini, hython, Nuke, WorkBuddy, or a model and supplies only software evidence. `PYTHONPATH` and `PYTHONHOME` are removed from launched processes. The target's `closure-evidence` directory contains the raw worker and server evidence.

For an approved production run, prepare a new project with an explicit configuration file:

```sh
python -I /path/to/bridge-install/run_runtime.py --tool prepare_workbuddy_graph.py --output /path/to/new-project --production-config /path/to/approved-hosts.json --execution-profile
python -I /path/to/new-project/control/server.py --backend production
```

`approved-hosts.json` contains the top-level `houdini` and `nuke` configuration objects. Use the existing trusted host configuration contracts for executable, native registration, preferences, endpoint and ownership settings. The generated production server rejects missing configuration and never substitutes software hosts.

For production configuration, set the controller repository root to the reported `deployment_root`; use that generation's `deploy/plugins/houdini` and `deploy/plugins/nuke` paths. Houdini registration is under `<target>/houdini-packages`; Nuke registration is under `<target>/nuke`. Only the Skill's selected native registrations are installed. Configure approved host executables, explicit preference directories, transport endpoint and scheduler root through the formal generator's production configuration. Installation alone never starts a host. These software checks do not modify global preferences.

Extract an updated release elsewhere and install into the same target. Content hashes select the new generation; the previous generation remains available for `--action rollback`. Rollback switches both imported runtime and native registration paths. `--action uninstall` removes managed runtime generations and registration blocks, preserving other plug-ins.

The activation journal restores runtime selection and registration after an interrupted switch. Re-run `--action status` to reconcile before launching a host. Keep the target local and writable only by the trusted operator, and stop owned hosts before update or rollback. Existing Python processes retain their imported generation until restarted.
