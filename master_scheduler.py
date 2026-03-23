

import requests
import time
import numpy as np
import csv
from datetime import datetime

# Thingsboard Configuration 
TB_HOST   = "localhost"
TB_USER   = "tenant@thingsboard.com"
TB_PASS   = "PASSWORD"

NODES = {
    "RaspberryPi": "RASPBERRY DEVICE ID",
    "BeagleBone":  "BEAGLEBONE DEVICE ID",
    "PC":          "PC DEVICE ID",
}

POLICY        = "UCB1"    # Policy choice: "UCB1" or "EXP3" or "RoundRobin"
EPOCHS        = 10         
INTERVAL      = 10        # seconds between epochs
SETTLING      = 3         # seconds to wait before fallback telemetry read
TASK_COST_MIN = 256       # minimum task cost (matrix size)
TASK_COST_MAX = 2048     # maximum task cost (matrix size)
LOG_FILE      = f"results_{POLICY}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

#Reward parameters
ALPHA        = 0.5        # CPU efficiency weight  (equal)
BETA         = 0.5        # Execution time weight  (equal)
MAX_EXEC_MS  = 10000      # normalization ceiling for execution time (ms)
OVERLOAD_THR = 90         # effective per-core load % that triggers penalty


#Bandit Policies
class BanditPolicy:
    def __init__(self, n_arms):
        self.n_arms       = n_arms
        self.total_reward = 0.0
        self.epoch        = 0

    def select(self): raise NotImplementedError
    def update(self, arm, reward): raise NotImplementedError
    def name(self): return self.__class__.__name__


class UCB1(BanditPolicy):
    def __init__(self, n_arms, c=2.0):
        super().__init__(n_arms)
        self.counts = np.zeros(n_arms)
        self.values = np.zeros(n_arms)
        self.t      = 0
        self.c      = c

    def select(self):
        self.t += 1
        for i in range(self.n_arms):
            if self.counts[i] == 0:
                return i
        ucb = self.values + self.c * np.sqrt(np.log(self.t) / self.counts)
        return int(np.argmax(ucb))

    def update(self, arm, reward):
        self.counts[arm] += 1
        self.values[arm] += (reward - self.values[arm]) / self.counts[arm]
        self.total_reward += reward
        self.epoch        += 1

    def state(self):
        return {
            "counts":   self.counts.tolist(),
            "values":   [round(v, 4) for v in self.values],
            "best_arm": int(np.argmax(self.values))
        }


class EXP3(BanditPolicy):
    def __init__(self, n_arms, gamma=0.1):
        super().__init__(n_arms)
        self.weights = np.ones(n_arms)
        self.gamma   = gamma

    def _probs(self):
        w = self.weights
        return (1 - self.gamma) * w / w.sum() + self.gamma / self.n_arms

    def select(self):
        probs = self._probs()
        return int(np.random.choice(self.n_arms, p=probs))

    def update(self, arm, reward):
        probs              = self._probs()
        r_hat              = reward / probs[arm]
        self.weights[arm] *= np.exp(self.gamma * r_hat / self.n_arms)
        self.total_reward += reward
        self.epoch        += 1

    def state(self):
        probs = self._probs()
        return {
            "weights":  [round(w, 4) for w in self.weights],
            "probs":    [round(p, 4) for p in probs],
            "best_arm": int(np.argmax(probs))
        }
    
class RoundRobin(BanditPolicy):
    def __init__(self, n_arms):
        super().__init__(n_arms)
        self.current = 0

    def select(self):
        arm = self.current
        self.current = (self.current + 1) % self.n_arms
        return arm

    def update(self, arm, reward):
        self.total_reward += reward
        self.epoch        += 1

    def state(self):
        return {
            "current": self.current,
            "best_arm": -1   # no learning, no best arm
        }


#Reward Function
def compute_reward(cpu_percent, exec_time_ms, n_cores=1):
    """
    Equal-weight efficiency reward (alpha = beta = 0.5).

    CPU term uses effective per-core load so heterogeneous nodes
    are compared fairly:
      BeagleBone (1 core)  @ 80% CPU -> effective_load = 80%  -> penalized
      Raspberry Pi (4 core) @ 80% CPU -> effective_load = 20%  -> rewarded
      PC (8 core)           @ 80% CPU -> effective_load = 10%  -> rewarded most

    reward = 0.5 * (1 - cpu_norm) + 0.5 * (1 - time_norm)
    """
    if cpu_percent is None or exec_time_ms is None:
        return 0.0

    # Effective load per core: key fairness normalization
    effective_load = min((cpu_percent / max(n_cores, 1)), 100)

    # Hard penalty if any single core is saturated
    if effective_load > OVERLOAD_THR:
        return 0.1

    cpu_norm  = min(effective_load / 100.0, 1.0)
    time_norm = min(exec_time_ms / MAX_EXEC_MS, 1.0)

    reward = ALPHA * (1.0 - cpu_norm) + BETA * (1.0 - time_norm)

    return round(max(0.0, min(1.0, reward)), 4)


#ThingsBoard Client
class TBClient:
    def __init__(self):
        self.token   = self._login()
        self.headers = {
            "X-Authorization": f"Bearer {self.token}",
            "Content-Type":    "application/json"
        }

    def _login(self):
        resp = requests.post(
            f"{TB_HOST}/api/auth/login",
            json={"username": TB_USER, "password": TB_PASS},
            timeout=10
        )
        resp.raise_for_status()
        print("✓ Logged in to ThingsBoard")
        return resp.json()["token"]

    def get_telemetry(self, device_id, keys):
        url  = f"{TB_HOST}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries"
        resp = requests.get(
            url,
            headers=self.headers,
            params={"keys": ",".join(keys), "limit": 1},
            timeout=10
        )
        resp.raise_for_status()
        data   = resp.json()
        result = {}
        for key in keys:
            try:
                result[key] = float(data[key][0]["value"])
            except (KeyError, IndexError, TypeError):
                result[key] = None
        return result

    def send_rpc(self, device_id, method, params, twoway=True):
        endpoint = "twoway" if twoway else "oneway"
        url      = f"{TB_HOST}/api/rpc/{endpoint}/{device_id}"
        resp     = requests.post(
            url,
            headers=self.headers,
            json={"method": method, "params": params, "timeout": 30000},
            timeout=35
        )
        resp.raise_for_status()
        return resp.json() if twoway else {}


#Task Generator
def generate_task():
    size = int(np.random.randint(TASK_COST_MIN, TASK_COST_MAX + 1))
    return {
        "type":    "matrix",
        "size":    size,
        "task_id": int(np.random.randint(1000, 9999))
    }


#Task Dispatcher
def dispatch_task(tb, name, device_id, task, results):
    """Dispatch task to one node and collect results."""
    try:
        response  = tb.send_rpc(device_id, "executeTask", task, twoway=True)

        exec_time = response.get("exec_time_ms", None)
        cpu       = response.get("cpu_percent",  None)
        n_cores   = int(response.get("n_cores",  1))

        #Fallback to telemetry if agent didn't return cpu
        if cpu is None:
            time.sleep(SETTLING)
            tel     = tb.get_telemetry(device_id, ["cpu_percent"])
            cpu     = tel.get("cpu_percent")
            n_cores = 1

        eff_load = round(cpu / max(n_cores, 1), 1) if cpu else None
        print(f"  [{name}] cpu={cpu:.1f}% | cores={n_cores} | "
              f"eff_load={eff_load}% | exec={exec_time:.0f}ms")

        results[name] = {
            "cpu_percent":  cpu,
            "exec_time_ms": exec_time,
            "n_cores":      n_cores,
        }

    except Exception as e:
        print(f"  [{name}] FAILED: {e}")
        # Treat failure as worst case. MAB learns to avoid this node
        results[name] = {
            "cpu_percent":  100.0,
            "exec_time_ms": MAX_EXEC_MS,
            "n_cores":      1,
        }

#Metrics Logger 
def init_logger():
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "epoch", "policy", "task_size",
            "selected_node", "arm",
            "cpu_percent", "n_cores", "effective_load",
            "exec_time_ms",
            "reward", "cumulative_reward", "avg_reward",
            "best_arm", "best_node",
            "learning_time_s", "timestamp"
        ])
    print(f"✓ Logging to {LOG_FILE}")


def log_epoch(epoch, task, arm, node_name,
              cpu, n_cores, exec_time, reward,
              cumulative, avg, best_arm, best_node, elapsed):
    eff_load = round((cpu / max(n_cores, 1)), 2) if cpu else ""
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            epoch, POLICY, task["size"],
            node_name, arm,
            round(cpu, 2) if cpu else "",
            n_cores,
            eff_load,
            round(exec_time, 1) if exec_time else "",
            reward,
            round(cumulative, 4),
            round(avg, 4),
            best_arm, best_node,
            round(elapsed, 2),
            datetime.now().isoformat()
        ])


#Main Loop
def run():
    arm_names = list(NODES.keys())
    n_arms    = len(arm_names)

    if POLICY == "UCB1":
        policy = UCB1(n_arms, c=2.0)
    elif POLICY == "EXP3":
        policy = EXP3(n_arms, gamma=0.1)
    elif POLICY == "RoundRobin":
        policy = RoundRobin(n_arms)
    else:
        raise ValueError(f"Unknown policy: {POLICY}")
    
    tb     = TBClient()
    init_logger()

    print(f"\n{'='*60}")
    print(f"Policy={POLICY} | Nodes={arm_names}")
    print(f"Epochs={EPOCHS} | Interval={INTERVAL}s")
    print(f"Task cost=[{TASK_COST_MIN},{TASK_COST_MAX}]")
    print(f"Reward: alpha={ALPHA} (core-normalized CPU) | beta={BETA} (time)")
    print(f"{'='*60}\n")

    start_time = time.time()

    for epoch in range(1, EPOCHS + 1):
        epoch_start = time.time()
        print(f"\n── Epoch {epoch}/{EPOCHS} ──────────────────────────────")

        # 1. Generate task
        task = generate_task()
        print(f"Task: size={task['size']} id={task['task_id']}")

        # 2. Select arm
        arm       = policy.select()
        node_name = arm_names[arm]
        device_id = NODES[node_name]
        print(f"Selected: {node_name} (arm {arm})")

        # 3. Dispatch task
        results = {}
        dispatch_task(tb, node_name, device_id, task, results)

        # 4. Compute reward
        r         = results.get(node_name, {})
        cpu       = r.get("cpu_percent")
        exec_time = r.get("exec_time_ms")
        n_cores   = r.get("n_cores", 1)
        reward    = compute_reward(cpu, exec_time, n_cores)
       #DEBUG
        print(f"\n  DEBUG {node_name}:")
        print(f"    cpu_percent    = {cpu}")
        print(f"    n_cores        = {n_cores}")
        print(f"    exec_time_ms   = {exec_time}")
        print(f"    effective_load = {round((cpu/max(n_cores,1)),1) if cpu else 'N/A'}%")
        print(f"    reward         = {reward}") 
        # 5. Update policy
        policy.update(arm, reward)

        # 6. Metrics
        elapsed    = time.time() - start_time
        avg_reward = policy.total_reward / policy.epoch
        state      = policy.state()
        best_arm   = state["best_arm"]
        best_node  = arm_names[best_arm]

        print(f"Reward: {reward:.4f} | Avg: {avg_reward:.4f} | "
              f"Best: {best_node} (arm {best_arm})")
        print(f"State: {state}")

        log_epoch(
            epoch, task, arm, node_name,
            cpu, n_cores, exec_time, reward,
            policy.total_reward, avg_reward,
            best_arm, best_node, elapsed
        )

        # 7. Sleep until next epoch
        epoch_elapsed = time.time() - epoch_start
        sleep_time    = max(0, INTERVAL - epoch_elapsed)
        print(f"Sleeping {sleep_time:.1f}s...")
        time.sleep(sleep_time)

    #Final Report
    total_time = time.time() - start_time
    state      = policy.state()
    print(f"\n{'='*60}")
    print(f"DONE | Policy={POLICY} | Total time={total_time:.1f}s")
    print(f"Total reward:   {policy.total_reward:.4f}")
    print(f"Average reward: {policy.total_reward / EPOCHS:.4f}")
    print(f"Best node:      {arm_names[state['best_arm']]}")
    print(f"Final state:    {state}")
    print(f"Results:        {LOG_FILE}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run()
