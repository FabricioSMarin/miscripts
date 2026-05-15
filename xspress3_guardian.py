#!/usr/bin/env python3
"""
XSpress3 Guardian

Combined IOC monitor and scan defender. Monitors the IOC screen session for:
1. Error messages in console output
2. Screen session termination (IOC crash)

When issues are detected during a scan, it:
- Pauses the scan
- Restarts the IOC
- Reinitializes XSpress3
- Resumes the scan
"""

import subprocess
import time
import sys
import argparse
import logging
from pathlib import Path
from epics import caget, caput

# Default configuration
DEFAULT_ERROR_PATTERNS = [
    "Mismatch on scalars descriptors",
    "xsp3_dma_check_desc returned XSP3_ERROR",
]

DEFAULT_LOG_DIR = Path("/tmp/xspress3_guardian")
DEFAULT_RESTART_COOLDOWN = 30
DEFAULT_CHECK_INTERVAL = 2


class XSpress3Guardian:
    def __init__(
        self,
        screen_session: str,
        restart_cmd: str,
        start_cmd: str,
        error_patterns: list[str],
        prefix: str,
        xp3_prefix: str,
        xp3_setup_calc: str,
        flag_pv: str = "",
        fly_inner_loop: str = "FscanH",
        step_inner_loop: str = "scan1",
        step_outer_loop: str = "scan2",
        fly_outer_loop: str = "Fscan1",
        log_dir: Path = DEFAULT_LOG_DIR,
        restart_cooldown: int = DEFAULT_RESTART_COOLDOWN,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
    ):
        self.screen_session = screen_session
        self.restart_cmd = restart_cmd
        self.start_cmd = start_cmd
        self.error_patterns = error_patterns
        self.log_dir = Path(log_dir)
        self.restart_cooldown = restart_cooldown
        self.check_interval = check_interval
        
        # EPICS PV prefixes
        self.prefix = prefix
        self.xp3_prefix = xp3_prefix
        self.xp3_setup_calc = xp3_setup_calc
        self.flag_pv = flag_pv
        self.fly_inner_loop = fly_inner_loop
        self.step_inner_loop = step_inner_loop
        self.step_outer_loop = step_outer_loop
        self.fly_outer_loop = fly_outer_loop
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.hardcopy_file = self.log_dir / "screen_hardcopy.txt"
        self.last_restart_time = 0
        self.previous_content = ""
        
        self._setup_logging()
    
    def _setup_logging(self):
        """Configure logging for the monitor itself."""
        log_file = self.log_dir / "guardian.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout),
            ],
        )
        self.logger = logging.getLogger(__name__)
    
    def _find_screen_session(self) -> str | None:
        """Find the full screen session name matching our pattern."""
        try:
            result = subprocess.run(
                ["screen", "-ls"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.split("\n"):
                if self.screen_session in line:
                    parts = line.strip().split()
                    if parts:
                        return parts[0]
            return None
        except Exception as e:
            self.logger.error(f"Error listing screen sessions: {e}")
            return None
    
    def _session_exists(self) -> bool:
        """Check if the screen session still exists."""
        return self._find_screen_session() is not None
    
    def _capture_screen_content(self) -> str:
        """Capture screen contents using hardcopy (non-interactive)."""
        session = self._find_screen_session()
        if not session:
            return ""
        
        try:
            subprocess.run(
                ["screen", "-S", session, "-X", "hardcopy", str(self.hardcopy_file)],
                capture_output=True,
                timeout=5,
            )
            
            if self.hardcopy_file.exists():
                return self.hardcopy_file.read_text()
        except subprocess.TimeoutExpired:
            self.logger.warning("Screen hardcopy timed out")
        except Exception as e:
            self.logger.error(f"Error capturing screen: {e}")
        
        return ""
    
    def _check_for_errors(self, content: str) -> str | None:
        """Check content for error patterns. Returns matched pattern or None."""
        for pattern in self.error_patterns:
            if pattern in content and pattern not in self.previous_content:
                return pattern
        return None
    
    def _check_flag_pv(self) -> bool:
        """Check if the flag PV is set (value == 1). Returns True if flag is triggered."""
        if not self.flag_pv:
            return False
        try:
            value = caget(self.flag_pv)
            return value == 1
        except Exception as e:
            self.logger.error(f"Error reading flag PV {self.flag_pv}: {e}")
            return False
    
    def _reset_flag_pv(self):
        """Reset the flag PV to 0 after handling."""
        if not self.flag_pv:
            return
        try:
            caput(self.flag_pv, 0)
            self.logger.info(f"Reset flag PV {self.flag_pv} to 0")
        except Exception as e:
            self.logger.error(f"Error resetting flag PV: {e}")
    
    def _is_scanning(self) -> tuple[bool, str]:
        """Check if a scan is currently running. Returns (is_scanning, scan_type)."""
        try:
            fly_scanning = caget(f"{self.prefix}{self.fly_inner_loop}.BUSY")
            fly_pause = caget(f"{self.prefix}FscanPause.VAL")
            
            step_scanning = caget(f"{self.prefix}{self.step_inner_loop}.BUSY")
            step_pause = caget(f"{self.prefix}scanPause.VAL")
            
            if fly_scanning and not fly_pause:
                return True, "fly"
            elif step_scanning and not step_pause:
                return True, "step"
            
            return False, ""
        except Exception as e:
            self.logger.error(f"Error checking scan status: {e}")
            return False, ""
    
    def _pause_scan(self, scan_type: str):
        """Pause the current scan."""
        try:
            if scan_type == "fly":
                caput(f"{self.prefix}{self.fly_inner_loop}.WAIT", 1)
                self.logger.info("Paused fly scan")
            elif scan_type == "step":
                caput(f"{self.prefix}{self.step_inner_loop}.WAIT", 1)
                self.logger.info("Paused step scan")
        except Exception as e:
            self.logger.error(f"Error pausing scan: {e}")
    
    def _resume_scan(self, scan_type: str):
        """Resume the current scan and update file number."""
        try:
            if scan_type == "fly":
                current_line = caget(f"{self.prefix}{self.fly_outer_loop}.CPT")
                current_scan_number = caget(f"{self.prefix}saveData_scanNumber")-1
                formated_name = f"8bmb_{current_scan_number:04d}"
                caput(f"8bmbsft:DetProxyF", 0)
                caput(f"{self.xp3_prefix}HDF1:FileNumber", current_line)
                caput(f"{self.xp3_prefix}HDF1:FileName", formated_name)
                caput(f"{self.prefix}{self.fly_inner_loop}.WAIT", 0)
                self.logger.info(f"Resumed fly scan at line {current_line}")
            elif scan_type == "step":
                current_line = caget(f"{self.prefix}{self.step_outer_loop}.CPT")
                current_scan_number = caget(f"{self.prefix}saveData_scanNumber")-1
                formated_name = f"8bmb_{current_scan_number:04d}"
                caput(f"{self.xp3_prefix}HDF1:FileNumber", current_line)
                caput(f"{self.xp3_prefix}HDF1:FileName", formated_name)
                caput(f"{self.prefix}{self.step_inner_loop}.WAIT", 0)
                self.logger.info(f"Resumed step scan at line {current_line}")
        except Exception as e:
            self.logger.error(f"Error resuming scan: {e}")
    
    def _reinit_xspress3(self):
        """Reinitialize XSpress3 after restart."""
        try:
            caput(self.xp3_setup_calc, 1)
            self.logger.info("Triggered XSpress3 reinitialization")
        except Exception as e:
            self.logger.error(f"Error reinitializing XSpress3: {e}")
    
    def _restart_ioc(self, reason: str, scan_type: str = "", use_start: bool = False) -> bool:
        """Restart the IOC, handling scan pause/resume if needed.
        
        Args:
            reason: Why the restart is happening
            scan_type: "fly", "step", or "" for both
            use_start: If True, use start_cmd (for crashes). If False, use restart_cmd.
        """
        current_time = time.time()
        
        if current_time - self.last_restart_time < self.restart_cooldown:
            remaining = self.restart_cooldown - (current_time - self.last_restart_time)
            self.logger.warning(
                f"Restart cooldown active, waiting {remaining:.0f}s before next restart"
            )
            return False
        
        cmd = self.start_cmd if use_start else self.restart_cmd
        action = "STARTING" if use_start else "RESTARTING"
        self.logger.warning(f"{action} IOC - Reason: {reason}")
        
        # Pause scans before restart
        self._pause_scan(scan_type)
        
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            self.logger.info(f"{action} output: {result.stdout}")
            if result.stderr:
                self.logger.info(f"Restart stderr: {result.stderr}")
            
            self.last_restart_time = current_time
            self.previous_content = ""
            
            # Wait for IOC to come back up
            self.logger.info("Waiting for IOC to restart...")
            time.sleep(10)
            
            # Always reinitialize XSpress3 after restart
            self._reinit_xspress3()
            time.sleep(3)
            
            # Resume scan if one was running
            self._resume_scan(scan_type)
            
            self.logger.info("IOC restart completed")
            return True
                
        except subprocess.TimeoutExpired:
            self.logger.error("IOC restart command timed out")
            return False
        except Exception as e:
            self.logger.error(f"IOC restart error: {e}")
            return False
    
    def run(self):
        """Main monitoring loop."""
        self.logger.info("=" * 60)
        self.logger.info("XSpress3 Guardian Starting")
        self.logger.info(f"Screen session: {self.screen_session}")
        self.logger.info(f"Restart command: {self.restart_cmd}")
        self.logger.info(f"Start command: {self.start_cmd}")
        self.logger.info(f"EPICS prefix: {self.prefix}")
        self.logger.info(f"XSpress3 prefix: {self.xp3_prefix}")
        self.logger.info(f"Flag PV: {self.flag_pv if self.flag_pv else 'None'}")
        self.logger.info(f"Monitoring for errors: {self.error_patterns}")
        self.logger.info(f"Check interval: {self.check_interval}s")
        self.logger.info(f"Restart cooldown: {self.restart_cooldown}s")
        self.logger.info("=" * 60)
        
        # Verify screen session exists
        session = self._find_screen_session()
        if session:
            self.logger.info(f"Found screen session: {session}")
        else:
            self.logger.warning(f"Screen session '{self.screen_session}' not found at startup")
        
        try:
            while True:
                is_scanning, scan_type = self._is_scanning()
                session_exists = self._session_exists()
                
                # Check for session termination (IOC crash)
                if not session_exists:
                    self.logger.error("Screen session terminated (IOC crashed)")
                    self._restart_ioc("Screen session terminated", scan_type, use_start=True)
                    # Wait for session to come back
                    time.sleep(10)
                
                # Check for error messages in console
                content = self._capture_screen_content()
                if content:
                    error_match = self._check_for_errors(content)
                    if error_match:
                        self.logger.error(f"Error detected: '{error_match}'")
                        self.logger.info(f"Scan in progress ({scan_type}) - restarting IOC")
                        self._restart_ioc(error_match, scan_type)
                    else:
                        self.previous_content = content
                
                # Check flag PV for silent crash detection
                if self._check_flag_pv():
                    self.logger.error(f"Flag PV {self.flag_pv} triggered (silent crash detected)")
                    self._restart_ioc("Flag PV triggered", scan_type)
                    self._reset_flag_pv()
                
                time.sleep(self.check_interval)
                
        except KeyboardInterrupt:
            self.logger.info("Guardian stopped by user (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"Guardian error: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(
        description="XSpress3 Guardian - Monitor IOC and protect scans",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  %(prog)s -s 2id_1ChXpress3 \\
    -r "/net/s2dserv/xorApps/.../2id_1ChXspress3.pl restart" \\
    --start "/net/s2dserv/xorApps/.../2id_1ChXspress3.pl start" \\
    --prefix "fsm:" --xp3 "XSP3_1Chan:" \\
    --xp3-setup "fsm:userTran2.PROC"
        """,
    )
    
    parser.add_argument(
        "-s", "--session",
        required=True,
        help="Screen session name (or partial match)",
    )
    parser.add_argument(
        "-r", "--restart",
        required=True,
        help="Full path to IOC restart command (for error recovery)",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Full path to IOC start command (for crash recovery)",
    )
    parser.add_argument(
        "--prefix",
        default="fsm:",
        help="EPICS scan PV prefix (default: 'fsm:')",
    )
    parser.add_argument(
        "--xp3",
        default="XSP3_1Chan:",
        help="XSpress3 PV prefix (default: 'XSP3_1Chan:')",
    )
    parser.add_argument(
        "--xp3-setup",
        default="8bmbsft:userTran14.PROC",
        help="XSpress3 setup/reinit calc PV",
    )
    parser.add_argument(
        "--flag-pv",
        default="",
        help="PV to monitor for silent crash (triggers restart when value == 1)",
    )
    parser.add_argument(
        "--fly-loop",
        default="Fscan1",
        help="Fly scan inner loop name (default: 'Fscan1')",
    )
    parser.add_argument(
        "--step-loop",
        default="scan1",
        help="Step scan inner loop name (default: 'scan1')",
    )
    parser.add_argument(
        "-e", "--error",
        action="append",
        dest="errors",
        help="Error pattern to trigger restart (can be specified multiple times)",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=DEFAULT_RESTART_COOLDOWN,
        help=f"Seconds between restarts (default: {DEFAULT_RESTART_COOLDOWN})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_CHECK_INTERVAL,
        help=f"Seconds between checks (default: {DEFAULT_CHECK_INTERVAL})",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help=f"Directory for log files (default: {DEFAULT_LOG_DIR})",
    )
    
    args = parser.parse_args()
    
    error_patterns = args.errors if args.errors else DEFAULT_ERROR_PATTERNS
    
    guardian = XSpress3Guardian(
        screen_session=args.session,
        restart_cmd=args.restart,
        start_cmd=args.start,
        error_patterns=error_patterns,
        prefix=args.prefix,
        xp3_prefix=args.xp3,
        xp3_setup_calc=args.xp3_setup,
        flag_pv=args.flag_pv,
        fly_inner_loop=args.fly_loop,
        step_inner_loop=args.step_loop,
        log_dir=args.log_dir,
        restart_cooldown=args.cooldown,
        check_interval=args.interval,
    )
    
    guardian.run()


if __name__ == "__main__":
    main()
