"""Isolated real-data backend for chart-load timing; never run in the main checkout.

Use a clean worktree, an explicit market-data key file, and a fresh history
folder for cold runs. Keep that folder for warm runs. No production cache reads.
The frontend runner refuses any database identity other than ux_sandbox.db.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keys-from', type=Path, required=True)
    parser.add_argument('--history-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8198)
    parser.add_argument('--frontend-url', default='http://127.0.0.1:3198')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for name in ('backend/.env', '.env', 'backend/token.json', 'backend/credentials.json', 'backend/pubsub-subscriber.json'):
        if (root / name).exists():
            parser.error('Use a clean worktree without environment or credential files')
    history = args.history_dir.resolve()
    # Keep writes within this disposable checkout, never a real cache path.
    if not history.is_relative_to(root / 'backend/data/ux_sandbox'):
        parser.error('--history-dir must be inside this worktree backend/data/ux_sandbox')
    from dotenv import dotenv_values
    allowed = {'ALPACA_API_KEY', 'ALPACA_API_SECRET', 'TRADIER_API_KEY', 'TRADIER_BASE_URL', 'POLYGON_API_KEY'}
    env = {k: v for k, v in dotenv_values(args.keys_from).items() if k in allowed and v}
    env.update({k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'SSL_CERT_FILE') if k in os.environ})
    sandbox = root / 'backend/data/ux_sandbox'
    sandbox.mkdir(parents=True, exist_ok=True)
    env.update(PYTHON_DOTENV_DISABLED='1', DATABASE_URL=f'sqlite:///{sandbox}/ux_sandbox.db',
               TJ_MANUAL_FILLS_BACKUP=str(sandbox / 'manual_fills.json'), CAPTURE_STORAGE_DIR=str(sandbox / 'captures'),
               FRONTEND_PUBLIC_URL=args.frontend_url, GMAIL_WATCH_AUTOSTART='false', GMAIL_LISTENER_ENABLED='false',
               WEBULL_LISTENER_AUTOSTART='false', LEVEL_ALERTS_AUTOSTART='false', PRACTICE_AGENT_ENABLED='false',
               PRACTICE_SCHEDULE_ENABLED='false', CAPTURE_TRANSCRIBER='off')
    os.chdir(root / 'backend')
    subprocess.run([sys.executable, 'scripts/seed_dev_data.py', '--database-url', env['DATABASE_URL']],
                   env=env, check=True, stdout=subprocess.DEVNULL)
    os.environ.clear()
    os.environ.update(env)
    sys.path.insert(0, str(root / 'backend'))
    from app.engine.chart_history import chart_history
    chart_history.root = history
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=args.port, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
