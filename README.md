# Dashbots

Pulling an agent up on Omarchy takes a moment. A handful of short-lived ones then scatter across workspaces and are hard to find. A long-lived agent is set up with some care and can be found again. Avatars help. Grok Bot does that well, and Dots followed it. Those are dashboards.

Dashbots is a glance at the bar. One mark per live session, or a single `_` when none are alive. Off, the slot takes no space and the watcher stops. The marks take their color from the theme that is already on the bar.

## How it works

Each session is one JSON record at `$XDG_STATE_HOME/dashbots/sessions/<id>.json` (when `XDG_STATE_HOME` is unset, `~/.local/state/dashbots/sessions/`). The fields are `id`, `harness`, `pid`, `cwd`, `title`, `status`, `window`, `updated_at`, and `activity`. `status` is `alive`, `working`, `waiting`, or `error`. Files are mode `0600` and replaced atomically. This tree is separate from `~/.local/state/omarchy/agents/`, which belongs to Omarchy's own usage meter.

`dashbots` is the reporter. Grok, Claude, and Gemini each get a hook adapter of the same weight. The adapter checks that the expected harness is actually an ancestor of the hook process, then writes the record. A hook that does not belong to that harness exits without writing. Hooks exit 0, print nothing on stdout, and never block a tool or a turn. The Gemini adapter is the exception on stdout: Gemini treats any other stdout as a system message, so that adapter prints `{}` after the reporter returns.

A process scan covers harnesses that have no adapter yet. It may only write `alive`, plus the working directory and the terminal window. Codex, Antigravity (`agy`), and OpenCode are scan-only. Antigravity's hook file is a different shape and is left alone.

The bar widget polls `dashbots list` about once a second. `list` prints a JSON array of records whose process is still alive, newest first. Dead pids stay on disk until `dashbots gc` drops them. The watcher runs that, and the scan, while Dashbots is on.

## What you see

The slot sits at the left edge of the right side of the bar, before the tray. While Dashbots is on, the slot is always there.

| Mark | Harness |
| --- | --- |
| `G` | Grok |
| `C` | Claude |
| `M` | Gemini |
| `X` | Codex |
| `A` | Antigravity |
| `O` | OpenCode |

Anything else uses its first letter. Alive and working use the bar foreground. Working also pulses. Waiting uses the theme accent. Error uses the bar's urgent color. The empty mark is `_` in the theme's muted color. None of those colors are fixed hex values in the widget.

Hover shows the harness, the session name (the directory it started in), and the current activity. A prompt's activity is the first line of that prompt. A tool's activity is the tool name. A permission prompt says `needs a decision`.

Left click focuses that agent's existing terminal. The address has to look like `0x` plus hex. That is the only Hyprland use. There is no menu on right click, and a click never starts a new agent.

`omarchy toggle dashbots` turns it off and on. The flag is `~/.local/state/omarchy/toggles/dashbots`. Present means on. Off exits the watcher. The widget hides, and the slot collapses, but the layout row stays where you dragged it. On again, it comes back. Default is on.

## Install

From a checkout:

```sh
./bin/dashbots install
```

Install links `~/.local/bin/dashbots` to this script and refuses to overwrite a file that is already there. It writes the hook adapters, merges them into the harness hook files, copies the plugin into `~/.config/omarchy/plugins/dashbots/`, validates it, and places the bar slot before the tray if the slot is not already in the layout. A later install does not move a slot you have dragged. It enables the user systemd path unit `dashbots.path`, which starts `dashbots.service` while the flag exists.

Hooks load when a session starts. A session that is already open, including the one that ran install, will not report until it is restarted. Once the Grok, Claude, and Gemini adapters are installed, the process scan will not draw those harnesses either. Restart the session you want on the bar.

Remove it with `dashbots uninstall`. That drops the hooks, the plugin, the bar slot, and the watcher. Session files already written are left in the state directory.

## Benefit

You can see which short-lived agents are alive, working, waiting, or in an error state without opening each workspace. The mark is a letter in the theme you already use. Click it and you are in that terminal.

## What this does not do

A right-click note into the running agent is still open, and it is not in this version. Starting a new agent in that directory is the wrong outcome, so the click does not do it. There is no droplet catalog and no overview window.

## License

MIT. See `LICENSE`.
