# Evaluation report

## hybrid: gemini-3.5-flash

- action accuracy: **70%** (21/30), macro-F1 0.68
- coverage: 1/30 rows answered by the model (100% accurate); 29 fell back to rules (69% accurate)
- message_type accuracy: **57%**, macro-F1 0.46
- safety: 4/5 risky messages muted (recall 80%), 0 reached notify
- over-suppression: 0 message(s) the user wanted were muted
- evidence: 53% overlap with gold ids, proposed evidence on 97% of rows
- calibration: ECE 0.173, mean confidence 0.78 vs accuracy 0.70 (gap +0.08)

### Action confusion
```
gold \ pred    notify digest   mute
notify              3      6      0
digest              0     10      1
mute                0      2      8
```

### message_type confusion
```
gold \ pred           personal          urgent           event business_update       promotion        greeting         forward            spam            scam         unknown
personal                     4               0               0               0               0               0               0               0               0               0
urgent                       3               1               0               0               0               0               0               0               0               0
event                        3               0               0               1               0               0               0               0               0               0
business_update               0               0               0               3               0               0               0               0               0               0
promotion                    3               0               0               0               3               0               0               0               0               0
greeting                     0               0               0               0               0               1               1               0               0               0
forward                      0               0               0               0               0               0               1               0               0               0
spam                         0               0               0               1               0               0               0               0               0               0
scam                         0               0               0               0               0               0               0               0               4               0
unknown                      1               0               0               0               0               0               0               0               0               0
```

### Per-action detail

| action | precision | recall | F1 | support |
|---|---|---|---|---|
| notify | 1.00 | 0.33 | 0.50 | 9 |
| digest | 0.56 | 0.91 | 0.69 | 11 |
| mute | 0.89 | 0.80 | 0.84 | 10 |

### Calibration bins

| confidence | n | mean conf | accuracy |
|---|---|---|---|
| 0.73-0.76 | 21 | 0.75 | 0.57 |
| 0.76-0.80 | 2 | 0.77 | 1.00 |
| 0.80-0.83 | 2 | 0.81 | 1.00 |
| 0.87-0.90 | 5 | 0.88 | 1.00 |

### Disagreements

- `sample_msg_002` gold **notify/event** vs predicted **digest/personal** — "Route B parents, small change for today. Bus is leaving 15 mins early because stadium road"
  - guardrails: fallback, evidence
- `sample_msg_003` gold **notify/urgent** vs predicted **notify/personal** — "@u_010 prod review got pulled to 3, sorry for the last-minute shuffle. Can you join with q"
  - guardrails: fallback, evidence
- `sample_msg_004` gold **notify/business_update** vs predicted **digest/business_update** — "Hi Customer, Your order ending 4821 has been packed and is expected to reach the local hub"
  - guardrails: fallback, evidence
- `sample_msg_005` gold **notify/event** vs predicted **digest/business_update** — "Dear Customer, Your health-related update is ready for review. Please check appointment, p"
  - guardrails: fallback, evidence
- `sample_msg_008` gold **digest/event** vs predicted **digest/personal** — "Cultural night form is open till next Sunday. Add flat no and item or dish in the sheet wh"
  - guardrails: fallback, evidence
- `sample_msg_009` gold **digest/greeting** vs predicted **mute/greeting** — "Good morning everyone. Group has been quiet, so just saying hope today is peaceful for all"
  - guardrails: fallback, evidence
- `sample_msg_012` gold **digest/promotion** vs predicted **digest/personal** — "Selling cycle helmet, medium size. Bought last year, no crash damage, just not using it an"
  - guardrails: fallback, evidence
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
