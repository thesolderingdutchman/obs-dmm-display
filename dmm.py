import json
import os
import pathlib
import sys
import threading

import webview
from webview.menu import Menu, MenuAction

from drivers import ut161b, ut8802e, ut8803e

DEFAULT_MEASUREMENT = {
    "value": "---",
    "unit": "",
    "mode": "Disconnected",
    "range": "",
}


class MeasurementStore:
    def __init__(self):
        self.measurement = dict(DEFAULT_MEASUREMENT)

    def update(self, measurement):
        self.measurement = measurement or dict(DEFAULT_MEASUREMENT)

    def snapshot(self):
        return dict(self.measurement)


store = MeasurementStore()

_window = None


def push_to_window(measurement):
    if _window is None:
        return
    try:
        _window.evaluate_js(f"applyMeasurement({json.dumps(measurement)})")
    except Exception as exc:
        print(f"[Push] {exc}")


def update_measurement(measurement):
    store.update(measurement)
    push_to_window(store.snapshot())


def create_driver_for_mode(mode: str):
    mode = mode.lower()

    if mode == "ut161b":
        return ut161b.Driver()

    if mode == "ut8802e":
        return ut8802e.Driver(
            packet_source=ut8802e.build_packet_source()
        )

    if mode == "ut8803e":
        return ut8803e.Driver(
            packet_source=ut8803e.build_packet_source()
        )

    raise ValueError(mode)


class DriverManager:
    def __init__(self, mode):
        self.driver = None
        self.thread = None
        self.stop_event = None
        self.mode = None

        self.switch(mode)

    def _worker(self, driver, stop_event, interval):
        while not stop_event.is_set():
            try:
                measurement = driver.read_measurement()
                update_measurement(measurement)
            except Exception as exc:
                print(f"[Hardware] {exc}")
                update_measurement(None)

                if stop_event.wait(2):
                    break

            stop_event.wait(interval)

        try:
            driver.close()
        except Exception:
            pass

    def switch(self, mode):
        if mode == self.mode:
            return

        print(f"Switching to {mode}")

        # Stop previous worker
        if self.stop_event:
            self.stop_event.set()

        if self.thread:
            self.thread.join(timeout=2)

        update_measurement(None)

        # Start new driver
        self.driver = create_driver_for_mode(mode)
        self.mode = mode

        interval = getattr(self.driver, "worker_interval", 0.3)

        self.stop_event = threading.Event()

        self.thread = threading.Thread(
            target=self._worker,
            args=(self.driver, self.stop_event, interval),
            daemon=True,
        )

        self.thread.start()


def prevent_app_nap():
    """Stop macOS from throttling this background/inactive app.

    Without this, App Nap can slow down timers and I/O for a packaged app
    once it loses focus or is fully occluded, which is on top of (and
    separate from) WKWebView's own background-tab throttling.
    """
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSActivityLatencyCritical, NSActivityUserInitiated, NSProcessInfo

        activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiated | NSActivityLatencyCritical,
            "Realtime OBS overlay updates",
        )
        return activity
    except Exception as exc:
        print(f"[AppNap] Could not disable App Nap: {exc}")
        return None


driver_manager = None


def select_ut161b():
    driver_manager.switch("ut161b")


def select_ut8802e():
    driver_manager.switch("ut8802e")


def select_ut8803e():
    driver_manager.switch("ut8803e")


def main():
    global driver_manager, _window

    # Keep a module-level reference so the activity token isn't garbage
    # collected and the App Nap exemption doesn't get released.
    global _app_nap_activity
    _app_nap_activity = prevent_app_nap()

    selected_mode = os.environ.get("DMM_MODE", "ut161b")

    driver_manager = DriverManager(selected_mode)

    app_menu = [
        Menu("__app__"),
        Menu(
            "Device",
            [
                MenuAction("UNI-T UT161B", select_ut161b),
                MenuAction("UNI-T UT8802E", select_ut8802e),
                MenuAction("UNI-T UT8803E", select_ut8803e),
            ],
        ),
    ]

    html_path = pathlib.Path(__file__).parent / "templates" / "index.html"

    _window = webview.create_window(
        title="OBS DMM Display",
        url=html_path.as_uri(),
        frameless=True,
        transparent=True,
        resizable=False,
        width=322,
        height=157,
    )

    # Push whatever we already have as soon as the page can receive it,
    # rather than waiting for the next hardware read.
    _window.events.loaded += lambda: push_to_window(store.snapshot())

    webview.start(menu=app_menu)

if __name__ == "__main__":
    main()
