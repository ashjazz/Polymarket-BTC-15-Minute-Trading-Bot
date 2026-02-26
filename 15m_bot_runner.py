import subprocess
import time
import sys
import os
from pathlib import Path
from datetime import datetime
from collections import deque

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Error tracking for intelligent backoff
error_history = deque(maxlen=10)  # Track last 10 errors
consecutive_errors = 0
MAX_BACKOFF = 300  # 5 minutes max backoff
BASE_BACKOFF = 5    # 5 seconds base backoff


def calculate_backoff(exit_code: int, consecutive_errors: int) -> int:
    """Calculate intelligent backoff time based on error pattern."""
    # Normal restart (user-triggered or scheduled)
    if exit_code in [0, 143, 15, -15]:
        return 2

    # Timeout or network errors need longer backoff
    if exit_code in [124, 137]:  # 124=timeout, 137=SIGKILL (often OOM)
        return min(60 * (2 ** min(consecutive_errors, 4)), MAX_BACKOFF)

    # Connection errors
    if exit_code == 1:  # Usually connection/timeout errors
        return min(BASE_BACKOFF * (2 ** consecutive_errors), MAX_BACKOFF)

    # Unknown errors - use exponential backoff
    return min(10 * (2 ** min(consecutive_errors, 5)), MAX_BACKOFF)


def run_bot():
    """Run the bot with auto-restart using the SAME Python environment."""
    global consecutive_errors

    BOT_SCRIPT = "bot.py"

    # CRITICAL: Use the SAME Python executable
    python_cmd = sys.executable

    # Get command line arguments (excluding the script name)
    # If you run "python 15m_bot_runner.py --live", this captures ['--live']
    bot_args = sys.argv[1:] if len(sys.argv) > 1 else []

    print("=" * 80)
    print("BTC 15-MIN TRADING BOT - AUTO-RESTART WRAPPER (ENHANCED)")
    print("=" * 80)
    print(f"Platform: {sys.platform}")
    print(f"Python: {python_cmd}")
    print(f"Bot script: {BOT_SCRIPT}")
    print(f"Bot arguments: {bot_args}")
    print(f"Virtual env: {sys.prefix}")
    print(f"Max backoff: {MAX_BACKOFF}s")
    print("=" * 80)
    print()

    # Check if bot script exists
    if not os.path.exists(BOT_SCRIPT):
        print(f"ERROR: Bot script '{BOT_SCRIPT}' not found!")
        print(f"Current directory: {os.getcwd()}")
        print(f"Files in directory: {os.listdir('.')}")
        print()
        print("Available .py files:")
        for file in os.listdir('.'):
            if file.endswith('.py'):
                print(f"  - {file}")
        print()
        print("Please set BOT_SCRIPT to your bot filename")
        sys.exit(1)

    restart_count = 0
    total_uptime = 0

    while True:
        restart_count += 1
        start_time = time.time()

        print("=" * 80)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
        print(f"Starting bot (restart #{restart_count}, consecutive_errors={consecutive_errors})...")
        print(f"Command: {python_cmd} {BOT_SCRIPT} {' '.join(bot_args)}")
        print("=" * 80)
        print()

        try:
            # Run the bot with arguments!
            cmd = [python_cmd, BOT_SCRIPT] + bot_args
            result = subprocess.run(
                cmd,
                check=False
            )

            exit_code = result.returncode
            session_duration = time.time() - start_time
            total_uptime += session_duration

            print()
            print("=" * 80)
            print(f"Bot stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Exit code: {exit_code}")
            print(f"Session duration: {session_duration:.1f}s")
            print(f"Total uptime: {total_uptime:.1f}s")
            print("=" * 80)

            # Track errors
            if exit_code in [0, 143, 15, -15]:
                # Normal termination - reset error counter
                consecutive_errors = 0
                print("✅ Normal auto-restart - loading fresh filters...")
                wait_time = 2
            else:
                # Error detected
                consecutive_errors += 1
                error_history.append({
                    'time': datetime.now().isoformat(),
                    'exit_code': exit_code,
                    'session_duration': session_duration,
                })

                wait_time = calculate_backoff(exit_code, consecutive_errors)
                print(f"⚠️ Error detected (code {exit_code}) - consecutive_errors={consecutive_errors}")
                print(f"   Using backoff: {wait_time}s (exponential)")

                # If too many consecutive errors, show recent history
                if consecutive_errors >= 3:
                    print("\n   Recent error history:")
                    for i, err in enumerate(list(error_history)[-5:]):
                        print(f"     [{i+1}] {err['time']} - exit={err['exit_code']}, duration={err['session_duration']:.1f}s")
                    print()

            print(f"Restarting in {wait_time} seconds...")
            print()
            time.sleep(wait_time)

        except KeyboardInterrupt:
            print()
            print("=" * 80)
            print("Keyboard interrupt received - stopping wrapper")
            print(f"Total restarts: {restart_count}")
            print(f"Total uptime: {total_uptime:.1f}s")
            print("=" * 80)
            break

        except Exception as e:
            consecutive_errors += 1
            print()
            print("=" * 80)
            print(f"ERROR running bot: {e}")
            print(f"Consecutive errors: {consecutive_errors}")
            print("=" * 80)

            wait_time = min(BASE_BACKOFF * (2 ** consecutive_errors), MAX_BACKOFF)
            print(f"Waiting {wait_time} seconds before retry...")
            print()
            time.sleep(wait_time)


if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\nStopped by user")
        sys.exit(0)