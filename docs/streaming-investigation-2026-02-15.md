# Streaming Output & Performance Investigation - 2026-02-15

## Initial Question

> There is a notable delay in responding to the user. This may give the user the impression that the app is not working. We somewhat mitigate this by returning a pending message, but I'd like to explore if we can do more. `handle_message()` in `main.py` sends its complete output from the subprocess only when the subprocess completes. Is it possible to stream the output received to the user while the subprocess is still running?

### Response

Yes, this is very doable. Instead of `subprocess.run()` (which waits for completion), you can use `subprocess.Popen()` to read stdout incrementally and update the Slack message as chunks arrive.

The approach:

1. Use `subprocess.Popen` instead of `subprocess.run`
2. Read stdout line-by-line (or in chunks) as it's produced
3. Periodically call `chat_update` to refresh the pending message with accumulated output
4. Throttle updates to avoid hitting Slack API rate limits (e.g., update at most every 1-2 seconds)

An initial streaming implementation was written using `Popen` with line-by-line reading and periodic `chat_update` calls.

---

## Deploy and Test

> deploy this and test it

Deployed to LXC container at `LXC_HOST` using `./deploy/deploy.sh`.

**Result:** User discarded the changes. The delay wasn't actually in Claude - running Claude on the command line on the deployed server was very responsive compared to the response delay via Slack.

---

## Adding Timing Instrumentation

> The delay is not actually Claude. I ran Claude on the command line on the deployed server and it was very responsive compared to the response delay via Slack. Let's measure the time spent in the Claude subprocess and log that.

Added timing around:
- Claude subprocess execution time
- `chat_update` Slack API call time

### First Timing Results

| Step | Time |
|---|---|
| Claude subprocess | **30.83s** |
| chat_update (Slack API) | **0.22s** |

The delay was almost entirely in the Claude subprocess (31 seconds). The Slack API call was negligible.

---

## CLI Baseline Comparison

> When I run the same prompt directly on the LXC container:
> ```
> $ time echo "What chardonnay wines do I have?" | claude --allowedTools "Bash(*)" -p "/winebuddy output for Slack mrkdwn, not markdown"
> real    0m14.895s
> ```

~15s on the CLI vs ~31s via the app - roughly double.

### Granular Timing Added

Added more timing breakdowns:
- Pending message send time (`say()` call)
- Claude subprocess time
- `chat_update` time
- Total handler time

### Second Timing Results

| Step | Time |
|---|---|
| Pending message (`say()`) | 0.16s |
| Claude subprocess | **69.93s** |
| chat_update | 0.24s |
| **Total** | **70.33s** |

The overhead was entirely in the Claude subprocess - and this time it took 70s, even worse than the previous 31s run.

---

## Isolating the Subprocess Mechanism

> User created a `measure.py` script and ran it directly on the LXC container via Doppler.

### measure.py Results (7 runs)

| Run | Time |
|---|---|
| 1 | 20.38s |
| 2 | 12.31s |
| 3 | 16.28s |
| 4 | 14.21s |
| 5 | 17.14s |
| 6 | 33.36s |
| 7 | 17.61s |

**Conclusion:** The subprocess via `measure.py` shows 12-33s - the same range as the CLI. There's no meaningful overhead from `subprocess.run` or the Slack app. It's just natural API response time variance. The problem is purely perceptual.

---

## Implementing Streaming with `--output-format stream-json`

The first attempt at streaming with `Popen` and line-by-line reading didn't work because `claude -p` in text mode buffers its entire response and writes it all to stdout at once.

### Discovery: `--output-format stream-json`

The Claude CLI supports `--output-format stream-json --verbose` which emits JSON events as Claude works (each assistant turn, tool use, etc.).

### Implementation

Updated `handle_message()` to:
1. Use `--output-format stream-json --verbose` flags
2. Parse JSON events from stdout line-by-line
3. Extract text from `assistant` and `result` type events
4. Update Slack every 2 seconds with the latest text

**Result:** Streaming messages now appear in Slack as Claude progresses.

---

## Adding Stream Event Logging

> I do see messages coming in. Let's log how long it takes for messages to arrive from the sub-process along with the message.

Added elapsed time logging for each stream event with type and content preview.

### Stream Event Timeline - Run 1 (28s total)

| Time | Event |
|---|---|
| 1.9s | `system/init` |
| 4.2s | assistant: "I'll query your wine cellar..." |
| 5.2-5.5s | tool use + result |
| 9.1-9.3s | another tool attempt |
| 11.0-12.5s | "Let me try with python3..." |
| 14.6-15.6s | "checking uv..." |
| 16.0-16.1s | another tool attempt |
| 18.0-19.7s | "use the virtual environment" |
| 27.3s | Final response |

### Stream Event Timeline - Run 2 (77s total - Claude got stuck)

| Time | Event |
|---|---|
| 1.9s | `system/init` |
| 4-5s | "I'll query..." |
| 8-11s | tool attempts |
| 13-48s | Stuck retrying "check for Python package managers" (4 tool calls over 35s!) |
| 58-61s | "use full path to uv" |
| 76.7s | Final response |

### Root Cause Identified

Two issues visible:

1. **Claude is struggling to find/use `uv`** - it's trying multiple approaches each run (python3 directly, checking for uv, using .venv). BashTool pre-flight check warnings confirmed this.
2. **The variability is Claude's multi-turn tool use**, not API latency. When it finds the right path quickly: 28s. When it fumbles: 77s.

---

## Fix: Adding PATH to systemd Service

The systemd service was missing `/home/winebuddy/.local/bin` from its PATH, which is where `uv` lives. Added an `Environment=PATH=...` directive to `winebuddy.service`:

```ini
Environment=PATH=/home/winebuddy/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
```

Deployed the updated service file with `daemon-reload` and restart.

**Result:** Claude's Bash tool can now find `uv` directly without fumbling through multiple approaches, leading to faster and more consistent response times.

---

## Summary of Changes

1. **`main.py`** - Switched from `subprocess.run` to `subprocess.Popen` with `--output-format stream-json --verbose`, streaming partial responses to Slack every 2 seconds
2. **`deploy/winebuddy.service`** - Added `Environment=PATH=...` to ensure Claude's Bash tool can find `uv` in the service context
