import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Third-party slot. The host injects PluginBarApi as `bar` (foreground,
// urgent, run, showTooltip, hideTooltip). Accent and muted stay on Color.
BarWidget {
  id: root

  property bool toggleOn: false
  property string listText: ""
  property var sessions: []
  property real workPulse: 1

  readonly property string home: Quickshell.env("HOME")
  readonly property string flagPath: home + "/.local/state/omarchy/toggles/dashbots"
  readonly property string binPath: home + "/.local/bin/dashbots"
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

  function markLetter(harness) {
    var name = String(harness || "").toLowerCase()
    if (name === "grok") return "G"
    if (name === "claude") return "C"
    if (name === "gemini") return "M"
    if (name === "codex") return "X"
    if (name === "agy" || name === "antigravity") return "A"
    if (name === "opencode") return "O"
    var ch = name.charAt(0)
    return ch ? ch.toUpperCase() : "?"
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

  function markColor(status) {
    if (status === "waiting") return Color.accent
    if (status === "error") return bar ? bar.urgent : Color.urgent
    return bar ? bar.foreground : Color.foreground
  }

  function tipFor(session) {
    if (!session || session.empty === true) return "No live agents"
    var lines = [harnessName(session.harness)]
    if (session.title) lines.push(String(session.title))
    if (session.activity) lines.push(String(session.activity))
    return lines.join("\n")
  }

  function focusSession(session) {
    if (!session || session.empty === true || !bar) return
    var addr = String(session.window || "")
    if (!/^0x[0-9a-fA-F]+$/.test(addr)) return
    bar.run("hyprctl dispatch focuswindow address:" + addr)
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

  function poll() {
    if (!flagProc.running) flagProc.running = true
  }

  onAnyWorkingChanged: if (!anyWorking) workPulse = 1

  Timer {
    interval: 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.poll()
  }

  Timer {
    interval: 700
    running: root.anyWorking
    repeat: true
    onTriggered: root.workPulse = root.workPulse < 0.7 ? 1 : 0.45
  }

  Process {
    id: flagProc
    command: ["test", "-f", root.flagPath]
    onExited: function(exitCode) {
      var on = exitCode === 0
      if (root.toggleOn !== on) {
        root.toggleOn = on
        if (!on) {
          root.sessions = []
          root.listText = ""
        }
      }
      if (on && !listProc.running) {
        listProc.buf = ""
        listProc.running = true
      }
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
      if (exitCode !== 0) return
      root.applyList(listProc.buf)
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
        required property var modelData
        readonly property bool blank: modelData && modelData.empty === true
        readonly property string sessionStatus: blank ? "" : String(modelData.status || "")

        bar: root.bar
        text: blank ? "_" : root.markLetter(modelData.harness)
        tooltipText: root.tipFor(modelData)
        slotSize: Style.bar.statusSlot
        fontSize: Style.bar.iconFont
        width: Style.bar.statusSlot
        height: root.barSize
        pressable: !blank
        useActiveColor: false
        foreground: blank ? Color.muted : root.markColor(sessionStatus)
        opacity: sessionStatus === "working" ? root.workPulse : 1

        onPressed: function(button) {
          if (button !== Qt.LeftButton) return
          root.focusSession(modelData)
        }
      }
    }
  }
}
