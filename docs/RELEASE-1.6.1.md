# Frivo 1.6.1

## Free voices load on every PC

On some PCs the free voices failed with "Load model from ...\voices\piper\kristin\model.onnx failed: system error number 13". Setup runs as an administrator, and newer versions of Python unpack files so that only that account can read them. Frivo, running as you, then wasn't allowed to load its own voices.

- Voices, voices you add, the voice library and the built-in AI are now unpacked so they take their permissions from the Frivo folder.
- Setup (install, update and Repair) resets the permissions on the voices folder, which fixes PCs that already have the problem.
- If it still happens, the error says which folder and how to fix it, instead of the raw error number.

## The built-in AI cleans up after itself

- **No more locked folder.** The built-in AI's engine could keep running after Frivo was closed, crashed or was stopped by an update. It then held its files open, so the folder couldn't be deleted ("open in another program") and the AI couldn't be downloaded again. On Windows the engine now always stops when Frivo does. Frivo also stops one left over from before when it starts, and setup, the launcher's Stop and the uninstaller stop it too.
- **Uninstalling removes it.** The engine and models (gigabytes) are deleted when Frivo is uninstalled, even if you keep your settings.
- **Download again**, next to Test, replaces the engine and the model, for when the AI won't start.
- **Remove says when it can't.** If a file is still in use, it says so, instead of reporting that the AI was removed when it wasn't.

## Choose where Frivo keeps its big files

**Settings › Storage** (new): pick a folder for each of these, on the PC Frivo runs on:

- **Built-in AI:** the engine and its models.
- **Voices you add:** from Browse free voices or Add a voice.
- **Saved replies.**
- **Reply audio.**

How it works:

- **Picking a folder:** each row shows the folder, how much it uses and the drive's free space. **Change…** opens a folder picker for that PC: drives, folders and **Make folder**. Frivo keeps the files in a subfolder of the one you pick (`builtin_ai`, `voices`, `saved`, `audio_cache`), never loose in it.
- **Moving:** what's already there is moved, with progress. Frivo switches over once the copy is complete, and only then deletes the old copy. If anything fails, nothing changes.
- **Already-used folders:** if Frivo's files are already in that folder (from an earlier install, say), it asks first and can use them instead of moving.
- **Back to Frivo's folder** puts everything back. If a picked drive isn't plugged in when Frivo starts, Frivo says so and uses its own folder until it's back.
- **What stays put:** settings, profiles and keys stay in Frivo's own folder. Backups never bring another PC's folders with them.
- **Uninstalling** also removes the built-in AI from a picked folder. If you delete your settings, it removes Frivo's subfolders there too, never anything else in the folder.
- **Ollama's models:** Storage explains how to move them on the Ollama PC (OLLAMA_MODELS).
