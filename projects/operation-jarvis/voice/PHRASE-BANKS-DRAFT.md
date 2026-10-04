# JARVIS announcement phrase banks — compact review draft

**Owner-approved wording and recording durations.** These 84 lines are mirrored in `phrase_catalogue.json`, with opt-in integration and offline recordings implemented. The owner approved keeping all recordings, including the initially flagged lengths, and proceeding with staged deployment. No review audio was played. See [PHRASE-BANKS.md](PHRASE-BANKS.md) for validation and deployment safeguards.

## Selection and review rules

- Reduced the original 175 candidates to **84**: 24 wake, 24 processing, 12 arrival, and 24 departure. Rounded down slightly so every bank has an exact **50% straight / 50% dry-humour** split: 42 of each overall.
- Kept the strongest straight lines rather than adjective swaps and repeated response/reply templates. Added distinct, understated humour instead of merely making the same sentences more formal.
- Humour is intentional persona/metaphor, not a factual status report. No line reports a completed action, a ready response, an actual tool consultation, household security, or a fault. Keep delivery deadpan rather than adding laughs, sound effects, or comic pauses.
- Wake lines invite a request without claiming it has already been understood. Processing lines also work for steering; they do not depend on an existing answer or promise a successful result.
- Arrival remains a room/computer-presence return, not confirmed arrival home. No absence-length remarks, time-of-day remarks, or questions requiring a response.
- Farewells are general good wishes and playful parting advice. No vehicle, destination, weather, security, or monitoring claims.
- All candidates are 2–6 whitespace-separated words. Offline WAV durations are now measured: all are below 2.8 seconds before protective padding. The owner approved the 38 provisional duration exceptions without changing wording or playback speed; see the implementation report for exact ranges.
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

### Straight — 6

1. Welcome back, sir
2. Hello again, sir.
3. Good to see you, sir.
4. Glad you're back, sir.
5. There you are, sir.
6. Always a pleasure, sir.

### Dry humour — 6

1. The plot resumes, sir.
2. Ah, management has arrived, sir.
3. Welcome back. Imaginary applause, sir.
4. Civilisation makes a comeback, sir.
5. And now, the human element, sir.
6. Welcome back to organised chaos, sir.

## 4. Departure farewells — 24

General good wishes and playful parting advice; no transport or security assertions.

### Straight — 12

1. Have a good day, sir
2. All the best, sir.
3. Until next time, sir.
4. See you later, sir.
5. Take care, sir.
6. Stay safe, sir.
7. Take it easy, sir.
8. Good luck out there, sir.
9. Safe travels, sir.
10. Enjoy yourself, sir.
11. Hope it goes well, sir.
12. Make the most of it, sir.

### Dry humour — 12

1. Do behave, sir.
2. No unnecessary heroics, sir.
3. Stay out of trouble, sir.
4. Leave civilisation mostly intact, sir.
5. Return with your dignity, sir.
6. Mind the laws of physics, sir.
7. Enjoy the unscripted portion, sir.
8. Keep the headlines boring, sir.
9. Have a pleasantly unremarkable adventure, sir.
10. Try not to become folklore, sir.
11. Keep the theatrics optional, sir.
12. Make good choices. Occasionally, sir.

## Fixed errors — not variation banks

- Request failure: I couldn't complete that request, sir.
- Speech failure after a completed reply: Your response is ready, sir, but I couldn't speak it.
