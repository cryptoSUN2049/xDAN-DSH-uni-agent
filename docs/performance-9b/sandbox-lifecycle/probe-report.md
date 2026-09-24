# Modal sandbox lifecycle probe

- task: terminal-lego-15k__task_02873   app: __harbor_probe__   sandbox_timeout_secs: 2700
- started: 2026-09-18T00:52:27Z

## 1. Finished trial should release its sandbox
before: 0 sandbox(es)
during: 1 sandbox(es) (polled until one appeared)
trial exit=0
20 s after the trial finished: 0 sandbox(es)

## 2. Killed client: the leak we paid 358 USD for on 2026-09-17
during: 1 sandbox(es)
killed the Harbor CLI (pid 522562)
30 s after the kill: 1 sandbox(es)
90 s after the kill: 1 sandbox(es)

## 3. Cleanup collects whatever is left (probe app only)
app __harbor_probe__ (ap-2LdXSUIxqGtJw9PnoLnAYx): 1 sandbox(es) known to Modal
  stopped sb-woE1g2QrJAbWUai1VUKqRM age=2min
terminated 1, kept 0
after cleanup: 0 sandbox(es)

Finished: 2026-09-18T00:55:17Z
