# Frivo 1.6.0

<!-- Running notes: each change for 1.6.0 is added here as it's made. -->

Frivo now works without OpenAI or Ollama: Clean up has a no-AI mode, there's a one-click AI that runs inside Frivo, and Chat replies has a No AI choice.

## Frivo works without any AI

**Clean up without AI.** With no OpenAI key and no Ollama, Clean up in English now works anyway, using Frivo's own rules on the CPU:

- **Spelling:** only words the dictionary doesn't know, and only when one fix is clearly right ("teh" → "the", "becuase" → "because").
- **Grammar and punctuation:** contractions typed without the apostrophe ("dont" → "don't", "im" → "I'm"), "i" → "I", always-wrong phrases ("could of", "alot"), and words typed twice. Spacing is fixed, sentences get capitals, and a message gets a full stop or question mark if it has none.
- **Never touched:** voice tags, slang and text-speak (lol, ngl, gonna), your Tag words, names, words in capitals, stretched words ("sooo"), links and emoji.
- **Also a fallback:** it's used when the AI can't be reached, or when it keeps rewording your message.
- **Labelled:** the reply shows **Cleaned up without AI**, and hovering the label says why.
- **Limits:** it can't fix a misheard word that's still a real word, or untangle a garbled sentence. That still takes an AI.

**Without any AI:** Word for word in English still needs no AI. Reply, and the other languages, say what they need and how to get it.

**No AI** is now a choice under Chat replies, next to OpenAI, Ollama and Built-in AI, for when you want nothing sent anywhere even with a key set. Each choice is a card that says what it does, what it runs on (OpenAI's servers, the Ollama PC's graphics card, or the processor and memory of the PC Frivo runs on) and roughly what it uses. Ollama's card works out the graphics memory from your own Fast, Balanced and Best models.

## The built-in AI

**Settings › Providers › Built-in AI**: one button downloads a small AI that Frivo runs itself, on the processor of the PC Frivo runs on (which may not be the one you browse from). There's no Ollama, account or key, and nothing else to install. Chat replies switch to **Built-in AI** when it's done.

- **Two sizes:**
  - **Small** (Qwen 3.5 2B): a 1.3 GB download, about 2.5 GB of memory.
  - **Better** (Qwen 3.5 4B): a 2.7 GB download, about 4.5 GB of memory. Better replies, about twice as slow.
- **The engine:** llama.cpp's own server, a fixed release, about 25 MB. Both downloads are checked against the checksums GitHub and Hugging Face publish before they're used. A wrong checksum, a cancelled download or a full drive leaves nothing behind.
- **How it runs:** it starts when a reply needs it (a few seconds) and only listens on the PC Frivo runs on. It runs at below-normal priority on half the processor's threads, so VRChat stays smooth. It frees its memory after an hour with no replies (**Free its memory when idle**: 15 minutes, 1 hour, 4 hours or Never).
- **Test** asks it for a line and says how long that took. **Remove** deletes one model or everything, and replies go back to OpenAI.
- **Same features:** the personality maker, tag suggestions and translation all work with it. The status pill shows it as **Built-in AI**.
- **Quality:** replies are simpler than OpenAI's or a big Ollama model's, and personas are less consistent.

## Falling back

- When the AI you picked can't answer (the built-in AI isn't downloaded, or Ollama is down), Clean up uses **No AI** (Frivo's rules) instead. The status pill says so, for example **Built-in AI not downloaded · Clean up uses No AI meanwhile**, instead of claiming it's falling back to OpenAI.
- **Fall back to OpenAI if a local AI is down** only appears once you've added an OpenAI key, and only falls back when it's on and there's a key.
- The status popover always starts with the AI picked for replies (OpenAI, Ollama, Built-in AI or No AI). Translation gets its own row only when it uses a different AI. Moving replies off the built-in AI moves translation off it too.

## Fixed: free voices wouldn't load on some PCs

On some PCs the free voices failed with "Load model from ...\voices\piper\kristin\model.onnx failed: system error number 13". Setup runs as an administrator, and newer versions of Python unpack files so that only that account can read them. Frivo, running as you, then wasn't allowed to load its own voices.

- Voices, voices you add, the voice library and the built-in AI are now unpacked so they take their permissions from the Frivo folder.
- Setup (install, update and Repair) resets the permissions on the voices folder, which fixes PCs that already have the problem.
- If it still happens, the error says which folder and how to fix it, instead of the raw error number.
