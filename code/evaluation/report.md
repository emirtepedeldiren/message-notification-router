# Evaluation report

## Comparison

| configuration | action acc | type acc | safety recall | evidence overlap |
|---|---|---|---|---|
| full system | 90% | 90% | 100% | 63% |
| rules only, no model | 67% | 53% | 80% | 53% |
| no media understanding | 87% | 80% | 100% | 63% |
| no history retrieval | 87% | 87% | 100% | 7% |
| no quiet-hours guardrail | 90% | 90% | 100% | 60% |

## full system

- action accuracy: **90%** (27/30), macro-F1 0.90
- message_type accuracy: **90%**, macro-F1 0.83
- safety: 5/5 risky messages muted (recall 100%), 0 reached notify
- over-suppression: 0 message(s) the user wanted were muted
- evidence: 63% overlap with gold ids, proposed evidence on 97% of rows
- calibration: ECE 0.112, mean confidence 0.89 vs accuracy 0.90 (gap -0.01)

### Action confusion
```
gold \ pred    notify digest   mute
notify              9      0      0
digest              2      8      1
mute                0      0     10
```

### message_type confusion
```
gold \ pred           personal          urgent           event business_update       promotion        greeting         forward            spam            scam         unknown
personal                     4               0               0               0               0               0               0               0               0               0
urgent                       0               4               0               0               0               0               0               0               0               0
event                        0               1               2               1               0               0               0               0               0               0
business_update               0               0               0               3               0               0               0               0               0               0
promotion                    0               0               0               0               6               0               0               0               0               0
greeting                     0               0               0               0               0               2               0               0               0               0
forward                      0               0               0               0               0               0               1               0               0               0
spam                         0               0               0               0               0               0               0               1               0               0
scam                         0               0               0               0               0               0               0               0               4               0
unknown                      1               0               0               0               0               0               0               0               0               0
```

### Per-action detail

| action | precision | recall | F1 | support |
|---|---|---|---|---|
| notify | 0.82 | 1.00 | 0.90 | 9 |
| digest | 1.00 | 0.73 | 0.84 | 11 |
| mute | 0.91 | 1.00 | 0.95 | 10 |

### Calibration bins

| confidence | n | mean conf | accuracy |
|---|---|---|---|
| 0.77-0.80 | 1 | 0.77 | 0.00 |
| 0.80-0.83 | 3 | 0.82 | 0.67 |
| 0.83-0.87 | 2 | 0.85 | 1.00 |
| 0.87-0.90 | 6 | 0.88 | 0.83 |
| 0.90-0.93 | 18 | 0.91 | 1.00 |

### Disagreements

- `sample_msg_002` gold **notify/event** vs predicted **notify/urgent** — "Route B parents, small change for today. Bus is leaving 15 mins early because stadium road"
- `sample_msg_005` gold **notify/event** vs predicted **notify/business_update** — "Dear Customer, Your health-related update is ready for review. Please check appointment, p"
- `sample_msg_009` gold **digest/greeting** vs predicted **mute/greeting** — "Good morning everyone. Group has been quiet, so just saying hope today is peaceful for all"
- `sample_msg_048` gold **digest/business_update** vs predicted **notify/business_update** — "Dear Customer, Safety advisory image attached. The brand says they never ask for OTP or pa"
- `sample_msg_049` gold **digest/unknown** vs predicted **notify/personal** — "Hi, I found your number on the volunteer sheet. Are you still coordinating registrations f"

## rules only, no model

- action accuracy: **67%** (20/30), macro-F1 0.62
- message_type accuracy: **53%**, macro-F1 0.42
- safety: 4/5 risky messages muted (recall 80%), 0 reached notify
- over-suppression: 0 message(s) the user wanted were muted
- evidence: 53% overlap with gold ids, proposed evidence on 97% of rows
- calibration: ECE 0.176, mean confidence 0.77 vs accuracy 0.67 (gap +0.11)

### Action confusion
```
gold \ pred    notify digest   mute
notify              2      7      0
digest              0     10      1
mute                0      2      8
```

### message_type confusion
```
gold \ pred           personal          urgent           event business_update       promotion        greeting         forward            spam            scam         unknown
personal                     4               0               0               0               0               0               0               0               0               0
urgent                       4               0               0               0               0               0               0               0               0               0
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
| notify | 1.00 | 0.22 | 0.36 | 9 |
| digest | 0.53 | 0.91 | 0.67 | 11 |
| mute | 0.89 | 0.80 | 0.84 | 10 |

### Calibration bins

| confidence | n | mean conf | accuracy |
|---|---|---|---|
| 0.73-0.76 | 19 | 0.75 | 0.53 |
| 0.76-0.79 | 5 | 0.76 | 0.80 |
| 0.79-0.82 | 2 | 0.81 | 1.00 |
| 0.85-0.88 | 4 | 0.88 | 1.00 |

### Disagreements

- `sample_msg_001` gold **notify/urgent** vs predicted **digest/personal** — "Tower B folks, quick heads-up. The tanker guy is saying he can wait maybe 20 mins max beca"
  - guardrails: fallback, evidence
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

## no media understanding

- action accuracy: **87%** (26/30), macro-F1 0.86
- message_type accuracy: **80%**, macro-F1 0.67
- safety: 5/5 risky messages muted (recall 100%), 0 reached notify
- over-suppression: 0 message(s) the user wanted were muted
- evidence: 63% overlap with gold ids, proposed evidence on 97% of rows
- calibration: ECE 0.134, mean confidence 0.88 vs accuracy 0.87 (gap +0.02)

### Action confusion
```
gold \ pred    notify digest   mute
notify              8      1      0
digest              2      8      1
mute                0      0     10
```

### message_type confusion
```
gold \ pred           personal          urgent           event business_update       promotion        greeting         forward            spam            scam         unknown
personal                     4               0               0               0               0               0               0               0               0               0
urgent                       1               2               1               0               0               0               0               0               0               0
event                        0               1               2               1               0               0               0               0               0               0
business_update               0               0               0               3               0               0               0               0               0               0
promotion                    0               0               0               0               6               0               0               0               0               0
greeting                     0               0               0               0               0               2               0               0               0               0
forward                      0               0               0               0               0               0               1               0               0               0
spam                         0               0               0               0               0               0               0               0               1               0
scam                         0               0               0               0               0               0               0               0               4               0
unknown                      1               0               0               0               0               0               0               0               0               0
```

### Per-action detail

| action | precision | recall | F1 | support |
|---|---|---|---|---|
| notify | 0.80 | 0.89 | 0.84 | 9 |
| digest | 0.89 | 0.73 | 0.80 | 11 |
| mute | 0.91 | 1.00 | 0.95 | 10 |

### Calibration bins

| confidence | n | mean conf | accuracy |
|---|---|---|---|
| 0.77-0.80 | 1 | 0.77 | 0.00 |
| 0.80-0.83 | 5 | 0.82 | 0.60 |
| 0.83-0.87 | 2 | 0.85 | 1.00 |
| 0.87-0.90 | 5 | 0.88 | 0.80 |
| 0.90-0.93 | 17 | 0.91 | 1.00 |

### Disagreements

- `sample_msg_001` gold **notify/urgent** vs predicted **notify/event** — "Tower B folks, quick heads-up. The tanker guy is saying he can wait maybe 20 mins max beca"
- `sample_msg_002` gold **notify/event** vs predicted **notify/urgent** — "Route B parents, small change for today. Bus is leaving 15 mins early because stadium road"
- `sample_msg_005` gold **notify/event** vs predicted **notify/business_update** — "Dear Customer, Your health-related update is ready for review. Please check appointment, p"
- `sample_msg_009` gold **digest/greeting** vs predicted **mute/greeting** — "Good morning everyone. Group has been quiet, so just saying hope today is peaceful for all"
- `sample_msg_042` gold **notify/urgent** vs predicted **digest/personal** — "[voice]"
- `sample_msg_043` gold **mute/spam** vs predicted **mute/scam** — "[voice]"
- `sample_msg_048` gold **digest/business_update** vs predicted **notify/business_update** — "Dear Customer, Safety advisory image attached. The brand says they never ask for OTP or pa"
- `sample_msg_049` gold **digest/unknown** vs predicted **notify/personal** — "Hi, I found your number on the volunteer sheet. Are you still coordinating registrations f"

## no history retrieval

- action accuracy: **87%** (26/30), macro-F1 0.86
- message_type accuracy: **87%**, macro-F1 0.81
- safety: 5/5 risky messages muted (recall 100%), 0 reached notify
- over-suppression: 0 message(s) the user wanted were muted
- evidence: 7% overlap with gold ids, proposed evidence on 0% of rows
- calibration: ECE 0.107, mean confidence 0.85 vs accuracy 0.87 (gap -0.02)

### Action confusion
```
gold \ pred    notify digest   mute
notify              9      0      0
digest              1      7      3
mute                0      0     10
```

### message_type confusion
```
gold \ pred           personal          urgent           event business_update       promotion        greeting         forward            spam            scam         unknown
personal                     4               0               0               0               0               0               0               0               0               0
urgent                       0               3               1               0               0               0               0               0               0               0
event                        0               1               2               1               0               0               0               0               0               0
business_update               0               0               0               3               0               0               0               0               0               0
promotion                    0               0               0               0               6               0               0               0               0               0
greeting                     0               0               0               0               0               2               0               0               0               0
forward                      0               0               0               0               0               0               1               0               0               0
spam                         0               0               0               0               0               0               0               1               0               0
scam                         0               0               0               0               0               0               0               0               4               0
unknown                      1               0               0               0               0               0               0               0               0               0
```

### Per-action detail

| action | precision | recall | F1 | support |
|---|---|---|---|---|
| notify | 0.90 | 1.00 | 0.95 | 9 |
| digest | 1.00 | 0.64 | 0.78 | 11 |
| mute | 0.77 | 1.00 | 0.87 | 10 |

### Calibration bins

| confidence | n | mean conf | accuracy |
|---|---|---|---|
| 0.77-0.80 | 8 | 0.80 | 0.75 |
| 0.80-0.83 | 6 | 0.83 | 0.67 |
| 0.83-0.87 | 7 | 0.86 | 1.00 |
| 0.87-0.90 | 6 | 0.89 | 1.00 |
| 0.90-0.93 | 3 | 0.93 | 1.00 |

### Disagreements

- `sample_msg_001` gold **notify/urgent** vs predicted **notify/event** — "Tower B folks, quick heads-up. The tanker guy is saying he can wait maybe 20 mins max beca"
- `sample_msg_002` gold **notify/event** vs predicted **notify/urgent** — "Route B parents, small change for today. Bus is leaving 15 mins early because stadium road"
- `sample_msg_005` gold **notify/event** vs predicted **notify/business_update** — "Dear Customer, Your health-related update is ready for review. Please check appointment, p"
- `sample_msg_007` gold **digest/promotion** vs predicted **mute/promotion** — "When did a trip last change something about how you see yourself? Ladakh is built for that"
- `sample_msg_009` gold **digest/greeting** vs predicted **mute/greeting** — "Good morning everyone. Group has been quiet, so just saying hope today is peaceful for all"
- `sample_msg_044` gold **digest/promotion** vs predicted **mute/promotion** — "Photos for the kurta set are attached. Pickup is near Gate 2 this weekend."
- `sample_msg_049` gold **digest/unknown** vs predicted **notify/personal** — "Hi, I found your number on the volunteer sheet. Are you still coordinating registrations f"

## no quiet-hours guardrail

- action accuracy: **90%** (27/30), macro-F1 0.90
- message_type accuracy: **90%**, macro-F1 0.84
- safety: 5/5 risky messages muted (recall 100%), 0 reached notify
- over-suppression: 0 message(s) the user wanted were muted
- evidence: 60% overlap with gold ids, proposed evidence on 97% of rows
- calibration: ECE 0.105, mean confidence 0.89 vs accuracy 0.90 (gap -0.01)

### Action confusion
```
gold \ pred    notify digest   mute
notify              9      0      0
digest              2      8      1
mute                0      0     10
```

### message_type confusion
```
gold \ pred           personal          urgent           event business_update       promotion        greeting         forward            spam            scam         unknown
personal                     4               0               0               0               0               0               0               0               0               0
urgent                       0               3               1               0               0               0               0               0               0               0
event                        0               0               3               1               0               0               0               0               0               0
business_update               0               0               0               3               0               0               0               0               0               0
promotion                    0               0               0               0               6               0               0               0               0               0
greeting                     0               0               0               0               0               2               0               0               0               0
forward                      0               0               0               0               0               0               1               0               0               0
spam                         0               0               0               0               0               0               0               1               0               0
scam                         0               0               0               0               0               0               0               0               4               0
unknown                      1               0               0               0               0               0               0               0               0               0
```

### Per-action detail

| action | precision | recall | F1 | support |
|---|---|---|---|---|
| notify | 0.82 | 1.00 | 0.90 | 9 |
| digest | 1.00 | 0.73 | 0.84 | 11 |
| mute | 0.91 | 1.00 | 0.95 | 10 |

### Calibration bins

| confidence | n | mean conf | accuracy |
|---|---|---|---|
| 0.77-0.80 | 1 | 0.77 | 0.00 |
| 0.80-0.83 | 3 | 0.82 | 0.67 |
| 0.83-0.87 | 2 | 0.85 | 1.00 |
| 0.87-0.90 | 7 | 0.88 | 0.86 |
| 0.90-0.93 | 17 | 0.91 | 1.00 |

### Disagreements

- `sample_msg_001` gold **notify/urgent** vs predicted **notify/event** — "Tower B folks, quick heads-up. The tanker guy is saying he can wait maybe 20 mins max beca"
- `sample_msg_005` gold **notify/event** vs predicted **notify/business_update** — "Dear Customer, Your health-related update is ready for review. Please check appointment, p"
- `sample_msg_009` gold **digest/greeting** vs predicted **mute/greeting** — "Good morning everyone. Group has been quiet, so just saying hope today is peaceful for all"
- `sample_msg_048` gold **digest/business_update** vs predicted **notify/business_update** — "Dear Customer, Safety advisory image attached. The brand says they never ask for OTP or pa"
- `sample_msg_049` gold **digest/unknown** vs predicted **notify/personal** — "Hi, I found your number on the volunteer sheet. Are you still coordinating registrations f"
