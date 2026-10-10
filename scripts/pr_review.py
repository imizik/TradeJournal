"""Compatibility for sessions that loaded the retired local-review hooks."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "hook":
        sys.exit(0)
    print("The cross-provider review loop is retired. Use native subagent review; "
          "see docs/agent/pr-review.md.", file=sys.stderr)
    sys.exit(2)
