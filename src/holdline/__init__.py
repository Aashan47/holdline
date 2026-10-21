"""holdline: hold the line on agent quality.

Trace what an agent does, check it against cases, measure the LLM judge before trusting it, and
fail the pull request when a change makes the agent measurably worse.
"""

__version__ = "0.1.0"

from .checks import CheckResult, check  # noqa: E402
from .gate import GateConfig, GateResult, gate  # noqa: E402
from .judge import calibrate, llm_judge  # noqa: E402
from .runner import CaseResult, Run, run, run_case  # noqa: E402
from .suite import Case, Suite  # noqa: E402
from .suite import load as load_suite  # noqa: E402
from .trace import Step, Trace, current, step, tool  # noqa: E402

__all__ = [
    "__version__", "Case", "CaseResult", "CheckResult", "GateConfig", "GateResult", "Run", "Step",
    "Suite", "Trace", "calibrate", "check", "current", "gate", "llm_judge", "load_suite", "run",
    "run_case", "step", "tool",
]
