import subprocess
import os

def run_command(cmd, cwd=None):
    print(f"Running: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd)
        return result.stdout
    except Exception as e:
        return str(e)

def main():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_app_dir = os.path.join(project_root, 'backend', 'app')
    output_file = os.path.join(project_root, 'modifiability_raw_output.txt')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=== STATIC ANALYSIS RAW OUTPUT ===\n\n")

        # 1. Radon Cyclomatic Complexity
        # -a calculates average, -nc shows blocks with complexity >= 6 (Grade B, C, D, E, F)
        f.write("--- 1. Cyclomatic Complexity (radon) ---\n")
        f.write("Blocks with complexity >= 6 (Grade B+):\n")
        out = run_command(f"radon cc {backend_app_dir} -a -nc")
        f.write(out + "\n\n")

        # 2. Pylint Similarities (Code Duplication)
        f.write("--- 2. Code Duplication (pylint similarities) ---\n")
        out = run_command(f"pylint {backend_app_dir} --disable=all --enable=similarities")
        f.write(out + "\n\n")

        # 3. Pydeps (Module Coupling Dependencies)
        # Using --show-deps outputs JSON dependency graph, avoiding Graphviz requirement
        f.write("--- 3. Module Coupling Dependencies (pydeps JSON) ---\n")
        out = run_command(f"pydeps {backend_app_dir} --show-deps")
        f.write(out + "\n\n")

    print(f"Static analysis finished. Raw output saved to {output_file}")

if __name__ == "__main__":
    main()
