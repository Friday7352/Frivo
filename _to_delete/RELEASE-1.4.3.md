# Frivo 1.4.3

## Frivo starts again after an in-app update

Updating from the browser stopped Frivo but sometimes left it stopped, so it had to be started again by hand on the Frivo PC.

- If Frivo isn't running again 20 seconds after an update installs, the updater now starts it itself, as the person who asked for the update, in their own Windows session.
- The helper that normally restarts Frivo now starts more reliably.

This fix applies to the updates after this one. Because the copy of Frivo you're updating from is the one that runs the update, installing 1.4.3 itself may still leave Frivo stopped once. If it does, start Frivo from the Start menu on the Frivo PC.
