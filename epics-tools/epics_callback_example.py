#!/home/beams/MARINF/dev/miniconda3/envs/pybs/bin/python
"""
Example of monitoring an EPICS PV and running a callback function when it changes.

This demonstrates how to use epics.PV callbacks to react to PV value changes in real-time.
"""

import epics
import time

def my_callback(pvname=None, value=None, char_value=None, **kw):
    """
    Callback function that gets called whenever the PV value changes.
    
    Args:
        pvname: Name of the PV that changed
        value: The new value (numeric)
        char_value: The new value as a string
        **kw: Additional keyword arguments (timestamp, etc.)
    """
    print(f"PV {pvname} changed to: {value} (string: {char_value})")
    if 'timestamp' in kw:
        print(f"  Timestamp: {kw['timestamp']}")


def main():
    # Create a PV object
    pv_name = "OPS:message7"  # Replace with your PV name
    pv = epics.PV(pv_name, connection_timeout=0.25)
    
    # Wait for connection (optional, but recommended)
    if pv.wait_for_connection(timeout=5.0):
        print(f"Connected to {pv_name}")
    else:
        print(f"Failed to connect to {pv_name}")
        return
    
    # Add a callback function that will be called whenever the PV value changes
    # The callback receives: pvname, value, char_value, and other kwargs
    callback_id = pv.add_callback(my_callback)
    
    print(f"Monitoring {pv_name}. Press Ctrl+C to stop...")
    print(f"Current value: {pv.get()}")
    
    try:
        # Keep the script running so callbacks can be received
        # Option 1: signal.pause() - blocks until interrupted (BEST for Linux/Mac)
        import signal
        try:
            signal.pause()  # Blocks until SIGINT (Ctrl+C) - more efficient than sleep
        except (AttributeError, KeyboardInterrupt):
            # Fallback: signal.pause() not available on Windows
            # Option 2: while True with sleep (works everywhere, but less efficient)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping monitor...")
    
    # Remove the callback when done (optional, but good practice)
    pv.remove_callback(callback_id)
    print("Callback removed. Exiting.")


# Example with a class-based callback
class PVMonitor:
    """Example class that monitors a PV with a callback."""
    
    def __init__(self, pv_name):
        self.pv_name = pv_name
        self.pv = epics.PV(pv_name, connection_timeout=0.25)
        self.callback_id = None
        self.value_count = 0
        
        # Wait for connection
        if self.pv.wait_for_connection(timeout=5.0):
            print(f"Connected to {pv_name}")
            # Add callback using a bound method
            self.callback_id = self.pv.add_callback(self.on_pv_change)
        else:
            print(f"Failed to connect to {pv_name}")
    
    def on_pv_change(self, pvname=None, value=None, char_value=None, **kw):
        """Callback method that gets called when PV changes."""
        self.value_count += 1
        print(f"[{self.value_count}] {pvname} = {value}")
        
        # You can add custom logic here
        if value is not None and value > 10:
            print(f"  Warning: Value {value} exceeds threshold!")
    
    def stop_monitoring(self):
        """Stop monitoring by removing the callback."""
        if self.callback_id is not None:
            self.pv.remove_callback(self.callback_id)
            self.callback_id = None


if __name__ == "__main__":
    # Example 1: Simple function callback
    print("=" * 60)
    print("Example 1: Simple function callback")
    print("=" * 60)
    # Uncomment to run:
    # main()
    
    # Example 2: Class-based callback
    print("\n" + "=" * 60)
    print("Example 2: Class-based callback")
    print("=" * 60)
    monitor = PVMonitor("OPS:message7")
    
    try:
        print("Monitoring... Press Ctrl+C to stop")
        # Use signal.pause() for cleaner blocking (Linux/Mac)
        # Falls back to sleep loop on Windows
        import signal
        try:
            signal.pause()
        except (AttributeError, KeyboardInterrupt):
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        monitor.stop_monitoring()
