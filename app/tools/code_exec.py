import subprocess
import tempfile
import os 

def run_code_sandboxed(code:str, timeout:int=10)->dict:
    """
    Executes Python code in an isolated Docker container — not in this
    process. Returns stdout, stderr, and whether it succeeded.

    - Infinite loops / resource exhaustion → handled by `timeout` and `-memory`/`-cpus` caps

    """
    with tempfile.NamedTemporaryFile(mode="w",suffix=".py", delete=False) as f:
        f.write(code)
        script_path = f.name

    try:
        result = subprocess.run([
                "docker", "run", "--rm",        #-rm for container is delete immediatly after running
                "--network", "none",              # cut all networking inside container
                "--memory", "128m",                # cap memory
                "--cpus", "0.5",                   # cap CPU
                "-v", f"{script_path}:/sandbox/script.py:ro",  # read-only mount
                "python:3.11-slim",
                "python", "/sandbox/script.py",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": f"Execution timed out after {timeout}s"}
    finally:
        os.unlink(script_path)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default="print('hello from sandbox')")
    args = parser.parse_args()
    print(run_code_sandboxed(args.code))