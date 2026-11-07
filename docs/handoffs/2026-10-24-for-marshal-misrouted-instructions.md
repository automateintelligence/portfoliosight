# Handoff for Marshal: instructions Jeff meant for you (sent to the portfoliosight session by mistake)

Written 2026-10-24 by the portfoliosight session. On the afternoon of 2026-10-24, Jeff typed
several orchestration messages into the portfoliosight session, thinking it was Marshal (the
"Multi-project orchestration system" session). This hands them to you.

## What Jeff asked you
1. "Give me brief status on all sessions. Label each session by project/repo. Priorities?"
2. He then narrowed it:
   - **Scope:** only the sessions he has already assigned you to monitor, not every session.
   - **Session to project:**
     - "RTSP video pipeline design" is **SecuritySight**.
     - "Plan MCP authentication for Bedrock models" and "EXP-04 control arm progress update" are
       **KnowledgeSight**.
     - "Multi-project orchestration system" is **you**.
   - **Order matters:** "Some of these sessions are blocking others and need to be completed in the
     correct order." Get the blocking order right before advancing any session.

## How Jeff wants you to work (standing guidance)
- **Delegate digging, keep your context.** "Think about your role. There is an economic balance of
  speed vs preserving your context window. Should you be looking, or should you send a message to
  the other session instructing it to investigate?" Send investigations to the session or agent
  that already has the context, and keep your own context for coordination.
- **Weigh tokens.** "If you feel you have sufficient context you could write [it yourself]. If you
  need to seek additional context to do so, maybe not." A message to another session costs your
  output tokens to write, plus that session's input tokens to read it. Output is five times
  dearer:
  - Opus 5.5 input: $4.00 per million tokens.
  - Opus 5.5 output: $20.00 per million tokens.

  As budget manager, write it yourself when you already hold the context; delegate when you would
  have to go and fetch it.
- **Be brief.** He replied "TLDR" to a long answer. Lead with the decision, as an a/b/c choice with
  its consequences, and keep the rest short.

## Session list as seen from portfoliosight (2026-10-24 12:43 PDT, titles and states only)
Nothing outside portfoliosight was running. Most cloud sessions were idle and most Remote Control
sessions were offline. Titles: RTSP video pipeline design (2), Bad detection feedback in
barkerstorage (2), Issuify spec in securitysight, Multi-project orchestration system, Neo4j
2026.09.0 pin re-lock (#458), Cloud session usage and credits, DMARC envelope_from domain issue,
Credential injection for AI agents, KnowledgeSight data integrations, Graphify update, App summary
for agent handoff, EXP-04 control arm progress update, Occupancy shadow results and global
cooldown, Language choice for IRA Planning Tool port, Return bar squished on frontend, Phase 0
status, Credits not appearing/usable, bigg7-mutable-beaver, Barkerstorage SS-barker issue,
Monitoring watch-rule-shadow and call-filter, Dispatch roadmap ideas, Sustained context design,
Plan MCP authentication for Bedrock models, Test video streaming with TCP protocol.

## portfoliosight, in one line (for your board)
The fixed-risk experiment is running. Both replay jobs are complete, research2003 GARCH is running
locally (about 2 days), TSP GARCH is pending a KS-002 launch fix, and an old-vs-new GARCH rule
calibration comparison is running. Details are in
`docs/handoffs/2026-10-24-fixed-risk-experiment-run.md` and protocol §11. It blocks nothing else
that we know of.

## Also tried in portfoliosight
Jeff tried `/grill-with-docs` (the grilling and domain-modeling skills) on a GARCH decision. It
produced `GLOSSARY.md` and ADR 0005 in two short rounds. It is available if he wants to grill a
cross-project ordering plan.
