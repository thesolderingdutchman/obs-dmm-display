import os
import threading
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify
from flask_cors import CORS  # Allows local HTML files to read this API safely

from drivers import ut161b, ut8802e, ut8803e

DEFAULT_MEASUREMENT = {"value": "---", "unit": "", "mode": "Disconnected", "range": ""}

latest_measurement = dict(DEFAULT_MEASUREMENT)


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


def update_measurement(measurement: Optional[Dict[str, Any]]) -> None:
    store.update(measurement)
    global latest_measurement
    latest_measurement = store.measurement


def worker_for_driver(driver: Any, interval: float = 0.3) -> None:
    while True:
        try:
            result = driver.read_measurement()
            if result is not None:
                update_measurement(result)
            else:
                update_measurement(None)
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


app = Flask(__name__)
CORS(app)  # This allows your local HTML file to fetch data from Flask safely


@app.route("/data")
def get_data():
    return jsonify(store.snapshot())


def create_driver_for_mode(mode: str) -> Any:
    mode = mode.lower()
    if mode in {"ut161b", "ut161b_only", "single"}:
        return ut161b.Driver()
    if mode in {"ut8802e", "ut8802e_only"}:
        return ut8802e.Driver(packet_source=ut8802e.build_packet_source())
    if mode in {"ut8803e"}:
        return ut8803e.Driver(packet_source=ut8803e.build_packet_source())
    raise ValueError(f"Unsupported device mode: {mode}")


if __name__ == "__main__":
    selected_mode = os.environ.get("DMM_MODE", "ut161b")
    driver = create_driver_for_mode(selected_mode)
    worker_interval = getattr(driver, "worker_interval", 0.3)
    driver_thread = threading.Thread(
        target=worker_for_driver,
        args=(driver, worker_interval),
        daemon=True,
    )
    driver_thread.start()

    print(f"\n🚀 API running on http://127.0.0.1:8080 using mode={selected_mode}")
    app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)
