#!/usr/bin/env bash
#
# Dashbots installer. Adds the Omarchy plugin, then runs `dashbots install`
# (CLI link, harness hooks, user units, menu row, bar slot).
#
# One line:
#   curl -fsSL https://raw.githubusercontent.com/Dayruke/dashbots/main/install.sh | bash
#
# From a clone, with the same Omarchy confirm prompt a bare `plugin add` uses:
#   ./install.sh
#
# The two commands this wraps:
#   omarchy plugin add https://github.com/Dayruke/dashbots.git --enable
#   ~/.config/omarchy/plugins/io.github.dayruke.dashbots/bin/dashbots install
#
# No extra packages. Nothing runs as root. `omarchy plugin add` still clones
# the repo. Piped (no TTY) skips the plugin-add confirm, same as --yes.
#
# Overrides:
#   DASHBOTS_REPO=user/repo     register from a fork
#   DASHBOTS_YES=1              skip plugin-add / plugin-update prompts
set -euo pipefail

REPO="${DASHBOTS_REPO:-Dayruke/dashbots}"
PLUGIN_ID="io.github.dayruke.dashbots"
# Omarchy and dashbots both use ~/.config here, not XDG_CONFIG_HOME.
PLUGIN_DIR="$HOME/.config/omarchy/plugins/${PLUGIN_ID}"
REPO_URL="https://github.com/${REPO}.git"

say() { printf '%s\n' "$*"; }
die() { say "$*" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
  die "Run this as your own user, not root. Dashbots installs under your home directory."
fi

command -v omarchy >/dev/null 2>&1 || die "This needs Omarchy 4 (the omarchy CLI is not on PATH)."
command -v python3 >/dev/null 2>&1 || die "This needs python3 on PATH."

# curl | bash has no TTY on stdin. omarchy plugin add would then either refuse
# or read the rest of this script as the confirm reply. --yes is the way through.
need_yes=0
if [ -n "${DASHBOTS_YES:-}" ] || [ ! -t 0 ] || [ ! -t 1 ]; then
  need_yes=1
fi

if [ -d "$PLUGIN_DIR/.git" ]; then
  say "==> ${PLUGIN_ID} is already there; updating"
  if [ "$need_yes" -eq 1 ]; then
    omarchy plugin update "$PLUGIN_ID" --yes
  else
    omarchy plugin update "$PLUGIN_ID"
  fi
elif [ -f "$PLUGIN_DIR/bin/dashbots" ]; then
  # A dev copy has no .git. `plugin update` refuses that and would stop here.
  say "==> ${PLUGIN_ID} is already there, and it is not a git checkout. Leaving those files."
else
  say "==> Adding ${PLUGIN_ID} from ${REPO}"
  if [ "$need_yes" -eq 1 ]; then
    omarchy plugin add "$REPO_URL" --enable --yes
  else
    omarchy plugin add "$REPO_URL" --enable
  fi
fi

DASHBOTS="${PLUGIN_DIR}/bin/dashbots"
if [ ! -f "$DASHBOTS" ]; then
  die "The plugin landed, but ${DASHBOTS} is missing. Check the clone at ${PLUGIN_DIR}."
fi

say "==> Running dashbots install (hooks, watcher, menu row, bar slot)"
exec python3 "$DASHBOTS" install
