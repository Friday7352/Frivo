# Frivo 1.6.1

## Free voices load on every PC

On some PCs the free voices failed with "Load model from ...\voices\piper\kristin\model.onnx failed: system error number 13". Setup runs as an administrator, and newer versions of Python unpack files so that only that account can read them. Frivo, running as you, then wasn't allowed to load its own voices.

- Voices, voices you add, the voice library and the built-in AI are now unpacked so they take their permissions from the Frivo folder.
- Setup (install, update and Repair) resets the permissions on the voices folder, which fixes PCs that already have the problem.
- If it still happens, the error says which folder and how to fix it, instead of the raw error number.
