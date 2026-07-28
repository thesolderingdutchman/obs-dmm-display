import os
import pathlib
import threading
import time
from typing import Any, Dict, Optional

import webview

from drivers import ut161b, ut8802e, ut8803e

DEFAULT_MEASUREMENT = {"value": "---", "unit": "", "mode": "Disconnected", "range": ""}


class MeasurementStore:
    def __init__(self) -> None:
        self.measurement = dict(DEFAULT_MEASUREMENT)

    def update(self, measurement: Optional[Dict[str, Any]]) -> None:
        if measurement is None:
            measurement = dict(DEFAULT_MEASUREMENT)
        self.measurement = measurement

    def snapshot(self) -> Dict[str, Any]:
        return dict(self.measurement)


store = MeasurementStore()


class MeasurementAPI:
    """Exposed to JavaScript via window.pywebview.api"""

    def get_measurement(self) -> Dict[str, Any]:
        return store.snapshot()


def update_measurement(measurement: Optional[Dict[str, Any]]) -> None:
    store.update(measurement)


def worker_for_driver(driver: Any, interval: float = 0.3) -> None:
    while True:
        try:
            result = driver.read_measurement()
            update_measurement(result if result is not None else None)
        except Exception as exc:
            print(f"[Hardware] status: {exc}. Retrying in 2s...")
            update_measurement(None)
            if hasattr(driver, "close"):
                try:
                    driver.close()
                except Exception:
                    pass
            time.sleep(2.0)
            continue
        time.sleep(interval)


def create_driver_for_mode(mode: str) -> Any:
    mode = mode.lower()
    if mode in {"ut161b", "ut161b_only", "single"}:
        return ut161b.Driver()
    if mode in {"ut8802e", "ut8802e_only"}:
        return ut8802e.Driver(packet_source=ut8802e.build_packet_source())
    if mode in {"ut8803e"}:
        return ut8803e.Driver(packet_source=ut8803e.build_packet_source())
    raise ValueError(f"Unsupported device mode: {mode}")


def main() -> None:
    selected_mode = os.environ.get("DMM_MODE", "ut161b")
    driver = create_driver_for_mode(selected_mode)
<<<<<<< HEAD
=======
    worker_interval = getattr(driver, "worker_interval", 0.3)
    driver_thread = threading.Thread(
        target=worker_for_driver,
        args=(driver, worker_interval),
        daemon=True,
    )
    driver_thread.start()
>>>>>>> main

    threading.Thread(
        target=worker_for_driver,
        args=(driver, 0.3),
        daemon=True,
    ).start()

    html_path = pathlib.Path(__file__).parent / "templates" / "index.html"

    webview.create_window(
        title="Meter Overlay",
        url=html_path.as_uri(),
        js_api=MeasurementAPI(),
        frameless=True,
        transparent=True,
        resizable=False,
        width=322,
        height=157,
    )

    webview.start()


if __name__ == "__main__":
    main()
