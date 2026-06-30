# QRP Cloud Controller

A standalone Python command-line utility and management system designed to automate experiment execution, cloud resource management, and result synchronization for quantitative research pipelines (QRP).

## Features

- **Git Automation**: Automated cloning, branch management, pulling code updates, and tracking code state for experiments.
- **AWS EC2 Orchestration**: Automates launching, stopping, monitoring, and scaling EC2 instances to run remote workloads.
- **SSH Management**: Securely connects to remote instances, executes setup tasks, runs experiments, and manages active sessions.
- **Experiment Execution**: Runs scripts/pipelines on remote compute resources, monitors logs, and handles execution lifecycles.
- **Result Synchronization**: Downloads logs, model checkpoints, data outputs, and generated reports back to local or centralized storage.

## Project Structure

```text
qrp-cloud-controller/
├── cloud/               # Python source files
│   ├── __init__.py      # Package initialization
│   ├── config.py        # Configuration loading and verification
│   ├── git_manager.py   # Git repository automation
│   ├── aws_manager.py   # AWS resource and EC2 management
│   ├── ssh_manager.py   # SSH connectivity and command execution
│   ├── sync_manager.py  # Bidirectional file/result synchronization
│   ├── runner.py        # Remote experiment run orchestrator
│   └── cli.py           # Command Line Interface (CLI) entry point
├── configs/             # YAML configurations
│   └── config.yaml
├── logs/                # Local runtime logs
├── downloads/           # Downloaded assets and artifacts
├── reports/             # Generated execution reports
└── temp/                # Temporary working directory
```

## Setup & Requirements

Requires **Python 3.12**.

To install dependencies:
```bash
pip install -r requirements.txt
```
