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

## Response, Echo and Mimic

The response styles are now **Response**, **Echo** and **Mimic**, and Echo and Mimic stick to what you wrote. Before, the model was only asked not to reword things, so an echo didn't always come back word for word.

- **Response:** the persona replies to what you typed in. This hasn't changed.
- **Echo:** says your own words back, with spelling, grammar and punctuation fixed. The personality shows only in tone and punctuation, never in extra or different words. Frivo checks every Echo against what you typed. If the model reworded it, Frivo tries once more without the personality, and if that's reworded too it uses your words as typed. You'll see **Kept to your words** under the message when this happens.
- **Mimic:** says exactly what you typed, with no personality. In English the AI isn't used at all, so it's instant, costs nothing to write, and works without an OpenAI key. With another language selected, it's translated as literally as that language allows.
- Echo and Mimic always say the whole message. The reply-length setting only applies to Response.
- **With personality** and **Exact echo** have been removed. Settings and profiles that used either one now use Echo.
