#!/bin/bash
# Started by mail_control for "RUN GLOBAL": runs the global_logger daily job, then emails the result.
cd "$HOME/global_logger"
./venv/bin/python -m global_logger daily > logs/mail_run.log 2>&1
rc=$?
summary=$(grep -E " ok:|ERROR|no daily|WARNING" logs/mail_run.log | tail -40)
/usr/bin/python3 - "$rc" "$summary" <<'PY'
import sys, os; sys.path.insert(0, os.path.expanduser("~/mail_control")); import pilib
pilib.send_mail(f"[Pi] RUN GLOBAL finished (exit code {sys.argv[1]})", sys.argv[2] + "\n\n" + pilib.FOOTER)
PY
