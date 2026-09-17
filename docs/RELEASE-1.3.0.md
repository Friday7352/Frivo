# Frivo 1.3.0

## 1.3.4: joint separation display

Evora's joint separation preview can return separated speech even when just one
person is active. These rows now say "unverified" and only say "overlap" when
Evora reports overlapping speech. Temporary voice labels remain separate from
confirmed people. A per-clip separation failure is shown in listening status.

## 1.3.3 patch

Translate each recovered voice using its own detected language. Display Evora's
optional persistent overlap tracks as Voice track N (unverified), separate from
confirmed people. Track IDs are session-scoped and cannot select a trusted
speaker. Requires Evora 1.3.1 with Follow repeated separated voices enabled;
this experimental setting is off by default and is not validated for crowded
VRChat worlds.

## 1.3.2 patch

Unassigned solo speech is now visibly labeled Unidentified voice. With Evora
1.3.0, speaker numbers appear only after enough consistent clean speech has
confirmed an identity. Restart listening after updating Evora to discard
the previous session's uncertain profiles.

## 1.3.1 patch

The Listening panel now has a Speaker setup link. It opens settings at the
Evora address configured in Frivo, including a different PC on your network.
Remote settings require Evora 1.2.1 and its private-network access setting.

Listening now displays Evora's individual speaker turns and translates each turn separately. Recovered overlapping voices appear in separate rows with an unverified overlap label; uncertain mixed speech is visibly unidentified.

Each listening session has separate temporary voice memory. Saved Evora names appear automatically, while random speakers keep a session-specific label. Stopping or resetting listening clears temporary memory without deleting enrolled voices. Final audio uploads are processed in order before the session is closed.

Update Evora to 1.2.0 for local listening. Configure speaker recognition on the Evora PC, wait for Ready, and enable experimental overlap recovery to attempt separation. Enroll familiar voices using 20–30 seconds of clear solo speech. Random voices need clear solo speech during the session before they can be matched reliably in overlap.

These changes do not guarantee perfect identification or transcription during simultaneous speech. Unverified recovered speech is not eligible for Evora's strict speaker filter. End-to-end accuracy and delay must be evaluated with the actual microphone or playback route.
