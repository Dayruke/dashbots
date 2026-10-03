import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Third-party slot. The host injects PluginBarApi as `bar` (foreground,
// urgent, run, showTooltip, hideTooltip). Accent and muted stay on Color.
//
// Bodies are single-color SVGs. Eyes are cut out of the shape, so the theme
// color is the body and the bar shows through the eyes. Working is the accent
// color and the body leans. A finished turn is muted, with dashes.
BarWidget {
  id: root

  // From ~/.config/dashbots/config. swingMs is one full cycle.
  // Lower is faster. animate false keeps a working icon still.
  property int swingMs: 2000
  property bool animate: true
  property string place: "center-right"
  property string appliedPlace: ""
  property bool placeQueued: false

  property bool toggleOn: false
  property bool listQueued: false
  property bool flagQueued: false
  property string listText: ""
  property var sessions: []
  // Degrees. Positive leans right. 0 is upright.
  property real lean: 0
  // Pixels. Negative is above the slot center.
  property real bob: 0
  // 0..1 across one full cycle. The pose is derived from this.
  property real phase: 0
  // Every body uses the size that still fits a 30° lean. Idle and
  // working stay the same, so a mark does not shrink when it swings.
  readonly property real iconScale: 0.85

  readonly property string home: Quickshell.env("HOME")
  readonly property string flagPath: home + "/.local/state/omarchy/toggles/dashbots"
  readonly property string sessionsDir: home + "/.local/state/dashbots/sessions"
  readonly property string binPath: home + "/.local/bin/dashbots"
  readonly property string configPath: {
    var base = Quickshell.env("XDG_CONFIG_HOME")
    if (!base) base = root.home + "/.config"
    return base + "/dashbots/config"
  }
  readonly property bool swingOn: root.animate && root.anyWorking
  // Blocks until a session file is added, replaced, or removed. Records are
  // renamed into place, so a status write is a new directory entry. Stdbuf
  // keeps each name on its own line when stdout is a pipe.
  readonly property string watchScript:
    "sessions=$1\n" +
    "if ! command -v inotifywait >/dev/null 2>&1; then\n" +
    "  echo 'dashbots: inotifywait is missing' >&2\n" +
    "  sleep 30\n" +
    "  exit 1\n" +
    "fi\n" +
    "while [[ ! -d \"$sessions\" ]]; do\n" +
    "  parent=$(dirname -- \"$sessions\")\n" +
    "  if [[ ! -d \"$parent\" ]]; then parent=$(dirname -- \"$parent\"); fi\n" +
    "  if [[ ! -d \"$parent\" ]]; then sleep 30; continue; fi\n" +
    "  inotifywait -q -t 60 -e create,moved_to -- \"$parent\" >/dev/null || true\n" +
    "done\n" +
    "cmd=(inotifywait -q -m -e close_write,create,delete,move --format %f -- \"$sessions\")\n" +
    "if command -v stdbuf >/dev/null 2>&1; then exec stdbuf -oL \"${cmd[@]}\"; fi\n" +
    "exec \"${cmd[@]}\"\n"
  readonly property bool anyWorking: {
    var list = root.sessions || []
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i].status === "working") return true
    }
    return false
  }
  readonly property var marks: {
    if (!root.toggleOn) return []
    if (!root.sessions || root.sessions.length === 0) return [{ empty: true }]
    return root.sessions
  }

  visible: toggleOn
  implicitWidth: toggleOn ? (vertical ? barSize : marksGrid.implicitWidth) : 0
  implicitHeight: toggleOn ? (vertical ? marksGrid.implicitHeight : barSize) : 0

  // The reporter picks a body per live session and keeps it. The widget
  // only draws the name it was given.
  function bodyName(session) {
    var body = String(session && session.body || "").toLowerCase()
    if (body === "circle" || body === "blob" || body === "triangle" || body === "square")
      return body
    return "circle"
  }

  function asleep(session) {
    if (!session || session.empty === true) return false
    return String(session.status || "") === "waiting"
        && String(session.activity || "") !== "needs a decision"
  }

  function faceUrl(session) {
    var body = bodyName(session)
    var face = asleep(session) ? "-sleep" : ""
    return Qt.resolvedUrl("icons/" + body + face + ".svg")
  }

  function harnessName(harness) {
    var name = String(harness || "").toLowerCase()
    if (name === "grok") return "Grok"
    if (name === "claude") return "Claude"
    if (name === "gemini") return "Gemini"
    if (name === "codex") return "Codex"
    if (name === "agy" || name === "antigravity") return "Antigravity"
    if (name === "opencode") return "OpenCode"
    return String(harness || "Agent")
  }

  function markColor(session) {
    if (!session || session.empty === true) return Color.muted
    var status = String(session.status || "")
    if (status === "error") return bar ? bar.urgent : Color.urgent
    if (status === "working") return Color.accent
    if (status === "waiting" && String(session.activity || "") === "needs a decision")
      return Color.accent
    if (status === "waiting") return Color.muted
    return bar ? bar.foreground : Color.foreground
  }

  function tipFor(session) {
    if (!session || session.empty === true) return "No live agents"
    var lines = [harnessName(session.harness)]
    if (session.title) lines.push(String(session.title))
    if (session.activity) lines.push(String(session.activity))
    return lines.join("\n")
  }

  // Focusing also switches to that window's workspace. Hyprland would
  // center the pointer on the window. The reporter turns that warp off
  // and puts the pointer back on the click.
  function focusSession(session) {
    if (!session || session.empty === true) return
    var addr = String(session.window || "")
    if (!/^0x[0-9a-fA-F]+$/.test(addr)) return
    if (focusProc.running) return
    focusProc.command = [root.binPath, "focus", addr]
    focusProc.running = true
  }

  function applyList(text) {
    var raw = String(text || "").trim()
    if (!raw) {
      if (root.listText !== "") {
        root.listText = ""
        root.sessions = []
      }
      return
    }
    var lines = raw.split("\n")
    var last = ""
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim()
      if (line) last = line
    }
    if (!last || last === root.listText) return
    var parsed
    try {
      parsed = JSON.parse(last)
    } catch (e) {
      return
    }
    if (!Array.isArray(parsed)) return
    root.listText = last
    root.sessions = parsed
  }

  function refreshFlag() {
    if (flagProc.running) {
      root.flagQueued = true
      return
    }
    root.flagQueued = false
    flagProc.running = true
  }

  // Temp files from the atomic replace start with a dot. The renamed
  // record is the only name that should refresh the slot.
  function noteSessionFile(name) {
    var file = String(name || "")
    if (file.length < 6 || file.charAt(0) === ".") return
    if (file.slice(-5) !== ".json") return
    if (!root.toggleOn) return
    listDebounce.restart()
  }

  function runList() {
    if (!root.toggleOn) return
    if (listProc.running) {
      root.listQueued = true
      return
    }
    root.listQueued = false
    listProc.buf = ""
    listProc.running = true
  }

  // OutSine on the way down, InSine on the way back up. Upright is the
  // high, fast point. Either lean is the low point.
  function poseAt(phase) {
    var p = phase
    if (!(p >= 0)) p = 0
    if (p >= 1) p = 0
    var seg = Math.floor(p * 4)
    if (seg < 0) seg = 0
    if (seg > 3) seg = 3
    var t = p * 4 - seg
    var eased = (seg % 2 === 0)
      ? Math.sin(t * Math.PI / 2)
      : (1 - Math.cos(t * Math.PI / 2))
    if (seg === 0) {
      root.lean = 30 * eased
      root.bob = -3 + 6 * eased
    } else if (seg === 1) {
      root.lean = 30 * (1 - eased)
      root.bob = 3 - 6 * eased
    } else if (seg === 2) {
      root.lean = -30 * eased
      root.bob = -3 + 6 * eased
    } else {
      root.lean = -30 * (1 - eased)
      root.bob = 3 - 6 * eased
    }
  }

  function readConfig(text) {
    var swing = 2000
    var motion = true
    var spot = "center-right"
    var lines = String(text || "").split("\n")
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim()
      if (!line || line.charAt(0) === "#") continue
      var parts = line.split(/\s+/)
      if (parts.length < 2) continue
      var key = parts[0]
      var value = parts[1]
      if (key === "swingMs") {
        var n = parseInt(value, 10)
        if (n > 0) swing = n
      } else if (key === "animate") {
        var word = value.toLowerCase()
        if (word === "true" || word === "yes" || word === "1" || word === "on") motion = true
        if (word === "false" || word === "no" || word === "0" || word === "off") motion = false
      } else if (key === "place") {
        if (value === "center-right" || value === "center-left" || value === "workspaces") spot = value
      }
    }
    root.swingMs = swing
    root.animate = motion
    root.place = spot
    if (spot !== root.appliedPlace) root.runPlace()
  }

  function runPlace() {
    root.appliedPlace = root.place
    if (placeProc.running) {
      root.placeQueued = true
      return
    }
    root.placeQueued = false
    placeProc.running = true
  }

  onPhaseChanged: if (root.swingOn) root.poseAt(root.phase)
  onSwingOnChanged: if (!root.swingOn) {
    root.phase = 0
    root.lean = 0
    root.bob = 0
  }
  onSwingMsChanged: if (swingClock && swingClock.running) swingClock.restart()

  onToggleOnChanged: {
    if (!root.toggleOn) {
      root.sessions = []
      root.listText = ""
      root.listQueued = false
      listDebounce.stop()
      if (sessionWatch.running) sessionWatch.running = false
      return
    }
    if (!sessionWatch.running) sessionWatch.running = true
    root.runList()
  }

  Timer {
    id: listDebounce
    interval: 100
    repeat: false
    onTriggered: root.runList()
  }

  Timer {
    id: sessionWatchRearm
    interval: 1000
    onTriggered: {
      if (root.toggleOn && !sessionWatch.running)
        sessionWatch.running = true
    }
  }

  // Saving the config applies swing speed, animation, and bar position.
  FileView {
    id: configFile
    path: root.configPath
    watchChanges: true
    printErrors: false
    onLoaded: root.readConfig(text())
    onFileChanged: reload()
  }

  // Creating or removing this file is the toggle.
  FileView {
    id: flagWatch
    path: root.flagPath
    watchChanges: true
    printErrors: false
    preload: false
    onFileChanged: root.refreshFlag()
  }

  Process {
    id: sessionWatch
    command: ["bash", "-c", root.watchScript, "dashbots-watch", root.sessionsDir]
    stdout: SplitParser {
      onRead: function(line) { root.noteSessionFile(line) }
    }
    onExited: function() {
      if (root.toggleOn) sessionWatchRearm.restart()
    }
  }

  Component.onCompleted: root.refreshFlag()

  // Metronome. Upright is the high point and the fast point. Either lean
  // is the low point, and the face slows there. One cycle is right, then left.
  // Duration is swingMs. Nested animations ignore that binding.
  NumberAnimation {
    id: swingClock
    target: root
    property: "phase"
    from: 0
    to: 1
    duration: Math.max(1, root.swingMs)
    easing.type: Easing.Linear
    loops: Animation.Infinite
    running: root.swingOn
  }

  Process {
    id: flagProc
    command: ["test", "-f", root.flagPath]
    onExited: function(exitCode) {
      var on = exitCode === 0
      if (root.toggleOn !== on) root.toggleOn = on
      if (root.flagQueued) root.refreshFlag()
    }
  }

  Process {
    id: focusProc
    command: [root.binPath, "focus"]
  }

  Process {
    id: placeProc
    command: [root.binPath, "place"]
    onExited: function() {
      if (!root.placeQueued) return
      root.placeQueued = false
      Qt.callLater(root.runPlace)
    }
  }

  Process {
    id: listProc
    command: [root.binPath, "list"]
    property string buf: ""
    stdout: SplitParser {
      onRead: function(line) { listProc.buf += line }
    }
    onExited: function(exitCode) {
      if (root.toggleOn && exitCode === 0)
        root.applyList(listProc.buf)
      if (!root.listQueued || !root.toggleOn) {
        root.listQueued = false
        return
      }
      Qt.callLater(root.runList)
    }
  }

  Grid {
    id: marksGrid
    columns: root.vertical ? 1 : Math.max(1, root.marks.length)
    columnSpacing: 0
    rowSpacing: 0

    Repeater {
      model: root.marks
      delegate: BarIconButton {
        id: button
        required property var modelData
        readonly property bool blank: modelData && modelData.empty === true
        readonly property string sessionStatus: blank ? "" : String(modelData.status || "")
        readonly property bool moving: sessionStatus === "working" && root.animate

        bar: root.bar
        text: blank ? "_" : ""
        hasVisualContent: true
        labelVisible: blank
        tooltipText: root.tipFor(modelData)
        slotSize: Style.bar.statusSlot
        fontSize: Style.bar.iconFont
        width: Style.bar.statusSlot
        height: root.barSize
        pressable: !blank
        useActiveColor: false
        foreground: root.markColor(modelData)

        onPressed: function(mouseButton) {
          if (mouseButton !== Qt.LeftButton) return
          root.focusSession(modelData)
        }

        // The SVG is white with transparent eyes. The effect replaces that
        // white with the theme role and leaves the eye holes clear. Same
        // arrangement as the tray's symbolic icons, so a new role repaints.
        Item {
          id: faceLayer
          visible: !button.blank
          anchors.centerIn: parent
          width: Style.bar.iconCanvas
          height: Style.bar.iconCanvas
          scale: root.iconScale
          rotation: button.moving ? root.lean : 0
          anchors.verticalCenterOffset: button.moving ? root.bob : 0
          transformOrigin: Item.Center

          Image {
            id: faceImage
            anchors.fill: parent
            source: root.faceUrl(button.modelData)
            fillMode: Image.PreserveAspectFit
            smooth: true
            visible: false
            layer.enabled: true
            sourceSize.width: Math.round(width * Screen.devicePixelRatio)
            sourceSize.height: Math.round(height * Screen.devicePixelRatio)
          }

          MultiEffect {
            anchors.fill: faceImage
            source: faceImage
            colorization: 1.0
            colorizationColor: button.foreground
          }
        }
      }
    }
  }
}
