# Prompt Automation Pro

Executes structured directives parsed from AI chat conversations.

An assistant writes a command into a chat. A browser extension recognises it,
a receiver ingests it, and a console turns it into an execution plan that an
operator advances step by step on the server. Results and files go back into
the chat through the same extension.

The system is deliberately not an autonomous agent runtime. Every step has an
explicit plan entry, an authorization decision made live at execution time, and
an audit record. What a run is allowed to do is frozen when the run is accepted;
whether it is still allowed to run is answered fresh on every step.

## How it works

Three components, three processes.

**Extension** — content scripts parse the assistant's message in ChatGPT and
Claude into structured items. Command markers follow `COMMAND_[A-Z0-9_]+`,
matched against a whole heading or paragraph block, never scanned loosely over
the page. The extension also delivers messages and files back into chats and
reports what it observes about tabs; it never decides what should happen.

**Receiver** (`server.py`, port 8867) — accepts a parse plus its attachments,
stages them until every expected file has arrived, computes a content
fingerprint, and either publishes a canonical Run or records a duplicate. Runs
live as directories under `data/`. The receiver is stdlib-only and holds no
configuration authority.

**Console** (`console_releases/<version>/`, port 8871) — compiles the parse into
an execution plan, applies the authorization gate, runs steps, streams logs,
resolves delivery targets, and serves the operator web UI.

## Core concepts

**Profile** — the configuration a run executes by: prompts, variables, directive
definitions, error-detection rules, delivery settings.

**Binding** — operator configuration linking one existing chat to a profile and a
role. Only the operator creates bindings.

**Run** — one accepted parse and its execution state. A run is created from an
immutable, content-addressed snapshot of the profile, so editing a profile never
changes how a run already in flight behaves.

**Live authorization** — provenance is frozen, permission is not. Disabling the
profile, or revoking or repointing the binding, blocks the next step of a run
that was already accepted.

**Automatic error detection** — the executor scans combined stdout and stderr for
high-confidence toolchain failures and stops the step even when the declared
`STOP_RUN`/`CONTINUE_RUN` criteria would allow continuing. Ordinary assertion
text is deliberately not treated as infrastructure failure.

## Repository layout

```
server.py                     receiver
platform_manager.py           platform process management
console_releases/<version>/   console releases; one is active at a time
extension/                    browser extension
packaging/                    release installer and manifests
docs/                         design documents and the decision journal
```

Console releases are versioned directories rather than branches: the running
release is selected by a marker file, so a release can be activated and rolled
back without touching the working tree.

## Development

Work proceeds in vertical slices, each independently verifiable and
independently reversible. The design document carries a decision journal; the
implementation map pins every planned change to exact byte ranges of a named
working base, and a verification chain checks that the map still describes the
code it claims to describe:

```
source bytes -> verify_inventory.py -> inventory.json -> verify_overlaps.py
             -> implementation map  -> verify_map.py
```

A working base is identified by a digest over the basis files, not by a commit,
so the chain holds whether or not a repository is present.

## Status

Platform 4.3.5, console 4.4.0, receiver 2.10.0, extension 2.11.6 in service.
Release 4.5.0 is under development.
