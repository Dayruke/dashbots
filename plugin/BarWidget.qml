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
// color and the body breathes. A finished turn is muted, with dashes.
BarWidget {
  id: root

  property bool toggleOn: false
  property string listText: ""
  property var sessions: []
  property real breath: 1

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

  function poll() {
    if (!flagProc.running) flagProc.running = true
  }

  onAnyWorkingChanged: if (!anyWorking) root.breath = 1

  Timer {
    interval: 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.poll()
  }

  // Size, not a same-color fade. A 16px opacity dip sits next to identical
  // marks and does not read as motion.
  SequentialAnimation {
    running: root.anyWorking
    loops: Animation.Infinite
    NumberAnimation {
      target: root
      property: "breath"
      from: 1
      to: 0.9
      duration: 1240
      easing.type: Easing.InOutSine
    }
    NumberAnimation {
      target: root
      property: "breath"
      from: 0.9
      to: 1
      duration: 1240
      easing.type: Easing.InOutSine
    }
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
    id: focusProc
    command: [root.binPath, "focus"]
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
        id: button
        required property var modelData
        readonly property bool blank: modelData && modelData.empty === true
        readonly property string sessionStatus: blank ? "" : String(modelData.status || "")

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
          scale: button.sessionStatus === "working" ? root.breath : 1
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
