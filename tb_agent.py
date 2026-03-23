import paho.mqtt.client as mqtt
import psutil
import json
import time
import threading
import numpy as np

#Thingsboard Configuration
TB_HOST  = "localhost"     
TB_PORT  = 1883
TB_TOKEN = "DEVICE ACCESS TOKEN"
NODE_ID  = "node-ID"           # human label: "pi", "bbb", "pc"

TELEMETRY_INTERVAL = 5        # seconds between telemetry publishes
N_CORES            = psutil.cpu_count(logical=True)   # detected at startup
AGENT_START_TIME = time.time()

#State
operational  = True
task_running = False
task_lock    = threading.Lock()


#Task Executors
def _run_matrix_task(size):
    """Matrix multiply-accumulate — O(n^3) compute."""
    A   = np.random.rand(size, size).astype(np.float32)
    B   = np.random.rand(size, size).astype(np.float32)
    acc = np.zeros((size, size), dtype=np.float32)
    # Scale iterations so small matrices still take measurable time
    for _ in range(3):
        acc += A @ B


def _run_sort_task(size):
    """Sort a large random array."""
    data = np.random.rand(size * 1000)
    data.sort()


def _run_fib_task(n):
    """Compute Fibonacci sequence — CPU-bound pure Python."""
    a, b = 0, 1
    for _ in range(min(n * 100, 50000)):
        a, b = b, a + b


def execute_task(params):
    """
    Execute a task and return cpu_percent, exec_time_ms, n_cores.
    CPU is sampled immediately after task completion for accuracy.
    n_cores is included so the master can compute per-core effective load.
    """
    global task_running
    import concurrent.futures

    task_type = params.get("type", "matrix")
    size      = int(params.get("size", 128))
    task_id   = params.get("task_id", 0)

    with task_lock:
        task_running = True

    print(f"Executing | type={task_type} size={size} id={task_id} cores={N_CORES}")

    # Prime CPU baseline
    psutil.cpu_percent(interval=None)
    time.sleep(0.2)

    start = time.time()

    try:
        # Run task in thread so we can sample CPU simultaneously
        with concurrent.futures.ThreadPoolExecutor() as ex:
            if task_type == "matrix":
                future = ex.submit(_run_matrix_task, size)
            elif task_type == "sort":
                future = ex.submit(_run_sort_task, size)
            elif task_type == "fib":
                future = ex.submit(_run_fib_task, size)
            else:
                future = ex.submit(_run_matrix_task, size)

            time.sleep(0.1)                      # let task warm up
            cpu = psutil.cpu_percent(interval=0.5)  # sample while running
            future.result()                      # wait for completion

    except Exception as e:
        print(f"Task error: {e}")
        cpu = psutil.cpu_percent(interval=0.2)   # fallback sample

    exec_time_ms = (time.time() - start) * 1000

    with task_lock:
        task_running = False

    eff_load = round(cpu / max(N_CORES, 1), 1)
    print(f"Done | exec={exec_time_ms:.0f}ms cpu={cpu:.1f}% "
          f"eff_load={eff_load}% cores={N_CORES}")

    return {
        "status":       "done",
        "task_id":      task_id,
        "exec_time_ms": round(exec_time_ms, 2),
        "cpu_percent":  round(cpu, 2),
        "n_cores":      N_CORES,
        "node_id":      NODE_ID
    }

#CPU temperature
def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read()) / 1000, 1)
    except Exception:
        return None


#MQTT Callbacks
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to ThingsBoard: {reason_code}")
    print(f"Node: {NODE_ID} | Cores: {N_CORES}")
    client.subscribe("v1/devices/me/rpc/request/+")


def on_message(client, userdata, msg):
    global operational

    request_id = msg.topic.split("/")[-1]
    payload    = json.loads(msg.payload)
    method     = payload.get("method")
    params     = payload.get("params", {})

    print(f"RPC | method={method} | params={params}")
    if time.time() - AGENT_START_TIME < 10:
        print(f"Discarding stale RPC: {method}")
        client.publish(
            f"v1/devices/me/rpc/response/{request_id}",
            json.dumps({"status": "discarded", "reason": "stale"})
        )
        return

    if method == "executeTask":
        # Run in thread so MQTT loop stays responsive
        def run_and_respond():
            result = execute_task(params)
            client.publish(
                f"v1/devices/me/rpc/response/{request_id}",
                json.dumps(result)
            )
        threading.Thread(target=run_and_respond, daemon=True).start()
        return  # response sent from thread

    elif method == "getStatus":
        response = {
            "node_id":      NODE_ID,
            "operational":  operational,
            "task_running": task_running,
            "n_cores":      N_CORES,
            "cpu":          psutil.cpu_percent(interval=0.2),
            "ram":          psutil.virtual_memory().percent,
            "temp":         get_cpu_temp()
        }

    elif method == "setOperational":
        operational = bool(params.get("value", True))
        response    = {"operational": operational}

    else:
        response = {"error": f"unknown method: {method}"}

    client.publish(
        f"v1/devices/me/rpc/response/{request_id}",
        json.dumps(response)
    )


#Telemetry Loop
def telemetry_loop(client):
    psutil.cpu_percent(interval=None)  # prime
    time.sleep(1)

    while True:
        if operational:
            cpu = psutil.cpu_percent(interval=None)
            payload = {
                "cpu_percent":    cpu,
                "ram_percent":    psutil.virtual_memory().percent,
                "ram_used_mb":    round(psutil.virtual_memory().used / 1024**2, 1),
                "cpu_temp":       get_cpu_temp(),
                "disk_percent":   psutil.disk_usage("/").percent,
                "n_cores":        N_CORES,
                "effective_load": round((cpu / max(N_CORES, 1)) * 100, 1),
                "task_running":   int(task_running),
                "operational":    1,
                "node_id":        NODE_ID
            }
        else:
            payload = {
                "operational": 0,
                "node_id":     NODE_ID
            }

        client.publish("v1/devices/me/telemetry", json.dumps(payload))
        print(f"Telemetry | cpu={payload.get('cpu_percent','N/A')}% "
              f"eff={payload.get('effective_load','N/A')}% "
              f"ram={payload.get('ram_percent','N/A')}%")
        time.sleep(TELEMETRY_INTERVAL)


#Main
def main():
    print(f"Starting agent | node={NODE_ID} | host={TB_HOST} | cores={N_CORES}")

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(TB_TOKEN)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(TB_HOST, TB_PORT)

    thread = threading.Thread(target=telemetry_loop, args=(client,), daemon=True)
    thread.start()

    client.loop_forever()


if __name__ == "__main__":
    main()
