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

## Free voices that run on your PC

Frivo can now speak without ElevenLabs. Pick a free voice in the Voice list and it's made right on the PC Frivo runs on, with no account, no key and no cost per reply. ElevenLabs works exactly as before. If you pick an ElevenLabs voice, nothing changes.

- **Kokoro** ("free on this PC" in the Voice list): 45 natural-sounding male and female voices. Most are American and British English, and there are also Spanish, French, Italian, Brazilian Portuguese, Hindi, Japanese and Mandarin voices. The best-sounding ones are marked *recommended*. They run on the CPU, so no graphics card is needed.
  - The voices download once (206 MB), the first time you pick, preview or use one, or when you press **Download** in **Settings → Voice & Speech → Free voices**. Progress shows on the status line, and the download is checked before it's used.
  - Any Kokoro voice can speak the languages above. For other languages (German, Korean, Russian and so on), pick a Windows or ElevenLabs voice.
- **Windows voices** ("built into Windows"): the voices that come with Windows, plus any language packs you've added. There's nothing to download and they're instant, but they sound more robotic.
- With a free voice selected, replies need no ElevenLabs key and use no credits. The reply-length card says "free with this voice" instead of quoting credits, and the line under each reply says **free voice**.
- **Speaking speed** works with every engine. Hovering a reply's time shows which engine spoke it.
- Setup installs the free voices automatically. If they can't be installed, setup still finishes: Frivo runs normally, ElevenLabs and Windows voices still work, and Settings says why Kokoro isn't available. Setup also installs the Microsoft Visual C++ runtime Kokoro needs if the PC doesn't already have it. Kokoro needs Python 3.10–3.13, which is what setup installs by default.

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
  - **Kokoro and Windows voices:** Frivo speaks each page on its own and joins them, so it knows exactly where each one ends. You may hear a slightly longer pause between pages.
- If you pause a reply, the next page waits, and when you play it again it carries on from where the voice is.
- The typing dots stay up between pages, the same as before.
- Replies sent without the voice (**Speak** off) still go as one message and page the way they always have.
- If the exact timing isn't available (ElevenLabs refuses that request, or a free voice can't be spoken a page at a time), Frivo works the timing out from the text instead. That can be off by a second or so on a long page.
- No new FrivOSC is needed: each page fits in one chatbox message, and FrivOSC passes those on exactly as they are.

## Old reply audio is deleted

Every spoken reply was saved in Frivo's audio folder and never removed. Replies older than 7 days are now deleted when Frivo starts and every six hours after that.

- Voice previews are kept, because there's one per voice and they're reused.
- To keep replies longer, set `audio_keep_days` in `config.json` (`0` keeps them all).
