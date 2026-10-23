# Frivo 1.4.3

## Frivo comes back after an in-app update

Updating from the browser stopped Frivo but didn't always start it again. When Frivo runs on another PC, that meant walking over to it.

The installer now handles the restart itself, on the PC Frivo runs on. Before an update stops Frivo, it notes which Windows account Frivo was running as. Once the update is installed, it starts Frivo again as that account, in that account's session, the same way signing in to Windows does. It does this even if the update fails partway through.

This works from this update onward. The installer for the new version is what runs during an update, so you don't have to wait for the next release.
