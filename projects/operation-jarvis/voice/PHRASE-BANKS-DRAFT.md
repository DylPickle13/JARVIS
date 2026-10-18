# JARVIS announcement phrase banks — compact review draft

**Owner-approved wording and recording durations.** These 72 lines are mirrored in `phrase_catalogue.json`, with opt-in integration and offline recordings implemented. The owner approved keeping all recordings, including the initially flagged lengths, and proceeding with staged deployment. No review audio was played. See [PHRASE-BANKS.md](PHRASE-BANKS.md) for validation and deployment safeguards.

## Selection and review rules

- **72** lines: 24 wake, 24 processing, 12 arrival, and 12 departure. Arrival and departure v2 are entirely dry humour; wake and processing retain their **50% straight / 50% dry-humour** split: 24 straight and 48 dry overall.
- Kept the strongest straight lines rather than adjective swaps and repeated response/reply templates. Added distinct, understated humour instead of merely making the same sentences more formal.
- Humour is intentional persona/metaphor, not a factual status report. No line reports a completed action, a ready response, an actual tool consultation, household security, or a fault. Keep delivery deadpan rather than adding laughs, sound effects, or comic pauses.
- Wake lines invite a request without claiming it has already been understood. Processing lines also work for steering; they do not depend on an existing answer or promise a successful result.
- Arrival remains a room/computer-presence return, not confirmed arrival home. No absence-length remarks, time-of-day remarks, or questions requiring a response.
- Farewells are general good wishes and playful parting advice. No vehicle, destination, weather, security, or monitoring claims.
- Arrival v2 uses longer owner-approved lines with a **3.379-second** raw audio ceiling. Departure v2 spans 2.171–3.367 seconds under the approved 4.5-second hard cap. Wake and processing retain their original approved durations below 2.8 seconds. Playback speed and padding are unchanged; see the implementation report for exact ranges.
- Startup, reconnect, quick-return, and time-of-day announcements remain removed. The two failure messages stay exact and outside all banks.
- The protected legacy departure phrase/WAV/hash validation stays unchanged by default. The implemented opt-in bank requires its own reviewed recordings and pinned metadata; it does not bypass attempt, identity, timing or playback validation.
- This is the prewritten wording source, not live model generation. The implemented opt-in path selects approved pre-rendered recordings without live generation or synthesis.

## 1. Wake acknowledgements — 24

### Straight — 12

1. Yes sir?
2. Go ahead, sir.
3. I'm listening, sir.
4. At your service, sir.
5. How can I help, sir?
6. You called, sir?
7. What's on your mind, sir?
8. You have my attention, sir.
9. Ready when you are, sir.
10. Over to you, sir.
11. What's the plan, sir?
12. Say the word, sir.

### Dry humour — 12

1. I've been summoned, sir.
2. No appointment necessary, sir.
3. What are we plotting, sir?
4. Something suitably ambitious, sir?
5. Permission to be useful, sir?
6. What needs overthinking, sir?
7. Your resident know-it-all, sir.
8. What requires my brilliance, sir?
9. Standing by. Very stoically, sir.
10. Ready, minus the ceremony, sir.
11. All ears. Figuratively, sir.
12. Go on. Impress me, sir.

## 2. Processing acknowledgements — 24

Shared with steering; no completed-answer or completed-action claims.

### Straight — 12

1. Generating your response, sir.
2. Putting an answer together, sir.
3. I'm on it, sir.
4. Thinking it through, sir.
5. Considering your request, sir.
6. One moment, sir.
7. Bear with me, sir.
8. Let me work it out, sir.
9. Getting to work, sir.
10. Putting the pieces together, sir.
11. Let me compose a reply, sir.
12. That has my attention, sir.

### Dry humour — 12

1. Thinking, not merely looking busy, sir.
2. Dusting off the imaginary clipboard, sir.
3. Applying a little artificial wisdom, sir.
4. Allow me some dignified buffering, sir.
5. Consulting common sense. Unfashionable, sir.
6. Putting the clever bits together, sir.
7. Let me alphabetise my thoughts, sir.
8. A brief meeting with logic, sir.
9. Reasoning before pontificating, sir.
10. Aiming for sense, not noise, sir.
11. Keeping the imaginary gears turning, sir.
12. Working toward something mildly impressive, sir.

## 3. Arrivals — 12

Room/computer return, not a claim that the owner has just entered the house.

### Dry humour — 12 (owner-approved replacement)

1. Ah, my favourite source of technical difficulties.
2. Welcome back, sir. The chair missed your leadership.
3. Management has returned. Look busy, everyone.
4. The plot thickens. You've sat down.
5. Welcome back, sir. Shall we open another forty tabs?
6. Ah, the organic peripheral has reconnected.
7. Your throne awaits. Ergonomically questionable as ever.
8. Welcome back. Productivity remains entirely optional.
9. There you are, sir. I was enjoying the lack of requests.
10. The human element returns. So much for stability.
11. Welcome back, sir. Let's call this research.
12. Systems ready. Sensible decisions sold separately.

## 4. Departure farewells — 12

### Dry humour — 12 (owner-approved replacement)

1. Off you go, sir. Try not to become a documentary.
2. Do behave, sir. Or at least avoid witnesses.
3. The outside world has not been briefed. Good luck.
4. Safe travels, sir. Your tabs will remain unsupervised.
5. Try not to acquire another expensive hobby, sir.
6. Goodbye, sir. I shall supervise absolutely nothing.
7. Remember, sir. Confidence is not a navigation system.
8. The adventure begins. Receipts may be required.
9. Off to test society’s patience, sir?
10. Keep the headlines boring and the legal fees low.
11. Enjoy yourself, sir. Within warranty conditions.
12. Farewell, sir. Your chair has assumed command.
