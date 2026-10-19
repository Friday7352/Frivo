# Frivo 1.5.0

<!-- Running notes: each change for 1.5.0 is added here as it's made. -->

## Typing dots stay up until your reply arrives

The VRChat typing dots used to disappear the moment you sent a message. Then nothing showed for the few seconds Frivo took to write, translate and voice the reply. Now the dots stay up the whole time and give way to the chatbox message when it appears.

- With **Speak** on, the dots stay up until the voice starts, which is when the message goes to the chatbox.
- With **Speak** off, they come down as soon as the message goes out.
- If something goes wrong, they come down straight away, and never stay up longer than 30 seconds.

## Auto-send only sends what you say

Auto-send used to be able to fire while you were fixing a dictated message by hand, sending it half-edited. Now, as soon as you type in the box, that message is yours: auto-send is paused for it, and only **Enter** sends it.

- The **Auto** switch shows it's paused (dimmed, with a dashed outline), and the status line says so.
- Once you send or clear that message, the next one goes back to normal, so dictating hands-free still sends by itself.
- Typing on its own never auto-sends, the same as before.

## Reply, Clean up and Word for word

The response styles have clearer names, and each one now does exactly what it says. Before, the model was only asked not to change your message, and it didn't always listen. The selected style's description now shows under the buttons, so you can see what it does without hovering.

- **Reply**: type what someone said to you, and the persona answers it in character. This works the same as before.
- **Clean up**: says what you *meant* to say. It fixes typos, misheard and autocorrected words, and grammar, and makes garbled sentences make sense. It keeps your slang and tone and adds nothing you didn't say. The personality only comes through in punctuation and emphasis.
  - Frivo checks every Clean up against what you typed. Filler or pet names you didn't use ("ugh", "honestly", "darling"), new content, or an answer instead of your message all get caught. If that happens, Frivo tries once more without the personality. If that's still wrong, it uses your words as typed, and the message shows **Kept to your words** underneath.
  - The check only runs in English. In other languages, Clean up translates what you meant under the same rules.
- **Word for word**: says exactly what you typed. In English the AI isn't used at all, so it's instant, costs nothing to write, and works without an OpenAI key. With another language selected, it's translated as literally as that language allows.
- **With personality** and **Exact echo** have been removed. Settings and profiles that used either one now use Clean up.
- Each profile has a **Follow reply length** switch (see below).

## Follow reply length, per profile

The profile editor has a new **Follow reply length** switch, and it works with every response style.

- **On:** Reply keeps to the **Reply length** slider, the same as before. Clean up and Word for word **summarize** anything longer than the slider so it fits. The summary stays in your voice, in the first person, and adds nothing you didn't say. The message shows **Shortened to fit the reply length** underneath.
  - Sometimes a summary can't be used: there's no OpenAI key, the request fails, or the summary added things you didn't say. Then Frivo keeps your whole sentences up to the limit instead, and the message shows **Trimmed to last full sentence**.
  - Short messages are never sent for summarizing, so Word for word in English still uses no AI unless a message is over the limit.
- **Off:** nothing is shortened. Clean up and Word for word say your whole message, and Reply isn't held to the slider either.
- Profiles made before 1.5.0 keep working the way they did: Reply follows the slider, and Clean up and Word for word say everything. Until you flip the switch yourself, it changes to match the style you pick.

## Typing while dictating keeps what you type

With the mic on, typing in the box used to be erased the next time dictation heard a word. Now what you type stays, and anything you say afterwards is added after it.

- If you type while a preview of your words is still showing, the finished words replace that preview when they come in. They aren't added a second time.
- Your cursor stays where it is when dictated words are added at the end, so you can keep typing.

## The microphone setting keeps your choice

The Microphone setting sometimes looked reset, and could really reset, until you clicked Reload. Until a page is allowed to use the mic, browsers hide every microphone's name. Frivo used to fill the list from that hidden list anyway.

- If the names aren't available yet, the list shows **Your saved microphone**. That's still the one dictation uses, and nothing gets overwritten.
- The list fills in on its own once the mic is allowed, when you plug a device in or out, and whenever you open Settings. You don't need to click Reload anymore.
- There's now a **System default** choice, which uses whatever Windows is set to.
- If your saved microphone isn't plugged in, the list says **Saved microphone (not connected)**. Dictation then uses the default microphone instead of failing, and the status line tells you.
- Live (Evora) dictation uses the microphone you pick here too, so the hint now says so.

## Free voices included with Frivo

Frivo can now speak without ElevenLabs. Pick a free voice in the Voice list and it's spoken right on the PC Frivo runs on. There's no account, no key and no cost per reply. The free voices are deliberately light: no graphics card, and very little CPU. ElevenLabs works exactly as before, and it's the choice for natural-sounding AI voices.

- **Six voices of Frivo's own** under **Free · included with Frivo**: Kristin, Cori and Alba (female), and John, Joe and Norman (male), in American and British English. They sound clearly better than Windows' voices.
  - They're light. Each runs on one CPU thread, never the graphics card. A long reply takes about a tenth of a second per second of speech to make, and short lines are ready almost at once. At most two voices are kept loaded, about 170 MB of memory each.
  - **Setup downloads them once** (about 280 MB), like Python and Frivo's libraries, and checks each file before using it. `FrivoSetup.exe` and in-app updates stay small. Updates and Repair keep the voices and only download one again if it's missing or damaged, and uninstalling removes them. Frivo itself never downloads anything for them.
  - If a voice couldn't be downloaded, setup still finishes and says so, and the other voices work. Run setup again and choose Repair to try again.
  - They speak English. For other languages, pick a Windows or ElevenLabs voice.
- **The voices built into Windows** under **Free · built into Windows**. Frivo now also lists the newer voices Windows installs with each language, which desktop programs can't normally see. On an English PC that's usually David, Zira and **Mark**. More come with each language you add in Windows **Settings → Time & language → Speech**. When Windows has the same voice in an older and a newer form, Frivo lists the newer one and moves anything using the older one over to it.
  - They start straight away. Frivo keeps one small speech helper running instead of starting Windows' speech engine again for every reply.
- With a free voice selected, replies need no ElevenLabs key and use no credits. The reply-length card says "free with this voice" instead of quoting credits, and the line under each reply says **free voice**.
- **Speaking speed** works with every voice. Hovering a reply's time shows which engine spoke it.
- Previewing a free voice plays a short line in that voice's own language.
- If you tried an earlier 1.5.0 build with the Kokoro voices: they've been removed. They needed far more CPU, and AI voices are what ElevenLabs is for. Anything that used a Kokoro voice now uses one of Frivo's voices of the same gender, and the Kokoro download is deleted the next time Frivo starts.

## A cleaner interface

The whole page has been redone. Everything still does what it did; it's laid out so the conversation gets the room and the controls are where you reach for them. Red is still the colour of the app.

- **One column.** The conversation has the whole width. The old left sidebar is gone; what it held is now a row of chips above the message box: the **voice**, the **language**, the **response style**, the **reply length** and the **volume**. Click a chip to change it.
- **A rail on the left** with four buttons: Chat, Listening, Voices and Settings. The one you're on is lit. The theme switch is at the bottom of the rail.
- **Top bar:** the profile (with New / Edit / Delete beside it), one **status pill**, and Clear chat. The pill turns orange and names the service when Evora, Ollama or FrivOSC is unreachable; click it for each service's state, what's wrong, a Settings button that opens its page, and your ElevenLabs balance. The update chip appears here when a new version is out.
- **Evora and Ollama are set up on the Providers page itself** (address, Test, model), and FrivOSC on the VRChat page — no more pages inside pages, and nothing expands inside a chip.
- **The message box is one row:** type, then Auto / Speak / Chatbox as small icons that light up red when on, the mic, and Send. "Ready." no longer shows as a status line; the line only appears when it has something to say.
- **Conversation:** your messages have no avatar; a run of replies shows the speaker once; the words / credits / time line shows when you hover a reply.
- **Listening is a drawer** that slides in beside the chat from the rail (or its Listen button). It's closed until you open it. While it runs with the drawer closed, the rail shows a red dot.
- **The voice picker is a sheet** from the right. Voices are grouped **Free · on this PC**, **Free · built into Windows** and **ElevenLabs**, each with a *free* or *credits* tag, with the voices you use most as chips at the top. It says whose voice you're choosing. The profile editor opens the same way.
- **Settings** is one page at a time: Accounts & keys, Voices, Replies, Dictation, Listening, VRChat, Providers, Updates. Every row is a label, a one-line hint and its control. **Settings save themselves** as you change them and say *Saved*; only the API keys keep a Save button, which appears once you've typed one. A **search box** finds any setting by its words, across every page.
- **On a phone** the rail becomes a bar along the bottom, the chips scroll sideways, and the message box stays pinned.
- **FrivOSC is one click away while it's connected.** A chip appears above the message box (it reads *Live* or *Muted* for your VRChat mic, with a green or red dot) and opens the four switches — VRChat OSC, Follow VRChat mute, Unmute when I send, Show typing dots. They're the same switches as Settings → VRChat, save themselves, and the chip disappears when FrivOSC isn't connected.

## Chatbox pages keep up with the voice

A long spoken reply used to flip through its chatbox pages every second and a half or so, far faster than the voice could say them. The last page was up while the voice was still on the first. Now each page appears as the voice gets to it.

- Frivo splits the reply into pages. Each page after the first appears when the voice finishes the last word of the page before it. The pages look the same as before, counter included.
  - **ElevenLabs:** Frivo asks for the time each character is spoken along with the audio. It's the same voice and the same credits.
  - **Frivo's and Windows' free voices:** Frivo speaks each page on its own and joins them, so it knows exactly where each one ends. You may hear a slightly longer pause between pages.
- If you pause a reply, the next page waits, and when you play it again it carries on from where the voice is.
- The typing dots stay up between pages, the same as before.
- Replies sent without the voice (**Speak** off) still go as one message and page the way they always have.
- If the exact timing isn't available (ElevenLabs refuses that request, or a free voice can't be spoken a page at a time), Frivo works the timing out from the text instead. That can be off by a second or so on a long page.
- No new FrivOSC is needed: each page fits in one chatbox message, and FrivOSC passes those on exactly as they are.

## Old reply audio is deleted

Every spoken reply was saved in Frivo's audio folder and never removed. Replies older than 7 days are now deleted when Frivo starts and every six hours after that.

- Voice previews are kept, because there's one per voice and they're reused.
- To keep replies longer, set `audio_keep_days` in `config.json` (`0` keeps them all).

## Dictation stays off when Frivo opens

With **Follow VRChat mute** on, opening Frivo while your VRChat mic was already live used to switch dictation on by itself. Now dictation is always off when the page opens. Mute and unmute in VRChat (or press the mic button) to start it.

- The same goes for FrivOSC reconnecting: it doesn't start dictation on its own.
- Turning **Follow VRChat mute** on while you're unmuted still starts dictation straight away, as the switch says.

## Three Ollama models to switch between

With **Chat replies** set to Ollama, an **AI** chip above the message box picks which model writes replies: **Fast**, **Balanced** or **Best**. You name the three in **Settings → Providers → Ollama** (for example `gemma3:4b`, `qwen3.5:4b` and `qwen3.5:9b`).

- Click the chip to see each model and how it's doing: whether it's downloaded on the Ollama PC, whether it's loaded, and whether it all fits on the graphics card. If part of it runs on the CPU, the chip says so, because that makes it slower.
- Switching unloads the other two and loads the new one straight away, so there's room on the graphics card (and for Evora, if it shares it) and the next reply doesn't wait.
- A model that isn't downloaded yet says exactly what to run on the Ollama PC (`ollama pull …`).

## Ollama works better

- **The model stays loaded.** Ollama used to unload it after five idle minutes, so the first reply after a break waited for it to load again.
- **No "thinking" first.** Models that think before answering (such as Qwen 3.5) now answer straight away, instead of coming back slow or empty.
- **No OpenAI key needed** when Chat replies uses Ollama, as the README always said.
- **Replies say which AI wrote them, and where.** Hovering a reply's time shows, for example, "Ollama · gemma3:4b (local): 1.3s · Frivo voice (free, local): 0.4s" or "OpenAI · gpt-4o-mini (cloud): 1.1s · ElevenLabs (cloud): 0.9s". It used to say "ChatGPT" whatever answered. If Ollama couldn't be reached and the fallback used OpenAI, the hover shows that too.

## Set up local AI, step by step

**Settings → Providers → Ollama** has a new link, **New to this? Set it up step by step**, which opens a guide to running Frivo's replies on your own graphics card with Ollama.

- Two questions first: whether the AI runs on the Frivo PC or another PC, and how much video memory its graphics card has (with a tick box for when Evora shares the card). The guide then picks the Fast, Balanced and Best models that fit, and says when Best will run partly on the CPU.
- Every command has a **Copy** button: paste it into PowerShell and press Enter. The steps only show what you need. On the same PC there's no firewall or address step.
- The settings step also restarts Ollama with those settings, so they always take effect. Setting them by hand and restarting Ollama the usual way can leave it running without them.
- The last step tests the address and switches Frivo over with one button.
- A troubleshooting section covers the usual snags: "ollama" not recognized, nothing listening, other PCs can't connect, a model only partly on the graphics card, a model not downloaded yet, and how to tell replies come from your own PC.

## The chips stay on one row

With the AI and VRChat chips (and **Use English** when a profile suggests another language), the chips above the message box no longer wrap into two rows. The voice chip gives way first: its details shorten, then it shows just the voice's name.

## Replies say Local or OpenAI

Hovering a reply shows a small **Local** (green) or **OpenAI** tag in the line underneath, so you can see at a glance where it was written. Hover the tag for the model's name.

## Graphics card memory graph

Click **Ready** to see how full the graphics card's memory has been over the
last 10 minutes, split into Ollama, Evora and everything else, with how busy
and how warm the card is. Hover over the graph to see any moment.

Evora reports the card, since it runs on the PC that has it. This needs the
latest Evora (its new `GET /gpu`). With an older Evora, or without Evora, Frivo shows
how much of each loaded Ollama model is on the graphics card instead, and
says why it can't show the whole card. Frivo keeps the readings in the
background, a couple of small requests every few seconds, so the graph
already has history when you open it.

## Animations, round 1

Frivo now moves like an iOS app: on springs, quick and soft, and never in
the way.

- **Popovers grow out of their chip.** The AI model, length, volume, VRChat
  and status popovers, and every dropdown, scale out of the button you
  clicked and shrink back into it. Close one half-way open and it reverses
  from where it is.
- **Buttons respond to your finger.** Chips, buttons and icons dip when
  pressed and spring back when you let go.
- **Toggles.** Switches spring across with a little overshoot and stretch
  while held; Speak, Chatbox and Auto pop when switched on.
- **The hover bubble.** In the voice and language pickers, the dropdowns, the
  AI model menu and a voice's menu, the row under your pointer lifts out a
  little. On a phone it lifts while your finger is on it.
- **The voice and language pickers** rise in on the same spring.

Everything animates only position, size and fade, which the graphics card
does for almost nothing, and Windows' "reduce animations" setting turns it
all off.
