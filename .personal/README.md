# Personal LCSign save-sync distribution

This fork follows **official LNPANDY/NX2Apple releases**, not the engine's development branch.
Its application update channel is `Tiomehsh/NX2Apple`; game build tools still use the official repository.

Every six hours, `personal-release.yml` checks the newest official release. It exports that release's
frontend, checks and applies `save-sync.patch`, changes only the application update channel and
personal version, then runs the save-transfer and updater tests and builds an arm64 frontend.
The official release ZIP must match GitHub's SHA-256 digest. Its bundled tools are retained;
only the frontend executable and version metadata are replaced. The resulting application must
pass the bundled-tool and strict signature checks before publication.

Version `0.7.2.1` means upstream `0.7.2`, personal patch revision `1`. Increase `REVISION` in
`release.py` when refreshing the personal patch for an existing official release.
The initial personal release is installed once; subsequent updates come through the app's updater.

The save patch detects a connected application's data container without an Xcode installation
receipt. It probes the active per-game layout and the legacy `Documents/save` layout, understands
current CoreDevice timestamps, and follows the Mac library marker when choosing the Mac save path.
Only committed `save` and optional `save_device` directories participate; `.work` directories do not.
It does not fake signing history, enable Xcode renewal, reinstall an iPhone app, or transfer saves
without the normal confirmation in the Saves window.

If the patch stops applying or a test/build fails, the workflow publishes nothing and the last
working release remains available. Review the failed Actions run, update the patch, then rerun
the workflow. When upstream adopts the fix, replace the patch with compatibility tests rather
than attempting to apply the same changes twice. Automatic integration is not guaranteed forever.

GitHub disables scheduled workflows in inactive public repositories after 60 days. Check the
Actions page if scheduled runs stop; workflow_dispatch remains the manual entry point.
No messages/issues are automatically posted and no game files, keys, saves or certificates are stored here.

Revision 2 adds bounded device queries with a process deadline, remembers the device that successfully exposes the game container, and prevents concurrent refresh requests. Unprepared devices cannot block discovery indefinitely.
