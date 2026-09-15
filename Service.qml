import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

Item {
  id: root
  property var settings: ({})
  property bool pending: false
  property string lastError: ""
  readonly property string accent: String(Color.accent)
  readonly property string helperPath: decodeURIComponent(String(Qt.resolvedUrl("sync.py")).replace(/^file:\/\//, ""))

  function scheduleSync() {
    pending = true
    debounce.restart()
  }

  onAccentChanged: scheduleSync()
  onSettingsChanged: scheduleSync()
  Component.onCompleted: scheduleSync()

  Timer {
    id: debounce
    interval: 500
    onTriggered: {
      if (worker.running) return
      root.pending = false
      worker.command = ["python3", root.helperPath, "--settings", JSON.stringify(root.settings)]
      worker.running = true
    }
  }

  Process {
    id: worker
    stdout: StdioCollector { }
    stderr: StdioCollector { id: errors }
    onExited: function(exitCode) {
      root.lastError = exitCode === 0 ? "" : errors.text.trim()
      if (root.lastError) console.warn("Omarchy RGB Sync:", root.lastError)
      if (root.pending) debounce.restart()
    }
  }
}
