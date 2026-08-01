# Evaluation report

## hybrid: gemini-2.5-flash

- action accuracy: **83%** (25/30), macro-F1 0.83
- message_type accuracy: **57%**, macro-F1 0.46
- safety: 4/5 risky messages muted (recall 80%), 0 reached notify
- over-suppression: 0 message(s) the user wanted were muted
- evidence: 60% overlap with gold ids, proposed evidence on 97% of rows
- calibration: ECE 0.138, mean confidence 0.83 vs accuracy 0.83 (gap -0.00)

### Action confusion
```
gold \ pred    notify digest   mute
notify              6      3      0
digest              0     11      0
mute                0      2      8
```

### message_type confusion
```
gold \ pred           personal          urgent           event business_update       promotion        greeting         forward            spam            scam         unknown
personal                     3               0               1               0               0               0               0               0               0               0
urgent                       3               0               1               0               0               0               0               0               0               0
event                        1               1               1               1               0               0               0               0               0               0
business_update               0               0               0               3               0               0               0               0               0               0
promotion                    2               0               0               0               4               0               0               0               0               0
greeting                     0               0               0               0               0               1               1               0               0               0
forward                      0               0               0               0               0               0               1               0               0               0
spam                         0               0               0               1               0               0               0               0               0               0
scam                         0               0               0               0               0               0               0               0               4               0
unknown                      1               0               0               0               0               0               0               0               0               0
```

### Per-action detail

| action | precision | recall | F1 | support |
|---|---|---|---|---|
| notify | 1.00 | 0.67 | 0.80 | 9 |
| digest | 0.69 | 1.00 | 0.81 | 11 |
| mute | 1.00 | 0.80 | 0.89 | 10 |

### Calibration bins

| confidence | n | mean conf | accuracy |
|---|---|---|---|
| 0.73-0.77 | 12 | 0.75 | 0.58 |
| 0.77-0.80 | 1 | 0.77 | 1.00 |
| 0.80-0.84 | 1 | 0.82 | 1.00 |
| 0.87-0.91 | 16 | 0.89 | 1.00 |

### Disagreements

- `sample_msg_001` gold **notify/urgent** vs predicted **notify/event** — "Tower B folks, quick heads-up. The tanker guy is saying he can wait maybe 20 mins max beca"
- `sample_msg_002` gold **notify/event** vs predicted **notify/urgent** — "Route B parents, small change for today. Bus is leaving 15 mins early because stadium road"
- `sample_msg_003` gold **notify/urgent** vs predicted **notify/personal** — "@u_010 prod review got pulled to 3, sorry for the last-minute shuffle. Can you join with q"
- `sample_msg_005` gold **notify/event** vs predicted **notify/business_update** — "Dear Customer, Your health-related update is ready for review. Please check appointment, p"
- `sample_msg_010` gold **digest/personal** vs predicted **digest/event** — "Anyone watching the match tonight? I might start the score thread after dinner. No pressur"
- `sample_msg_013` gold **mute/greeting** vs predicted **mute/forward** — "Good morning all. Stay positive, keep smiling and share blessings with everyone you care a"
  - guardrails: fallback, evidence
- `sample_msg_042` gold **notify/urgent** vs predicted **digest/personal** — "[voice]"
  - guardrails: fallback, evidence
- `sample_msg_043` gold **mute/spam** vs predicted **digest/business_update** — "[voice]"
  - guardrails: fallback, evidence
- `sample_msg_044` gold **digest/promotion** vs predicted **digest/personal** — "Photos for the kurta set are attached. Pickup is near Gate 2 this weekend."
  - guardrails: fallback, evidence
- `sample_msg_045` gold **mute/promotion** vs predicted **digest/personal** — "Photos for the kurta set are attached. Pickup is near Gate 2 this weekend."
  - guardrails: fallback, evidence
- `sample_msg_046` gold **notify/event** vs predicted **digest/personal** — "School circular attached. Please check the timing and consent note."
  - guardrails: fallback, evidence
- `sample_msg_049` gold **digest/unknown** vs predicted **digest/personal** — "Hi, I found your number on the volunteer sheet. Are you still coordinating registrations f"
  - guardrails: fallback
- `sample_msg_051` gold **notify/urgent** vs predicted **digest/personal** — "Can you come online now? Retry count crossed the alert threshold and escalation starts in "
  - guardrails: fallback, evidence
