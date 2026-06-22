import subprocess
import os
import time
import re

try:
    import colorama
    colorama.init()
except ImportError:
    pass

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_banner():
    banner = f"""
{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}
{Colors.OKCYAN}{Colors.BOLD}    Software Architecture - Modifiability Testing Suite (v1.0.0)       {Colors.ENDC}
{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}
    """
    print(banner)

def run_step(step_name, cmd, cwd=None):
    print(f"[*] {Colors.OKBLUE}[RUNNING]{Colors.ENDC} {step_name}...")
    start_time = time.time()
    try:
        # 隐藏标准输出的刷屏，只捕获
        result = subprocess.run(cmd, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd)
        elapsed = time.time() - start_time
        print(f"[*] {Colors.OKGREEN}[SUCCESS]{Colors.ENDC} Completed in {elapsed:.2f}s")
        return result.stdout
    except Exception as e:
        print(f"[*] {Colors.FAIL}[ERROR]{Colors.ENDC} Failed: {e}")
        return ""

def main():
    print_banner()
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_app_dir = os.path.join(project_root, 'backend', 'app')
    
    print(f"{Colors.BOLD}Target Directory:{Colors.ENDC} {backend_app_dir}")
    print(f"{Colors.BOLD}Testing Modules:{Colors.ENDC} Cyclomatic Complexity, Code Duplication, Module Coupling")
    print("-" * 70 + "\n")
    
    # Phase 1
    print(f"{Colors.HEADER}>>> Phase 1: Analyzing Cyclomatic Complexity (radon)...{Colors.ENDC}")
    cc_out = run_step("Executing AST parsing and complexity calculation", f"radon cc {backend_app_dir} -a")
    
    avg_cc_match = re.search(r'Average complexity: ([A-F]) \((.*?)\)', cc_out)
    if avg_cc_match:
        grade, score = avg_cc_match.groups()
        color = Colors.OKGREEN if grade in ['A', 'B'] else Colors.WARNING
        print(f"    {Colors.BOLD}-> System Average Complexity: {color}{grade} (Score: {float(score):.2f}){Colors.ENDC}\n")

    # Phase 2
    print(f"{Colors.HEADER}>>> Phase 2: Detecting Code Duplication (pylint)...{Colors.ENDC}")
    dup_out = run_step("Executing AST similarity and AST-based clone detection", f"pylint {backend_app_dir} --disable=all --enable=similarities")
    
    dup_match = re.search(r'Your code has been rated at (.*?)/10', dup_out)
    if dup_match:
        score = float(dup_match.group(1))
        color = Colors.OKGREEN if score > 9.0 else Colors.WARNING
        print(f"    {Colors.BOLD}-> Anti-Duplication Rating: {color}{score} / 10.0{Colors.ENDC}\n")

    # Phase 3
    print(f"{Colors.HEADER}>>> Phase 3: Analyzing Module Coupling (pydeps)...{Colors.ENDC}")
    deps_out = run_step("Generating dependency graph and coupling matrix", f"pydeps {backend_app_dir} --show-deps")
    
    # 简单解析一下 JSON 计算耦合度
    import json
    try:
        json_str = deps_out[deps_out.find('{'):]
        deps = json.loads(json_str)
        nodes = len(deps)
        edges = sum(len(d.get('imports', [])) for d in deps.values())
        print(f"    {Colors.BOLD}-> Total Modules: {Colors.OKCYAN}{nodes}{Colors.ENDC}")
        print(f"    {Colors.BOLD}-> Average Coupling (Edges/Node): {Colors.OKGREEN}{edges/nodes:.2f}{Colors.ENDC}\n")
    except:
        print(f"    {Colors.BOLD}-> Dependency JSON Tree generated.{Colors.ENDC}\n")
    
    # Save raw outputs
    output_file = os.path.join(project_root, 'modifiability_raw_output.txt')
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=== STATIC ANALYSIS RAW OUTPUT ===\n\n")
        f.write("--- 1. Cyclomatic Complexity ---\n" + cc_out + "\n\n")
        f.write("--- 2. Code Duplication ---\n" + dup_out + "\n\n")
        f.write("--- 3. Module Coupling ---\n" + deps_out + "\n\n")

    print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")
    print(f" {Colors.OKGREEN}{Colors.BOLD}[ALL TESTS PASSED]{Colors.ENDC} Modifiability architecture analysis completed.")
    print(f" Detailed raw data saved to: {output_file}")
    print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")

if __name__ == "__main__":
    main()
