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

## Animations, round 2

The rest of the iOS-style motion.

**The chat**
- Your message lifts up out of the message box.
- A reply grows out of the typing dots it replaces; a reply on its own rises in softly.
- The typing dots move as a smooth wave.
- Switching profile: the "now talking to" divider opens from the middle and the profile letter pops.
- The conversation glides to the newest message instead of jumping.

**While a reply is spoken**
- The bubble's rim glows with the voice's loudness. It's worked out once from the audio, so it costs nothing while playing.
- **The word being spoken glows.** Only when the timing is exact: ElevenLabs (every reply now uses its with-timestamps request, which costs the same credits) and Windows voices that report their words. Frivo's own free voices don't report words, so their replies show no glow; nothing is estimated.
- Dots under a reply that goes to the VRChat chatbox a page at a time tick along as each page is sent.
- While dictating, a ring around the mic follows your voice.

**Panels**
- The voice picker and profile editor slide all the way in from the right, and back out when closed.
- The language picker and the update dialog rise and scale in, and shrink away.
- Settings slides in from the left; the conversation comes back from the right.
- Settings pages slide in from the right, and Back slides the list in from the left. Sections cross-fade.
- The listening drawer slides in on a spring.
- The status popover grows and shrinks to fit when Credits is opened; the GPU graph sweeps in from the left.
- The chips glide to their new places when one appears, disappears or changes width (like "Use English").

Everything holds 60 frames a second with the processor slowed four times, about a phone's speed. Windows' "reduce animations" setting still turns it all off.

## Frees the graphics card when idle

An Ollama model used to stay on the graphics card until Ollama stopped. Now it
stays loaded while you're using Frivo and leaves the graphics card's memory
after an hour with no replies. The next reply takes a few seconds longer
while it loads again. Change it under **Settings > Providers > Free the
graphics card when idle**: 15 minutes, 1 hour, 4 hours or Never. The local
AI guide's settings step now sets Ollama's own default to an hour too.

## Saved replies

Keep a spoken reply and play it again whenever you like, for free.

- Hover over a spoken reply and click **Save**.
- **Saved**, on the left, lists them, newest first, with a search box.
- Click one to play it. It goes into the chat and the VRChat chatbox exactly as it did the first time: the same voice, the chatbox pages timed to it, the glowing words. Nothing is generated, so it costs no credits, and the AI remembers saying it.
- Delete one with the bin on its row (click twice).

They're kept in `%APPDATA%\Frivo\saved\`, apart from the 7-day audio clean-up, so they stay until you delete them.

## The conversation survives a refresh

Refreshing the page, or closing and reopening it, brings the conversation back,
until you press **Clear** (the bin in the top bar). Each message keeps its time.
Old replies come back quietly: nothing plays by itself, and a reply's voice is
only loaded when you click it. Spoken replies are kept for 7 days, so an older
one says its audio has been cleaned up; save a reply to keep it. The AI's memory
of the conversation follows the same rule: kept until Clear (or until Frivo
restarts). It's kept per browser, so your phone has its own.

## The volume chip holds still

Dragging the volume slider used to make it jump back and forth: as the number
changed width ("95%", "100%"), the chip row re-fitted and moved the slider under
the pointer. The chip keeps one width now, and the row waits for the popover to
close before it re-fits.

## Your own voices

- **Add a voice** at the bottom of the voice list adds a Piper voice from your computer: the `.onnx` file with its `.onnx.json`, or a `.zip`, `.tar.gz` or `.tar.bz2` that holds them (sherpa-onnx voice archives work too).
- Added voices are free and run on the processor, like the other free voices. They're listed under **Free · added by you** and kept in `%APPDATA%\Frivo\voices`.
- Each voice's **…** menu can rename or remove it. A profile still set to a removed voice says so instead of going quiet.
- Frivo tries every voice before keeping it, and refuses programs (`.exe`, `.vb`, `.bat` and the like). Adding the same voice twice is recognised.
- A voice speaks its own language; picking a German voice for English replies is caught and explained.

## Voice tags and Delivery

For ElevenLabs voices.

- **Voice tags** are a word or two in square brackets, like `[laughs]`, `[softly]`, `[whispers]` or `[sighs]`. The voice acts them out instead of reading them. The ✦ button in the message box puts one in where your cursor is, and **Suggest for my message** has the AI add a few that fit. It only adds tags; your words stay exactly as typed, and **Undo** puts it back.
- **Expressive voice** (per profile, and in Settings > Voices for the default) lets the AI use tags in its own replies, and tells it how: sparingly, where they fit the persona, and with the tags carrying the emotion instead of capitals and exclamation marks. With Clean up it may add one or two; Word for word keeps yours and adds none.
- **Delivery**: Calm, Natural or Lively. Calm is steadier and tells the AI not to write in capitals or pile up exclamation marks, and it takes out `[shouts]`. Natural is exactly what Frivo sent before. Lively swings more.
- Tags show as small marks in the conversation. The chatbox, the word count, the translation and the free voices never see them. The word highlight still follows the voice.
- Anything with a tag, and every reply from an Expressive profile, is spoken with ElevenLabs' v3 model. It doesn't take the Speaking speed setting. If ElevenLabs refuses v3, the reply is spoken the usual way without the tags.

## The personality maker

Above the personality box, in the profile editor and in Settings > Replies. It uses the AI you've set up for chat replies, Ollama or OpenAI.

- **Create**: describe a personality in a few words ("a sleepy pirate who loves his cat") and the AI writes the whole thing: who they are, how they talk, what they care about, how they react, and what they never do. It's written for how Frivo uses it (a Clean up profile gets delivery and tone, not opinions) and leaves reply length and language to the app. With something already in the box, it rewrites from your idea and keeps what fits.
- **Ideas to add** appear above the box: things the personality doesn't cover yet, worked out from what's written and from how the profile has actually been talking in your conversation. Click one to put it in (at the end of the sentence your cursor is in). × turns it down, and it isn't suggested again for that profile. New ideas come a moment after you stop typing, or with ↻.
- **Add all** has the AI work every idea in so it reads as one piece. If the AI drops anything you'd written, the ideas are added at the end instead.
- **Undo** after anything the AI changed.

## Voice tag ideas as you type, and one accent

- With an ElevenLabs voice, a moment after you stop typing (four words or more), the AI suggests where a voice tag would fit. Each idea floats just above the word it goes before, and that word is softly marked; pointing at an idea marks its word more clearly. Click one to put it in, **Add all** for every one, × to hide them for this message. An idea whose spot you've since changed disappears. **Suggest tags as I type** in the ✦ menu turns it off.
- The v3 voice no longer drifts between accents. It used to work out the language from each line by itself, and guessed differently on short or tagged lines, so one voice could sound American, Scottish or Russian from one reply to the next. Frivo now tells it the language you've selected and keeps its delivery steady, and accent tags (`[british accent]`) are only used when you type them yourself.

### Live, and a steadier accent

- Tag ideas now update as you type: Frivo asks the moment you finish each word (one question at a time), ideas that still fit stay where they are and glide along with their word, new ones fade in and ones that no longer fit fade out. The box doesn't jump in height between updates.
- The accent kept changing for two more reasons, both fixed. A message with a tag used the v3 model and one without used the usual model, and the same voice sounds different enough on each to seem like another accent; now, once a conversation has used v3, it stays on v3 for half an hour. And v3 on Natural used its looser setting, where a voice wanders; Natural (and Calm) now use v3's steadiest setting, which still performs the tags, and Lively uses its middle one.

### Voice tags, fixed up

- **Instant.** The moment you type, Frivo's own quick rules put up ideas for words that plainly call for one ("haha", "ugh", "wow", a "guess what...!" sentence), shown dashed. The AI is asked as you finish each word and its ideas replace them. If the AI can't answer, the quick ones stay.
- **They change with the text.** Each idea remembers the words it was made for: it follows its word, goes when that word changes, and goes when you put a tag in front of that word yourself (typed, or from the ✦ picker).
- **Scrolled away.** When a long message has scrolled, ideas for words out of view are counted on a small arrow at that edge (‹ 2); click it to scroll to them.
- **Dictation** and a click in the dictation history now update the ideas too, and switching to a free voice clears them.
- **The accent, properly.** ElevenLabs' own guidance says v3 is "more likely to produce variable results" on text under about 250 characters, which is most replies, and the API has continuity fields for exactly that. Each v3 request now carries the ids and words of the last three things the voice said in this conversation (previous_request_ids / previous_text), which the API uses to match the new line to them, plus the language and a fixed seed. Natural and Lively are back on v3's Natural setting (Robust muted the tags); Calm stays Robust.

### Suggest up front, Hold the accent, and exporting clips

- **Suggest** is now its own button in the message box, next to ✦. It adds the AI's tags to the whole message in one go, as before; the status line says what it added.
- The live ideas above the words now come after a pause or at the end of a sentence, with the whole message in view, instead of after every word; Frivo's own quick guesses are gone. **Ideas as I type** in the ✦ menu turns them off.
- **Hold the accent** (Settings > Voices) is the continuity between expressive lines that keeps a short reply from drifting into another accent. It also pulls each line toward how the last ones sounded, which can soften the tags, so it's a switch: off, every line is spoken fresh, the way it was before. The fixed seed is gone.
- **Saved** clips can be kept on your computer: a download arrow on each one (named by who said it and its first words), and **Export all** for every clip as a zip with a text list of what each one says.

### Auto tags, and a quieter message box

- The voice-tag controls are one split pill: **✦ Suggest** tags the message, the small arrow opens the menu (the tag picker, Auto tags, Ideas as I type). Speak and Chatbox can still be hidden from the box in Settings > Appearance.
- **Auto tags** (in that menu): the AI tags every message you send on its way to the voice, and a Reply profile's replies too, with no clicking. The pill shows **Auto** while it's on, the live ideas step aside, and a reply the AI tagged says "Auto tags" under it. It's one extra AI call per message.

### The anchor: one accent, natural tags

- **Hold the accent** is now three-way. *Follow* (what it was) matched each expressive line to the voice's last three, which held the accent but made every line inherit the mood and pace of the one before. **Anchor**, the new default, matches every line to one short, plain sentence the voice said once (made the first time, about 40 credits), so the accent is pinned to one recording and nothing carries over between lines. *Off* speaks every line fresh.
- **Accent** (Settings > Voices): pick the accent the anchor is made in: American, Southern US, British, Scottish, Irish, Australian, French, German, Russian, Japanese, or the voice's own. It's said once, in the anchor; the lines themselves carry no accent tag, so the tags stay natural.
- **The anchor** row shows what the voice is being matched to, with **Hear it** and **Make a new one** for when the first try came out wrong. An anchor ElevenLabs no longer knows is replaced on its own.
- The ✦ menu is redesigned: a proper header with Suggest, the tags in three groups you can scan, and Auto tags and Ideas as I type as clear rows.

### Voice tags on Eleven v4

- Tags are now performed by **Eleven v4**, which ElevenLabs released in September 2026 and recommends over v3 for audio tags ("a net upgrade over Eleven v3, delivering better results in almost every case"). The same tags work. **Tags model** in Settings > Voices picks v4, v4 Turbo (faster to start) or v3. If your account refuses the one picked, Frivo steps down to v3, then to the standard model without tags, and remembers for an hour.
- v4 also gets a **Similarity** setting, which holds every line closer to the voice's own recording without copying any other line's mood.
- **Hold the accent** is back to **Off** by default and was reset to Off once on update: both Anchor and Follow hold the accent by pulling every line toward another recording, and that dulls the tags. They're still there if you want them.
- The voice list labels ElevenLabs voices by how well they take tags, from what ElevenLabs reports about each: **v4 ready** (listed by ElevenLabs as made for its expressive models), **tags** (a voice clone or designed voice, which ElevenLabs recommends for them), **older** (a default voice from before the expressive models; tags work, but it may drift between accents).

### Shape words for tags

- A profile switch (and one in Settings > Voices for the default profile) for **Clean up** profiles with an ElevenLabs voice. Clean up adds voice tags itself and may lightly change the words right next to each tag so the line flows with it performed: dropping a "haha" when [laughs] performs it, adding a short "oh" or "well" after [gasps] or [sighs], moving a comma so the pause lands. Nothing else changes: same meaning, same order, nothing new said.
- It has its own check, a little looser than Clean up's (lead-ins and dropped fillers are fine), that still catches real rewording. If the AI goes too far twice, Frivo uses your words with tags only.
- With Auto tags on as well, there's no separate tagging call: the clean-up does both.
- A reply shaped this way says "Shaped for tags" under it. The switch is dimmed for Reply and Word for word, where it does nothing.

### The voice list: favorites for the voice in use, and removing voices

- The voice in use shows its check in the coloured mark on the left, and its **…** menu is the same as every other row's, so it can be added to or removed from Favorites. (The menu was there before, hidden behind the check.)
- **Remove from my ElevenLabs voices**, in a voice's **…** menu, takes it out of your ElevenLabs voices. One added from the Voice Library can be added back from there; a voice you made yourself is deleted for good, and the warning says which. ElevenLabs' default voices can't be removed, so they don't offer it. A voice still used by a profile (or the default) is refused, naming the profiles, so nothing is left pointing at a voice that's gone. Its anchors are removed with it.
- **Text-speak becomes a tag.** With Shape words for tags on, a typed "lol", "haha", "hehe", "LMAO", "omg", "ugh" and the like is never read out: the AI swaps it for the tag that fits how it's meant (a light "lol" becomes [chuckles], "hahaha" [laughs hard], "hehe" [giggles], an awkward "haha" after an apology [nervous laugh], a sarcastic "lol" [scoffs], "omg" [gasps]). Anything it misses, or a message it falls back on, gets a laugh tag by size instead, so no "lol" is ever spoken. The chatbox shows the message without them.
- **Tag words.** The words that become tags are one central list, in Settings > Voices > Tag words, used by every profile with Shape words for tags on. Each is a word or phrase and the tag it becomes (`brb` → [sighs], `im dead` → [laughs hard]), or **AI picks**, which chooses from how it's meant. Stretched-out spellings match too ("loool", "hahaha"), and phrases match with any spacing. Take a word off and it's read out as typed; **Put back the defaults** restores lol, haha, lmao, lmfao, rofl, hehe, heh, teehee, omg, ugh, smh and pfft.
- **Fixed: tags read out as words.** When ElevenLabs refused both v4 and v3, Frivo stepped down to the standard model for an hour, but only the first message had its tags taken out; the rest were sent with them, and the standard model reads tags aloud. The standard model now never gets tags. Before a model is given up on, it's tried once more without its optional extras (the language hint, Similarity, the accent anchor); if one of those was the problem, that one just isn't sent again and the model stays. A refusal now shows ElevenLabs' own reason on the status line, and in Settings > Voices > Tags model with **Try again now**.
- **The tag lists, redone.** The ✦ picker sets its tags in three columns (Feeling, Voice, Sounds) like stage directions, has a box at the top for **any tag** you can think of ("trying not to laugh"), and keeps the ones you type under **Yours** for next time. Tag words in Settings is two short sections: the words the AI picks a tag for, on one line, and the words with their own tag, one per row, each tag shown the way it looks in a message.

## Evora frees the graphics card too

- Settings > Evora has two timers, passed on to Evora (which needs its own update): **Free the listening models** (after listening stops: 5 minutes, 15 minutes, 1 hour or never) and **Free speech-to-text** (after no dictation or listening: 15 minutes, 1 hour, 4 hours or never). Listening's models are the big ones; they stay while listening is on.
- The GPU graph shows what Evora has loaded ("listening + speech") and when each will be freed, under Ollama's countdown, which now says it's Ollama's.

## Better voice tags

- **Tag rules.** What the AI adds is checked before the voice gets it: a feeling tag at the very end of a line (which colours nothing) is dropped, a tag that just repeats the words beside it (`[happy] I'm so happy`) is dropped, piles and repeats are thinned, and there's a cap per sentence. Sounds like `[laughs]` and `[sighs]` are kept first. Tags you type yourself are never touched.
- **Context.** Suggest, the live ideas and Auto tags now see the last few lines of the conversation and the profile's personality, plus examples of good and bad tagging, so a line is tagged for what it means in the moment.
- **Tag amount** (Settings > Voices, and each profile): Subtle, Normal or Dramatic.
- **Your tag taste.** Frivo notices which suggested tags you keep, delete or add yourself, and which replies you retake without tags. The AI leans towards the ones you keep; one you always remove stops being added. Settings > Voices shows what it has learned, with Forget my taste.
- **Retake** on a spoken ElevenLabs reply: Say it again, Without tags, or Different tags. The words stay the same, the new take replaces the old one, and the AI's memory of the conversation keeps the version you heard.
