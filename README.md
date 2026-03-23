master_scheduler.py
====================
PC Master: MAB-based task scheduler for IoT-Edge-Cloud environment.

Arms:
  0 = Raspberry Pi
  1 = BeagleBone Black
  2 = PC (local execution)

Each epoch:
  1. Generate a task with configurable cost
  2. Select node via MAB policy (UCB1 or EXP3)
  3. Dispatch task via ThingsBoard RPC
  4. Collect execution results (cpu_percent, exec_time_ms, n_cores)
  5. Compute core-aware equal-weight efficiency reward
  6. Update MAB policy
  7. Log metrics (reward, convergence, learning time)
usage:
On PC hosting Thingsboard:
  python master_scheduler.py

tb_agent.py
============
Generic IoT node agent. runs on Raspberry Pi, BeagleBone Black, or PC.

Connects to ThingsBoard via MQTT and:
  - Publishes telemetry (cpu, ram, temp, disk, n_cores) every seconds as set in TELEMETRY_INTERVAL
  - Handles RPC commands:
      executeTask     -> runs a task, returns (cpu, exec_time_ms, n_cores)
      getStatus       -> returns current node state
      setOperational  -> pause/resume telemetry

Usage:
  python tb_agent.py

Configure TB_HOST, TB_TOKEN and NODE_ID before running.

plot_results.py
================
Generates publication-quality graphs from master_scheduler.py CSV output.

Produces:
  1. fig_reward.pdf        — Reward per epoch: UCB1 vs EXP3 vs Round-Robin
  2. fig_exec_time.pdf     — Execution time per node over epochs
  3. fig_convergence.pdf   — Arm selection frequency over epochs (convergence)

Usage:
  python plot_results.py \
      --ucb  results_UCB1_YYYYMMDD_HHMMSS.csv \
      --exp3 results_EXP3_YYYYMMDD_HHMMSS.csv \
      --rr   results_RoundRobin_YYYYMMDD_HHMMSS.csv   # optional

  If --rr is omitted, a synthetic round-robin baseline is computed as the mean reward across all arms from the UCB1 run.

Output directory: ./figures/

Scripts are included to install the dependancies and Python virtual environments:
install_master.sh - Host Device running Thingsboard (PC)
install_pi.sh - Raspberry PI Worker Device
install_bbb.sh - BeagleBone Worker Device
