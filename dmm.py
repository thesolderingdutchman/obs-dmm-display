import os
import pathlib
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


class MeasurementAPI:
    def get_measurement(self):
        print("API:", store.snapshot())
        return store.snapshot()


def update_measurement(measurement):
    store.update(measurement)


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
                # print(
                #     f"[Hardware] {self.mode} measurement: {measurement['value']} {measurement['unit']} ({measurement['mode']})"
                # )

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

        #
        # Stop previous worker
        #

        if self.stop_event:
            self.stop_event.set()

        if self.thread:
            self.thread.join(timeout=2)

        update_measurement(None)

        #
        # Start new driver
        #

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


driver_manager = None


def select_ut161b():
    driver_manager.switch("ut161b")


def select_ut8802e():
    driver_manager.switch("ut8802e")


def select_ut8803e():
    driver_manager.switch("ut8803e")


def main():
    global driver_manager

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


    api = MeasurementAPI()
    print(dir(api))

    webview.create_window(
        title="OBS DMM Display",
        url=html_path.as_uri(),
        js_api=api,
        frameless=True,
        transparent=True,
        resizable=False,
        width=322,
        height=157,
    )

    webview.start(debug=True, menu=app_menu)

if __name__ == "__main__":
    main()
