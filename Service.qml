import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

Item {
  id: root
  property var settings: ({})
  property var manifest: null
  property bool pending: false
  property bool pendingForce: false
  property bool pendingReconnect: false
  property bool suspended: false
  property bool recoveryWaiting: false
  property string lastError: ""
  readonly property string accent: String(Color.accent)
  readonly property string helperPath: decodeURIComponent(String(Qt.resolvedUrl("sync.py")).replace(/^file:\/\//, ""))

  readonly property int reconnectIntervalSec: Math.max(15, Number(settings.reconnectIntervalSec) || 60)
  readonly property bool managedServer: settings.managedServer === true
  onManagedServerChanged: {
    server.running = managedServer
    if (!managedServer) { recoveryWaiting = false; recoverySettle.stop() }
  }

  // Omarchy injects settings into bar widgets, but not service entry points.
  // Watch our own inline entry, including atomic shell.json replacements.
  FileView {
    id: configFile
    path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        var entries = JSON.parse(text()).plugins || []
        var id = root.manifest ? root.manifest.id : "io.github.fewhnhouse.omarchy-rgb"
        var next = entries.find(function(entry) { return entry.id === id }) || {}
        if (JSON.stringify(next) !== JSON.stringify(root.settings)) root.settings = next
      } catch (error) {
        console.warn("Omarchy RGB Sync: cannot read settings:", error)
      }
    }
  }

  function scheduleSync(force) {
    pending = true
    pendingForce = pendingForce || force !== false
    debounce.restart()
  }

  function recover(reconnect) {
    pendingReconnect = pendingReconnect || reconnect === true
    // Controllers and wireless receivers may take several seconds to wake.
    settle.restart()
    retry.restart()
  }

  function sleepEvent(line) {
    if (line.trim() === "boolean true") {
      suspended = true
      settle.stop()
      retry.stop()
    } else if (line.trim() === "boolean false") {
      suspended = false
      recover(true)
    }
  }

  function deviceEvent(line) {
    if (/^UDEV\s.*\s(add|remove|change)\s/.test(line)) recover(/\sadd\s/.test(line))
  }

  onAccentChanged: scheduleSync()
  onSettingsChanged: scheduleSync()
  Component.onCompleted: scheduleSync()

  Timer {
    id: debounce
    interval: 500
    onTriggered: {
      if (worker.running || root.suspended || root.recoveryWaiting) return
      root.pending = false
      worker.command = ["python3", root.helperPath, "--settings", JSON.stringify(root.settings)]
      if (!root.pendingForce) worker.command = worker.command.concat(["--check"])
      if (root.managedServer && server.running) worker.command = worker.command.concat(["--allow-recovery"])
      if (root.pendingReconnect) worker.command = worker.command.concat(["--reconnect"])
      root.pendingReconnect = false
      root.pendingForce = false
      worker.running = true
    }
  }

  Process {
    id: worker
    stdout: StdioCollector { id: output }
    stderr: StdioCollector { id: errors }
    onExited: function(exitCode) {
      root.lastError = exitCode === 0 ? "" : errors.text.trim()
      if (root.lastError) console.warn("Omarchy RGB Sync:", root.lastError)
      try {
        var recovery = JSON.parse(output.text).recovery
        if (recovery && root.managedServer && !root.settings.paused) {
          if (recovery.action === "rescan") {
            root.recoveryWaiting = true
            recoverySettle.restart()
          } else if (recovery.action === "restart" && server.running) {
            // Stop only our Process object. Never kill other OpenRGB instances.
            root.recoveryWaiting = true
            server.running = false
          } else if (recovery.retry && !retry.running) {
            retry.restart()
          }
        }
      } catch (error) { /* A failed helper may have no JSON output. */ }
      if (root.pending) debounce.restart()
    }
  }

  Timer { id: settle; interval: 2000; onTriggered: root.scheduleSync() }
  Timer { id: retry; interval: 15000; onTriggered: root.scheduleSync() }
  Timer {
    id: recoverySettle
    interval: 15000
    onTriggered: { root.recoveryWaiting = false; root.scheduleSync() }
  }

  // Wireless wakeups do not always produce a udev event. Discover periodically,
  // but only write colors when the selected inventory or settings changed.
  Timer {
    interval: root.reconnectIntervalSec * 1000
    running: !root.suspended
    repeat: true
    onTriggered: { if (!worker.running) root.scheduleSync(false) }
  }

  Process {
    id: sleepMonitor
    command: ["dbus-monitor", "--system", "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'"]
    running: true
    stdout: SplitParser { onRead: function(line) { root.sleepEvent(line) } }
    stderr: StdioCollector { }
    onExited: sleepRestart.restart()
  }
  Timer { id: sleepRestart; interval: 5000; onTriggered: sleepMonitor.running = true }

  Process {
    id: deviceMonitor
    command: ["udevadm", "monitor", "--udev", "--subsystem-match=usb", "--subsystem-match=hidraw"]
    running: true
    stdout: SplitParser { onRead: function(line) { root.deviceEvent(line) } }
    stderr: StdioCollector { }
    onExited: deviceRestart.restart()
  }
  Timer { id: deviceRestart; interval: 5000; onTriggered: deviceMonitor.running = true }

  // Some devices restore onboard lighting when the owning OpenRGB process
  // exits. Keep one owner alive; short-lived helpers connect as SDK clients.
  Process {
    id: server
    command: ["openrgb", "--server", "--server-host", "127.0.0.1", "--server-port", "6742", "--noautoconnect"]
    running: root.managedServer
    stdout: StdioCollector { }
    stderr: StdioCollector { }
    onStarted: { root.recoveryWaiting = false; root.recover() }
    onExited: { if (root.managedServer) serverRestart.restart() }
  }
  Timer { id: serverRestart; interval: 10000; onTriggered: { if (root.managedServer) server.running = true } }
}
