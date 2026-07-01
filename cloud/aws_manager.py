"""AWS resource manager for provisioning and monitoring compute resources.

Handles starting, stopping, provisioning, and querying the state of AWS EC2 instances.
"""

import logging
import time
from typing import Any, Dict
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from rich.logging import RichHandler

# Set up Rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("aws_manager")


class AWSManager:
    """Manages AWS EC2 instance lifecycles and metadata."""

    def __init__(self, region: str = "ap-south-1", instance_id: str = "") -> None:
        """Initialize AWSManager.

        Args:
            region: AWS region.
            instance_id: Target EC2 instance ID.
        """
        self.region = region
        self.instance_id = instance_id
        self._ec2_client = None

    @property
    def ec2_client(self) -> Any:
        """Lazily initialize and return the boto3 EC2 client."""
        if self._ec2_client is None:
            self._ec2_client = boto3.client("ec2", region_name=self.region)
        return self._ec2_client

    def _get_instance_info(self) -> Dict[str, Any]:
        """Helper to query description of the target instance and return state and IPs.

        Returns:
            Structured dictionary containing status, state, public IP, and private IP.
        """
        if not self.instance_id:
            return {
                "success": False,
                "error": "AWS EC2 Instance ID is not configured in configs/config.yaml or passed as an argument.",
                "instance_state": "unknown",
                "public_ip": None,
                "private_ip": None,
            }
        try:
            response = self.ec2_client.describe_instances(InstanceIds=[self.instance_id])
            reservations = response.get("Reservations", [])
            if not reservations:
                return {
                    "success": False,
                    "error": f"Instance {self.instance_id} not found.",
                    "instance_state": "unknown",
                    "public_ip": None,
                    "private_ip": None,
                }
            instances = reservations[0].get("Instances", [])
            if not instances:
                return {
                    "success": False,
                    "error": f"Instance {self.instance_id} not found.",
                    "instance_state": "unknown",
                    "public_ip": None,
                    "private_ip": None,
                }
            instance = instances[0]
            state = instance.get("State", {}).get("Name", "unknown")
            public_ip = instance.get("PublicIpAddress")
            private_ip = instance.get("PrivateIpAddress")
            return {
                "success": True,
                "instance_state": state,
                "public_ip": public_ip,
                "private_ip": private_ip,
            }
        except (ClientError, BotoCoreError) as e:
            logger.error(f"AWS API Error describing instance {self.instance_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "instance_state": "unknown",
                "public_ip": None,
                "private_ip": None,
            }
        except Exception as e:
            logger.error(f"Unexpected error describing instance {self.instance_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "instance_state": "unknown",
                "public_ip": None,
                "private_ip": None,
            }

    def start_instance(self) -> Dict[str, Any]:
        """Starts the EC2 instance.

        Returns:
            Structured dictionary.
        """
        logger.info(f"Initiating start sequence for instance {self.instance_id}...")
        if not self.instance_id:
            return self._get_instance_info()
        try:
            self.ec2_client.start_instances(InstanceIds=[self.instance_id])
            logger.info(f"Start command sent successfully to instance {self.instance_id}.")
            return self._get_instance_info()
        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to start instance {self.instance_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "instance_state": "unknown",
                "public_ip": None,
                "private_ip": None,
            }

    def stop_instance(self) -> Dict[str, Any]:
        """Stops the EC2 instance.

        Returns:
            Structured dictionary.
        """
        logger.info(f"Initiating stop sequence for instance {self.instance_id}...")
        if not self.instance_id:
            return self._get_instance_info()
        try:
            self.ec2_client.stop_instances(InstanceIds=[self.instance_id])
            logger.info(f"Stop command sent successfully to instance {self.instance_id}.")
            return self._get_instance_info()
        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to stop instance {self.instance_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "instance_state": "unknown",
                "public_ip": None,
                "private_ip": None,
            }

    def reboot_instance(self) -> Dict[str, Any]:
        """Reboots the EC2 instance.

        Returns:
            Structured dictionary.
        """
        logger.info(f"Initiating reboot for instance {self.instance_id}...")
        if not self.instance_id:
            return self._get_instance_info()
        try:
            self.ec2_client.reboot_instances(InstanceIds=[self.instance_id])
            logger.info(f"Reboot command sent successfully to instance {self.instance_id}.")
            return self._get_instance_info()
        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to reboot instance {self.instance_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "instance_state": "unknown",
                "public_ip": None,
                "private_ip": None,
            }

    def get_instance_state(self) -> Dict[str, Any]:
        """Queries the current state of the EC2 instance.

        Returns:
            Structured dictionary containing status, state, public IP, and private IP.
        """
        return self._get_instance_info()

    def wait_until_running(self, timeout: int = 300, delay: int = 5) -> Dict[str, Any]:
        """Waits until the EC2 instance is in the running state.

        Args:
            timeout: Maximum wait time in seconds.
            delay: Interval between description polling in seconds.

        Returns:
            Structured dictionary.
        """
        logger.info(f"Waiting for instance {self.instance_id} to reach 'running' state...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            info = self._get_instance_info()
            if not info["success"]:
                return info
            state = info["instance_state"]
            logger.info(f"Current state: {state}")
            if state == "running":
                logger.info(f"Instance {self.instance_id} is now running.")
                return info
            elif state in ["shutting-down", "terminated"]:
                err_msg = f"Aborting wait. Instance transitioned to terminal state: {state}"
                logger.warning(err_msg)
                return {
                    "success": False,
                    "error": err_msg,
                    "instance_state": state,
                    "public_ip": info.get("public_ip"),
                    "private_ip": info.get("private_ip"),
                }
            time.sleep(delay)
        err_msg = f"Timed out waiting for instance to reach 'running' state after {timeout}s."
        logger.error(err_msg)
        return {
            "success": False,
            "error": err_msg,
            "instance_state": "unknown",
            "public_ip": None,
            "private_ip": None,
        }

    def wait_until_stopped(self, timeout: int = 300, delay: int = 5) -> Dict[str, Any]:
        """Waits until the EC2 instance is in the stopped state.

        Args:
            timeout: Maximum wait time in seconds.
            delay: Interval between description polling in seconds.

        Returns:
            Structured dictionary.
        """
        logger.info(f"Waiting for instance {self.instance_id} to reach 'stopped' state...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            info = self._get_instance_info()
            if not info["success"]:
                return info
            state = info["instance_state"]
            logger.info(f"Current state: {state}")
            if state == "stopped":
                logger.info(f"Instance {self.instance_id} is now stopped.")
                return info
            elif state in ["terminated"]:
                err_msg = "Aborting wait. Instance was terminated."
                logger.warning(err_msg)
                return {
                    "success": False,
                    "error": err_msg,
                    "instance_state": state,
                    "public_ip": None,
                    "private_ip": None,
                }
            time.sleep(delay)
        err_msg = f"Timed out waiting for instance to reach 'stopped' state after {timeout}s."
        logger.error(err_msg)
        return {
            "success": False,
            "error": err_msg,
            "instance_state": "unknown",
            "public_ip": None,
            "private_ip": None,
        }

    def get_public_ip(self) -> Dict[str, Any]:
        """Gets the public IP address of the EC2 instance.

        Returns:
            Structured dictionary.
        """
        return self._get_instance_info()

    def get_private_ip(self) -> Dict[str, Any]:
        """Gets the private IP address of the EC2 instance.

        Returns:
            Structured dictionary.
        """
        return self._get_instance_info()
