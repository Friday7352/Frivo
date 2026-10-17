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
